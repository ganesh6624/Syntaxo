"""
Accounts: registration, username login, JWT sessions, recovery by email, mobile numbers.
"""
import hashlib
import logging
import re
import secrets
from datetime import timedelta

import bcrypt
import jwt
from django.conf import settings
from django.core.cache import cache

from . import agent, mailer, plans, store
from .util import DAY_MS, HttpError, iso, iso_from_ms, ms_of, now_ms

log = logging.getLogger("syntaxo")

SECRET = settings.SECRET_KEY
TOKEN_TTL = timedelta(days=7)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")

# Mobile numbers: country code + national number, stored in E.164 form (e.g. +919876543210)
COUNTRY_CODES = ["+91", "+1", "+44", "+61", "+65", "+971", "+966", "+974", "+977", "+880", "+94", "+60", "+49", "+33", "+81"]


def normalize_mobile(country_code, mobile) -> dict:
    cc = str(country_code or "+91").strip()
    num = re.sub(r"^0+", "", re.sub(r"[\s().-]", "", str(mobile or "")))
    if cc not in COUNTRY_CODES:
        return {"error": "Please choose a valid country code."}
    if not num:
        return {"error": "Please enter your mobile number."}
    if not num.isdigit() or not num.isascii():
        return {"error": "Mobile number can contain digits only."}
    if cc == "+91":
        if not re.fullmatch(r"[6-9]\d{9}", num):
            return {"error": "Enter a valid 10-digit Indian mobile number (starts with 6, 7, 8 or 9)."}
    elif not re.fullmatch(r"\d{6,14}", num):
        return {"error": "Enter a valid mobile number (6–14 digits)."}
    return {"value": cc + num, "countryCode": cc}


def validate_registration(b) -> dict | None:
    """Shared rules (the frontend mirrors these for instant feedback)."""
    if len(str(b.get("fullName") or "").strip()) < 2:
        return {"field": "fullName", "msg": "Please enter your full name (at least 2 characters)."}
    if len(str(b.get("fullName")).strip()) > 80:
        return {"field": "fullName", "msg": "Full name is too long (max 80 characters)."}
    u = str(b.get("username") or "").strip()
    if not 3 <= len(u) <= 20:
        return {"field": "username", "msg": "Username must be 3–20 characters long."}
    if not USERNAME_RE.match(u):
        return {"field": "username", "msg": "Username can use letters, numbers, _ . or - (no spaces)."}
    email = str(b.get("email") or "").strip()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return {"field": "email", "msg": "Please enter a valid email address, e.g. name@gmail.com."}
    m = normalize_mobile(b.get("countryCode"), b.get("mobile"))
    if m.get("error"):
        return {"field": "mobile", "msg": m["error"]}
    pw = b.get("password")
    if not isinstance(pw, str) or len(pw) < 6:
        return {"field": "password", "msg": "Password must be at least 6 characters."}
    if len(pw.encode()) > 72:
        return {"field": "password", "msg": "Password is too long (max 72 characters)."}
    return None


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(10)).decode()


def check_password(pw, hashed) -> bool:
    try:
        return bcrypt.checkpw(str(pw or "").encode()[:72], str(hashed).encode())
    except ValueError:
        return False


def register(body) -> tuple[dict, dict | None]:
    err = validate_registration(body)
    if err:
        raise HttpError(400, err["msg"], err["field"])
    username, email = str(body["username"]).strip(), str(body["email"]).strip().lower()
    if store.username_taken(username):
        raise HttpError(409, "That username is already taken — try another one.", "username")
    if store.email_taken(email):
        raise HttpError(409, "An account with this email already exists. Try logging in instead.", "email")
    mob = normalize_mobile(body.get("countryCode"), body.get("mobile"))
    if store.mobile_taken(mob["value"]):
        raise HttpError(409, "An account with this mobile number already exists.", "mobile")
    goal = body.get("goalLanguage")
    goal = goal if goal in ("python", "javascript", "java", "cpp", "sql") else None

    now = iso()
    assigned = agent.assign_agent(store.user_count())
    user = {
        "userId": store.next_user_id(),
        "fullName": str(body["fullName"]).strip(),
        "username": username,
        "email": email,
        "mobile": mob["value"],
        "mobileCountryCode": mob["countryCode"],
        "passwordHash": hash_password(body["password"]),
        "createdAt": now,
        "trialEndsAt": iso_from_ms(now_ms() + plans.TRIAL_DAYS * DAY_MS),
        "subscription": None,
        "lastLoginAt": None,
        "plan": "free",
        "planInterest": None,
        "goalLanguage": goal,
        "agent": {"agentId": assigned["id"], "assignedAt": now},
        "stats": {"xp": 0, "gamesPlayed": 0, "streak": {"current": 0, "best": 0, "lastDay": None}},
        "progress": {},  # { lang: { "level": { bestScore, bestAccuracy, stars, attempts, passed } } }
        "agentLog": [],
    }
    agent.log(user, "welcome", f"Hi {user['fullName'].split(' ')[0]}! I'm {assigned['name']}, your personal coding agent. "
                               f"I'll track every game you play and guide you to the right next step.")
    store.insert_user(user)
    mail = None
    try:
        mail = mailer.send(user["email"], **mailer.welcome(user, plans.TRIAL_DAYS))
    except Exception as e:  # noqa: BLE001
        log.error(f"[mail] welcome email failed: {e}")
    return user, mail


