from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import RegisterView, UserDetailView, UserViewSet, TelegramBindViewSet, FeishuOAuthViewSet
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

router = DefaultRouter()
router.register(r'users', UserViewSet)
router.register(r'telegram', TelegramBindViewSet, basename='telegram')
router.register(r'feishu', FeishuOAuthViewSet, basename='feishu')

urlpatterns = [
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', UserDetailView.as_view(), name='auth_me'),
    path('', include(router.urls)),
]
