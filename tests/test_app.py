"""
Syntaxo test-suite.   Run:  python manage.py test tests
(Uses a throw-away in-memory database — your real data is never touched.)
"""
import contextlib
import io
import re

from django.core.cache import cache
from django.test import TestCase

from core import auth, content, store
from core.tutor import patterns
from core.util import add_months, jround


def quiet():
    """Swallow the demo-mode e-mails printed to the console."""
    return contextlib.redirect_stdout(io.StringIO())


class Api(TestCase):
    def setUp(self):
        cache.clear()
        self.n = 0

    def post(self, url, data=None, **kw):
        with quiet():
            return self.client.post(url, data or {}, content_type="application/json", **kw)

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def register(self, username="alice", email=None, mobile=None, **extra):
        self.n += 1
        body = {"fullName": "Alice Coder", "username": username, "email": email or f"{username}@example.com", "password": "secret123",
                "countryCode": "+91", "mobile": f"98765432{self.n:02d}" if mobile is None else mobile, "goalLanguage": "python", **extra}
        return self.post("/api/auth/register", body)

    def login(self, identifier="alice", password="secret123"):
        r = self.post("/api/auth/login", {"identifier": identifier, "password": password})
        return r, (r.json().get("token") if r.status_code == 200 else None)

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class RegistrationTests(Api):
    def test_register_login_me(self):
        r = self.register()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertRegex(r.json()["userId"], r"^CQ\d{6}$")
        self.assertEqual(r.json()["mobile"], "+919876543201")
        r, tok = self.login("ALICE")  # usernames are case-insensitive
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.cookies["cq_token"].value)
        self.assertTrue(r.cookies["cq_token"]["httponly"])
        me = self.get("/api/me", **self.auth(tok)).json()["user"]
        self.assertEqual((me["username"], me["access"]["status"], me["access"]["daysLeft"]), ("alice", "trial", 30))
        self.assertNotIn("passwordHash", me)

    def test_login_with_email_and_user_id(self):
        uid = self.register().json()["userId"]
        self.assertEqual(self.login("alice@example.com")[0].status_code, 200)
        self.assertEqual(self.login(uid)[0].status_code, 200)

    def test_validation(self):
        for field, value in [("username", "a b"), ("email", "nope"), ("password", "123"), ("mobile", "12345"), ("mobile", ""), ("countryCode", "+999")]:
            r = self.register(**{field: value})
            self.assertEqual(r.status_code, 400, (field, value))

    def test_duplicates_are_rejected(self):
        self.register()
        self.assertEqual(self.register("ALICE", email="x@example.com").json()["field"], "username")
        self.assertEqual(self.register("bob", email="Alice@Example.com").json()["field"], "email")
        self.assertEqual(self.register("carol", mobile="9876543201").json()["field"], "mobile")

    def test_wrong_password_and_lockout(self):
        self.register()
        codes = [self.login(password="bad")[0].status_code for _ in range(6)]
        self.assertEqual(codes[0], 401)
        self.assertEqual(codes[-1], 429)

    def test_tokens(self):
        self.assertEqual(self.get("/api/me").json()["code"], "NO_TOKEN")
        self.assertEqual(self.get("/api/me", HTTP_AUTHORIZATION="Bearer " + "junk" * 10).json()["code"], "BAD_TOKEN")
        self.register()
        _, tok = self.login()
        self.assertEqual(self.get("/api/me", HTTP_X_AUTH_TOKEN=tok).status_code, 200)
        self.assertEqual(self.get("/api/me").status_code, 200)  # via the cookie set at login

    def test_cookie_post_must_be_json(self):
        self.register()
        self.login()
        r = self.client.post("/api/me/mobile", "countryCode=%2B91&mobile=9876500000", content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 403)

    def test_change_mobile(self):
        self.register()
        _, tok = self.login()
        r = self.post("/api/me/mobile", {"countryCode": "+44", "mobile": "07700 900123"}, **self.auth(tok))
        self.assertEqual(r.json()["mobile"], "+447700900123")

    def test_old_bcryptjs_hash(self):
        # standard bcrypt hashes ($2a$ / $2b$ prefixes) for the password "hello123"
        self.assertTrue(auth.check_password("hello123", "$2b$10$Qh4uMERgMVGXUfHhxJkFPO6FAhC8rnvojoLuifF3UOOdwm6SNuDv6"))
        self.assertTrue(auth.check_password("hello123", "$2a$10$Qh4uMERgMVGXUfHhxJkFPO6FAhC8rnvojoLuifF3UOOdwm6SNuDv6"))


