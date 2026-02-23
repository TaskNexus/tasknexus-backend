from django.apps import AppConfig


class PlatformConfigApp(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'config'
    label = 'platform_config'  # Avoid conflict with Django's internal 'config'
    verbose_name = 'Platform Configuration'
