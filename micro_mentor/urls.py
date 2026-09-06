from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health_view(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("", health_view, name="root"),
    path("health/", health_view, name="health"),
    path("admin/", admin.site.urls),
    path("api/", include("mentorship.urls")),
]
