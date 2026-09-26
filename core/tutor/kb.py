"""
Built-in knowledge base for the personal-agent chat (works with no AI key), loaded from
core/data/kb.json and core/data/programs.json.

  concept:    {id, keys: [trigger phrases], title, text (Markdown), code?: {lang: source}, lang?: only this language}
  comparison: {id, terms: [[synonyms of A], [synonyms of B], …], title, text}
  error:      {pattern (regex), lang?, title, text}
  program:    {id, keys, title, idea, code: {python, javascript, java, cpp}, output (verified by running all 4)}
"""
import json
import re
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data"
_kb = json.loads((_DATA / "kb.json").read_text(encoding="utf-8"))

CONCEPTS: list[dict] = _kb["concepts"]
COMPARISONS: list[dict] = _kb["comparisons"]
ERRORS: list[dict] = []
for e in _kb["errors"]:
    flags = re.I if "i" in e.get("flags", "") else 0
    ERRORS.append({**{k: v for k, v in e.items() if k not in ("pattern", "flags")}, "re": re.compile(e["pattern"], flags)})

PROGRAMS: list[dict] = json.loads((_DATA / "programs.json").read_text(encoding="utf-8"))
