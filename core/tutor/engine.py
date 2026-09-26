"""
Personal-agent chat ("Ask your agent").

Every message goes through local intents first — they are grounded in the app's own data:
  greeting / help · my progress & what next · quiz me (questions from the verified question bank)
  · pattern programs (code generated + output computed) · classic programs · common error messages
Everything else is answered by the AI model when one is configured (see llm.py), otherwise by the
built-in tutor: curated concepts & comparisons (kb.py) + every lesson cheat-sheet of the curriculum.
The agent only talks about the subjects taught here (programming, the 5 languages, DSA basics).
"""
import logging
import re
from functools import lru_cache

from .. import agent as agent_mod
from .. import content, store
from ..util import display_name, iso, now_ms, pick, shuffled
from . import llm, patterns
from .kb import COMPARISONS, CONCEPTS, ERRORS, PROGRAMS

log = logging.getLogger("syntaxo")

LANG = {"python": {"name": "Python", "fence": "python"}, "javascript": {"name": "JavaScript", "fence": "javascript"},
        "java": {"name": "Java", "fence": "java"}, "cpp": {"name": "C++", "fence": "cpp"}, "sql": {"name": "SQL", "fence": "sql"}}
MAX_HISTORY = 80
LETTERS = "ABCDEFGH"


def fence(lang, src) -> str:
    return "```" + (LANG.get(lang, {}).get("fence", "") if lang else "") + "\n" + str(src).rstrip() + "\n```"


# ───────────────────────── text normalisation ─────────────────────────
TYPOS = [(re.compile(p), to) for p, to in [
    (r"\brambows?\b|\brambo\b|\brom?bus\b|\brhombas\b|\brhombous\b|\brambus\b|\brhomb\b", "rhombus"), (r"\bbutter ?fl[iy]e?s?\b|\bbutterfy\b", "butterfly"),
    (r"\bhart\b|\bheart ?shape[d]?\b", "heart"), (r"\bdimond\b|\bdaimond\b", "diamond"), (r"\bpyramind\b|\bpiramid\b|\bpyramed\b", "pyramid"),
    (r"\brecurs+i?on\b|\brecurtion\b|\brecursin\b", "recursion"), (r"\bf[u]?n[c]?t?ions?\b|\bfuction\b|\bfuntion\b|\bfunctoin\b", "function"),
    (r"\bdict(i)?on(a|e)r(y|ies)\b|\bdictonary\b", "dictionary"), (r"\btupp?les?\b", "tuple"), (r"\bstr[i]?ngs?\b", "string"), (r"\blsit\b", "list"),
    (r"\bcondtion(al)?s?\b|\bcondition(al)?s?\b", "conditional"), (r"\bloo+ps?\b", "loop"), (r"\bvaraibles?\b|\bvariabels?\b", "variable"),
    (r"\barr(a)?y(s)?\b", "array"), (r"\bsql\s*query\b", "sql query"), (r"\bc plus plus\b|\bcpp\b", "c++"), (r"\bjs\b", "javascript"), (r"\bpy\b", "python"),
    (r"\bdifferen(ce|t)s?\b|\bdiff\b|\bdifference between\b", "difference"), (r"\bexplain(ation)?\b", "explain"), (r"\bexamples?\b|\beg\b", "example"),
]]
_PLURAL_KEEP = {"has", "does", "was", "this", "yes", "always", "process", "analysis", "its", "plus", "less", "ddls"}


def _singular(m):
    w, stem, suf = m.group(0), m.group(1), m.group(2)
    if len(w) < 4 or re.search(r"(ss|us|is|ies|ous)$", w) or w in _PLURAL_KEEP:
        return w
    if suf == "es":
        return stem if re.search(r"(s|x|z|sh|ch)$", stem) else stem + "e"
    return stem


@lru_cache(maxsize=4096)
def norm(text) -> str:
    s = str(text or "").lower().replace("\u2018", "'").replace("\u2019", "'").replace("node.js", "nodejs")
    s = re.sub(r"\.(?!\d)", " ", s)
    s = re.sub(r"[^a-z0-9+#_.'=<>!\s-]", " ", s)
    s = " " + re.sub(r"\s+", " ", s) + " "
    for rx, to in TYPOS:
        s = rx.sub(to, s)
    s = re.sub(r"\b([a-z]{3,}?)(es|s)\b", _singular, s)  # plural → singular ("loops" → "loop")
    return " " + re.sub(r"\s+", " ", s).strip() + " "


def has(n, phrase) -> bool:
    return f" {phrase} " in n


def words(n) -> list[str]:
    return [w for w in n.strip().split(" ") if w]


def code_lang(raw) -> str | None:
    if not raw:
        return None
    if re.search(r"#include|cout\s*<<|cin\s*>>|std::|int main\s*\(", raw):
        return "cpp"
    if re.search(r"System\.out|public static void|public class|String\[\]", raw):
        return "java"
    if re.search(r"console\.log|=>|\b(let|const|var)\s+\w+\s*=|function\s+\w+\s*\(", raw):
        return "javascript"
    if re.search(r"^\s*(def|elif|import|from)\b|print\(|:\s*$|\bself\b|range\(", raw, re.M):
        return "python"
    if re.search(r"\b(select|insert|update|delete|create table)\b[\s\S]*\b(from|into|set|values|\()", raw, re.I):
        return "sql"
    return None


