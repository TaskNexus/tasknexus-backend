from django.apps import AppConfig


class ClientAgentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'client_agents'
    verbose_name = '客户端 Agent'

    def ready(self):
        # Import signals when app is ready
        try:
            import client_agents.signals  # noqa
        except ImportError:
            pass
