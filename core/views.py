"""
All HTTP routes: the JSON API used by the single-page app (public/app.js) and the static files.
"""
import hashlib
import logging
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, JsonResponse

from . import agent, auth, billing, content, game, mailer, plans, store, tutor
from .http import api, clear_session_cookie, client_ip, set_session_cookie
from .util import DAY_MS, HttpError, iso_from_ms, ms_of, now_ms, to_date_string

log = logging.getLogger("syntaxo")


# ───────────────────────── static files ─────────────────────────
def _asset_version() -> str:
    parts = []
    for f in ("app.js", "styles.css"):
        try:
            parts.append(format(int((settings.PUBLIC_DIR / f).stat().st_mtime * 1000), "x"))
        except OSError:
            parts.append("0")
    return "".join(parts)


def _html(file):
    def view(request):
        p = settings.PUBLIC_DIR / file
        if not p.exists():
            raise Http404
        v = _asset_version()
        html = p.read_text(encoding="utf-8").replace('/styles.css"', f'/styles.css?v={v}"').replace('/app.js"', f'/app.js?v={v}"')
        resp = HttpResponse(html, content_type="text/html; charset=utf-8")
        resp["Cache-Control"] = "no-store"
        return resp
    return view


index_page = _html("index.html")
admin_page = _html("admin.html")


def public_file(request, path):
    """Serve files from public/ (no directory listing, no path traversal, ETag revalidation)."""
    base = settings.PUBLIC_DIR.resolve()
    p = (base / path).resolve()
    if base not in p.parents or not p.is_file() or p.name.startswith("."):
        raise Http404
    st = p.stat()
    etag = '"' + hashlib.md5(f"{st.st_mtime_ns}-{st.st_size}".encode()).hexdigest() + '"'  # noqa: S324 — cache key only
    if request.headers.get("If-None-Match") == etag:
        resp = HttpResponseNotModified()
    else:
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        resp = FileResponse(open(p, "rb"), content_type=ctype)
    resp["ETag"] = etag
    resp["Cache-Control"] = "no-cache"
    return resp


def api_not_found(request, path=""):
    return JsonResponse({"error": "Not found"}, status=404)


# ───────────────────────── auth ─────────────────────────
@api(methods=("POST",))
def register(request, body):
    user, mail = auth.register(body)
    a = agent.get_agent(user["agent"]["agentId"])
    return {"userId": user["userId"], "username": user["username"], "fullName": user["fullName"], "email": user["email"], "mobile": user["mobile"],
            "trialDays": plans.TRIAL_DAYS, "agent": {"name": a["name"], "emoji": a["emoji"], "title": a["title"], "color": a["color"]},
            "emailSent": bool(mail) and not mail.get("demo"), "demoEmail": bool(mail and mail.get("demo"))}, 201


@api(methods=("POST",))
def login(request, body):
    user, token = auth.login(body, client_ip(request))
    resp = JsonResponse({"token": token, "user": auth.public_user(user)}, json_dumps_params={"ensure_ascii": False})
    set_session_cookie(resp, token)
    return resp


@api(methods=("POST",))
def logout(request, body):
    resp = JsonResponse({"ok": True})
    clear_session_cookie(resp)
    return resp


@api(methods=("POST",))
def forgot(request, body):
    return auth.forgot(body)


@api(methods=("POST",))
def verify_code(request, body):
    return auth.verify_code(body)


@api(methods=("POST",))
def reset_password(request, body):
    return auth.reset_password(body)


@api(auth_required=True)
def me(request, user, body):
    return {"user": auth.public_user(user)}


@api(auth_required=True, methods=("POST",))
def me_mobile(request, user, body):
    return auth.update_mobile(user, body)


# ───────────────────────── curriculum & game ─────────────────────────
@api(auth_required=True)
def languages(request, user, body):
    return {"access": plans.access_for(user),
            "languages": [{**l, "levels": [{**lv, "unlocked": game.is_unlocked(user, l["id"], lv["level"]),
                                            "progress": game.progress_of(user, l["id"], lv["level"])} for lv in l["levels"]]}
                          for l in content.catalog()]}


@api()
def public_languages(request, body):
    return {"languages": content.catalog(), "trialDays": plans.TRIAL_DAYS}


@api(auth_required=True, access=True)
def lesson(request, user, body, lang, level):
    les = content.lesson(lang, level)
    if not les:
        raise HttpError(404, "Lesson not found.")
    return {"lesson": {**les, "unlocked": game.is_unlocked(user, lang, level)}}


@api(auth_required=True, access=True, methods=("POST",))
def game_start(request, user, body):
    return game.start(user, body.get("lang"), body.get("level"))


@api(auth_required=True, access=True, methods=("POST",))
def game_next(request, user, body):
    return game.next_question(user, body.get("sessionId"))


@api(auth_required=True, access=True, methods=("POST",))
def game_answer(request, user, body):
    return game.answer(user, body.get("sessionId"), body.get("answer"))


@api(auth_required=True, access=True, methods=("POST",))
def game_finish(request, user, body):
    return game.finish(user, body.get("sessionId"))


# ───────────────────────── agent & chat ─────────────────────────
@api(auth_required=True)
def agent_report(request, user, body):
    return agent.report(user)


def _agent_card(user):
    a = agent.get_agent(user["agent"]["agentId"])
    return {"name": a["name"], "title": a["title"], "color": a["color"]}


CHAT_LIMIT, CHAT_WINDOW_MS = 20, 60_000


