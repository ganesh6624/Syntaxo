"""
Game engine — all grading happens on the server so scores tracked by the agent are trustworthy.
Flow: start → (next → answer) × N → finish
"""
import re
import uuid

from . import agent, content, plans, store
from .util import HttpError, iso, jround, now_ms, shuffled

QUESTION_TIME_MS = 30_000       # short questions
LONG_QUESTION_TIME_MS = 45_000  # long code (> 8 lines) or multi-line (pattern / table) answers
GRACE_MS = 3_000
ROUND_SIZE = 10                 # questions per game, drawn fresh from the part's pool (100–320 questions)
RECENT_KEEP = 120               # per part: recently served question ids we try not to repeat
LIVES = 5
PASS_ACCURACY = 60


def _norm_fill(s) -> str:
    s = re.sub(r"\s+", " ", str("" if s is None else s).strip().lower())
    return re.sub(r"\(\)$", "", re.sub(r";$", "", s))


def progress_of(user, lang_id, level) -> dict | None:
    return ((user.get("progress") or {}).get(lang_id) or {}).get(str(level))


def is_unlocked(user, lang_id, level) -> bool:
    level = int(level)
    return level == 1 or bool((progress_of(user, lang_id, level - 1) or {}).get("passed"))


def _get_session(user, sid) -> dict:
    s = store.get_session(sid)
    if not s or s["userId"] != user["userId"]:
        raise HttpError(404, "Game session not found or expired. Start again.")
    return s


def time_limit_for(q) -> int:
    """Longer timer for long code or multi-line answer options (patterns, query results)."""
    lines = len((q.get("code") or "").split("\n"))
    tall = any(len(str(o).split("\n")) > 2 for o in (q.get("options") or []))
    return LONG_QUESTION_TIME_MS if lines > 8 or tall else QUESTION_TIME_MS


def pick_round(user, lang_id, level, questions) -> list:
    """
    Build a varied, adaptive round:
     • avoid questions this user saw recently on this part,
     • spread picks across question families ("kinds") so a round mixes concepts,
     • give extra weight to topics the user has been getting wrong.
    """
    key = f"{lang_id}:{level}"
    recent_map = user.setdefault("recentQ", {})
    recent = set(recent_map.get(key) or [])
    fresh = [q for q in questions if q["id"] not in recent]
    if len(fresh) < ROUND_SIZE:
        fresh = questions
        recent_map[key] = []

    acc = {}
    for a in store.attempts_for(user["userId"]):
        if a["lang"] != lang_id or a["level"] != level:
            continue
        for x in a.get("answers", []):
            t = acc.setdefault(x["topic"], {"c": 0, "n": 0})
            t["n"] += 1
            if x.get("correct"):
                t["c"] += 1

    def weakness(topic):
        t = acc.get(topic)
        return 1 - t["c"] / t["n"] if t and t["n"] >= 2 else 0

    by_kind = {}
    for q in shuffled(fresh):
        by_kind.setdefault(q.get("kind"), []).append(q)
    kinds = shuffled(list(by_kind))
    kinds.sort(key=lambda k: (-weakness(by_kind[k][0]["topic"]), -len(by_kind[k])))
    out = []
    while len(out) < ROUND_SIZE and any(by_kind[k] for k in kinds):
        for k in kinds:
            if by_kind[k] and len(out) < ROUND_SIZE:
                out.append(by_kind[k].pop())
    rnd = shuffled(out)
    recent_map[key] = ((recent_map.get(key) or []) + [q["id"] for q in rnd])[-RECENT_KEEP:]
    return rnd


def start(user, lang_id, level) -> dict:
    store.gc_sessions()
    try:
        level = int(level)
    except (TypeError, ValueError):
        raise HttpError(404, "Level not found.")
    lang, lv = content.get_language(lang_id), content.get_level(lang_id, level)
    if not lang or not lv:
        raise HttpError(404, "Level not found.")
    if not is_unlocked(user, lang_id, level):
        raise HttpError(403, f"Pass Part {level - 1} first to unlock this part.")
    if not plans.access_for(user)["canPlay"]:
        raise HttpError(402, "Your free trial has ended. Subscribe to continue.")
    picked = pick_round(user, lang_id, level, lv["questions"])
    order = []
    for q in picked:
        n_opts = len(q.get("options") or [])
        perm = shuffled(range(n_opts)) if q["type"] in ("mcq", "output") else list(range(n_opts))  # bug-hunt keeps line order
        order.append({"qid": q["id"], "limitMs": time_limit_for(q), "perm": perm})
    s = {"id": str(uuid.uuid4()), "userId": user["userId"], "lang": lang_id, "level": level, "order": order, "idx": 0,
         "state": "await_next", "servedAt": None, "lives": LIVES, "score": 0, "combo": 0, "maxCombo": 0, "answers": [], "createdAt": now_ms()}
    store.create_session(s)
    return {"sessionId": s["id"], "language": lang["name"], "icon": lang["icon"], "level": level, "title": lv["title"],
            "total": len(order), "lives": LIVES, "timeLimitMs": QUESTION_TIME_MS, "poolSize": len(lv["questions"])}


def _public_question(s) -> dict:
    o = s["order"][s["idx"]]
    q = content.get_question(s["lang"], s["level"], o["qid"])
    return {"index": s["idx"], "total": len(s["order"]), "type": q["type"], "topic": q["topic"], "prompt": q["prompt"], "code": q.get("code") or None,
            "options": [q["options"][i] for i in o["perm"]] if q.get("options") else None,
            "timeLimitMs": o["limitMs"], "remainingMs": max(0, o["limitMs"] - (now_ms() - s["servedAt"]))}


