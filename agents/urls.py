from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AgentViewSet

router = DefaultRouter()
router.register(r'agents', AgentViewSet, basename='agents')

urlpatterns = [
    path('', include(router.urls)),
]
