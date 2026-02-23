# -*- coding: utf-8 -*-
"""
Platform Configuration API Views

GET  /api/platform/config/ — Read config (admin only)
PUT  /api/platform/config/ — Update config (admin only)
GET  /api/platform/feishu-login-status/ — Check if Feishu login is enabled (public)
"""

import copy

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework import status

from config.models import PlatformConfig


class PlatformConfigView(APIView):
    """
    Platform-wide configuration endpoint.
    Only superusers / admin users can access.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        """Return the platform config, with app_secret masked."""
        config = PlatformConfig.get_config()
        safe_config = copy.deepcopy(config)
        self._mask_secrets(safe_config)
        return Response(safe_config)

    def put(self, request):
        """Update the platform config."""
        new_config = request.data
        if not isinstance(new_config, dict):
            return Response(
                {'detail': 'Config must be a JSON object'},
                status=status.HTTP_400_BAD_REQUEST
            )

        obj = PlatformConfig.get_instance()
        existing = obj.config or {}

        # Handle app_secret: if it ends with '***' (masked), keep the old value
        new_feishu = new_config.get('feishu', {})
        old_feishu = existing.get('feishu', {})
        if new_feishu.get('app_secret', '').endswith('***'):
            new_feishu['app_secret'] = old_feishu.get('app_secret', '')

        # Merge: replace top-level keys
        existing.update(new_config)
        obj.config = existing
        obj.save()

        # Return masked version
        safe_config = copy.deepcopy(obj.config)
        self._mask_secrets(safe_config)
        return Response(safe_config)

    @staticmethod
    def _mask_secrets(config: dict):
        """Mask sensitive fields in config for API response."""
        feishu = config.get('feishu', {})
        if feishu.get('app_secret'):
            secret = feishu['app_secret']
            feishu['app_secret'] = secret[:6] + '***' if len(secret) > 6 else '***'


class FeishuLoginStatusView(APIView):
    """
    Public endpoint: returns whether Feishu login is enabled.
    No authentication required — used by the login page.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        feishu_config = PlatformConfig.get_feishu_config()
        return Response({
            'login_enabled': feishu_config.get('login_enabled', False)
        })