def detect_lang(n, raw="") -> str | None:
    if re.search(r"\bjava ?script\b|\bjavascript\b|\bnode(js)?\b", n):
        return "javascript"
    if re.search(r"\bjava\b|\barraylist\b|\bhashmap\b|\bhashset\b|\btreemap\b|\bstringbuilder\b|\bscanner\b|\bsystem out\b|\bjvm\b|\bnullpointerexception\b", n):
        return "java"
    if re.search(r"c\+\+|\bstl\b|\bunordered_map\b|\bcout\b|\bcin\b|\bpush_back\b|\bmultiset\b", n):
        return "cpp"
    if re.search(r"\bpython\b", n):
        return "python"
    if re.search(r"\bsql\b|\bmysql\b|\bsqlite\b|\bpostgres(ql)?\b|\boracle\b|\bdatabase\b|\bquery\b|\bddl\b|\bdml\b|\bdql\b|\bdcl\b|\btcl\b", n):
        return "sql"
    return code_lang(raw)


def looks_like_code(raw) -> bool:
    return bool("```" in raw
                or re.search(r"^\s*(select|insert|update|delete|create|alter)\b.+\b(from|into|set|table|values)\b", raw, re.I)
                or (len(raw.split("\n")) >= 2 and re.search(r"[;{}()=]|print|def |for |if ", raw))
                or re.search(r"\b(print|console\.log|System\.out\.println|cout)\s*(\(|<<)", raw))


# ───────────────────────── curriculum index ─────────────────────────
STOP_IDENT = set(("list str string int float set dict tuple print main for while if else return new class public static void select from where and or not in is "
                  "x s lst arr a b n i j t d m v e k key value true false null none the of to by as on at it an do be count len num nums text word name item items obj").split())
SHEET = []
for _L in content.LANGUAGES:
    for _lv in _L["levels"]:
        for _row in _lv["lesson"].get("sheet") or []:
            if not _row or not _row[0]:
                continue
            _syntax, _meaning = _row[0], _row[1] if len(_row) > 1 else ""
            _idents = list(dict.fromkeys(w for w in re.findall(r"[a-z_][a-z0-9_]{2,}", str(_syntax).lower()) if w not in STOP_IDENT))
            SHEET.append({"lang": _L["id"], "level": _lv["level"], "title": _lv["title"], "syntax": _syntax, "meaning": _meaning, "idents": _idents})
LEVEL_WORDS = {w for _L in content.LANGUAGES for _lv in _L["levels"] for w in norm(_lv["title"] + " " + _lv["topic"]).strip().split(" ") if len(w) > 2}
_FIND_SKIP = {"what", "explain", "example", "quiz", "question", "python", "java", "javascript", "about", "with", "give", "part"}


def find_level(lang, n, keys=()):
    L = content.get_language(lang)
    if not L:
        return None
    best, best_score = None, 0
    m = re.search(r"\bpart (\d+)\b|\blevel (\d+)\b", n)
    wanted = int(m.group(1) or m.group(2)) if m else None
    for lv in L["levels"]:
        t = norm(lv["title"] + " " + lv["topic"])
        s = 0
        for w in words(n):
            if len(w) > 3 and w not in _FIND_SKIP and has(t, w):
                s += 2
        for k in keys:
            if " " + norm(k).strip() in t:
                s += 3
        if wanted == lv["level"]:
            s += 10
        if s > best_score:
            best, best_score = lv, s
    return best


# ───────────────────────── vocabulary (on-topic check) ─────────────────────────
STRONG = set(("code coding program programming programmer python java javascript c++ sql mysql sqlite database query syntax error bug debug compile compiler interpreter output "
              "function variable loop array list tuple dictionary recursion string integer boolean algorithm pattern oop class object method inheritance polymorphism pointer "
              "exception stack queue sort sorting search complexity ddl dml dql dcl tcl join schema table column row primary foreign constraint lambda closure promise async "
              "dsa data structure structure leetcode hackerrank iteration conditional operator operand datatype char float double long vector hashmap arraylist stl").split())
WEAK = set()
for _c in CONCEPTS:
    for _k in _c["keys"]:
        _kn = norm(_k).strip()
        (STRONG if " " in _kn else WEAK).add(_kn)
CONCEPT_SINGLE = set(WEAK)
for _r in SHEET:
    WEAK.update(_r["idents"])
WEAK.update(LEVEL_WORDS)


def on_topic_score(n) -> int:
    s = sum(2 for k in STRONG if has(n, k))
    s += sum(1 for w in words(n) if len(w) > 2 and w in WEAK)
    return s


# ───────────────────────── knowledge retrieval ─────────────────────────
def score_concept(c, n, lang) -> float:
    best = 0.0
    for k in c["keys"]:
        kn = norm(k).strip()
        if kn and f" {kn} " in n:
            best = max(best, 10 + len(kn.split(" ")) * 6 + len(kn) / 10)
    if not best:
        return 0
    if c.get("lang") and lang and c["lang"] != lang:
        best *= 0.55
    if lang and (c.get("code") or {}).get(lang):
        best += 2
    return best


def find_comparison(n):
    cmp_word = re.search(r"\b(difference|vs|versus|compare|comparison|better|between)\b", n)
    best, best_score = None, 0
    for v in COMPARISONS:
        hits = [any((t if t.startswith(" ") or t.endswith(" ") else " " + norm(t).strip() + " ") in n for t in syns) for syns in v["terms"]]
        if all(hits):
            s = len("".join(t for syns in v["terms"] for t in syns if " " + norm(t).strip() + " " in n))
            if s > best_score:
                best, best_score = v, s
    return best if best and (cmp_word or best_score > 12) else None


def sheet_matches(n, lang):
    ws = set(words(n))
    hits = [r for r in SHEET if any(i in ws or i.replace("_", "") in ws for i in r["idents"])]
    lang_hits = [r for r in hits if r["lang"] == lang] if lang else hits
    return lang_hits or hits


