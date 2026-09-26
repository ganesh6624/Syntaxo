"""
Email sending.
 • Real mode: set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, MAIL_FROM
   (e.g. Gmail: smtp.gmail.com / 465 / your address / an App Password).
 • Demo mode (no SMTP configured): emails are printed to the server console and returned
   to the API caller as `devPreview`, so the whole flow can be tested without a mail server.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from .util import to_date_string

log = logging.getLogger("syntaxo")

SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
FROM = os.environ.get("MAIL_FROM", "Syntaxo <no-reply@syntaxo.app>")
DEMO = not SMTP_HOST


def _wrap(title, body):
    return (f'<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">'
            f'<div style="background:linear-gradient(90deg,#ecd190,#b88c2e);color:#3b2a05;padding:18px 22px;font-size:20px;font-weight:bold">Syntaxo</div>'
            f'<div style="padding:22px;color:#111827;line-height:1.6"><h2 style="margin-top:0">{title}</h2>{body}</div>'
            f'<div style="padding:12px 22px;background:#f9fafb;color:#6b7280;font-size:12px">You received this email because of activity on your Syntaxo account.</div></div>')


def send(to, subject, text, html) -> dict:
    if DEMO:
        body = text.replace("\n", "\n   ")
        log.info(f"\n[demo email] To: {to}\n   Subject: {subject}\n   {body}\n")
        return {"demo": True, "devPreview": {"to": to, "subject": subject, "text": text}}
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = FROM, to, subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=20) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS or "")
            s.send_message(msg)
    return {"demo": False}


# All user-provided values are HTML-escaped in the HTML versions.
def welcome(u, trial_days):
    n, un, uid = escape(u["fullName"]), escape(u["username"]), escape(u["userId"])
    return {
        "subject": f"Welcome to Syntaxo, {u['username']}!",
        "text": f"Hi {u['fullName']},\n\nYour account is ready!\nUsername: {u['username']}\nUser ID: {u['userId']}\n\n"
                f"Log in with your username and password. Your {trial_days}-day free trial starts today.\n\nHappy coding!",
        "html": _wrap("Welcome aboard!", f'<p>Hi {n}, your account is ready.</p><p style="font-size:22px">Username: <b style="font-family:monospace;color:#b88c2e">{un}</b></p>'
                                        f'<p>User ID: {uid}</p><p>Log in with your username and password. Your <b>{trial_days}-day free trial</b> starts today.</p>'),
    }


def recovery(u, code, minutes):
    n, un, uid = escape(u["fullName"]), escape(u["username"]), escape(u["userId"])
    return {
        "subject": f"Syntaxo account recovery — code {code}",
        "text": f"Hi {u['fullName']},\n\nYour username is: {u['username']}\n(User ID: {u['userId']})\n\nTo reset your password, enter this verification code: {code}\n"
                f"The code expires in {minutes} minutes.\n\nIf you didn't request this, you can ignore this email.",
        "html": _wrap("Account recovery", f'<p>Hi {n},</p><p>Your username is: <b style="font-family:monospace;font-size:18px;color:#b88c2e">{un}</b> '
                                          f'<span style="color:#6b7280">(User ID {uid})</span></p><p>To reset your password, enter this code:</p>'
                                          f'<p style="font-size:30px;letter-spacing:8px;font-weight:bold;font-family:monospace">{code}</p>'
                                          f'<p style="color:#6b7280">The code expires in {minutes} minutes. If you didn\'t request this, ignore this email.</p>'),
    }


def password_changed(u):
    n, un = escape(u["fullName"]), escape(u["username"])
    return {
        "subject": "Your Syntaxo password was changed",
        "text": f"Hi {u['fullName']},\n\nThe password for username {u['username']} (User ID {u['userId']}) was just changed. "
                f"If this wasn't you, reset it immediately using \"Forgot username or password\".",
        "html": _wrap("Password changed", f"<p>Hi {n}, the password for username <b>{un}</b> was just changed.</p><p>If this wasn't you, reset it immediately.</p>"),
    }


def receipt(u, plan, sub, payment_id):
    n = escape(u["fullName"])
    until = to_date_string(sub["expiresAt"])
    return {
        "subject": f"Payment received — Syntaxo {plan['name']} plan",
        "text": f"Hi {u['fullName']},\n\nThank you for subscribing!\nPlan: {plan['name']}\nAmount: ₹{plan['price']}\nValid until: {until}\nPayment ID: {payment_id}\n\nHappy coding!",
        "html": _wrap("Payment received", f'<p>Hi {n}, thank you for subscribing!</p><table style="width:100%"><tr><td>Plan</td><td><b>{plan["name"]}</b></td></tr>'
                                          f'<tr><td>Amount</td><td><b>₹{plan["price"]}</b></td></tr><tr><td>Valid until</td><td><b>{until}</b></td></tr>'
                                          f'<tr><td>Payment ID</td><td style="font-family:monospace">{escape(payment_id)}</td></tr></table>'),
    }
