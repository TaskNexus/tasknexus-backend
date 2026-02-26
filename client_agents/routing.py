from django.urls import re_path
from . import consumers
from .log_consumer import AgentLogConsumer

websocket_urlpatterns = [
    re_path(r'ws/agent/$', consumers.AgentConsumer.as_asgi()),
    re_path(r'ws/agent-log/(?P<task_id>\d+)/$', AgentLogConsumer.as_asgi()),
]