def pref_lang(user, no_sql=False) -> str:
    attempts = store.attempts_for(user["userId"])
    last = attempts[-1]["lang"] if attempts else None
    st = user.get("chatState") or {}
    for x in (st.get("lang"), last, user.get("goalLanguage"), "python"):
        if x and x in LANG and not (no_sql and x == "sql"):
            return x
    return "python"


def concept_answer(c, lang, n, user):
    code = c.get("code") or {}
    if lang and code.get(lang):
        L = lang
    elif c.get("lang"):
        L = c["lang"]
    elif code:
        pl = pref_lang(user)
        L = pl if pl in code else next(iter(code))
    else:
        L = None
    text = f"### {c['title']}\n{c['text']}"
    if L and code.get(L):
        text += f"\n\n**Example in {LANG[L]['name']}:**\n{fence(L, code[L])}"
    others = [k for k in code if k != L]
    actions = []
    LL = L or pref_lang(user)
    lvl = find_level(LL, n, c["keys"])
    wants_methods = bool(re.search(r"\b(method|function|built in|builtin|operation|command)\b", n)) and c["id"] not in ("functiontypes", "function")
    if wants_methods and lvl:
        sheet_rows = (lvl["lesson"].get("sheet") or [])[:14]
    else:
        sheet_rows = [[r["syntax"], r["meaning"]] for r in sheet_matches(n, L) if r["lang"] == L][:4]
    if sheet_rows and (wants_methods or re.search(r"what does|use of|how to use", n)):
        head = f"{LANG[LL]['name']} cheat sheet — Part {lvl['level']}: {lvl['title']}" if wants_methods and lvl else f"Quick reference ({LANG[L]['name']})"
        text += f"\n\n**{head}:**\n" + "\n".join(f"- `{row[0]}` — {row[1] if len(row) > 1 else ''}" for row in sheet_rows)
    if lvl:
        actions.append({"label": f"Open lesson: {LANG[LL]['name']} Part {lvl['level']}", "href": f"#/learn/{LL}/{lvl['level']}"})
        actions.append({"label": "Quiz me on this", "send": f"Quiz me on {LANG[LL]['name']} part {lvl['level']}"})
    for o in others[:3]:
        actions.append({"label": f"Show in {LANG[o]['name']}", "send": f"{c['keys'][0]} example in {LANG[o]['name']}"})
    return {"text": text, "actions": actions}


def sheet_answer(rows, lang):
    by_lang = {}
    for r in rows:
        by_lang.setdefault(r["lang"], []).append(r)
    langs = sorted(by_lang, key=lambda l: (0 if l == lang else 1, -len(by_lang[l]) if l != lang else 0))[: (1 if lang else 2)]
    text, actions = "", []
    for l in langs:
        lst = by_lang[l][:6]
        text += ("\n\n" if text else "") + f"**{LANG[l]['name']}** — from Part {lst[0]['level']}: {lst[0]['title']}\n" + "\n".join(f"- `{r['syntax']}` — {r['meaning']}" for r in lst)
        les = content.lesson(l, lst[0]["level"])
        if les and les.get("code") and len(langs) == 1:
            text += f"\n\n**Try it:**\n{fence(l, les['code'])}"
        actions.append({"label": f"Open lesson: {LANG[l]['name']} Part {lst[0]['level']}", "href": f"#/learn/{l}/{lst[0]['level']}"})
        actions.append({"label": "Quiz me on this", "send": f"Quiz me on {LANG[l]['name']} part {lst[0]['level']}"})
    if not lang and len(by_lang) > 1:
        text += '\n\n_Tell me the language (e.g. "…in Java") and I\'ll focus on it._'
    return {"text": text, "actions": actions}


# ───────────────────────── patterns ─────────────────────────
PATTERN_WORDS = [(re.compile(p), pid) for p, pid in [
    (r"inverted butterfly|bow ?tie", "hourglass"), (r"butterfly", "butterfly"), (r"rhombus|parallelogram", "rhombus"), (r"rainbow|\barch\b", "rainbow"), (r"heart", "heart"),
    (r"hourglass|sand ?glass|sand ?clock", "hourglass"), (r"diamond", "diamond"), (r"invert\w* (full )?pyramid|reverse pyramid|upside down pyramid", "invpyramid"),
    (r"pyramid|christmas tree|triangle pyramid", "pyramid"), (r"invert\w* mirror|invert\w* right align", "invmirror"), (r"mirror|right align|left triangle", "mirror"),
    (r"invert\w* (right|half|triangle)|reverse (right )?triangle|invert\w* half pyramid", "invright"), (r"hollow square|square frame|box pattern", "hollowsq"),
    (r"solid square|square pattern|square", "square"), (r"number (triangle|pattern)|floyd|123", "numtri"), (r"alphabet|letter|character pattern|abc", "alphatri"),
    (r"arrow|half diamond", "arrow"), (r"right (angle|angled)?\s*triangle|half pyramid|star triangle|triangle", "right"),
]]


def describe_rows(p) -> str:
    label = lambda ch: "spaces" if ch == " " else "numbers (the row number)" if ch == "num" else "letters" if ch == "alpha" else "stars"  # noqa: E731
    out = []
    for i, b in enumerate(p["blocks"]):
        parts = " + ".join(f"`{cnt}` {label(ch)}" for ch, cnt in b["parts"])
        if b.get("once"):
            out.append(f"- one row of {parts}")
        else:
            prefix = ("Upper part" if i == 0 else "Lower part") + ": " if len(p["blocks"]) > 1 else ""
            out.append(f"- {prefix}rows `i = {b['i'][0]} → {b['i'][1]}`: {parts}")
    return "\n".join(out)


