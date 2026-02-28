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
from rest_framework.routers import DefaultRouter

from tasks.feishu_views import FeishuUsersView
from config.views import (
    PlatformConfigView,
    FeishuLoginStatusView,
    RegistrationStatusView,
    InviteLinkViewSet,
    InviteValidateView,
)

invite_router = DefaultRouter()
invite_router.register(r'invites', InviteLinkViewSet, basename='invite')


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('api/health/', health_check, name='health_check'),
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
    path('api/platform/config/', PlatformConfigView.as_view(), name='platform-config'),
    path('api/platform/feishu-login-status/', FeishuLoginStatusView.as_view(), name='feishu-login-status'),
    path('api/platform/registration-status/', RegistrationStatusView.as_view(), name='registration-status'),
    path('api/platform/invites/validate/', InviteValidateView.as_view(), name='invite-validate'),
    path('api/platform/', include(invite_router.urls)),
]

