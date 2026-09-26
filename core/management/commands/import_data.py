"""
Restore accounts, game history and payments from a JSON backup made by `python manage.py export_data`.

    python manage.py import_data                   # reads data/backup.json
    python manage.py import_data path/to/backup.json

Existing accounts (same User ID) are skipped, so running it twice is safe.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import store
from core.models import Attempt, Payment, Player


class Command(BaseCommand):
    help = "Restore accounts, attempts and payments from a JSON backup (see export_data)."

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", default=str(settings.DATA_DIR / "backup.json"))
        parser.add_argument("--if-empty", action="store_true", help="only import when the database has no accounts yet")

    @transaction.atomic
    def handle(self, *args, **opts):
        f = Path(opts["file"])
        if opts["if_empty"] and (Player.objects.exists() or not f.exists()):
            return
        if not f.exists():
            raise CommandError(f"{f} not found")
        data = json.loads(f.read_text(encoding="utf-8"))
        users = attempts = payments = skipped = 0
        for u in data.get("users", []):
            if Player.objects.filter(user_id=u["userId"]).exists():
                skipped += 1
                continue
            u.setdefault("stats", {"xp": 0, "gamesPlayed": 0, "streak": {"current": 0, "best": 0, "lastDay": None}})
            u.setdefault("progress", {})
            u.setdefault("agentLog", [])
            store.insert_user(u)
            users += 1
        for a in data.get("attempts", []):
            if not Attempt.objects.filter(attempt_id=a["id"]).exists():
                store.insert_attempt(a)
                attempts += 1
        for p in data.get("payments", []):
            if not Payment.objects.filter(order_id=p["orderId"]).exists():
                store.insert_payment(p)
                payments += 1
        nxt = (data.get("meta") or {}).get("nextUserNo")
        if nxt:
            nums = [int(x[2:]) for x in Player.objects.values_list("user_id", flat=True) if x[2:].isdigit()]
            store.set_next_user_no(max([int(nxt), *[n + 1 for n in nums]]))
        self.stdout.write(self.style.SUCCESS(f"Imported {users} users ({skipped} already present), {attempts} attempts, {payments} payments."))