def make_token(user) -> str:
    from datetime import datetime, timezone
    return jwt.encode({"sub": user["userId"], "exp": datetime.now(timezone.utc) + TOKEN_TTL}, SECRET, algorithm="HS256")


def login(body, ip) -> tuple[dict, str]:
    identifier = str(body.get("identifier") or body.get("username") or "").strip()
    key = f"login:{ip}|{identifier.lower()}"
    rec = cache.get(key) or {"n": 0, "until": 0}
    if rec["until"] > now_ms():
        raise HttpError(429, "Too many failed attempts. Try again in a minute.")
    user = store.find_user_by_login(identifier)
    if not user or not check_password(body.get("password"), user["passwordHash"]):
        rec["n"] += 1
        if rec["n"] >= 5:
            rec = {"n": 0, "until": now_ms() + 60_000}
        cache.set(key, rec, 600)
        raise HttpError(401, "Invalid username or password.")
    cache.delete(key)
    user["lastLoginAt"] = iso()
    store.save_user(user)
    return user, make_token(user)


# ─── Forgot username / password (email is unique → identifies exactly one account) ───
CODE_TTL_MIN, RESEND_SECONDS, MAX_CODE_ATTEMPTS = 10, 60, 5


def _hash_code(code) -> str:
    return hashlib.sha256(str(code).encode()).hexdigest()


