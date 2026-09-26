"""
HTTP plumbing for the JSON API: body parsing, auth, access checks, errors, CORS and logging.

    @api(auth=True, access=True, methods=("POST",))
    def view(req, user, body): return {...}

• The token can arrive as `Authorization: Bearer …`, `X-Auth-Token` (survives proxies that strip
  Authorization) or the HttpOnly `cq_token` cookie.
• Cookie-authenticated POSTs must be JSON — HTML forms on other sites cannot send JSON, so this
  blocks cross-site request forgery while keeping the cookie fallback.
• If the handler changed the logged-in user's data, it is saved automatically.
"""
import copy
import functools
import json
import logging
from urllib.parse import unquote

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import auth, store
from .util import HttpError

log = logging.getLogger("syntaxo")

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Auth-Token, x-admin-key",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}
COOKIE_NAME = "cq_token"
COOKIE_MAX_AGE = 7 * 86400


class ApiMiddleware:
    """CORS for /api/*, preflight handling and request logging for auth & billing."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_api = request.path.startswith("/api/")
        if is_api and request.method == "OPTIONS":
            resp = HttpResponse(status=204)
        else:
            resp = self.get_response(request)
        if is_api:
            for k, v in CORS_HEADERS.items():
                resp[k] = v
            resp["Cache-Control"] = "no-store"
            if request.path.startswith(("/api/auth", "/api/billing")):
                log.info(f"[api] {request.method} {request.path} → {resp.status_code}")
        return resp


def token_from(request) -> tuple[str | None, str | None]:
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer ") and len(h) > 20:
        return h[7:], "authorization"
    if request.headers.get("X-Auth-Token"):
        return request.headers["X-Auth-Token"], "x-auth-token"
    c = request.COOKIES.get(COOKIE_NAME)
    if c:
        return unquote(c), "cookie"
    return None, None


def client_ip(request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")


def error_response(e: HttpError) -> JsonResponse:
    data = {"error": e.message}
    if e.field:
        data["field"] = e.field
    data.update(e.extra)
    return JsonResponse(data, status=e.status)


def set_session_cookie(resp, token):
    resp.set_cookie(COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, path="/", httponly=True, secure=True, samesite="None")


def clear_session_cookie(resp):
    resp.set_cookie(COOKIE_NAME, "", max_age=0, path="/", httponly=True, secure=True, samesite="None")


def _parse_body(request) -> dict:
    if request.method != "POST":
        return {}
    raw = request.body
    if len(raw) > settings.API_MAX_BODY:
        raise HttpError(413, "Request is too large.")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HttpError(400, "Invalid request data.")
    if not isinstance(data, dict):
        raise HttpError(400, "Invalid request data.")
    return data


def api(auth_required=False, access=False, methods=("GET",), admin=False):
    def deco(fn):
        @csrf_exempt
        @functools.wraps(fn)
        def view(request, *args, **kwargs):
            if request.method not in methods:
                return JsonResponse({"error": "Method not allowed."}, status=405)
            try:
                if admin and request.headers.get("x-admin-key") != settings.ADMIN_KEY:
                    raise HttpError(401, "Invalid admin key.")
                user, before = None, None
                if auth_required:
                    token, via = token_from(request)
                    # CSRF defence: a cookie-authenticated POST must be JSON. Browsers cannot send a
                    # cross-site JSON request with cookies without a CORS preflight we never approve.
                    if via == "cookie" and request.method == "POST" and not request.content_type.startswith("application/json"):
                        raise HttpError(403, "Requests must be sent as JSON.")
                body = _parse_body(request)
                if auth_required:
                    user, code, msg = auth.user_from_token(token)
                    if not user:
                        if not (code == "NO_TOKEN" and request.path == "/api/me"):
                            log.warning(f"[auth] 401 {code} on {request.method} {request.path} (via {via or 'none'})")
                        raise HttpError(401, msg, code=code)
                    if access:
                        denied = auth.access_error(user)
                        if denied:
                            raise denied
                    before = copy.deepcopy(user)
                result = fn(request, user, body, *args, **kwargs) if auth_required else fn(request, body, *args, **kwargs)
                if user is not None and user != before:
                    store.save_user(user)
                if isinstance(result, HttpResponse):
                    return result
                status = 200
                if isinstance(result, tuple):
                    result, status = result
                return JsonResponse(result, status=status, safe=False, json_dumps_params={"ensure_ascii": False})
            except HttpError as e:
                return error_response(e)
            except Exception:  # noqa: BLE001
                log.exception(f"[error] {request.method} {request.path}")
                return JsonResponse({"error": "Something went wrong."}, status=500)
        return view
    return deco
