import logging
import json
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from projects.models import Project
from .models import ChatSession, ChatMessage
from .serializers import ChatSessionSerializer, ChatMessageSerializer
from django.shortcuts import get_object_or_404

try:
    import openai
except ImportError:
    openai = None

logger = logging.getLogger('django')

class ChatViewSet(viewsets.ViewSet):
    """
    A ViewSet for handling AI Chat completions and Session Management.
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get', 'post'], url_path='sessions')
    def sessions(self, request):
        """
        GET: List all chat sessions for the current user.
        POST: Create a new empty session manually.
        """
        if request.method == 'GET':
            sessions = ChatSession.objects.filter(user=request.user)
            serializer = ChatSessionSerializer(sessions, many=True)
            return Response(serializer.data)
        
        elif request.method == 'POST':
            serializer = ChatSessionSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                session = serializer.save()
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'], url_path='messages')
    def get_messages(self, request, pk=None):
        """Get messages for a specific session."""
        session = get_object_or_404(ChatSession, pk=pk, user=request.user)
        messages = session.messages.all()
        serializer = ChatMessageSerializer(messages, many=True)
        return Response(serializer.data)
        
    @action(detail=True, methods=['patch', 'delete'], url_path='session')
    def manage_session(self, request, pk=None):
        """Update (rename) or delete a session."""
        session = get_object_or_404(ChatSession, pk=pk, user=request.user)
        
        if request.method == 'DELETE':
            session.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        if request.method == 'PATCH':
            title = request.data.get('title')
            if title:
                session.title = title
                session.save()
                return Response(ChatSessionSerializer(session).data)
            return Response({'error': 'Title required'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='completions')
    def completions(self, request):
        """
        Handle chat completions using the unified ChatService.
        """
        data = request.data
        project_id = data.get('project_id')
        model_group_name = data.get('model_group')
        model_name = data.get('model')
        messages_payload = data.get('messages', [])
        session_id = data.get('session_id')
        
        user_content = None
        if messages_payload and len(messages_payload) > 0:
            last_msg = messages_payload[-1]
            if last_msg.get('role') == 'user':
                user_content = last_msg.get('content')

        # Basic Validation
        if not all([project_id, model_group_name]):
             return Response(
                {'error': 'Missing required fields: project_id, model_group'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
            from agents.services import ChatService
            
            service = ChatService(
                user=request.user,
                session_id=session_id,
                project_id=project_id,
                model_group=model_group_name,
                model_name=model_name
            )
            
            result = service.process_message(
                user_content=user_content,
                messages_payload=messages_payload
            )
            
            return Response(result)

        except Project.DoesNotExist:
            return Response({'error': 'Project not found'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as ve:
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Chat completion failed")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'], url_path='completions/stream')
    def completions_stream(self, request):
        """
        Handle chat completions with SSE streaming response.
        Each message is sent as it's generated, allowing real-time display.
        """
        from django.http import StreamingHttpResponse
        
        data = request.data
        project_id = data.get('project_id')
        model_group_name = data.get('model_group')
        model_name = data.get('model')
        messages_payload = data.get('messages', [])
        session_id = data.get('session_id')
        
        user_content = None
        if messages_payload and len(messages_payload) > 0:
            last_msg = messages_payload[-1]
            if last_msg.get('role') == 'user':
                user_content = last_msg.get('content')

        # Basic Validation
        if not all([project_id, model_group_name]):
            return Response(
                {'error': 'Missing required fields: project_id, model_group'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        def event_stream():
            """Generator that yields SSE formatted events."""
            try:
                from agents.services import ChatService
                
                service = ChatService(
                    user=request.user,
                    session_id=session_id,
                    project_id=project_id,
                    model_group=model_group_name,
                    model_name=model_name
                )
                
                for event in service.process_message_stream(
                    user_content=user_content,
                    messages_payload=messages_payload
                ):
                    # Format as SSE: "data: {json}\n\n"
                    yield f"data: {json.dumps(event)}\n\n"
                    
            except Exception as e:
                logger.exception("Streaming chat completion failed")
                error_event = {'type': 'error', 'error': str(e)}
                yield f"data: {json.dumps(error_event)}\n\n"
        
        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'  # Disable nginx buffering
        return response
