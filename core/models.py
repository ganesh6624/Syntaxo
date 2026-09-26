"""
Database models.

Each record keeps its full data in a JSON document (`doc`) so the game logic can work with
plain Python dicts, while the fields that must be searchable or unique (username, email,
mobile …) are real indexed columns with UNIQUE constraints enforced by the database.
"""
from django.db import models


class Player(models.Model):
    user_id = models.CharField("User ID", max_length=20, unique=True)
    username = models.CharField(max_length=40)
    username_key = models.CharField(max_length=40, unique=True, editable=False)  # lower-case, for unique checks
    email = models.CharField(max_length=254, unique=True)                        # stored lower-case
    mobile = models.CharField(max_length=20, unique=True, null=True, blank=True)  # E.164, e.g. +919876543210
    full_name = models.CharField(max_length=120)
    xp = models.IntegerField(default=0, db_index=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)
    doc = models.JSONField(default=dict)

    class Meta:
        ordering = ["user_id"]
        verbose_name = "player"

    def __str__(self):
        return f"{self.user_id} · {self.username}"


class Attempt(models.Model):
    """One finished game (used by the personal agent for its analysis)."""
    attempt_id = models.CharField(max_length=40, unique=True)
    user_id = models.CharField(max_length=20, db_index=True)
    lang = models.CharField(max_length=20)
    level = models.IntegerField()
    accuracy = models.IntegerField(default=0)
    passed = models.BooleanField(default=False)
    at = models.DateTimeField(db_index=True)
    doc = models.JSONField(default=dict)

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"{self.user_id} {self.lang} P{self.level} {self.accuracy}%"


class Payment(models.Model):
    order_id = models.CharField(max_length=80, unique=True)
    user_id = models.CharField(max_length=20, db_index=True)
    plan = models.CharField(max_length=20)
    amount = models.IntegerField()
    status = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField()
    doc = models.JSONField(default=dict)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.order_id} {self.status}"


class GameSession(models.Model):
    """A game in progress (kept in the database so it survives restarts and works with many workers)."""
    session_id = models.CharField(max_length=40, unique=True)
    user_id = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(db_index=True)
    doc = models.JSONField(default=dict)


class Counter(models.Model):
    """Named counters, e.g. the next User ID number."""
    name = models.CharField(max_length=40, unique=True)
    value = models.BigIntegerField(default=0)
