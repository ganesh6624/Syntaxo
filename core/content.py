"""
Syntaxo curriculum — backed by the verified question bank.

    core/data/curriculum.json   languages → parts ("levels"): title, topic, premium flag, lesson card
    core/data/pool.json         every question (14,000+), each code answer verified by really running it

Every part has 100–320 questions; each game draws a fresh random round from them (see game.py).
Question types: mcq · output (predict the output) · bug (pick the broken line) · fill (typed answer).
"""
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
LANG_IDS = ["python", "javascript", "java", "cpp", "sql"]
MIN_QUESTIONS = 10


def _playable(q) -> bool:
    if q.get("type") == "fill":
        return bool(str(q.get("answer") or "").strip())
    opts = q.get("options") or []
    return len(opts) >= 2 and isinstance(q.get("answer"), int) and 0 <= q["answer"] < len(opts)


def _load():
    meta = {l["id"]: l for l in json.loads((DATA / "curriculum.json").read_text(encoding="utf-8"))["languages"]}
    pool = json.loads((DATA / "pool.json").read_text(encoding="utf-8"))["levels"]
    langs = []
    for lid in LANG_IDS:
        m = meta.get(lid)
        if not m:
            continue
        levels = []
        for lv in m["levels"]:
            # a multiple-choice question needs a valid answer among ≥ 2 options, a fill-in needs an answer
            qs = [q for q in pool.get(f"{lid}:{lv['level']}", []) if _playable(q)]
            if len(qs) < MIN_QUESTIONS:
                continue
            levels.append({"level": lv["level"], "title": lv["title"], "topic": lv["topic"], "premium": bool(lv.get("premium")),
                           "lesson": lv.get("lesson") or {}, "questions": qs, "byId": {q["id"]: q for q in qs}})
        if levels:
            langs.append({"id": lid, "name": m["name"], "icon": m.get("icon", ""), "color": m.get("color", ""),
                          "tagline": m.get("tagline", ""), "levels": levels})
    return langs


LANGUAGES = _load()
_BY_ID = {l["id"]: l for l in LANGUAGES}


def get_language(lang_id):
    return _BY_ID.get(lang_id)


def get_level(lang_id, level):
    lang = _BY_ID.get(lang_id)
    if not lang:
        return None
    try:
        level = int(level)
    except (TypeError, ValueError):
        return None
    return next((l for l in lang["levels"] if l["level"] == level), None)


def get_question(lang_id, level, qid):
    lv = get_level(lang_id, level)
    return lv["byId"].get(qid) if lv else None


@lru_cache(maxsize=1)
def catalog():
    """Public catalog — never includes answers."""
    return [{"id": l["id"], "name": l["name"], "icon": l["icon"], "color": l["color"], "tagline": l["tagline"],
             "levels": [{"level": lv["level"], "title": lv["title"], "topic": lv["topic"], "premium": lv["premium"],
                         "questionCount": len(lv["questions"])} for lv in l["levels"]]} for l in LANGUAGES]


def lesson(lang_id, level):
    lang = _BY_ID.get(lang_id)
    lv = get_level(lang_id, level)
    if not lang or not lv:
        return None
    topics = list(dict.fromkeys(q["topic"] for q in lv["questions"]))
    ls = lv["lesson"]
    return {"language": lang["id"], "languageName": lang["name"], "icon": lang["icon"], "level": lv["level"], "title": lv["title"],
            "premium": lv["premium"], "summary": ls.get("summary", ""), "code": ls.get("code", ""), "sheet": ls.get("sheet", []),
            "questionCount": len(lv["questions"]), "topics": topics}


def stats():
    return [{"id": l["id"], "levels": len(l["levels"]), "questions": sum(len(lv["questions"]) for lv in l["levels"])} for l in LANGUAGES]