@api(auth_required=True, methods=("GET", "POST"))
def agent_chat(request, user, body):
    if request.method == "GET":
        return {"agent": _agent_card(user), **tutor.mode(), "history": (user.get("chat") or [])[-60:], "suggestions": tutor.suggestions(user)}
    denied = auth.access_error(user)
    if denied:
        raise denied
    message = str(body.get("message") or "").strip()
    if not message:
        raise HttpError(400, "Type a message first.")
    if len(message) > 4000:
        raise HttpError(400, "That message is too long (max 4000 characters).")
    key, now = f"chat:{user['userId']}", now_ms()
    hits = [t for t in (cache.get(key) or []) if now - t < CHAT_WINDOW_MS]
    if len(hits) >= CHAT_LIMIT:
        raise HttpError(429, "You are sending messages very fast — wait a few seconds and try again.")
    cache.set(key, hits + [now], 120)
    r = tutor.reply(user, message)
    agent_msg = {"role": "agent", "text": r["text"], "source": r["source"]}
    if r.get("quiz"):
        agent_msg["quiz"] = r["quiz"]
    if r.get("actions"):
        agent_msg["actions"] = r["actions"]
    tutor.push_history(user, {"role": "user", "text": message})
    tutor.push_history(user, agent_msg)
    return {"reply": user["chat"][-1]}


@api(auth_required=True, methods=("POST",))
def agent_chat_clear(request, user, body):
    user["chat"], user["chatState"] = [], {}
    return {"ok": True}


# ───────────────────────── subscription & billing ─────────────────────────
@api(auth_required=True)
def plans_view(request, user, body):
    r = agent.report(user)
    history = [{k: p.get(k) for k in ("orderId", "paymentId", "plan", "amount", "paidAt")} for p in store.payments_for(user["userId"]) if p["status"] == "paid"]
    return {"plans": plans.PLANS, "access": plans.access_for(user), "suggestion": r["planSuggestion"], "paymentMode": billing.MODE, "history": history[::-1]}


@api(auth_required=True, methods=("POST",))
def billing_order(request, user, body):
    return billing.create_order(user, body.get("plan"))


@api(auth_required=True, methods=("POST",))
def billing_verify(request, user, body):
    pay = billing.verify(user, body)
    sub = plans.activate(user, pay["plan"], pay["paymentId"])
    plan = plans.get_plan(pay["plan"])
    agent.log(user, "plan", f"Subscribed to the {plan['name']} plan — full access until {to_date_string(sub['expiresAt'])}. Let's keep learning!")
    store.save_user(user)
    try:
        mailer.send(user["email"], **mailer.receipt(user, plan, sub, pay["paymentId"]))
    except Exception as e:  # noqa: BLE001
        log.error(f"[mail] receipt failed: {e}")
    return {"ok": True, "subscription": sub, "access": plans.access_for(user), "paymentId": pay["paymentId"]}


# ───────────────────────── leaderboard ─────────────────────────
@api(auth_required=True)
def leaderboard(request, user, body):
    rows = [{"username": u["username"], "xp": u["stats"]["xp"], "rank": agent.rank_for(u["stats"]["xp"])["title"], "games": u["stats"]["gamesPlayed"],
             "streak": u["stats"]["streak"]["best"], "agent": agent.get_agent(u["agent"]["agentId"])["name"], "me": u["userId"] == user["userId"]}
            for u in store.all_users()]
    rows.sort(key=lambda r: -r["xp"])
    top = [{**r, "pos": i + 1} for i, r in enumerate(rows[:20])]
    my_pos = next((i + 1 for i, r in enumerate(rows) if r["me"]), 0)
    return {"top": top, "myPos": my_pos, "total": len(rows)}


# ───────────────────────── admin (x-admin-key) ─────────────────────────
@api(admin=True)
def admin_users(request, body):
    out = []
    for u in store.all_users():
        r, a = agent.report(u), plans.access_for(u)
        detail = f"{a['daysLeft']}d left" if a["status"] == "trial" else f"{a['planName']} · {a['daysLeft']}d left" if a["status"] == "active" else a.get("reason")
        o = r["overview"]
        out.append({"userId": u["userId"], "fullName": u["fullName"], "username": u["username"], "email": u["email"], "mobile": u.get("mobile") or "",
                    "createdAt": u.get("createdAt"), "lastLoginAt": u.get("lastLoginAt"), "access": a["status"], "accessDetail": detail,
                    "revenue": sum(p["amount"] for p in store.payments_for(u["userId"]) if p["status"] == "paid"),
                    "agent": r["agent"]["name"], "xp": o["xp"], "rank": o["rank"]["title"], "games": o["gamesPlayed"], "accuracy": o["accuracy"],
                    "levelsPassed": o["levelsPassed"], "streak": o["streak"]["current"], "engagement": r["engagement"],
                    "suggestedPlan": r["planSuggestion"]["plan"], "weak": [f"{t['langName']}: {t['topic']}" for t in r["topics"]["weak"]],
                    "skills": {l["name"]: l["skill"] for l in r["languages"]}})
    return {"paymentMode": billing.MODE, "emailMode": "demo" if mailer.DEMO else "smtp", "users": out}


@api(admin=True, methods=("POST",))
def admin_trial(request, body, user_id):
    u = store.find_user_by_id(user_id)
    if not u:
        raise HttpError(404, "User not found.")
    try:
        days = int(body.get("days") or 0)
    except (TypeError, ValueError):
        raise HttpError(400, "days must be a number.")
    if days > 0:
        u["trialEndsAt"] = iso_from_ms(max(now_ms(), ms_of(plans.trial_ends_at(u))) + days * DAY_MS)
    else:
        u["trialEndsAt"] = iso_from_ms(now_ms() - 1000)
        if u.get("subscription"):
            u["subscription"]["expiresAt"] = iso_from_ms(now_ms() - 1000)
    store.save_user(u)
    return {"ok": True, "access": plans.access_for(u)}
