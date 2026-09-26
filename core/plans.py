"""
Access model
 • Every new user gets a FREE TRIAL of TRIAL_DAYS (default 30) with full access.
 • After the trial, learning & playing require an active subscription.
 • Subscribing while already subscribed extends from the current expiry date.
"""
import math

from django.conf import settings

from .util import DAY_MS, add_months, iso, iso_from_ms, ms_of, now_ms, parse_iso

TRIAL_DAYS = settings.TRIAL_DAYS

PLANS = [
    {"id": "monthly", "name": "Monthly", "price": 199, "currency": "INR", "months": 1, "period": "month", "highlight": False, "badge": None,
     "features": ["All languages & all parts", "All game modes", "Full personal-agent analytics", "Leaderboard & streaks"]},
    {"id": "quarterly", "name": "Quarterly", "price": 499, "currency": "INR", "months": 3, "period": "3 months", "highlight": True, "badge": "Most popular · save 16%",
     "features": ["Everything in Monthly", "Personalised learning path from your agent", "Completion certificates", "Priority access to new languages"]},
    {"id": "yearly", "name": "Yearly", "price": 1499, "currency": "INR", "months": 12, "period": "year", "highlight": False, "badge": "Best value · save 37%",
     "features": ["Everything in Quarterly", "Interview-prep challenge packs", "Weekly progress report by email", "Priority support"]},
]


def get_plan(plan_id):
    return next((p for p in PLANS if p["id"] == plan_id), None)


def trial_ends_at(user) -> str:
    if user.get("trialEndsAt"):
        return user["trialEndsAt"]
    created = ms_of(user.get("createdAt")) or now_ms()
    return iso_from_ms(created + TRIAL_DAYS * DAY_MS)


def _active_sub(user, now):
    sub = user.get("subscription")
    if sub and sub.get("status") == "active" and ms_of(sub.get("expiresAt")) > now:
        return sub
    return None


def access_for(user, now=None) -> dict:
    """Single source of truth for "can this user learn/play right now?"."""
    now = now or now_ms()
    t_end = ms_of(trial_ends_at(user))
    sub = _active_sub(user, now)
    if sub:
        plan = get_plan(sub["plan"])
        return {"status": "active", "canPlay": True, "plan": sub["plan"], "planName": plan["name"] if plan else sub["plan"],
                "expiresAt": sub["expiresAt"], "daysLeft": math.ceil((ms_of(sub["expiresAt"]) - now) / DAY_MS),
                "trialEndsAt": iso_from_ms(t_end), "trialDays": TRIAL_DAYS}
    if now < t_end:
        return {"status": "trial", "canPlay": True, "plan": None, "trialEndsAt": iso_from_ms(t_end),
                "daysLeft": math.ceil((t_end - now) / DAY_MS), "trialDays": TRIAL_DAYS}
    had_sub = bool(user.get("subscription"))
    return {"status": "expired", "reason": "subscription-expired" if had_sub else "trial-expired", "canPlay": False, "plan": None,
            "trialEndsAt": iso_from_ms(t_end), "daysLeft": 0, "trialDays": TRIAL_DAYS,
            "expiredAt": user["subscription"]["expiresAt"] if had_sub else iso_from_ms(t_end)}


def activate(user, plan_id, payment_id) -> dict:
    """Activate / extend a subscription after a verified payment."""
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError("Unknown plan")
    now = now_ms()
    cur_sub = _active_sub(user, now)
    start_from = parse_iso(cur_sub["expiresAt"]) if cur_sub else parse_iso(iso_from_ms(now))
    user["subscription"] = {
        "plan": plan["id"], "status": "active",
        "startedAt": cur_sub["startedAt"] if cur_sub else iso_from_ms(now),
        "expiresAt": iso(add_months(start_from, plan["months"])),
        "lastPaymentId": payment_id, "amount": plan["price"], "currency": plan["currency"],
    }
    user["plan"] = plan["id"]
    return user["subscription"]
