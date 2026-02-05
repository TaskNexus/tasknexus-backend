from django.contrib import admin
from .models import ClientAgent, AgentTask, AgentWorkspace


@admin.register(ClientAgent)
class ClientAgentAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'platform', 'hostname', 'last_heartbeat', 'created_at']
    list_filter = ['status', 'platform']
    search_fields = ['name', 'hostname', 'ip_address']
    readonly_fields = ['last_heartbeat', 'hostname', 'platform', 'ip_address', 
                       'agent_version', 'created_at', 'updated_at']
    
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'created_by')
        }),
        ('状态', {
            'fields': ('status', 'last_heartbeat')
        }),
        ('系统信息', {
            'fields': ('hostname', 'platform', 'ip_address', 'agent_version'),
            'classes': ('collapse',)
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AgentWorkspace)
class AgentWorkspaceAdmin(admin.ModelAdmin):
    list_display = ['name', 'agent', 'status', 'get_labels']
    list_filter = ['status', 'agent']
    search_fields = ['name', 'agent__name']
    
    def get_labels(self, obj):
        return ', '.join(obj.labels) if obj.labels else '-'
    get_labels.short_description = '标签'


@admin.register(AgentTask)
class AgentTaskAdmin(admin.ModelAdmin):
    list_display = ['id', 'agent', 'workspace', 'status', 'command_short', 'created_at', 'finished_at']
    list_filter = ['status', 'agent', 'workspace']
    search_fields = ['command', 'node_id', 'pipeline_id']
    readonly_fields = ['created_at', 'dispatched_at', 'started_at', 'finished_at',
                       'exit_code', 'stdout', 'stderr', 'result']

    def command_short(self, obj):
        return obj.command[:50] + '...' if len(obj.command) > 50 else obj.command
    command_short.short_description = '命令'
