import logging
from pathlib import Path
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.http import HttpResponse
from .models import ClientAgent, AgentWorkspace, AgentTask
from .consumers import AGENT_LOG_DIR
from .serializers import (
    ClientAgentSerializer, 
    ClientAgentCreateSerializer,
    ClientAgentUpdateSerializer,
    AgentWorkspaceSerializer,
    AgentWorkspaceCreateSerializer,
    AgentWorkspaceUpdateSerializer,
    AgentTaskSerializer
)
from config.pagination import StandardResultsSetPagination

logger = logging.getLogger('django')


class ClientAgentViewSet(viewsets.ModelViewSet):
    """客户端 Agent 管理 API"""
    queryset = ClientAgent.objects.all()
    serializer_class = ClientAgentSerializer
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return ClientAgentCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ClientAgentUpdateSerializer
        return ClientAgentSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=['get'])
    def online(self, request):
        """获取在线 Agent 列表"""
        agents = self.queryset.filter(status='ONLINE')
        serializer = self.get_serializer(agents, many=True)
        return Response(serializer.data)


class AgentWorkspaceViewSet(viewsets.ModelViewSet):
    """Agent 工作空间管理 API"""
    queryset = AgentWorkspace.objects.all()
    serializer_class = AgentWorkspaceSerializer

    def get_serializer_class(self):
        if self.action == 'create':
            return AgentWorkspaceCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return AgentWorkspaceUpdateSerializer
        return AgentWorkspaceSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # 按 Agent 过滤
        agent_id = self.request.query_params.get('agent')
        if agent_id:
            queryset = queryset.filter(agent_id=agent_id)
        
        # 按状态过滤
        ws_status = self.request.query_params.get('status')
        if ws_status:
            queryset = queryset.filter(status=ws_status)
        
        # 按标签过滤
        label = self.request.query_params.get('label')
        if label:
            queryset = queryset.filter(labels__contains=label)
        
        return queryset

    @action(detail=False, methods=['get'])
    def available(self, request):
        """获取可用的工作空间（Agent 在线且 workspace 空闲）"""
        label = request.query_params.get('label', '')
        
        queryset = self.queryset.filter(
            agent__status='ONLINE',
            status='IDLE'
        )
        
        if label:
            queryset = queryset.filter(labels__contains=label)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class AgentTaskViewSet(viewsets.ModelViewSet):
    """Agent 任务 API"""
    queryset = AgentTask.objects.all()
    serializer_class = AgentTaskSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # 按 Agent 过滤
        agent_id = self.request.query_params.get('agent')
        if agent_id:
            queryset = queryset.filter(agent_id=agent_id)
        
        # 按工作空间过滤
        workspace_id = self.request.query_params.get('workspace')
        if workspace_id:
            queryset = queryset.filter(workspace_id=workspace_id)
        
        # 按状态过滤
        task_status = self.request.query_params.get('status')
        if task_status:
            queryset = queryset.filter(status=task_status)
        
        # 按 Pipeline 过滤
        pipeline_id = self.request.query_params.get('pipeline')
        if pipeline_id:
            queryset = queryset.filter(pipeline_id=pipeline_id)
        
        return queryset

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """取消任务"""
        task = self.get_object()
        if task.status in ['PENDING', 'DISPATCHED']:
            task.status = 'CANCELLED'
            task.save(update_fields=['status'])
            return Response({'message': '任务已取消'})
        return Response(
            {'error': '只能取消待分发或已分发的任务'},
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=True, methods=['get'])
    def log(self, request, pk=None):
        """获取任务日志文件内容"""
        task = self.get_object()
        log_path = AGENT_LOG_DIR / f"task_{task.id}.log"
        
        content = ''
        if log_path.exists():
            content = log_path.read_text(encoding='utf-8', errors='replace')
        
        return Response({
            'task_id': task.id,
            'status': task.status,
            'content': content,
        })
