from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'plugins'
    verbose_name = 'TaskNexus Plugins'
    
    def ready(self):
        # Auto-discover plugins on app ready (optional)
        pass