class RecoveryTests(Api):
    def test_full_recovery(self):
        self.register()
        r = self.post("/api/auth/forgot", {"email": "ALICE@example.com"})
        self.assertEqual(r.status_code, 200)
        code = re.search(r"code: (\d{6})", r.json()["devPreview"]["text"]).group(1)
        self.assertEqual(self.post("/api/auth/forgot", {"email": "alice@example.com"}).status_code, 429)  # cooldown
        wrong = "000000" if code != "000000" else "111111"
        self.assertEqual(self.post("/api/auth/verify-code", {"email": "alice@example.com", "code": wrong}).status_code, 400)
        r = self.post("/api/auth/verify-code", {"email": "alice@example.com", "code": code})
        self.assertEqual(r.json()["username"], "alice")
        rt = r.json()["resetToken"]
        self.assertEqual(self.post("/api/auth/reset-password", {"resetToken": rt, "password": "brandnew1"}).status_code, 200)
        self.assertEqual(self.post("/api/auth/reset-password", {"resetToken": rt, "password": "again1234"}).status_code, 400)
        self.assertEqual(self.login(password="brandnew1")[0].status_code, 200)
        self.assertEqual(self.login(password="secret123")[0].status_code, 401)

    def test_unknown_email(self):
        self.assertEqual(self.post("/api/auth/forgot", {"email": "ghost@example.com"}).status_code, 404)

    def test_reset_token_cannot_log_in(self):
        self.register()
        r = self.post("/api/auth/forgot", {"email": "alice@example.com"})
        code = re.search(r"code: (\d{6})", r.json()["devPreview"]["text"]).group(1)
        rt = self.post("/api/auth/verify-code", {"email": "alice@example.com", "code": code}).json()["resetToken"]
        self.client.cookies.clear()
        self.assertEqual(self.get("/api/me", **self.auth(rt)).json()["code"], "WRONG_TOKEN")


class GameTests(Api):
    def setUp(self):
        super().setUp()
        self.register()
        _, self.tok = self.login()

    def play(self, lang="python", level=1, perfect=True):
        s = self.post("/api/game/start", {"lang": lang, "level": level}, **self.auth(self.tok))
        self.assertEqual(s.status_code, 200, s.content)
        sid = s.json()["sessionId"]
        while True:
            n = self.post("/api/game/next", {"sessionId": sid}, **self.auth(self.tok)).json()
            if n["done"]:
                break
            sess = store.get_session(sid)
            o = sess["order"][sess["idx"]]
            q = content.get_question(lang, level, o["qid"])
            if q["type"] == "fill":
                ans = q["answer"][0] if perfect else "zzz"
            else:
                ans = o["perm"].index(q["answer"]) if perfect else (o["perm"].index(q["answer"]) + 1) % len(o["perm"])
            a = self.post("/api/game/answer", {"sessionId": sid, "answer": ans}, **self.auth(self.tok)).json()
            self.assertEqual(a["correct"], perfect)
            if a["done"]:
                break
        return self.post("/api/game/finish", {"sessionId": sid}, **self.auth(self.tok))

    def test_perfect_round_unlocks_next_part(self):
        self.assertEqual(self.post("/api/game/start", {"lang": "python", "level": 2}, **self.auth(self.tok)).status_code, 403)
        f = self.play().json()
        self.assertEqual((f["result"]["accuracy"], f["result"]["stars"], f["result"]["passed"]), (100, 3, True))
        self.assertTrue(f["unlockedNext"])
        self.assertGreater(f["xpEarned"], 50)
        self.assertEqual(self.post("/api/game/start", {"lang": "python", "level": 2}, **self.auth(self.tok)).status_code, 200)
        me = self.get("/api/me", **self.auth(self.tok)).json()["user"]
        self.assertTrue(me["progress"]["python"]["1"]["passed"])
        self.assertEqual(len(store.attempts_for(me["userId"])), 1)

    def test_failed_round_loses_lives(self):
        f = self.play(perfect=False).json()
        self.assertFalse(f["result"]["passed"])
        self.assertEqual(f["result"]["livesLeft"], 0)

    def test_round_order_rules(self):
        sid = self.post("/api/game/start", {"lang": "sql", "level": 1}, **self.auth(self.tok)).json()["sessionId"]
        self.assertEqual(self.post("/api/game/answer", {"sessionId": sid, "answer": 0}, **self.auth(self.tok)).status_code, 409)
        self.assertEqual(self.post("/api/game/finish", {"sessionId": sid}, **self.auth(self.tok)).status_code, 409)

    def test_catalog_hides_answers(self):
        langs = self.get("/api/languages", **self.auth(self.tok)).json()["languages"]
        self.assertEqual([l["id"] for l in langs], ["python", "javascript", "java", "cpp", "sql"])
        self.assertNotIn("questions", langs[0]["levels"][0])
        self.assertGreaterEqual(min(lv["questionCount"] for l in langs for lv in l["levels"]), 100)

    def test_agent_report_after_game(self):
        self.play()
        rep = self.get("/api/agent/report", **self.auth(self.tok)).json()
        self.assertEqual(rep["overview"]["gamesPlayed"], 1)
        self.assertTrue(rep["recommendations"])