def pattern_answer(n, lang, user):
    pid = next((p for rx, p in PATTERN_WORDS if rx.search(n)), None)
    p = patterns.get(pid) if pid else None
    target = lang if lang and lang != "sql" else pref_lang(user, True)
    if not p:
        intro = next(c for c in CONCEPTS if c["id"] == "patterns")["text"]
        return {"text": f"{intro}\n\nPick one:", "actions": [{"label": x, "send": f"{x} pattern in {LANG[target]['name']}"} for x in
                                                             ["Butterfly", "Rhombus", "Heart", "Diamond", "Pyramid", "Hourglass", "Rainbow", "Hollow square", "Number triangle"]]}
    L = target
    m = re.search(r"\bn ?= ?(\d+)\b|\b(\d+) (row|line)\b|\bsize (\d+)\b|\bof (\d+)\b", n)
    size = int(m.group(1) or m.group(2) or m.group(4) or m.group(5)) if m else (3 if p["id"] == "heart" else 4)
    size = max(p.get("minN") or 2, min(4 if p["id"] == "heart" else 9, size))
    style = "repeat" if re.search(r"\bshort|one line|repeat|without nested|simple\b", n) and not re.search(r"nested", n) else "loops"
    code = patterns.wrap_program(L, patterns.render(p, size, L, style))
    out = patterns.shape(p, size)
    text = (f"### {p['name']} pattern — {LANG[L]['name']} (n = {size})\n{fence(L, code)}\n**Output:**\n{fence('', chr(10).join(out))}\n"
            f"**How it works** — the outer loop prints one row per `i`; each row is:\n{describe_rows(p)}")
    if lang == "sql":
        text = f"_Pattern programs are written with loops, which SQL doesn't have — here it is in {LANG[L]['name']}._\n\n" + text
    other = [x for x in ("python", "javascript", "java", "cpp") if x != L]
    actions = [{"label": f"In {LANG[o]['name']}", "send": f"{p['name']} pattern in {LANG[o]['name']} n={size}"} for o in other]
    actions.append({"label": "Shorter version", "send": f"{p['name']} pattern in {LANG[L]['name']} short n={size}"} if style == "loops"
                   else {"label": "Nested-loop version", "send": f"{p['name']} pattern in {LANG[L]['name']} nested n={size}"})
    actions.append({"label": "Practise patterns", "href": f"#/lang/{L}"})
    return {"text": text, "actions": actions}


# ───────────────────────── classic programs ─────────────────────────
def find_program(n):
    if not re.search(r"\b(program|code|write|check|print|find|logic|algorithm|how to|series|number|example|solution|calculate|count|swap|reverse)\b", n):
        return None
    best, bs = None, 0
    for p in PROGRAMS:
        for k in p["keys"]:
            kn = norm(k).strip()
            if has(n, kn) and len(kn) > bs:
                best, bs = p, len(kn)
    return best


def program_answer(p, lang, user):
    pl = pref_lang(user, True)
    L = lang if lang and lang in p["code"] else pl if pl in p["code"] else "python"
    text = f"### {p['title']} — {LANG[L]['name']}\n{p['idea']}\n{fence(L, p['code'][L])}\n**Output:**\n{fence('', p['output'])}"
    return {"text": text, "actions": [{"label": f"In {LANG[o]['name']}", "send": f"{p['keys'][0]} program in {LANG[o]['name']}"} for o in p["code"] if o != L]}


