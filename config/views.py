# -*- coding: utf-8 -*-
"""
Platform Configuration API Views

GET  /api/platform/config/ — Read config (admin only)
PUT  /api/platform/config/ — Update config (admin only)
GET  /api/platform/feishu-login-status/ — Check if Feishu login is enabled (public)
GET  /api/platform/registration-status/ — Check if registration is enabled (public)
POST /api/platform/invites/ — Create invite link (admin only)
GET  /api/platform/invites/ — List invite links (admin only)
DELETE /api/platform/invites/{id}/ — Revoke invite link (admin only)
GET  /api/platform/invites/validate/?token=xxx — Validate invite token (public)
"""

import copy
from datetime import timedelta

from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, AllowAny
from rest_framework import status, serializers, viewsets, permissions

from config.models import PlatformConfig, InviteLink


class PlatformConfigView(APIView):
    """
    Platform-wide configuration endpoint.
    Only superusers / admin users can access.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        """Return the platform config, with secrets masked."""
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

        # Handle smtp_password: if it ends with '***' (masked), keep the old value
        new_email = new_config.get('email', {})
        old_email = existing.get('email', {})
        if new_email.get('smtp_password', '').endswith('***'):
            new_email['smtp_password'] = old_email.get('smtp_password', '')

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

        email = config.get('email', {})
        if email.get('smtp_password'):
            pwd = email['smtp_password']
            email['smtp_password'] = pwd[:3] + '***' if len(pwd) > 3 else '***'


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


class RegistrationStatusView(APIView):
    """
    Public endpoint: returns whether manual registration is enabled.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        reg_config = PlatformConfig.get_registration_config()
        return Response({
            'registration_enabled': reg_config.get('registration_enabled', True)
        })


# ==================== Invite Links ====================

class InviteLinkSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = InviteLink
        fields = [
            'id', 'token', 'created_by', 'created_by_username',
            'expires_at', 'max_uses', 'used_count', 'is_active',
            'is_valid', 'created_at',
        ]
        read_only_fields = ['id', 'token', 'created_by', 'used_count', 'created_at']


class InviteLinkViewSet(viewsets.ModelViewSet):
    """
    Admin-only CRUD for invite links.
    """
    queryset = InviteLink.objects.all()
    serializer_class = InviteLinkSerializer
    permission_classes = [IsAdminUser]
    http_method_names = ['get', 'post', 'delete']

    def create(self, request, *args, **kwargs):
        expires_hours = request.data.get('expires_hours', 168)  # default 7 days
        max_uses = request.data.get('max_uses', 1)

        try:
            expires_hours = int(expires_hours)
            max_uses = int(max_uses)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid parameters'}, status=status.HTTP_400_BAD_REQUEST)

        invite = InviteLink.objects.create(
            created_by=request.user,
            expires_at=timezone.now() + timedelta(hours=expires_hours),
            max_uses=max_uses,
        )
        serializer = self.get_serializer(invite)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        """Soft-delete: mark as inactive instead of deleting."""
        instance.is_active = False
        instance.save(update_fields=['is_active'])


class InviteValidateView(APIView):
    """
    Public endpoint: validate an invite token.
    GET /api/platform/invites/validate/?token=xxx
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get('token')
        if not token:
            return Response({'valid': False, 'detail': '缺少邀请码'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            invite = InviteLink.objects.get(token=token)
        except (InviteLink.DoesNotExist, Exception):
            return Response({'valid': False, 'detail': '邀请链接无效'})

        if not invite.is_valid:
            reason = '邀请链接已过期或已被使用'
            if not invite.is_active:
                reason = '邀请链接已被撤销'
            return Response({'valid': False, 'detail': reason})

        return Response({'valid': True})
