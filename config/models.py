import uuid

from django.db import models
from django.conf import settings
from django.utils import timezone


class PlatformConfig(models.Model):
    """
    Platform-wide configuration - singleton model.
    Stores global settings like Feishu integration config in a JSONField.

    Usage:
        config = PlatformConfig.get_config()
        feishu = PlatformConfig.get_feishu_config()

    Config structure:
        {
            "feishu": {
                "app_id": "cli_xxx",
                "app_secret": "xxx",
                "redirect_uri": "http://...",
                "login_enabled": true
            },
            "registration": {
                "registration_enabled": true
            },
            "email": {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "user@example.com",
                "smtp_password": "xxx",
                "smtp_use_tls": true,
                "from_email": "noreply@example.com"
            }
        }
    """
    CACHE_KEY = 'platform_config'
    CACHE_TIMEOUT = 300  # 5 minutes

    config = models.JSONField(default=dict, blank=True, verbose_name="Configuration")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Platform Configuration"
        verbose_name_plural = "Platform Configuration"

    def __str__(self):
        return "Platform Configuration"

    def save(self, *args, **kwargs):
        # Ensure singleton: always use pk=1
        self.pk = 1
        super().save(*args, **kwargs)
        # Invalidate cache on save
        from django.core.cache import cache
        cache.delete(self.CACHE_KEY)

    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def get_config(cls) -> dict:
        """Get the full config dict, with caching."""
        from django.core.cache import cache
        config = cache.get(cls.CACHE_KEY)
        if config is None:
            obj = cls.get_instance()
            config = obj.config or {}
            cache.set(cls.CACHE_KEY, config, cls.CACHE_TIMEOUT)
        return config

    @classmethod
    def get_feishu_config(cls) -> dict:
        """
        Get Feishu config from DB.
        Returns dict with keys: app_id, app_secret, redirect_uri, login_enabled
        """
        config = cls.get_config()
        feishu = config.get('feishu', {})
        return {
            'app_id': feishu.get('app_id', ''),
            'app_secret': feishu.get('app_secret', ''),
            'redirect_uri': feishu.get('redirect_uri', ''),
            'login_enabled': feishu.get('login_enabled', False),
        }

    @classmethod
    def get_registration_config(cls) -> dict:
        """Get registration config. Default: registration enabled."""
        config = cls.get_config()
        reg = config.get('registration', {})
        return {
            'registration_enabled': reg.get('registration_enabled', True),
        }

    @classmethod
    def get_email_config(cls) -> dict:
        """Get SMTP email config from DB."""
        config = cls.get_config()
        email = config.get('email', {})
        return {
            'smtp_host': email.get('smtp_host', ''),
            'smtp_port': email.get('smtp_port', 587),
            'smtp_user': email.get('smtp_user', ''),
            'smtp_password': email.get('smtp_password', ''),
            'smtp_use_tls': email.get('smtp_use_tls', True),
            'from_email': email.get('from_email', ''),
        }


class InviteLink(models.Model):
    """
    Invitation link for user registration.
    Bypass the registration_enabled toggle but still require email verification.
    """
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_invites',
    )
    expires_at = models.DateTimeField()
    max_uses = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invite {self.token} (by {self.created_by})"

    @property
    def is_valid(self) -> bool:
        """Check if the invite link is still usable."""
        if not self.is_active:
            return False
        if timezone.now() > self.expires_at:
            return False
        if self.used_count >= self.max_uses:
            return False
        return True
