from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Syntaxo administration"
admin.site.site_title = "Syntaxo admin"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("core.urls")),
]
