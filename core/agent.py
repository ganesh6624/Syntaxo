"""
Personal Coding Agent
---------------------
Every user gets one agent at registration. The agent:
 • records every game attempt
 • computes skill per language, topic mastery, speed, trend, streaks
 • writes observations to the user's agent log (milestones, weak topics, rank-ups…)
 • produces recommendations (what to play next) and a subscription-plan suggestion
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from django.conf import settings

from . import content, plans, store
from .util import iso, jround, pct, pick, title_case, display_name

AGENTS = [
    {"id": "byte", "name": "Byte", "emoji": "", "title": "Robot Coach", "color": "#d8b25a",
     "voice": {"great": ["Flawless execution! My circuits are buzzing.", "Zero bugs detected. You are compiling beautifully!"],
               "good": ["Solid run! A few tweaks and you will be unstoppable.", "Nice work — your progress graph is trending up!"],
               "poor": ["Every error is data. Let's debug this together.", "Don't worry — even my first program crashed. Try again!"]}},
    {"id": "nova", "name": "Nova", "emoji": "", "title": "Wise Mentor", "color": "#c9a13f",
     "voice": {"great": ["Masterful. You have truly understood this part.", "Perfect wisdom — onward to the next chapter."],
               "good": ["Well done. Understanding grows with each attempt.", "A good step forward, young coder."],
               "poor": ["Patience. Read the lesson once more; clarity will come.", "The expert was once a beginner. Try again."]}},
    {"id": "blaze", "name": "Blaze", "emoji": "", "title": "Speed Trainer", "color": "#e0a806",
     "voice": {"great": ["BOOM! Fast AND accurate. That's how it's done!", "Perfect score — you're on fire!"],
               "good": ["Nice pace! Let's sharpen those last few answers.", "Good hustle — now go for three stars!"],
               "poor": ["Shake it off, champ. Warm-up round is over — go again!", "Slow down, read carefully, then strike!"]}},
    {"id": "luna", "name": "Luna", "emoji": "", "title": "Debug Detective", "color": "#b88c2e",
     "voice": {"great": ["Case closed! Not a single clue missed.", "Purrfect. You found every answer."],
               "good": ["Good detective work! A couple of mysteries remain.", "Nicely solved — let's crack the rest."],
               "poor": ["Hmm, the evidence says: review the lesson and try again.", "Every great detective revisits the scene. Replay this level!"]}},
]

RANKS = [{"title": "Novice", "min": 0}, {"title": "Apprentice", "min": 300}, {"title": "Coder", "min": 900},
         {"title": "Hacker", "min": 2000}, {"title": "Architect", "min": 4000}, {"title": "Legend", "min": 8000}]


def get_agent(agent_id):
    return next((a for a in AGENTS if a["id"] == agent_id), AGENTS[0])


def public_agent(a):
    return {k: v for k, v in a.items() if k != "voice"}


def assign_agent(existing_user_count: int):
    """Round-robin assignment keeps the agent load balanced."""
    return AGENTS[existing_user_count % len(AGENTS)]


def rank_for(xp: int) -> dict:
    i = 0
    while i + 1 < len(RANKS) and xp >= RANKS[i + 1]["min"]:
        i += 1
    cur = RANKS[i]
    nxt = RANKS[i + 1] if i + 1 < len(RANKS) else None
    return {"title": cur["title"], "level": i + 1, "min": cur["min"], "next": nxt["min"] if nxt else None,
            "nextTitle": nxt["title"] if nxt else None,
            "progress": jround((xp - cur["min"]) / (nxt["min"] - cur["min"]) * 100) if nxt else 100}


def log(user, type_, text, key=None):
    entry = {"at": iso(), "type": type_, "text": text}
    if key:
        entry["key"] = key
    user["agentLog"] = ([entry] + list(user.get("agentLog") or []))[:60]


def today_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(ZoneInfo(settings.APP_TZ)).strftime("%Y-%m-%d")


def update_streak(user) -> bool:
    s = user["stats"]["streak"]
    today = today_key()
    if s.get("lastDay") == today:
        return False
    yesterday = today_key(datetime.now(timezone.utc) - timedelta(days=1))
    s["current"] = s["current"] + 1 if s.get("lastDay") == yesterday else 1
    s["best"] = max(s.get("best", 0), s["current"])
    s["lastDay"] = today
    return True


def topic_stats(attempts) -> list[dict]:
    m = {}
    for a in attempts:
        for ans in a.get("answers", []):
            k = f"{a['lang']}:{ans['topic']}"
            t = m.setdefault(k, {"lang": a["lang"], "topic": ans["topic"], "level": a["level"], "correct": 0, "total": 0})
            t["total"] += 1
            if ans.get("correct"):
                t["correct"] += 1
            t["level"] = a["level"]
    return [{**t, "pct": pct(t["correct"], t["total"])} for t in m.values()]


def on_attempt(user, attempt, prev_best, rank_before, streak_changed) -> dict:
    """Called after every finished game. Returns the agent's feedback and writes log entries."""
    a = get_agent(user["agent"]["agentId"])
    lang = content.get_language(attempt["lang"])
    lv = content.get_level(attempt["lang"], attempt["level"])
    tier = "great" if attempt["accuracy"] == 100 else "good" if attempt["passed"] else "poor"
    tips = []
    if prev_best is not None and attempt["accuracy"] > prev_best:
        tips.append(f"You improved from {prev_best}% to {attempt['accuracy']}% on this level.")
    missed = list(dict.fromkeys(title_case(x["topic"]) for x in attempt["answers"] if not x["correct"]))
    if missed:
        tips.append(f"Review: {', '.join(missed)}. Re-read the lesson card before replaying.")
    avg_sec = jround(attempt["avgTimeMs"] / 100) / 10
    if attempt["passed"] and avg_sec < 8:
        tips.append(f"Speedy! Avg {avg_sec:g}s per answer.")
    elif avg_sec > 20:
        tips.append(f"You averaged {avg_sec:g}s per answer — reading the lesson first will speed you up.")
    if attempt["maxCombo"] >= 3:
        tips.append(f"Combo streak of {attempt['maxCombo']}!")

    if attempt["passed"] and (prev_best is None or prev_best < 60):
        log(user, "milestone", f"Completed {lang['name']} · Part {lv['level']} \"{lv['title']}\" with {attempt['accuracy']}% accuracy.")
    for w in (t for t in topic_stats(store.attempts_for(user["userId"])) if t["total"] >= 3 and t["pct"] < 60):
        key = f"weak:{w['lang']}:{w['topic']}"
        if not any(e.get("key") == key for e in user.get("agentLog") or []):
            log(user, "insight", f"I noticed {title_case(w['topic'])} in {content.get_language(w['lang'])['name']} is a weak spot "
                                 f"({w['pct']}% correct). I've added it to your recommendations.", key=key)
    rank_after = rank_for(user["stats"]["xp"])
    if rank_after["title"] != rank_before["title"]:
        log(user, "rank", f"Rank up! You are now a {rank_after['title']}.")
    cur = user["stats"]["streak"]["current"]
    if streak_changed and cur in (3, 7, 14, 30):
        log(user, "streak", f"{cur}-day streak! Consistency is the #1 predictor of success.")
    return {"agent": {"id": a["id"], "name": a["name"], "emoji": a["emoji"], "color": a["color"]}, "tier": tier,
            "message": pick(a["voice"][tier]), "tips": tips}


