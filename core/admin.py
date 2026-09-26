"""Django admin (/django-admin/) — create a login with:  python manage.py createsuperuser"""
from django.contrib import admin

from .models import Attempt, GameSession, Payment, Player


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("user_id", "username", "full_name", "email", "mobile", "xp", "created_at")
    search_fields = ("user_id", "username", "full_name", "email", "mobile")
    readonly_fields = ("user_id", "username_key", "created_at", "updated_at")
    ordering = ("user_id",)


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ("user_id", "lang", "level", "accuracy", "passed", "at")
    list_filter = ("lang", "passed")
    search_fields = ("user_id",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("order_id", "user_id", "plan", "amount", "status", "created_at")
    list_filter = ("status", "plan")
    search_fields = ("order_id", "user_id")


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ("session_id", "user_id", "created_at")