class ChatTests(Api):
    def setUp(self):
        super().setUp()
        self.register()
        _, self.tok = self.login()

    def say(self, m):
        return self.post("/api/agent/chat", {"message": m}, **self.auth(self.tok))

    def test_chat_flow(self):
        self.assertIn("immutable", self.say("what is a tuple in python").json()["reply"]["text"])
        q = self.say("quiz me on python").json()["reply"]
        self.assertTrue(q["quiz"]["options"])
        self.assertRegex(self.say("A").json()["reply"]["text"], "Correct|Not quite")
        self.assertIn("#include", self.say("pyramid pattern in c++").json()["reply"]["text"])
        self.assertIn("only help with", self.say("best pizza in town?").json()["reply"]["text"])
        h = self.get("/api/agent/chat", **self.auth(self.tok)).json()
        self.assertEqual(len(h["history"]), 10)
        self.post("/api/agent/chat/clear", {}, **self.auth(self.tok))
        self.assertEqual(self.get("/api/agent/chat", **self.auth(self.tok)).json()["history"], [])

    def test_limits(self):
        self.assertEqual(self.say("").status_code, 400)
        self.assertEqual(self.say("x" * 4001).status_code, 400)
        codes = [self.say("hi").status_code for _ in range(21)]
        self.assertEqual(codes[-1], 429)


class SubscriptionTests(Api):
    def setUp(self):
        super().setUp()
        self.uid = self.register().json()["userId"]
        _, self.tok = self.login()

    def test_expired_trial_then_subscribe(self):
        r = self.post(f"/api/admin/users/{self.uid}/trial", {"days": 0}, HTTP_X_ADMIN_KEY="admin123")
        self.assertEqual(r.json()["access"]["status"], "expired")
        r = self.get("/api/lesson/python/1", **self.auth(self.tok))
        self.assertEqual((r.status_code, r.json()["code"]), (402, "SUBSCRIPTION_REQUIRED"))
        self.assertEqual(self.post("/api/game/start", {"lang": "python", "level": 1}, **self.auth(self.tok)).status_code, 402)
        o = self.post("/api/billing/order", {"plan": "yearly"}, **self.auth(self.tok)).json()
        v = self.post("/api/billing/verify", {"orderId": o["orderId"]}, **self.auth(self.tok))
        self.assertEqual(v.json()["access"]["status"], "active")
        self.assertGreaterEqual(v.json()["access"]["daysLeft"], 364)
        self.assertEqual(self.post("/api/billing/verify", {"orderId": o["orderId"]}, **self.auth(self.tok)).status_code, 409)
        self.assertEqual(self.get("/api/lesson/python/1", **self.auth(self.tok)).status_code, 200)
        self.assertEqual(self.get("/api/plans", **self.auth(self.tok)).json()["history"][0]["amount"], 1499)

    def test_admin_requires_key(self):
        self.assertEqual(self.get("/api/admin/users").status_code, 401)
        users = self.get("/api/admin/users", HTTP_X_ADMIN_KEY="admin123").json()["users"]
        self.assertEqual(users[0]["mobile"], "+919876543201")


class StaticTests(Api):
    def test_pages_and_assets(self):
        r = self.get("/")
        self.assertRegex(r.content.decode(), r"/app\.js\?v=\w+")
        a = self.get("/styles.css")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(self.get("/styles.css", HTTP_IF_NONE_MATCH=a["ETag"]).status_code, 304)
        self.assertEqual(self.get("/admin.html").status_code, 200)

    def test_no_access_outside_public(self):
        for p in ("/manage.py", "/data/.secret", "/..%2Fmanage.py", "/.hidden"):
            self.assertEqual(self.get(p).status_code, 404, p)
        self.assertEqual(self.get("/api/unknown").json()["error"], "Not found")


class UnitTests(TestCase):
    def test_js_rounding(self):
        self.assertEqual([jround(0.5), jround(1.5), jround(2.5), jround(-0.5)], [1, 2, 3, 0])

    def test_add_months_clamps_day(self):
        from datetime import datetime, timezone
        self.assertEqual(add_months(datetime(2026, 1, 31, tzinfo=timezone.utc), 1).day, 28)

    def test_mobile_normalisation(self):
        self.assertEqual(auth.normalize_mobile("+91", "098765 43210")["value"], "+919876543210")
        self.assertIn("error", auth.normalize_mobile("+91", "5876543210"))   # Indian numbers start with 6-9
        self.assertIn("error", auth.normalize_mobile("+999", "9876543210"))

    def test_patterns_render(self):
        code = patterns.render(patterns.get("pyramid"), 3, "python")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(code, {})  # noqa: S102 — our own generated program
        self.assertEqual([l.strip() for l in buf.getvalue().splitlines()], ["*", "***", "*****"])


class BackupTests(Api):
    def test_export_then_import_restores_everything(self):
        import json
        import tempfile
        from pathlib import Path

        from django.core.management import call_command

        from core.models import Attempt, Player

        uid = self.register().json()["userId"]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "backup.json")
            with quiet():
                call_command("export_data", str(f))
            data = json.loads(f.read_text())
            self.assertEqual([u["userId"] for u in data["users"]], [uid])
            Attempt.objects.all().delete()
            Player.objects.all().delete()
            with quiet():
                call_command("import_data", str(f))
        user = store.find_user_by_login("alice")
        self.assertEqual((user["userId"], user["email"], user["mobile"]), (uid, "alice@example.com", "+919876543201"))
        self.assertEqual(self.login()[0].status_code, 200)   # same password still works after restore
