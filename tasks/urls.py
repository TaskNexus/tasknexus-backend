from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TaskViewSet, PeriodicTaskViewSet, ScheduledTaskViewSet, WebhookTaskViewSet, webhook_trigger

router = DefaultRouter()
router.register(r'periodic', PeriodicTaskViewSet)
router.register(r'scheduled', ScheduledTaskViewSet)
router.register(r'webhook', WebhookTaskViewSet)
router.register(r'', TaskViewSet)

urlpatterns = [
    path('webhook/<str:token>/trigger/', webhook_trigger, name='webhook-trigger'),
    path('', include(router.urls)),
]
