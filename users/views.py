from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import UserSerializer
from django.contrib.auth import get_user_model

User = get_user_model()

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    # Allow any user (authenticated or not) to access this view
    permission_classes = (permissions.AllowAny,)
    serializer_class = UserSerializer

class UserDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

from rest_framework import viewsets, filters

class UserViewSet(viewsets.ModelViewSet):
    """
    Search/List users for project membership.
    Manage Platform Members.
    """
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'email']
    
    def get_queryset(self):
        queryset = User.objects.all()
        username = self.request.query_params.get('username')
        if username:
            queryset = queryset.filter(username__icontains=username)
        return queryset

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_staff and not user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only Admin/Owner can delete users.")
        
        # Admin cannot delete Superuser
        if instance.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Cannot delete Owner.")

        # Admin cannot delete other Admins ?? (Assuming Owner deletes Admins)
        if instance.is_staff and not user.is_superuser:
             from rest_framework.exceptions import PermissionDenied
             raise PermissionDenied("Only Owner can delete Admins.")

        instance.delete()

    def perform_update(self, serializer):
        user = self.request.user
        if not user.is_staff and not user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only Admin/Owner can modify users.")
        
        # Check targets
        instance = self.get_object()
        
        # Prevent modification of Superuser by non-Superuser
        if instance.is_superuser and not user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only Owner can modify Owner.")
        
        serializer.save()


from rest_framework.decorators import action
from rest_framework import status
from django.core.cache import cache
import random
import string


class TelegramBindViewSet(viewsets.ViewSet):
    """
    ViewSet for Telegram binding operations.
    """
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='generate-code')
    def generate_code(self, request):
        """
        Generate a 6-digit binding code and store it in Redis.
        """
        code = ''.join(random.choices(string.digits, k=6))
        cache_key = f"tg_bind:{code}"
        # Store user_id with 5 minute TTL
        cache.set(cache_key, request.user.id, timeout=300)
        return Response({
            'code': code,
            'expires_in': 300,
            'instruction': f'请在 Telegram 中向机器人发送: /bind {code}'
        })

    @action(detail=False, methods=['post'], url_path='unbind')
    def unbind(self, request):
        """
        Remove TelegramUser association for the current user.
        """
        from .models import TelegramUser
        try:
            tg_user = TelegramUser.objects.get(user=request.user)
            tg_user.delete()
            return Response({'message': 'Telegram 已解绑'})
        except TelegramUser.DoesNotExist:
            return Response({'error': '未绑定 Telegram'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='status')
    def get_status(self, request):
        """
        Get current user's Telegram binding status.
        """
        from .models import TelegramUser
        try:
            tg_user = TelegramUser.objects.get(user=request.user)
            return Response({
                'bound': True,
                'telegram_id': tg_user.telegram_id,
                'username': tg_user.username
            })
        except TelegramUser.DoesNotExist:
            return Response({'bound': False})
