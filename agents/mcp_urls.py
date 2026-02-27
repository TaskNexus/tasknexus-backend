from django.urls import path
from .mcp_views import MCPTestConnectionView

urlpatterns = [
    path('test/', MCPTestConnectionView.as_view(), name='mcp-test-connection'),
]
