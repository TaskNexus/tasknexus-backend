from django.db import models


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
