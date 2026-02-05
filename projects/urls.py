from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProjectViewSet, DashboardStatsView, ProjectMemberViewSet

router = DefaultRouter()
router.register(r'members', ProjectMemberViewSet, basename='project-members')
router.register(r'', ProjectViewSet, basename='projects')

urlpatterns = [
    path('dashboard/', DashboardStatsView.as_view(), name='dashboard'),
    path('', include(router.urls)),
]