# ───────────────────────── code review (built-in) ─────────────────────────
def review_code(raw, lang):
    m = re.search(r"```[a-z+]*\n?([\s\S]*?)```", raw, re.I)
    code = m.group(1) if m else raw
    notes = []
    for i, ln in enumerate(code.split("\n")):
        t, no = ln.strip(), i + 1
        if not t or re.match(r"^(#|//|--|/\*|\*)", t):
            continue
        if lang == "python":
            if re.match(r"^(if|elif|else|for|while|def|class|try|except|finally|with)\b", t) and not re.search(r":\s*(#.*)?$", t):
                notes.append(f"Line {no}: `{t}` must end with a colon `:`.")
            if re.match(r"^(if|elif|while)\b[^=!<>]*[^=!<>]=[^=]", t):
                notes.append(f"Line {no}: use `==` to compare — a single `=` is assignment.")
            if re.match(r"^else if\b", t):
                notes.append(f"Line {no}: Python uses `elif`, not `else if`.")
            if re.match(r"^print\s+[\"'\w]", t):
                notes.append(f"Line {no}: in Python 3, print needs parentheses: `print(...)`.")
            if re.search(r"\.(length|push)\b", t):
                notes.append(f"Line {no}: Python lists use `len(x)` and `.append()` (not `.length`/`.push`).")
            if re.search(r"&&|\|\||!(?!=)", t):
                notes.append(f"Line {no}: Python uses `and`, `or`, `not` instead of `&&`, `||`, `!`.")
        elif lang in ("java", "cpp", "javascript"):
            if (lang != "javascript" and not re.search(r"[;{}]\s*(//.*)?$", t)
                    and not re.match(r"^(if|else|for|while|do|switch|case|default|public|private|protected|class|#|template|try|catch|finally|@)", t)
                    and not re.search(r"[,(+\-*/&|]$", t)):
                notes.append(f"Line {no}: `{t[:60]}` looks like it is missing a semicolon `;`.")
            if re.match(r"^(if|while)\s*\([^=!<>]*[^=!<>]=[^=]", t):
                notes.append(f"Line {no}: `=` inside a condition assigns — did you mean `==`{' (or `===`)' if lang == 'javascript' else ''}?")
            if re.match(r"^(if|for|while)\s*\(.*\)\s*;$", t):
                notes.append(f"Line {no}: the `;` right after `{t.split('(')[0]}(...)` ends the statement — the block below will always run.")
            if lang == "java" and re.search(r"\bstring\s+\w+\s*=", t):
                notes.append(f"Line {no}: Java's type is `String` with a capital S.")
            if lang == "java" and re.search(r"\bsystem\.out", t):
                notes.append(f"Line {no}: it is `System.out` with a capital S.")
            if lang == "javascript" and re.search(r"[^=!]==[^=]", t):
                notes.append(f"Line {no}: prefer `===` over `==` to avoid type conversion surprises.")
            if re.search(r"\bfor\s*\(.*<=\s*\w+\.(length|size\(\))", t):
                notes.append(f"Line {no}: `<= length` goes one past the last index — use `<`.")
        elif lang == "sql":
            if re.search(r"=\s*null\b", t, re.I):
                notes.append(f"Line {no}: compare with `IS NULL` / `IS NOT NULL`, never `= NULL`.")
            if re.search(r'"[^"]*"', t) and re.search(r"where|values|set", t, re.I):
                notes.append(f"Line {no}: text values should use single quotes `'...'`.")
            if re.search(r"where[\s\S]*\b(count|sum|avg|max|min)\s*\(", t, re.I):
                notes.append(f"Line {no}: aggregate functions can't be used in WHERE — use HAVING after GROUP BY.")
    if lang == "python" and re.search(r"range\(\s*len\([^)]*\)\s*\+\s*1\s*\)", code):
        notes.append("`range(len(x) + 1)` goes one past the last index → IndexError.")
    if lang == "sql" and re.search(r"\bgroup by\b[\s\S]*\bwhere\b", code, re.I):
        notes.append("Clause order is SELECT → FROM → WHERE → GROUP BY → HAVING → ORDER BY; WHERE must come before GROUP BY.")
    defs = [a or b or c for a, b, c in re.findall(r"\bdef\s+(\w+)|function\s+(\w+)|\b(?:int|void|long|double|static \w+|bool|string|String)\s+(\w+)\s*\(", code)]
    defs = [d for d in defs if d and d != "main"]
    recursive = [f for f in defs if len(re.findall(rf"\b{re.escape(f)}\s*\(", code)) >= 2
                 and re.search(rf"\b{re.escape(f)}\s*\([^)]*\)[\s\S]*\b{re.escape(f)}\s*\(", code)]
    uses = []
    if re.search(r"\bfor\b", code):
        uses.append("a **for loop**")
    if re.search(r"\bwhile\b", code):
        uses.append("a **while loop**")
    if re.search(r"\b(if|elif|else)\b|\?.*:", code):
        uses.append("**conditions**")
    if defs:
        uses.append(f"{'functions' if len(defs) > 1 else 'a function'} {', '.join(f'`{d}`' for d in defs)}")
    if recursive:
        uses.append(f"**recursion** (`{recursive[0]}` calls itself — make sure the base case is reached)")
    if re.search(r"\bclass\b", code):
        uses.append("a **class**")
    if re.search(r"\[.*\]", code) and lang == "python":
        uses.append("**lists / indexing**")
    if lang == "sql":
        kw = re.findall(r"\b(join|group by|having|order by)\b", code, re.I)
        if kw:
            uses.append(", ".join(dict.fromkeys(f"`{x.upper()}`" for x in kw)))
    text = f"I read your {LANG[lang]['name'] + ' ' if lang else ''}code."
    if uses:
        text += f" It uses {', '.join(uses)}."
    uniq = list(dict.fromkeys(notes))[:8]
    text += ("\n\n**Things to fix:**\n" + "\n".join(f"- {x}" for x in uniq)) if uniq else \
        "\n\nI don't see any of the common mistakes (missing colons/semicolons, `=` vs `==`, off-by-one loops)."
    text += "\n\n_Tip: I can't run code in this chat. Paste the exact error message you get and I'll explain it, or ask me about any concept used above._"
    return {"text": text}


# ───────────────────────── quiz (from the verified question bank) ─────────────────────────
def current_level(user, lang) -> int:
    L = content.get_language(lang)
    if not L:
        return 1
    prog = (user.get("progress") or {}).get(lang) or {}
    lv = next((x for x in L["levels"] if not (prog.get(str(x["level"])) or {}).get("passed")), None)
    return lv["level"] if lv else L["levels"][-1]["level"]


def make_quiz(user, lang, level):
    lv = content.get_level(lang, level)
    qs = [q for q in lv["questions"] if q["type"] in ("mcq", "output") and isinstance(q.get("options"), list) and 2 <= len(q["options"]) <= 6]
    st = user["chatState"]
    recent = set(st.get("recentQuiz") or [])
    fresh = [q for q in qs if q["id"] not in recent]
    q = pick(fresh or qs)
    order = shuffled(range(len(q["options"])))
    st["quiz"] = {"lang": lang, "level": lv["level"], "qid": q["id"], "order": order, "at": now_ms()}
    st["lastQuiz"] = {"lang": lang, "level": lv["level"]}
    st["recentQuiz"] = ((st.get("recentQuiz") or []) + [q["id"]])[-40:]
    return {"text": f"Here's a practice question from **{LANG[lang]['name']} · Part {lv['level']}: {lv['title']}** _(practice only — it doesn't affect your score)_:",
            "quiz": {"prompt": q["prompt"], "code": q.get("code") or "", "codeLang": LANG[lang]["fence"],
                     "options": [str(q["options"][i]) for i in order], "letters": list(LETTERS[:len(order)])}}


