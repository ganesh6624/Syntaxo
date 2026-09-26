"""
Run every classic program the agent can show (core/data/programs.json) in Python, JavaScript, Java and C++,
check that all four print exactly the same thing, and store that output (the chat shows it under "Output").

    python manage.py verify_programs            # uses whichever compilers are installed (python3 always)
    python manage.py verify_programs --dry-run  # check only, don't rewrite programs.json

The JavaScript / Java / C++ examples are only run if that language's compiler/runtime is installed on the
computer (node, javac/java, g++); otherwise they are skipped. The web app itself never needs them.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

FILE = Path(__file__).resolve().parents[2] / "data" / "programs.json"

RUNNERS = {
    "python": ("a.py", [], ["python3", "a.py"], "python3"),
    "javascript": ("a.js", [], ["node", "a.js"], "node"),
    "java": ("Main.java", [["javac", "Main.java"]], ["java", "-cp", ".", "Main"], "javac"),
    "cpp": ("a.cpp", [["g++", "-O0", "-o", "a", "a.cpp"]], ["./a"], "g++"),
}


def clean(s: str) -> str:
    return "\n".join(l.rstrip() for l in s.replace("\r", "").split("\n")).strip()


class Command(BaseCommand):
    help = "Run the chat tutor's classic programs in all 4 languages and verify their outputs match."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        programs = json.loads(FILE.read_text(encoding="utf-8"))
        available = {lang for lang, r in RUNNERS.items() if shutil.which(r[3])}
        for lang in sorted(set(RUNNERS) - available):
            self.stdout.write(self.style.WARNING(f"! {lang} toolchain not found — skipped"))
        if "python" not in available:
            raise CommandError("python3 is required (its output is the reference).")
        bad = 0
        for p in programs:
            outs = {}
            with tempfile.TemporaryDirectory(prefix="prog-") as d:
                try:
                    for lang in RUNNERS:
                        if lang not in available:
                            continue
                        fname, builds, run, _ = RUNNERS[lang]
                        Path(d, fname).write_text(p["code"][lang], encoding="utf-8")
                        for b in builds:
                            subprocess.run(b, cwd=d, check=True, capture_output=True, timeout=120)
                        outs[lang] = clean(subprocess.run(run, cwd=d, check=True, capture_output=True, timeout=60, text=True).stdout)
                except subprocess.SubprocessError as e:
                    bad += 1
                    err = getattr(e, "stderr", b"") or b""
                    self.stdout.write(self.style.ERROR(f"✗ {p['id']} failed to run: {(err.decode() if isinstance(err, bytes) else err)[:400]}"))
                    continue
            ref = outs["python"]
            diff = [k for k, v in outs.items() if v != ref]
            if diff:
                bad += 1
                self.stdout.write(self.style.ERROR(f"✗ {p['id']} differs in {', '.join(diff)}"))
                for k in diff:
                    self.stdout.write(f"   {k}: {outs[k]!r}\n   python: {ref!r}")
            else:
                self.stdout.write(f"✓ {p['id']}")
                p["output"] = ref
        if not opts["dry_run"]:
            FILE.write_text(json.dumps(programs, ensure_ascii=False, indent=1), encoding="utf-8")
        msg = f"{len(programs) - bad}/{len(programs)} programs verified in {', '.join(sorted(available))}"
        if bad:
            raise CommandError(msg)
        self.stdout.write(self.style.SUCCESS(msg))
