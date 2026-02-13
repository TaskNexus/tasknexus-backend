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


class FeishuOAuthViewSet(viewsets.ViewSet):
    """
    Feishu OAuth login endpoints.
    """
    
    @action(detail=False, methods=['get'], url_path='login_url', permission_classes=[permissions.AllowAny])
    def login_url(self, request):
        """
        Generate Feishu authorization URL.
        
        GET /api/auth/feishu/login_url/
        Returns: { "authorize_url": "https://accounts.feishu.cn/..." }
        """
        from .feishu_oauth import FeishuOAuthService
        
        service = FeishuOAuthService()
        state = request.query_params.get('state', '')
        authorize_url = service.get_authorize_url(state=state)
        
        return Response({'authorize_url': authorize_url})
    
    @action(detail=False, methods=['get'], url_path='qr_login_url', permission_classes=[permissions.AllowAny])
    def qr_login_url(self, request):
        """
        Generate Feishu QR code login URL for SDK.
        
        GET /api/auth/feishu/qr_login_url/
        Returns: { 
            "goto_url": "https://passport.feishu.cn/...", 
            "redirect_url_with_code": "https://passport.feishu.cn/...&tmp_code={tmp_code}"
        }
        """
        from .feishu_oauth import FeishuOAuthService
        from urllib.parse import urlencode, quote
        
        service = FeishuOAuthService()
        state = request.query_params.get('state', '')
        
        # Build the authorization parameters
        params = {
            'client_id': service.app_id,
            'redirect_uri': service.redirect_uri,
            'response_type': 'code',
            'state': state,
        }
        
        # Base URL for QR code SDK
        base_url = 'https://passport.feishu.cn/suite/passport/oauth/authorize'
        goto_url = f"{base_url}?{urlencode(params)}"
        
        # URL to redirect to after scanning (with tmp_code placeholder)
        redirect_url_with_code = f"{goto_url}&tmp_code={{tmp_code}}"
        
        return Response({
            'goto_url': goto_url,
            'redirect_url_with_code': redirect_url_with_code
        })
    
    @action(detail=False, methods=['get'], url_path='callback', permission_classes=[permissions.AllowAny])
    def callback(self, request):
        """
        Handle Feishu OAuth callback.
        
        GET /api/auth/feishu/callback/?code=xxx
        1. Exchange code for access_token
        2. Get Feishu user info
        3. Find or create user
        4. Return JWT tokens
        """
        from .feishu_oauth import FeishuOAuthService, FeishuOAuthError
        from rest_framework_simplejwt.tokens import RefreshToken
        
        code = request.query_params.get('code')
        if not code:
            return Response({'error': 'Missing authorization code'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            service = FeishuOAuthService()
            
            # Exchange code for token
            token_data = service.exchange_code_for_token(code)
            access_token = token_data.get('access_token')
            
            if not access_token:
                return Response({'error': 'Failed to get access token'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Get user info
            user_info = service.get_user_info(access_token)
            open_id = user_info.get('open_id')
            union_id = user_info.get('union_id')
            name = user_info.get('name', '')
            avatar_url = user_info.get('avatar_url', '')
            
            if not open_id:
                return Response({'error': 'Failed to get user info'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Find or create user
            user = User.objects.filter(feishu_openid=open_id).first()
            
            if not user:
                # Create new user with Feishu info
                username = f"feishu_{open_id[:8]}"
                # Ensure unique username
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1
                
                user = User.objects.create(
                    username=username,
                    feishu_openid=open_id,
                    feishu_union_id=union_id,
                    feishu_name=name,
                    feishu_avatar_url=avatar_url,
                    first_name=name,
                )
            else:
                # Update existing user info
                user.feishu_union_id = union_id
                user.feishu_name = name
                user.feishu_avatar_url = avatar_url
                user.save(update_fields=['feishu_union_id', 'feishu_name', 'feishu_avatar_url'])
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'access': str(refresh.access_token),
                'refresh': str(refresh),
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'feishu_name': user.feishu_name,
                }
            })
            
        except FeishuOAuthError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Internal error: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def bind(self, request):
        """
        Bind Feishu account to current logged-in user.
        
        POST /api/auth/feishu/bind/ { "code": "xxx" }
        """
        from .feishu_oauth import FeishuOAuthService, FeishuOAuthError
        
        code = request.data.get('code')
        if not code:
            return Response({'error': 'Missing authorization code'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            service = FeishuOAuthService()
            
            token_data = service.exchange_code_for_token(code)
            access_token = token_data.get('access_token')
            
            if not access_token:
                return Response({'error': 'Failed to get access token'}, status=status.HTTP_400_BAD_REQUEST)
            
            user_info = service.get_user_info(access_token)
            open_id = user_info.get('open_id')
            union_id = user_info.get('union_id')
            name = user_info.get('name', '')
            avatar_url = user_info.get('avatar_url', '')
            
            # Check if this Feishu account is already bound to another user
            existing_user = User.objects.filter(feishu_openid=open_id).exclude(id=request.user.id).first()
            if existing_user:
                return Response({'error': '该飞书账号已绑定其他用户'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Bind to current user
            request.user.feishu_openid = open_id
            request.user.feishu_union_id = union_id
            request.user.feishu_name = name
            request.user.feishu_avatar_url = avatar_url
            request.user.save(update_fields=['feishu_openid', 'feishu_union_id', 'feishu_name', 'feishu_avatar_url'])
            
            return Response({
                'message': '飞书账号绑定成功',
                'feishu_name': name,
            })
            
        except FeishuOAuthError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def unbind(self, request):
        """
        Unbind Feishu account from current user.
        
        POST /api/auth/feishu/unbind/
        """
        if not request.user.feishu_openid:
            return Response({'error': '未绑定飞书账号'}, status=status.HTTP_400_BAD_REQUEST)
        
        request.user.feishu_openid = None
        request.user.feishu_union_id = None
        request.user.feishu_name = None
        request.user.feishu_avatar_url = None
        request.user.save(update_fields=['feishu_openid', 'feishu_union_id', 'feishu_name', 'feishu_avatar_url'])
        
        return Response({'message': '飞书账号已解绑'})
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def status(self, request):
        """
        Get current user's Feishu binding status.
        
        GET /api/auth/feishu/status/
        """
        if request.user.feishu_openid:
            return Response({
                'bound': True,
                'feishu_name': request.user.feishu_name,
                'feishu_avatar_url': request.user.feishu_avatar_url,
            })
        else:
            return Response({'bound': False})