def _fmt_topic(t):
    L = content.get_language(t["lang"])
    return {"lang": t["lang"], "langName": L["name"], "icon": L["icon"], "topic": title_case(t["topic"]), "pct": t["pct"],
            "correct": t["correct"], "total": t["total"]}


def report(user) -> dict:
    """Full analysis for the agent dashboard, the chat and the admin page."""
    a = get_agent(user["agent"]["agentId"])
    attempts = sorted(store.attempts_for(user["userId"]), key=lambda x: x["at"])
    answers = [x for at in attempts for x in at.get("answers", [])]
    correct = sum(1 for x in answers if x.get("correct"))
    avg_time_ms = sum(x["timeMs"] for x in answers) / len(answers) if answers else 0
    progress = user.get("progress") or {}

    languages = []
    for l in content.LANGUAGES:
        prog = progress.get(l["id"]) or {}
        levels = []
        for lv in l["levels"]:
            p = prog.get(str(lv["level"])) or prog.get(lv["level"]) or {"bestAccuracy": 0, "stars": 0, "attempts": 0, "passed": False}
            levels.append({"level": lv["level"], "title": lv["title"], **p})
        passed = sum(1 for x in levels if x.get("passed"))
        skill = jround(sum(x.get("bestAccuracy") or 0 for x in levels) / len(levels))
        played = [x for x in attempts if x["lang"] == l["id"]]
        languages.append({"id": l["id"], "name": l["name"], "icon": l["icon"], "color": l["color"], "skill": skill,
                          "levelsPassed": passed, "totalLevels": len(l["levels"]), "attempts": len(played),
                          "lastPlayed": played[-1]["at"] if played else None,
                          "status": "mastered" if passed == len(l["levels"]) else "learning" if played else "not-started",
                          "levels": levels})

    topics = topic_stats(attempts)
    strong = sorted([t for t in topics if t["total"] >= 2 and t["pct"] >= 80], key=lambda t: -t["pct"])
    weak = sorted([t for t in topics if t["total"] >= 2 and t["pct"] < 60], key=lambda t: t["pct"])

    trend = [{"at": x["at"], "accuracy": x["accuracy"], "label": f"{x['lang']} P{x['level']}"} for x in attempts[-10:]]
    last3, prev3 = attempts[-3:], attempts[-6:-3]
    avg = lambda arr: sum(x["accuracy"] for x in arr) / len(arr) if arr else 0  # noqa: E731
    if len(prev3) < 1:
        trend_dir = "new"
    elif avg(last3) > avg(prev3) + 5:
        trend_dir = "up"
    elif avg(last3) < avg(prev3) - 5:
        trend_dir = "down"
    else:
        trend_dir = "steady"
    speed = "—" if not answers else "Lightning" if avg_time_ms < 6000 else "Steady" if avg_time_ms < 15000 else "Thoughtful"

    # recommendations
    recs, seen = [], set()

    def push(r):
        k = f"{r.get('lang')}:{r.get('level')}"
        if r.get("lang") and k in seen:
            return
        if r.get("lang"):
            seen.add(k)
        recs.append(r)

    for w in weak[:2]:
        L = content.get_language(w["lang"])
        push({"kind": "revise", "priority": "high", "text": f"Revise {title_case(w['topic'])} in {L['name']} — only {w['pct']}% correct so far.",
              "lang": w["lang"], "level": w["level"]})
    for l in languages:
        for lv in l["levels"]:
            if lv.get("attempts", 0) > 0 and not lv.get("passed"):
                push({"kind": "replay", "priority": "high", "text": f"Replay {l['name']} · Part {lv['level']} \"{lv['title']}\" "
                      f"(best {lv.get('bestAccuracy', 0)}%, need 60% to pass).", "lang": l["id"], "level": lv["level"]})
    for l in (x for x in languages if x["status"] == "learning"):
        lvls = l["levels"]
        nxt = next((lv for i, lv in enumerate(lvls) if not lv.get("passed") and (i == 0 or lvls[i - 1].get("passed"))), None)
        if nxt:
            push({"kind": "continue", "priority": "medium", "text": f"Continue {l['name']} with Part {nxt['level']}: \"{nxt['title']}\".",
                  "lang": l["id"], "level": nxt["level"]})
    for l in languages:
        for lv in l["levels"]:
            if lv.get("passed") and lv.get("stars", 0) < 3:
                push({"kind": "perfect", "priority": "low", "text": f"Go for 3 stars on {l['name']} · Part {lv['level']} (currently {lv.get('stars', 0)}★).",
                      "lang": l["id"], "level": lv["level"]})
    if not attempts:
        g = content.get_language(user.get("goalLanguage")) or content.LANGUAGES[0]
        push({"kind": "start", "priority": "high", "text": f"Start your journey with {g['name']} · Part 1. It only takes 3 minutes!", "lang": g["id"], "level": 1})
    elif any(l["status"] == "mastered" for l in languages) or len(attempts) >= 6:
        fresh = next((l for l in languages if l["status"] == "not-started"), None)
        if fresh:
            push({"kind": "explore", "priority": "low", "text": f"Ready for something new? Try {fresh['name']}.", "lang": fresh["id"], "level": 1})
    streak = user["stats"]["streak"]
    if streak.get("lastDay") != today_key() and attempts:
        recs.append({"kind": "streak", "priority": "medium", "text": f"Play one game today to keep your {streak['current']}-day streak alive!"})

    # engagement & subscription targeting
    active_days = len({x["at"][:10] for x in attempts})
    levels_passed = sum(l["levelsPassed"] for l in languages)
    engagement = min(100, jround(len(attempts) * 4 + active_days * 8 + streak.get("best", 0) * 5 + levels_passed * 3))
    access = plans.access_for(user)
    suggestion = {"plan": "monthly", "reason": "Start with Monthly — flexible, cancel anytime, full access to every part."}
    if engagement >= 70:
        suggestion = {"plan": "yearly", "reason": f"You're one of our most consistent learners (engagement {engagement}). Yearly gives you the best value — 37% cheaper than monthly."}
    elif engagement >= 30:
        suggestion = {"plan": "quarterly", "reason": f"You're building a solid habit (engagement {engagement}). Quarterly keeps your momentum going and saves 16%."}
    if access["status"] == "trial" and access["daysLeft"] <= 7:
        d = access["daysLeft"]
        suggestion["reason"] = f"Your free trial ends in {d} day{'' if d == 1 else 's'}. " + suggestion["reason"]

    fn = display_name(user)
    if not attempts:
        headline = f"I'm ready when you are, {fn}! Pick a language and play your first game."
    elif trend_dir == "new":
        headline = f"Great start, {fn}! I've logged your first game{'s' if len(attempts) > 1 else ''}. Keep playing so I can map your strengths."
    elif trend_dir == "up":
        headline = f"Your accuracy is climbing — great momentum, {fn}!"
    elif trend_dir == "down":
        headline = "Your last few games were tougher. Let's revisit the weak spots below."
    else:
        headline = f"Steady progress. {'Here' + chr(39) + 's what I suggest next.' if recs else ''}"

    return {
        "agent": {**public_agent(a), "assignedAt": user["agent"].get("assignedAt")},
        "headline": headline,
        "overview": {"xp": user["stats"]["xp"], "rank": rank_for(user["stats"]["xp"]), "gamesPlayed": len(attempts),
                     "questionsAnswered": len(answers), "accuracy": pct(correct, len(answers)),
                     "avgTimeSec": jround(avg_time_ms / 100) / 10, "speedLabel": speed, "streak": streak,
                     "levelsPassed": levels_passed, "totalLevels": sum(l["totalLevels"] for l in languages), "activeDays": active_days},
        "languages": [{**{k: v for k, v in l.items() if k != "levels"},
                       "levels": [{"level": lv["level"], "title": lv["title"], "bestAccuracy": lv.get("bestAccuracy") or 0,
                                   "stars": lv.get("stars") or 0, "passed": bool(lv.get("passed")), "attempts": lv.get("attempts") or 0}
                                  for lv in l["levels"]]} for l in languages],
        "topics": {"strong": [_fmt_topic(t) for t in strong[:6]], "weak": [_fmt_topic(t) for t in weak[:6]], "all": [_fmt_topic(t) for t in topics]},
        "trend": trend, "trendDirection": trend_dir, "recommendations": recs[:6],
        "engagement": engagement, "planSuggestion": suggestion, "access": access,
        "log": [{k: v for k, v in e.items() if k != "key"} for e in (user.get("agentLog") or [])[:25]],
    }