def forgot(body) -> dict:
    e = str(body.get("email") or "").strip().lower()
    if not EMAIL_RE.match(e):
        raise HttpError(400, "Please enter a valid email address.", "email")
    user = store.find_user_by_email(e)
    if not user:
        raise HttpError(404, "No account is registered with this email. Check the spelling or create a new account.", "email")
    r = user.get("reset")
    if r and now_ms() - ms_of(r["sentAt"]) < RESEND_SECONDS * 1000:
        wait = -(-(RESEND_SECONDS * 1000 - (now_ms() - ms_of(r["sentAt"]))) // 1000)
        raise HttpError(429, f"Please wait {wait}s before requesting a new code.")
    code = str(secrets.randbelow(900000) + 100000)
    user["reset"] = {"codeHash": _hash_code(code), "expiresAt": iso_from_ms(now_ms() + CODE_TTL_MIN * 60000), "attempts": 0, "sentAt": iso()}
    store.save_user(user)
    try:
        mail = mailer.send(user["email"], **mailer.recovery(user, code, CODE_TTL_MIN))
    except Exception as err:  # noqa: BLE001
        log.error(f"[mail] recovery email failed: {err}")
        user["reset"] = None
        store.save_user(user)
        raise HttpError(502, "We could not send the email right now. Please try again later.")
    masked = re.sub(r"^(.)(.*)(.@.*)$", lambda m: m.group(1) + "*" * max(1, len(m.group(2))) + m.group(3), user["email"])
    return {"ok": True, "sentTo": masked, "expiresInMin": CODE_TTL_MIN, "resendIn": RESEND_SECONDS,
            "demo": mail.get("demo"), "devPreview": mail.get("devPreview")}


def verify_code(body) -> dict:
    user = store.find_user_by_email(body.get("email"))
    r = user.get("reset") if user else None
    if not r:
        raise HttpError(400, "Please request a new verification code.")
    if ms_of(r["expiresAt"]) < now_ms():
        user["reset"] = None
        store.save_user(user)
        raise HttpError(400, "This code has expired. Please request a new one.")
    if r["attempts"] >= MAX_CODE_ATTEMPTS:
        user["reset"] = None
        store.save_user(user)
        raise HttpError(429, "Too many wrong attempts. Please request a new code.")
    if _hash_code(str(body.get("code") or "").strip()) != r["codeHash"]:
        r["attempts"] += 1
        store.save_user(user)
        raise HttpError(400, f"Incorrect code. {MAX_CODE_ATTEMPTS - r['attempts']} attempt(s) left.", "code")
    user["reset"] = None
    store.save_user(user)
    from datetime import datetime, timezone
    reset_token = jwt.encode({"sub": user["userId"], "purpose": "reset", "pv": user["passwordHash"][-10:],
                              "exp": datetime.now(timezone.utc) + timedelta(minutes=15)}, SECRET, algorithm="HS256")
    return {"userId": user["userId"], "username": user["username"], "fullName": user["fullName"], "resetToken": reset_token}


def reset_password(body) -> dict:
    try:
        payload = jwt.decode(str(body.get("resetToken") or ""), SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HttpError(400, "Your reset session expired. Please start again.")
    if payload.get("purpose") != "reset":
        raise HttpError(400, "Invalid reset session.")
    user = store.find_user_by_id(payload.get("sub"))
    if not user or user["passwordHash"][-10:] != payload.get("pv"):
        raise HttpError(400, "This reset link was already used. Please start again.")
    pw = body.get("password")
    if not isinstance(pw, str) or len(pw) < 6:
        raise HttpError(400, "Password must be at least 6 characters.", "password")
    if len(pw.encode()) > 72:
        raise HttpError(400, "Password is too long (max 72 characters).", "password")
    user["passwordHash"] = hash_password(pw)
    agent.log(user, "security", "Your password was reset using email verification.")
    store.save_user(user)
    try:
        mailer.send(user["email"], **mailer.password_changed(user))
    except Exception as e:  # noqa: BLE001
        log.error(f"[mail] {e}")
    return {"ok": True, "userId": user["userId"], "username": user["username"]}


def user_from_token(token) -> tuple[dict | None, str | None, str | None]:
    """→ (user, error_code, message)."""
    if not token:
        return None, "NO_TOKEN", "Please log in."
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None, "EXPIRED", "Your session expired. Please log in again."
    except jwt.PyJWTError:
        return None, "BAD_TOKEN", "Please log in again."
    if payload.get("purpose"):
        return None, "WRONG_TOKEN", "Please log in."
    user = store.find_user_by_id(payload.get("sub"))
    if not user:
        return None, "NO_ACCOUNT", "This account no longer exists. Please register again."
    return user, None, None


def public_user(u) -> dict:
    a = agent.get_agent(u["agent"]["agentId"])
    return {
        "userId": u["userId"], "fullName": u["fullName"], "username": u["username"], "email": u["email"], "mobile": u.get("mobile") or None,
        "createdAt": u.get("createdAt"), "plan": u.get("plan"), "planInterest": u.get("planInterest"), "goalLanguage": u.get("goalLanguage"),
        "stats": u["stats"], "rank": agent.rank_for(u["stats"]["xp"]), "progress": u.get("progress") or {}, "access": plans.access_for(u),
        "agent": {**agent.public_agent(a), "assignedAt": u["agent"].get("assignedAt")},
    }


def update_mobile(user, body) -> dict:
    """Add / change the mobile number from the profile."""
    m = normalize_mobile(body.get("countryCode"), body.get("mobile"))
    if m.get("error"):
        raise HttpError(400, m["error"], "mobile")
    if store.mobile_taken(m["value"], user["userId"]):
        raise HttpError(409, "Another account already uses this mobile number.", "mobile")
    user["mobile"], user["mobileCountryCode"] = m["value"], m["countryCode"]
    return {"mobile": user["mobile"]}


def access_error(user) -> HttpError | None:
    """Blocks learning & playing once the free trial is over and there is no active subscription."""
    a = plans.access_for(user)
    if a["canPlay"]:
        return None
    msg = ("Your subscription has expired. Renew to continue learning." if a.get("reason") == "subscription-expired"
           else f"Your {plans.TRIAL_DAYS}-day free trial has ended. Subscribe to continue learning.")
    return HttpError(402, msg, code="SUBSCRIPTION_REQUIRED", access=a)
