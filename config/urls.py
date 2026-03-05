"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.core.cache import cache
from django.db import connections
from django.utils import timezone
from rest_framework.routers import DefaultRouter

from tasks.feishu_views import FeishuUsersView, FeishuCardCallbackView
from config.views import (
    PlatformConfigView,
    FeishuLoginStatusView,
    RegistrationStatusView,
    InviteLinkViewSet,
    InviteValidateView,
)

invite_router = DefaultRouter()
invite_router.register(r'invites', InviteLinkViewSet, basename='invite')


STARTED_AT = timezone.now()


def _database_ready():
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, None
    except Exception as exc:  # pragma: no cover - health endpoint fallback
        return False, str(exc)


def _redis_ready():
    key = "__healthcheck__:redis"
    marker = timezone.now().isoformat()
    try:
        cache.set(key, marker, timeout=5)
        if cache.get(key) != marker:
            return False, "cache read-after-write mismatch"
        return True, None
    except Exception as exc:  # pragma: no cover - health endpoint fallback
        return False, str(exc)


def health_live(request):
    return JsonResponse({"status": "ok", "check": "live"})


def health_startup(request):
    return JsonResponse(
        {
            "status": "ok",
            "check": "startup",
            "started_at": STARTED_AT.isoformat(),
        }
    )


def health_ready(request):
    db_ok, db_error = _database_ready()
    redis_ok, redis_error = _redis_ready()
    ok = db_ok and redis_ok
    response = {
        "status": "ok" if ok else "error",
        "check": "ready",
        "dependencies": {
            "database": {"ok": db_ok, "error": db_error},
            "redis": {"ok": redis_ok, "error": redis_error},
        },
    }
    return JsonResponse(response, status=200 if ok else 503)


urlpatterns = [
    path('api/health/', health_ready, name='health_check_legacy'),
    path('api/health/live', health_live, name='health_live'),
    path('api/health/ready', health_ready, name='health_ready'),
    path('api/health/startup', health_startup, name='health_startup'),
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.urls')),
    path('api/workflows/', include('workflows.urls')),
    path('api/projects/', include('projects.urls')),
    path('api/tasks/', include('tasks.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/components/', include('components.urls')),
    path('api/categories/', include('components.category_urls')),
    path('api/ai/', include('agents.urls')),
    path('api/mcp/', include('agents.mcp_urls')),
    path('api/client-agents/', include('client_agents.urls')),
    path('api/feishu/users/', FeishuUsersView.as_view(), name='feishu-users'),
    path('api/feishu/card-callback/', FeishuCardCallbackView.as_view(), name='feishu-card-callback'),
    path('api/platform/config/', PlatformConfigView.as_view(), name='platform-config'),
    path('api/platform/feishu-login-status/', FeishuLoginStatusView.as_view(), name='feishu-login-status'),
    path('api/platform/registration-status/', RegistrationStatusView.as_view(), name='registration-status'),
    path('api/platform/invites/validate/', InviteValidateView.as_view(), name='invite-validate'),
    path('api/platform/', include(invite_router.urls)),
]