def quiz_answer(user, raw):
    st = user["chatState"]["quiz"]
    if not st:
        return None
    q = content.get_question(st["lang"], st["level"], st["qid"])
    if not q:
        user["chatState"]["quiz"] = None
        return None
    t = raw.strip()
    m = re.match(r"^\s*(?:option\s*|answer\s*(?:is\s*)?)?([a-h]|[1-8])\s*[.)]?\s*$", t, re.I)
    if m:
        idx = int(m.group(1)) - 1 if m.group(1).isdigit() else LETTERS.find(m.group(1).upper())
    else:
        opts = [str(q["options"][i]).strip().lower() for i in st["order"]]
        idx = opts.index(t.lower()) if t.lower() in opts else -1
    if idx < 0 or idx >= len(st["order"]):
        return None
    chosen = st["order"][idx]
    correct_pos = st["order"].index(q["answer"])
    ok = chosen == q["answer"]
    user["chatState"]["quiz"] = None
    s = user["chatState"].setdefault("quizScore", {"right": 0, "total": 0})
    s["total"] += 1
    if ok:
        s["right"] += 1
    head = (f"**Correct!** {pick(['Nice work.', 'Well done!', 'Exactly right.', 'Spot on!'])}" if ok else
            f"**Not quite.** The right answer is **{LETTERS[correct_pos]}** → `{str(q['options'][q['answer']]).split(chr(10))[0]}`.")
    text = head + (f"\n\n{q['explain']}" if q.get("explain") else "") + f"\n\n_Chat quiz score: {s['right']}/{s['total']}_"
    return {"text": text, "actions": [{"label": "Another question", "send": "Another question"},
                                      {"label": "Explain this topic", "send": f"Explain {q['topic'].replace('-', ' ')} in {LANG[st['lang']]['name']}"},
                                      {"label": f"Play {LANG[st['lang']]['name']} Part {st['level']}", "href": f"#/learn/{st['lang']}/{st['level']}"}]}


# ───────────────────────── progress ─────────────────────────
def progress_answer(user):
    r = agent_mod.report(user)
    o = r["overview"]
    st = o["streak"]["current"]
    lines = [f"Here's your progress, {display_name(user)}:", "",
             f"- **{o['xp']} XP** · rank **{o['rank']['title']}**" + (f" ({o['rank']['next'] - o['xp']} XP to {o['rank']['nextTitle']})" if o["rank"]["next"] else ""),
             f"- **{o['gamesPlayed']}** games · **{o['accuracy']}%** accuracy · **{o['levelsPassed']}/{o['totalLevels']}** parts passed · streak **{st}** day{'' if st == 1 else 's'}"]
    started = [l for l in r["languages"] if l["status"] != "not-started"]
    if started:
        lines.append("- Languages: " + ", ".join(f"{l['name']} {l['skill']}% ({l['levelsPassed']}/{l['totalLevels']} parts)" for l in started))
    if r["topics"]["weak"]:
        lines.append("- Needs practice: " + ", ".join(f"{t['langName']} · {t['topic']} ({t['pct']}%)" for t in r["topics"]["weak"][:3]))
    if r["topics"]["strong"]:
        lines.append("- Strong at: " + ", ".join(f"{t['langName']} · {t['topic']}" for t in r["topics"]["strong"][:3]))
    if r["recommendations"]:
        lines += ["", f"**My suggestion:** {r['recommendations'][0]['text']}"]
    actions = []
    for x in [x for x in r["recommendations"] if x.get("lang")][:2]:
        nm = content.get_language(x["lang"])["name"]
        actions.append({"label": f"{'Revise' if x['kind'] == 'revise' else 'Play'} {nm} Part {x['level']}", "href": f"#/learn/{x['lang']}/{x['level']}"})
    if r["topics"]["weak"]:
        w = r["topics"]["weak"][0]
        actions.append({"label": f"Explain {w['topic']}", "send": f"Explain {w['topic']} in {w['langName']}"})
    actions.append({"label": "Full agent report", "href": "#/agent"})
    return {"text": "\n".join(lines), "actions": actions}


# ───────────────────────── suggestions & help ─────────────────────────
def suggestions(user) -> list[str]:
    L = LANG[pref_lang(user)]["name"]
    Lc = LANG[pref_lang(user, True)]["name"]
    return [f"Explain recursion in {Lc}", f"Butterfly pattern in {Lc}", "Types of functions", "Difference between list and tuple",
            "DELETE vs TRUNCATE vs DROP", f"Quiz me on {L}", "How am I doing?"]


def help_text(a) -> str:
    return (f"I'm **{a['name']}**, your {a['title'].lower()}. Ask me anything about what you're learning here — **Python, JavaScript, Java, C++ and SQL**:\n"
            '- concepts: *"what is a tuple"*, *"explain joins"*, *"types of recursion"*\n'
            '- methods: *"what does strip() do"*, *"ArrayList methods"*\n'
            '- comparisons: *"list vs tuple"*, *"WHERE vs HAVING"*\n'
            '- pattern programs: *"heart pattern in Java"*\n'
            "- errors: paste an error message or your code\n"
            '- practice: *"quiz me on Python strings"*\n'
            '- your progress: *"how am I doing?"*')