def _done(s) -> bool:
    return s["idx"] >= len(s["order"]) or s["lives"] <= 0


def next_question(user, sid) -> dict:
    s = _get_session(user, sid)
    if _done(s):
        return {"done": True}
    if s["state"] == "await_next":
        s["servedAt"] = now_ms()
        s["state"] = "await_answer"
        store.save_session(s)
    return {"done": False, "question": _public_question(s), "lives": s["lives"], "score": s["score"], "combo": s["combo"]}


def answer(user, sid, given) -> dict:
    s = _get_session(user, sid)
    if s["state"] != "await_answer":
        raise HttpError(409, "No question is waiting for an answer.")
    o = s["order"][s["idx"]]
    q = content.get_question(s["lang"], s["level"], o["qid"])
    if not q:
        raise HttpError(410, "This question is no longer available. Start a new game.")
    perm, limit = o["perm"], o["limitMs"]
    time_ms = now_ms() - s["servedAt"]
    timed_out = time_ms > limit + GRACE_MS or given is None

    correct = False
    if not timed_out:
        if q["type"] == "fill":
            correct = any(_norm_fill(a) == _norm_fill(given) for a in q["answer"])
        else:
            try:
                idx = int(given)
            except (TypeError, ValueError):
                idx = -1
            correct = 0 <= idx < len(perm) and perm[idx] == q["answer"]

    points = 0
    if correct:
        s["combo"] += 1
        s["maxCombo"] = max(s["maxCombo"], s["combo"])
        speed_bonus = jround(50 * (1 - min(time_ms, limit) / limit))
        multiplier = min(1.5, 1 + 0.1 * (s["combo"] - 1))
        points = jround((100 + speed_bonus) * multiplier)
        s["score"] += points
    else:
        s["combo"] = 0
        s["lives"] -= 1

    s["answers"].append({"qid": o["qid"], "topic": q["topic"], "type": q["type"], "correct": correct, "timedOut": timed_out, "timeMs": min(time_ms, limit)})
    s["idx"] += 1
    s["state"] = "await_next"
    store.save_session(s)
    return {"correct": correct, "timedOut": timed_out, "points": points, "score": s["score"], "combo": s["combo"], "lives": s["lives"],
            "done": _done(s), "correctAnswer": q["answer"][0] if q["type"] == "fill" else perm.index(q["answer"]), "explain": q.get("explain")}


def finish(user, sid) -> dict:
    s = _get_session(user, sid)
    if not _done(s):
        raise HttpError(409, "Game is not finished yet.")
    store.delete_session(sid)

    total = len(s["order"])
    correct = sum(1 for a in s["answers"] if a["correct"])
    accuracy = jround(correct / total * 100) if total else 0
    passed = accuracy >= PASS_ACCURACY and s["lives"] > 0
    stars = 0 if not passed else 3 if accuracy == 100 else 2 if accuracy >= 80 else 1
    avg_time_ms = jround(sum(a["timeMs"] for a in s["answers"]) / len(s["answers"])) if s["answers"] else 0

    prog = user.setdefault("progress", {}).setdefault(s["lang"], {})
    p = prog.setdefault(str(s["level"]), {"bestScore": 0, "bestAccuracy": 0, "stars": 0, "attempts": 0, "passed": False})
    prev_best = p["bestAccuracy"] if p["attempts"] else None
    first_pass = passed and not p["passed"]
    new_best = s["score"] > p["bestScore"]

    xp = jround(s["score"] / 10) + stars * 10 + (50 if first_pass else 0)
    if not new_best and not first_pass:
        xp = jround(xp / 2)  # replays still count, but less

    rank_before = agent.rank_for(user["stats"]["xp"])
    p["attempts"] += 1
    p["bestScore"] = max(p["bestScore"], s["score"])
    p["bestAccuracy"] = max(p["bestAccuracy"], accuracy)
    p["stars"] = max(p["stars"], stars)
    p["passed"] = p["passed"] or passed
    p["lastPlayedAt"] = iso()
    user["stats"]["xp"] += xp
    user["stats"]["gamesPlayed"] += 1
    streak_changed = agent.update_streak(user)

    attempt = store.insert_attempt({"id": str(uuid.uuid4()), "userId": user["userId"], "lang": s["lang"], "level": s["level"], "score": s["score"],
                                    "correct": correct, "total": total, "accuracy": accuracy, "stars": stars, "passed": passed, "xpEarned": xp,
                                    "maxCombo": s["maxCombo"], "avgTimeMs": avg_time_ms, "livesLeft": s["lives"], "answers": s["answers"], "at": iso()})
    feedback = agent.on_attempt(user, attempt, prev_best, rank_before, streak_changed)

    lang = content.get_language(s["lang"])
    nxt = content.get_level(s["lang"], s["level"] + 1)
    rank_after = agent.rank_for(user["stats"]["xp"])
    return {
        "result": {"lang": s["lang"], "languageName": lang["name"], "level": s["level"], "title": content.get_level(s["lang"], s["level"])["title"],
                   "score": s["score"], "correct": correct, "total": total, "accuracy": accuracy, "stars": stars, "passed": passed,
                   "maxCombo": s["maxCombo"], "avgTimeSec": jround(avg_time_ms / 100) / 10, "livesLeft": s["lives"], "newBest": new_best, "firstPass": first_pass},
        "xpEarned": xp, "totalXp": user["stats"]["xp"], "rank": rank_after, "rankUp": rank_after["title"] != rank_before["title"],
        "streak": user["stats"]["streak"],
        "unlockedNext": {"lang": s["lang"], "level": nxt["level"], "title": nxt["title"], "premium": nxt["premium"]} if first_pass and nxt else None,
        "hasNext": bool(nxt), "agentFeedback": feedback,
    }
