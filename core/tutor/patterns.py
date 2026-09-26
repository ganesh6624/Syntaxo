"""
Pattern programs (star / number / alphabet patterns) for Python, JavaScript, Java and C++.

Every pattern is described once as loop "blocks" (core/data/patterns.json); code is rendered per
language in two styles:
  • repeat — string repetition ("*" * i, "*".repeat(i), string(i, '*'))
  • loops  — classic nested loops that print one character at a time
`shape()` computes the exact output, so the chat always shows code + its real output.
"""
import json
import re
from pathlib import Path

PATTERNS = json.loads((Path(__file__).resolve().parent.parent / "data" / "patterns.json").read_text(encoding="utf-8"))
_EXPR_OK = re.compile(r"^[\dni\s()+\-*]+$")


def _ev(expr: str, n: int, i: int) -> int:
    if not _EXPR_OK.match(expr):
        raise ValueError(f"bad pattern expression: {expr}")
    return eval(expr, {"__builtins__": {}}, {"n": n, "i": i})  # noqa: S307 — whitelisted arithmetic only


def _ch_for(kind: str, i: int) -> str:
    return str(i) if kind == "num" else chr(64 + i) if kind == "alpha" else kind


def shape(p: dict, n: int) -> list[str] | None:
    """Evaluate a pattern spec → list of printed lines (trailing spaces removed)."""
    lines = []
    for b in p["blocks"]:
        if b.get("once"):
            rows = [None]
        else:
            a, z, step = _ev(b["i"][0], n, 0), _ev(b["i"][1], n, 0), b["i"][2]
            rows = list(range(a, z + 1)) if step > 0 else list(range(a, z - 1, -1))
        for i in rows:
            line = ""
            for ch, cnt in b["parts"]:
                k = _ev(cnt, n, i if i is not None else 0)
                if k < 0:
                    return None
                line += _ch_for(ch, i if i is not None else 0) * k
            lines.append(line.rstrip())
    return lines


# ── code rendering ──
def _paren(e):
    return f"({e})" if " " in e else e


def _plus_one(e):
    if e.isdigit():
        return str(int(e) + 1)
    return e[:-4] if e.endswith(" - 1") else f"{e} + 1"


def _minus_one(e):
    if e.isdigit():
        return str(int(e) - 1)
    return e[:-4] if e.endswith(" + 1") else f"{e} - 1"


def _py_range(b):
    a, z, s = b["i"]
    if s > 0:
        return f"range({_plus_one(z)})" if a == "0" else f"range({a}, {_plus_one(z)})"
    return f"range({a}, {_minus_one(z)}, -1)"


def _c_loop(b, lang):
    a, z, s = b["i"]
    t = "let" if lang == "javascript" else "int"
    return f"for ({t} i = {a}; i <= {z}; i++)" if s > 0 else f"for ({t} i = {a}; i >= {z}; i--)"


def _part_repeat(lang, ch, cnt):
    if lang == "python":
        s = "str(i)" if ch == "num" else "chr(64 + i)" if ch == "alpha" else f'"{ch}"'
        return s if cnt == "1" else f"{s} * {_paren(cnt)}"
    if lang == "javascript":
        s = "String(i)" if ch == "num" else "String.fromCharCode(64 + i)" if ch == "alpha" else f'"{ch}"'
        return s if cnt == "1" else f"{s}.repeat({cnt})"
    if lang == "java":
        s = "String.valueOf(i)" if ch == "num" else "String.valueOf((char) (64 + i))" if ch == "alpha" else f'"{ch}"'
        return s if cnt == "1" else f"{s}.repeat({cnt})"
    c = "char('0' + i)" if ch == "num" else "char('A' + i - 1)" if ch == "alpha" else f"'{ch}'"
    return f"string({cnt}, {c})"


def _row_repeat(lang, parts):
    e = " + ".join(_part_repeat(lang, ch, cnt) for ch, cnt in parts)
    return {"python": f"print({e})", "javascript": f"console.log({e});", "java": f"System.out.println({e});", "cpp": f"cout << {e} << endl;"}[lang]


def _row_loops(lang, parts, ind):
    out = []
    for ch, cnt in parts:
        if lang == "python":
            c = "i" if ch == "num" else "chr(64 + i)" if ch == "alpha" else f'"{ch}"'
        elif lang == "javascript":
            c = "i" if ch == "num" else "String.fromCharCode(64 + i)" if ch == "alpha" else f'"{ch}"'
        elif lang == "java":
            c = "i" if ch == "num" else "(char) (64 + i)" if ch == "alpha" else f'"{ch}"'
        else:
            c = "i" if ch == "num" else "char('A' + i - 1)" if ch == "alpha" else f'"{ch}"'
        put = {"python": f'print({c}, end="")', "javascript": f"row += {c};", "java": f"System.out.print({c});", "cpp": f"cout << {c};"}[lang]
        if cnt == "1":
            out.append(ind + put)
        elif lang == "python":
            out += [f"{ind}for j in range({cnt}):", f"{ind}    {put}"]
        else:
            out.append(f"{ind}for ({'let' if lang == 'javascript' else 'int'} j = 0; j < {cnt}; j++) {put}")
    if lang == "python":
        out.append(f"{ind}print()")
    elif lang == "javascript":
        out = [f'{ind}let row = "";'] + out + [f"{ind}console.log(row);"]
    else:
        out.append(ind + ("System.out.println();" if lang == "java" else "cout << endl;"))
    return out


def render(p: dict, n: int, lang: str, style: str = "loops") -> str:
    """Program body (without the Java class / C++ main wrapper) that prints the pattern."""
    ind1 = "  " if lang == "javascript" else "    "
    lines = [f"n = {n}" if lang == "python" else f"const n = {n};" if lang == "javascript" else f"int n = {n};"]
    for b in p["blocks"]:
        parts = [tuple(x) for x in b["parts"]]
        if b.get("once"):
            if style == "repeat":
                lines.append(_row_repeat(lang, parts))
            elif lang == "javascript":
                lines += ["{", *_row_loops(lang, parts, ind1), "}"]
            else:
                lines += _row_loops(lang, parts, "")
            continue
        body = [ind1 + _row_repeat(lang, parts)] if style == "repeat" else _row_loops(lang, parts, ind1)
        if lang == "python":
            lines += [f"for i in {_py_range(b)}:", *body]
        else:
            lines += [f"{_c_loop(b, lang)} {{", *body, "}"]
    return "\n".join(lines)


def wrap_program(lang: str, body: str) -> str:
    ind = lambda s, k: "\n".join(" " * k + l for l in s.split("\n"))  # noqa: E731
    if lang == "java":
        return f"public class Main {{\n    public static void main(String[] args) {{\n{ind(body, 8)}\n    }}\n}}"
    if lang == "cpp":
        return f"#include <iostream>\nusing namespace std;\n\nint main() {{\n{ind(body, 4)}\n    return 0;\n}}"
    return body


def get(pattern_id: str) -> dict | None:
    return next((p for p in PATTERNS if p["id"] == pattern_id), None)
