from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ClientAgentViewSet, AgentWorkspaceViewSet, AgentTaskViewSet

router = DefaultRouter()
router.register(r'agents', ClientAgentViewSet, basename='client-agent')
router.register(r'workspaces', AgentWorkspaceViewSet, basename='agent-workspace')
router.register(r'agent-tasks', AgentTaskViewSet, basename='agent-task')

urlpatterns = [
    path('', include(router.urls)),
]

