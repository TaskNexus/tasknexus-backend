from rest_framework import serializers
from .models import ClientAgent, AgentWorkspace, AgentTask


class AgentWorkspaceSerializer(serializers.ModelSerializer):
    """Agent 工作空间序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = AgentWorkspace
        fields = ['id', 'name', 'labels', 'status', 'status_display', 'pipeline_id']
        read_only_fields = ['id', 'status', 'pipeline_id']


class ClientAgentSerializer(serializers.ModelSerializer):
    """客户端 Agent 序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    workspaces = AgentWorkspaceSerializer(many=True, read_only=True)
    
    class Meta:
        model = ClientAgent
        fields = [
            'id', 'name', 'status', 'status_display',
            'last_heartbeat', 'hostname', 'platform', 'ip_address', 'agent_version',
            'description', 'environment', 'created_at', 'updated_at', 'created_by', 'created_by_name',
            'workspaces'
        ]
        read_only_fields = [
            'id', 'status', 'last_heartbeat', 'hostname', 'platform', 
            'ip_address', 'agent_version', 'created_at', 'updated_at'
        ]


class ClientAgentCreateSerializer(serializers.ModelSerializer):
    """创建 Agent 序列化器"""
    class Meta:
        model = ClientAgent
        fields = ['id', 'name', 'description']
        read_only_fields = ['id']


class ClientAgentUpdateSerializer(serializers.ModelSerializer):
    """更新 Agent 序列化器"""
    class Meta:
        model = ClientAgent
        fields = ['name', 'description', 'environment']


class AgentWorkspaceCreateSerializer(serializers.ModelSerializer):
    """创建工作空间序列化器"""
    class Meta:
        model = AgentWorkspace
        fields = ['id', 'agent', 'name', 'labels']
        read_only_fields = ['id']


class AgentWorkspaceUpdateSerializer(serializers.ModelSerializer):
    """更新工作空间序列化器"""
    class Meta:
        model = AgentWorkspace
        fields = ['name', 'labels']


class AgentTaskSerializer(serializers.ModelSerializer):
    """Agent 任务序列化器"""
    agent_name = serializers.CharField(source='agent.name', read_only=True)
    workspace_name = serializers.CharField(source='workspace.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = AgentTask
        fields = [
            'id', 'agent', 'agent_name', 'workspace', 'workspace_name',
            'pipeline_id', 'client_repo_url', 'client_repo_ref', 'command', 'timeout',
            'status', 'status_display', 'exit_code', 'stdout', 'stderr',
            'result', 'error_message',
            'created_at', 'dispatched_at', 'started_at', 'finished_at', 'last_heartbeat'
        ]
        read_only_fields = [
            'id', 'status', 'exit_code', 'stdout', 'stderr', 'result', 'error_message',
            'created_at', 'dispatched_at', 'started_at', 'finished_at', 'last_heartbeat'
        ]


class AgentTaskCreateSerializer(serializers.ModelSerializer):
    """创建任务序列化器"""
    class Meta:
        model = AgentTask
        fields = [
            'agent', 'workspace',
            'client_repo_url', 'client_repo_ref', 'command', 'timeout'
        ]
