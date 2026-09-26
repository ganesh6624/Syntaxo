"""
Save every account, game attempt and payment to one JSON file (a portable backup).

    python manage.py export_data                   # writes data/backup.json
    python manage.py export_data path/to/file.json

Restore with:  python manage.py import_data path/to/file.json
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core import store
from core.models import Attempt, Counter, Payment


class Command(BaseCommand):
    help = "Export accounts, attempts and payments to a JSON backup file."

    def add_arguments(self, parser):
        parser.add_argument("file", nargs="?", default=str(settings.DATA_DIR / "backup.json"))

    def handle(self, *args, **opts):
        users = store.all_users()
        attempts = [a.doc for a in Attempt.objects.order_by("id")]
        payments = [p.doc for p in Payment.objects.order_by("id")]
        c = Counter.objects.filter(name="nextUserNo").first()
        data = {"meta": {"nextUserNo": c.value if c else None}, "users": users, "attempts": attempts, "payments": payments}
        f = Path(opts["file"])
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)
        self.stdout.write(self.style.SUCCESS(f"Saved {len(users)} users, {len(attempts)} attempts, {len(payments)} payments → {f}"))
