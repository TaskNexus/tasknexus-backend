import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .services import ChatService

logger = logging.getLogger('django')

class AgentViewSet(viewsets.ViewSet):
    """
    ViewSet for direct interaction with AI Agent services.
    Currently focuses on stateless or session-based interactions.
    """
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['post'], url_path='chat')
    def chat(self, request):
        """
        Execute a chat completion. 
        Expects essentially the same payload as the legacy chat app for now.
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
                
        if not all([project_id, model_group_name]):
             return Response(
                {'error': 'Missing required fields: project_id, model_group'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        try:
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
            
        except Exception as e:
            logger.exception("Agent chat failed")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