def system_prompt(user, a) -> str:
    r = agent_mod.report(user)
    o = r["overview"]
    curriculum = "\n".join(f"{l['name']}: " + "; ".join(f"P{lv['level']} {lv['title']}" for lv in l["levels"]) for l in content.LANGUAGES)
    started = "; ".join(f"{l['name']} {l['skill']}% skill, {l['levelsPassed']}/{l['totalLevels']} parts" for l in r["languages"] if l["status"] != "not-started") or "none yet"
    weak = ", ".join(f"{t['langName']} {t['topic']} {t['pct']}%" for t in r["topics"]["weak"]) or "none detected yet"
    nxt = r["recommendations"][0]["text"] if r["recommendations"] else "start any language Part 1"
    goal = LANG.get(user.get("goalLanguage") or "", {}).get("name", "not chosen")
    return f"""You are {a['name']}, the "{a['title']}" — the personal coding agent of {user['fullName']} on Syntaxo, a platform where students learn programming by playing games, part by part.

PERSONALITY: warm, encouraging, clear. Match the student's level (they are learners, often beginners). Address them by name ({display_name(user)}) occasionally.

SCOPE — only help with the subjects taught here: Python, JavaScript, Java, C++, SQL, and general programming topics (logic, data structures & algorithms basics, OOP, debugging, pattern programs, databases, how to study coding, coding interview prep). If the student asks about anything unrelated (general knowledge, news, entertainment, personal advice, other school subjects, etc.), politely say you can only help with programming and the subjects on Syntaxo, and suggest a related coding question instead. Never write harmful code.

STYLE:
- Be concise: usually under 200 words. Start with the direct answer, then a short example.
- Use Markdown: **bold**, bullet lists, and fenced code blocks with the language (```python, ```java, ```cpp, ```javascript, ```sql). Show the expected output of code when helpful.
- When they share code: point out the exact bug and line, then show the fixed code.
- For pattern problems: give the code and the printed output.
- If they ask for a practice question, you may ask one multiple-choice question and wait for their answer.
- Relate answers to their curriculum when useful (e.g. "this is covered in Python Part 3").

STUDENT CONTEXT (from your tracking):
- Rank {o['rank']['title']}, {o['xp']} XP, {o['gamesPlayed']} games, {o['accuracy']}% accuracy, streak {o['streak']['current']} days.
- Languages: {started}. First-choice language: {goal}.
- Weak topics: {weak}.
- Next step you recommended: {nxt}.

CURRICULUM (parts per language):
{curriculum}"""


# ───────────────────────── main entry ─────────────────────────
GREETING = re.compile(r"^ (hi+|hello+|hey+|hii+|helo|namaste|namaskar|good (morning|afternoon|evening)|yo|hola|sup) ")
THANKS = re.compile(r"\b(thank|thanks|thx|ty|thank you|great|awesome|nice|cool|ok|okay|got it)\b")
WHO = re.compile(r"\b(who are you|what can you do|your name|what do you do|help me use|how to use this chat)\b")
PROGRESS = re.compile(r"\b(my (progress|score|stats|statistic|xp|rank|streak|performance|report|level)|how am i doing|how i am doing|weak (topic|area|spot)|strong topic|"
                      r"what should i (learn|study|practice|practise|do|play)|what next|next step|where should i start|recommend me|suggest me)\b")
QUIZ = re.compile(r"\b(quiz|test me|ask me|mcq|practice question|practise question|challenge me|give me (a |an |one |some )?(question|problem|challenge|mcq)|another question|next question|one more)\b")
AGAIN = re.compile(r"\b(another|next|one more)\b")


def reply(user, message) -> dict:
    """→ {text, actions?: [{label, href | send}], quiz?: {prompt, code, codeLang, options, letters}, source}"""
    raw = str(message or "")[:4000]
    n = norm(raw)
    a = agent_mod.get_agent(user["agent"]["agentId"])
    st = user.setdefault("chatState", {})
    if not isinstance(st, dict):
        st = user["chatState"] = {}
    explicit = detect_lang(n, raw)
    if explicit:
        st["lang"] = explicit
    lang = explicit or st.get("lang") or None
    wc = len(words(n))

    # 1. pending quiz answer
    if st.get("quiz"):
        r = quiz_answer(user, raw)
        if r:
            return {**r, "source": "built-in"}
        if now_ms() - st["quiz"]["at"] > 30 * 60000 or wc > 2:
            st["quiz"] = None
    # 2. greetings / thanks / help
    if wc <= 4 and GREETING.match(n):
        body = re.sub(r"^I'm \*\*\w+\*\*, your [^.]+\. ", "", help_text(a))
        return {"text": f"{pick(['Hi', 'Hello', 'Hey'])} {display_name(user)}! {body}", "actions": [{"label": s, "send": s} for s in suggestions(user)[:5]], "source": "built-in"}
    if wc <= 6 and THANKS.search(n) and "?" not in raw:
        return {"text": pick([f"You're welcome, {display_name(user)}! Anything else you want to learn?", "Happy to help! Want a quick practice question?", "Anytime! Keep that streak going."]),
                "actions": [{"label": "Quiz me", "send": f"Quiz me on {LANG[pref_lang(user)]['name']}"}, {"label": "How am I doing?", "send": "How am I doing?"}], "source": "built-in"}
    if WHO.search(n) or n.strip() == "help":
        return {"text": help_text(a), "actions": [{"label": s, "send": s} for s in suggestions(user)], "source": "built-in"}
    # 3. progress
    if PROGRESS.search(n):
        return {**progress_answer(user), "source": "built-in"}
    # 4. quiz
    if QUIZ.search(n):
        again = AGAIN.search(n)
        L = explicit or (again and (st.get("lastQuiz") or {}).get("lang")) or pref_lang(user)
        lvl = find_level(L, n)
        if not lvl and again and st.get("lastQuiz") and st["lastQuiz"]["lang"] == L:
            lvl = content.get_level(L, st["lastQuiz"]["level"])
        if not lvl:
            lvl = content.get_level(L, current_level(user, L))
        return {**make_quiz(user, L, lvl["level"]), "source": "built-in"}
    # 5. pattern programs (verified generator)
    cmp = find_comparison(n)
    if (not cmp and (has(n, "pattern") or re.search(r"\b(butterfly|rhombus|heart|diamond|pyramid|hourglass|rainbow)\b", n))
            and not re.search(r"\bdesign pattern|singleton|factory pattern|regex|regular expression|like\b.*\bpattern\b", n)):
        return {**pattern_answer(n, explicit, user), "source": "built-in"}
    # 5b. classic programs (verified code in 4 languages)
    prog = find_program(n)
    if prog and not cmp:
        return {**program_answer(prog, explicit, user), "source": "built-in"}
    # 6. AI model for everything else (when configured)
    if llm.configured():
        try:
            history = []
            for m in user.get("chat") or []:
                q = m.get("quiz")
                txt = (f"{m['text']}\n{q['prompt']}\n{q.get('code') or ''}\n" + "\n".join(f"{q['letters'][i]}) {o}" for i, o in enumerate(q["options"]))) if q else m["text"]
                history.append({"role": m["role"], "text": txt})
            text = llm.chat(system_prompt(user, a), history, raw)
            if text:
                return {"text": text, "source": "ai"}
        except Exception as e:  # noqa: BLE001
            log.error(f"[chat] AI provider failed, using built-in tutor: {e}")
    return {**built_in(user, raw, n, lang, explicit, cmp, a), "source": "built-in"}


