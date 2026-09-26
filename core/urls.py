from django.urls import path, re_path

from . import views as v

urlpatterns = [
    # pages
    path("", v.index_page),
    path("index.html", v.index_page),
    path("admin.html", v.admin_page),

    # auth
    path("api/auth/register", v.register),
    path("api/auth/login", v.login),
    path("api/auth/logout", v.logout),
    path("api/auth/forgot", v.forgot),
    path("api/auth/verify-code", v.verify_code),
    path("api/auth/reset-password", v.reset_password),
    path("api/me", v.me),
    path("api/me/mobile", v.me_mobile),

    # curriculum & games
    path("api/languages", v.languages),
    path("api/public/languages", v.public_languages),
    path("api/lesson/<str:lang>/<int:level>", v.lesson),
    path("api/game/start", v.game_start),
    path("api/game/next", v.game_next),
    path("api/game/answer", v.game_answer),
    path("api/game/finish", v.game_finish),

    # agent & chat
    path("api/agent/report", v.agent_report),
    path("api/agent/chat", v.agent_chat),
    path("api/agent/chat/clear", v.agent_chat_clear),

    # subscription & billing
    path("api/plans", v.plans_view),
    path("api/billing/order", v.billing_order),
    path("api/billing/verify", v.billing_verify),

    # leaderboard & admin
    path("api/leaderboard", v.leaderboard),
    path("api/admin/users", v.admin_users),
    path("api/admin/users/<str:user_id>/trial", v.admin_trial),

    re_path(r"^api/(?P<path>.*)$", v.api_not_found),
    # everything else: files from public/ (app.js, styles.css …)
    re_path(r"^(?P<path>[A-Za-z0-9_.\-/]+)$", v.public_file),
]
