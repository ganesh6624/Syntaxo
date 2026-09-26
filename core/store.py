"""
Data access layer — the only module that talks to the database.

Users, attempts and payments are handled as plain dicts (the same shape the frontend sees);
this module maps them to the Django models in core/models.py.
"""
from django.db import IntegrityError, transaction
from django.db.models import F

from .models import Attempt, Counter, GameSession, Payment, Player
from .util import HttpError, now_ms, parse_iso

FIRST_USER_NO = 100001


def _norm(s) -> str:
    return str(s or "").strip().lower()


# ───────────────────────── users ─────────────────────────
def _player_fields(user: dict) -> dict:
    return {
        "user_id": user["userId"],
        "username": user["username"],
        "username_key": _norm(user["username"]),
        "email": _norm(user["email"]),
        "mobile": user.get("mobile") or None,
        "full_name": user.get("fullName") or "",
        "xp": int((user.get("stats") or {}).get("xp") or 0),
        "created_at": parse_iso(user.get("createdAt")),
        "doc": user,
    }


def find_user_by_id(user_id) -> dict | None:
    p = Player.objects.filter(user_id__iexact=str(user_id or "").strip()).only("doc").first()
    return p.doc if p else None


def find_user_by_login(identifier) -> dict | None:
    """Username (what the UI asks for); User ID and email are also accepted."""
    key = _norm(identifier)
    if not key:
        return None
    p = (Player.objects.filter(username_key=key).first()
         or Player.objects.filter(email=key).first()
         or Player.objects.filter(user_id__iexact=key).first())
    return p.doc if p else None


def find_user_by_email(email) -> dict | None:
    p = Player.objects.filter(email=_norm(email)).first()
    return p.doc if p else None


def username_taken(username) -> bool:
    return Player.objects.filter(username_key=_norm(username)).exists()


def email_taken(email) -> bool:
    return Player.objects.filter(email=_norm(email)).exists()


def mobile_taken(mobile, except_user_id=None) -> bool:
    if not mobile:
        return False
    qs = Player.objects.filter(mobile=mobile)
    if except_user_id:
        qs = qs.exclude(user_id=except_user_id)
    return qs.exists()


def next_user_id() -> str:
    with transaction.atomic():
        c, created = Counter.objects.select_for_update().get_or_create(name="nextUserNo", defaults={"value": FIRST_USER_NO})
        if created:
            # continue after the highest existing number (e.g. after importing old data)
            nums = [int(u[2:]) for u in Player.objects.values_list("user_id", flat=True) if u[2:].isdigit()]
            c.value = max([FIRST_USER_NO - 1, *nums]) + 1
        n = c.value
        Counter.objects.filter(pk=c.pk).update(value=n + 1)
    return f"CQ{n}"


def set_next_user_no(n: int):
    Counter.objects.update_or_create(name="nextUserNo", defaults={"value": int(n)})


def insert_user(user: dict) -> dict:
    try:
        Player.objects.create(**_player_fields(user))
    except IntegrityError as e:  # two sign-ups racing for the same username / email / mobile
        msg = str(e).lower()
        field = "email" if "email" in msg else "mobile" if "mobile" in msg else "username"
        raise HttpError(409, {"email": "An account with this email already exists. Try logging in instead.",
                              "mobile": "An account with this mobile number already exists.",
                              "username": "That username is already taken — try another one."}[field], field)
    return user


def save_user(user: dict):
    f = _player_fields(user)
    Player.objects.filter(user_id=user["userId"]).update(**{k: v for k, v in f.items() if k != "user_id"})


def all_users() -> list[dict]:
    return [p.doc for p in Player.objects.all().only("doc")]


def user_count() -> int:
    return Player.objects.count()


# ───────────────────────── attempts ─────────────────────────
def insert_attempt(a: dict) -> dict:
    Attempt.objects.create(attempt_id=a["id"], user_id=a["userId"], lang=a["lang"], level=a["level"],
                           accuracy=a.get("accuracy", 0), passed=bool(a.get("passed")), at=parse_iso(a["at"]), doc=a)
    return a


def attempts_for(user_id) -> list[dict]:
    return [x.doc for x in Attempt.objects.filter(user_id=user_id).order_by("at", "id").only("doc")]


# ───────────────────────── payments ─────────────────────────
def insert_payment(p: dict) -> dict:
    Payment.objects.create(order_id=p["orderId"], user_id=p["userId"], plan=p["plan"], amount=p["amount"],
                           status=p["status"], created_at=parse_iso(p["createdAt"]), doc=p)
    return p


def find_payment(order_id) -> dict | None:
    p = Payment.objects.filter(order_id=str(order_id or "")).first()
    return p.doc if p else None


def save_payment(p: dict):
    Payment.objects.filter(order_id=p["orderId"]).update(status=p["status"], doc=p)


def payments_for(user_id) -> list[dict]:
    return [x.doc for x in Payment.objects.filter(user_id=user_id).order_by("created_at", "id")]


# ───────────────────────── game sessions ─────────────────────────
SESSION_MAX_AGE_MS = 60 * 60 * 1000


def create_session(s: dict):
    from .util import iso_from_ms
    GameSession.objects.create(session_id=s["id"], user_id=s["userId"], created_at=parse_iso(iso_from_ms(s["createdAt"])), doc=s)


def get_session(session_id) -> dict | None:
    s = GameSession.objects.filter(session_id=str(session_id or "")).first()
    return s.doc if s else None


def save_session(s: dict):
    GameSession.objects.filter(session_id=s["id"]).update(doc=s)


def delete_session(session_id):
    GameSession.objects.filter(session_id=session_id).delete()


def gc_sessions():
    from .util import iso_from_ms
    GameSession.objects.filter(created_at__lt=parse_iso(iso_from_ms(now_ms() - SESSION_MAX_AGE_MS))).delete()


__all__ = [n for n in dir() if not n.startswith("_")] + ["F"]