def built_in(user, raw, n, lang, explicit, cmp, a):
    # errors pasted
    err = next((e for e in ERRORS if e["re"].search(raw)), None)
    if err:
        text = f"### {err['title']}\n{err['text']}"
        cl = code_lang(raw)
        if looks_like_code(raw) and cl:
            text += f"\n\n---\n{review_code(raw, cl)['text']}"
        return {"text": text, "actions": [{"label": "Show common mistakes", "send": f"common mistakes in {LANG[err.get('lang') or lang or 'python']['name']}"}]}
    # comparisons
    if cmp:
        acts = [{"label": f"Explain {t[0].strip()}", "send": f"Explain {t[0].strip()}{' in ' + LANG[lang]['name'] if lang else ''}"}
                for t in cmp["terms"] if re.search(r"[a-z]", t[0])][:2]
        return {"text": f"### {cmp['title']}\n{cmp['text']}", "actions": acts}
    # code pasted → review
    if looks_like_code(raw) and (code_lang(raw) or lang):
        return review_code(raw, code_lang(raw) or lang)
    # common mistakes
    if re.search(r"\bcommon (mistake|error)|beginner mistake\b", n):
        L = lang or "python"
        lst = [e for e in ERRORS if not e.get("lang") or e["lang"] == L][:8]
        return {"text": f"**Common {LANG[L]['name']} errors:**\n" + "\n".join(f"- **{e['title']}** — {e['text'].split(chr(10))[0]}" for e in lst)
                        + "\n\nPaste any error message and I'll explain it."}
    # concepts + cheat-sheet methods
    scored = sorted(((c, score_concept(c, n, lang)) for c in CONCEPTS), key=lambda x: -x[1])
    scored = [x for x in scored if x[1] > 0]
    rows = sheet_matches(n, lang)
    top = scored[0] if scored else None
    multi_word_hit = bool(top and top[1] >= 22)
    method_q = bool(re.search(r"\b(what does|what is the use of|use of|how to use|how does|method|meaning of|syntax of)\b", n)
                    or re.search(r"\w\s*\(\s*\)|\.\w+\(", raw) or len(words(n)) <= 5)
    specific = [r for r in rows if any(has(n, i) and i not in CONCEPT_SINGLE for i in r["idents"])]

    def focus(lst):
        pl = pref_lang(user)
        return explicit or lang or (pl if any(r["lang"] == pl for r in lst) else None)

    if specific and method_q and not multi_word_hit:
        return sheet_answer(specific, focus(specific))
    if top:
        return concept_answer(top[0], explicit or lang, n, user)
    if rows:
        return sheet_answer(rows, focus(rows))

    # on-topic but unknown → point to lessons; off-topic → politely decline
    ots = on_topic_score(n)
    on_topic = ots >= 2 or (explicit and ots >= 1) or looks_like_code(raw)
    if not on_topic:
        return {"text": f"I'm {a['name']}, your coding agent, so I can only help with **programming** — Python, JavaScript, Java, C++, SQL, logic, "
                        f"data structures and your progress here. Try asking me something like:",
                "actions": [{"label": s, "send": s} for s in suggestions(user)[:5]]}
    L = lang or pref_lang(user)
    lvl = find_level(L, n)
    les = content.lesson(L, lvl["level"]) if lvl else None
    if les:
        return {"text": f"I don't have a ready answer for that exact question, but it's related to **{LANG[L]['name']} Part {lvl['level']}: {lvl['title']}**:\n\n"
                        f"{les['summary']}\n\n{fence(L, les['code']) if les.get('code') else ''}",
                "actions": [{"label": f"Open lesson Part {lvl['level']}", "href": f"#/learn/{L}/{lvl['level']}"},
                            {"label": "Quiz me on this", "send": f"Quiz me on {LANG[L]['name']} part {lvl['level']}"}]}
    return {"text": 'I\'m not sure about that one yet. Try rephrasing with the concept name (for example *"explain dictionary in Python"* or *"what is a foreign key"*), or pick a topic:',
            "actions": [{"label": s, "send": s} for s in suggestions(user)]}


# ───────────────────────── history helpers ─────────────────────────
def push_history(user, entry):
    chat = user.setdefault("chat", [])
    chat.append({**entry, "at": iso()})
    if len(chat) > MAX_HISTORY:
        del chat[: len(chat) - MAX_HISTORY]


def mode() -> dict:
    p = llm.provider()
    return {"mode": "ai", "provider": p["id"], "model": p["model"]} if p else {"mode": "built-in"}
