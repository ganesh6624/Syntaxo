"""
Validate the question bank (core/data/pool.json).

    python manage.py check_questions          # structure: fields, options, answers, duplicates, counts
    python manage.py check_questions --run    # also re-run every Python "What does this code print?" question

Exit code 1 when a problem is found.
"""
import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core import content

POOL = Path(__file__).resolve().parents[2] / "data" / "pool.json"
TYPES = {"mcq", "output", "fill", "bug", "order"}

# runs a batch of snippets in a child process, 3 s limit each; prints JSON {id: stdout | "!ErrorName"}
_RUNNER = r'''
import sys, json, io, contextlib, signal
jobs = json.load(open(sys.argv[1])); res = {}
class TO(Exception): pass
def h(s, f): raise TO()
signal.signal(signal.SIGALRM, h)
for j in jobs:
    buf = io.StringIO()
    try:
        signal.alarm(3)
        with contextlib.redirect_stdout(buf):
            exec(compile(j["code"], "<q>", "exec"), {"__name__": "__main__"})
        res[j["id"]] = buf.getvalue()
    except BaseException as e:
        res[j["id"]] = "!" + type(e).__name__
    finally:
        signal.alarm(0)
print(json.dumps(res))
'''


def norm(s):
    return "\n".join(l.rstrip() for l in str(s).replace("\r", "").split("\n")).strip("\n")


class Command(BaseCommand):
    help = "Validate the question bank and optionally re-run the Python output questions."

    def add_arguments(self, parser):
        parser.add_argument("--run", action="store_true", help="execute Python output questions and compare with the stored answer")

    def handle(self, *args, **opts):
        levels = json.loads(POOL.read_text(encoding="utf-8"))["levels"]
        problems, ids = [], collections.Counter()
        for key, qs in levels.items():
            for q in qs:
                ids[q.get("id")] += 1
                where = f"{key} {q.get('id')}"
                for f in ("id", "topic", "type", "prompt"):
                    if not q.get(f):
                        problems.append(f"{where}: missing {f}")
                if q.get("type") not in TYPES:
                    problems.append(f"{where}: unknown type {q.get('type')!r}")
                if q.get("type") == "fill":
                    if not q.get("answer") and q.get("answer") != 0:
                        problems.append(f"{where}: fill question without answer")
                    continue
                opts_ = q.get("options") or []
                if len(opts_) < 2:
                    problems.append(f"{where}: fewer than 2 options")
                    continue
                if len({norm(o) for o in opts_}) != len(opts_):
                    problems.append(f"{where}: duplicate options")
                a = q.get("answer")
                if not isinstance(a, int) or not 0 <= a < len(opts_):
                    problems.append(f"{where}: answer index {a!r} out of range")
        problems += [f"duplicate id {i} ×{n}" for i, n in ids.items() if n > 1]

        # every part the game shows must have enough questions for varied rounds
        for lang in content.LANGUAGES:
            for lv in lang["levels"]:
                n = len(lv["questions"])
                if n < 100:
                    problems.append(f"{lang['id']} part {lv['level']}: only {n} questions")

        if opts["run"]:
            problems += self.run_python(levels)

        total = sum(len(v) for v in levels.values())
        for p in problems[:60]:
            self.stdout.write(self.style.ERROR("✗ " + p))
        s = content.stats()
        self.stdout.write(f"{total} questions in {len(levels)} parts · shown in the game: {s}")
        if problems:
            raise CommandError(f"{len(problems)} problem(s) found")
        self.stdout.write(self.style.SUCCESS("Question bank OK"))

    def run_python(self, levels):
        jobs = [{"id": q["id"], "code": q["code"], "want": norm(q["options"][q["answer"]])}
                for k, qs in levels.items() if k.startswith("python:") for q in qs
                if q.get("type") == "output" and q.get("code") and q.get("options")]
        with tempfile.TemporaryDirectory() as d:
            inp, runner = Path(d, "jobs.json"), Path(d, "run.py")
            inp.write_text(json.dumps(jobs), encoding="utf-8")
            runner.write_text(_RUNNER, encoding="utf-8")
            out = json.loads(subprocess.run([sys.executable, str(runner), str(inp)], capture_output=True, text=True, timeout=900, cwd=d).stdout)
        bad = []
        for j in jobs:
            got = out.get(j["id"], "")
            if got.startswith("!"):
                # questions whose answer is an error ("TypeError", "Error: …") are expected to fail
                if got[1:].lower() not in j["want"].lower() and "error" not in j["want"].lower():
                    bad.append(f"{j['id']}: raised {got[1:]} but answer is {j['want']!r}")
            elif norm(got) != j["want"] and not (norm(got) == "" and j["want"] == "(empty line)"):  # label the game shows for blank output
                bad.append(f"{j['id']}: prints {norm(got)!r} but answer is {j['want']!r}")
        self.stdout.write(f"re-ran {len(jobs)} Python output questions, {len(bad)} mismatch(es)")
        return bad
