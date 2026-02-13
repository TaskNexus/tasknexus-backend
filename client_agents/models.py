from django.db import models
from users.models import User


class ClientAgent(models.Model):
    """客户端 Agent 注册信息"""
    STATUS_CHOICES = [
        ('ONLINE', '在线'),
        ('OFFLINE', '离线'),
    ]

    name = models.CharField(max_length=255, unique=True, verbose_name='名称')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OFFLINE', verbose_name='状态')
    last_heartbeat = models.DateTimeField(null=True, blank=True, verbose_name='最后心跳')

    # 系统信息（由 Agent 上报）
    hostname = models.CharField(max_length=255, blank=True, verbose_name='主机名')
    platform = models.CharField(max_length=50, blank=True, verbose_name='平台')  # windows/linux/darwin
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP 地址')
    agent_version = models.CharField(max_length=50, blank=True, verbose_name='Agent 版本')

    # 元数据
    description = models.TextField(blank=True, verbose_name='描述')
    environment = models.JSONField(default=dict, blank=True, verbose_name='环境变量配置')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name='创建者')

    class Meta:
        verbose_name = '客户端 Agent'
        verbose_name_plural = '客户端 Agent'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"


class AgentWorkspace(models.Model):
    """Agent 工作空间"""
    STATUS_CHOICES = [
        ('IDLE', '空闲'),
        ('RUNNING', '运行中'),
    ]

    agent = models.ForeignKey(
        ClientAgent,
        on_delete=models.CASCADE,
        related_name='workspaces',
        verbose_name='Agent'
    )
    name = models.CharField(max_length=100, verbose_name='名称')
    labels = models.JSONField(default=list, blank=True, verbose_name='标签')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='IDLE', verbose_name='状态')
    pipeline_id = models.CharField(max_length=64, blank=True, default='', verbose_name='Pipeline ID')

    class Meta:
        verbose_name = 'Agent 工作空间'
        verbose_name_plural = 'Agent 工作空间'
        unique_together = [['agent', 'name']]
        ordering = ['agent', 'name']

    def __str__(self):
        return f"{self.agent.name}/{self.name}"


class AgentTask(models.Model):
    """分发给 Agent 的任务"""
    STATUS_CHOICES = [
        ('PENDING', '待分发'),
        ('DISPATCHED', '已分发'),
        ('RUNNING', '执行中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
        ('TIMEOUT', '超时'),
        ('CANCELLED', '已取消'),
    ]

    agent = models.ForeignKey(
        ClientAgent, 
        on_delete=models.CASCADE, 
        related_name='tasks',
        verbose_name='Agent'
    )
    workspace = models.ForeignKey(
        AgentWorkspace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
        verbose_name='工作空间'
    )

    # 任务脚本仓库配置
    client_repo_url = models.CharField(max_length=500, blank=True, verbose_name='脚本仓库地址')
    client_repo_ref = models.CharField(max_length=255, default='main', verbose_name='仓库分支/Commit')

    # 执行配置
    command = models.TextField(verbose_name='执行命令')
    timeout = models.IntegerField(default=3600, verbose_name='超时时间（秒）')

    # Pipeline 关联
    pipeline_id = models.CharField(max_length=64, blank=True, default='', verbose_name='Pipeline ID')

    # 状态
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name='状态')
    
    # 执行结果
    exit_code = models.IntegerField(null=True, blank=True, verbose_name='退出码')
    stdout = models.TextField(blank=True, verbose_name='标准输出')
    stderr = models.TextField(blank=True, verbose_name='错误输出')
    result = models.JSONField(default=dict, blank=True, verbose_name='执行结果')
    error_message = models.TextField(blank=True, verbose_name='错误信息')

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    dispatched_at = models.DateTimeField(null=True, blank=True, verbose_name='分发时间')
    started_at = models.DateTimeField(null=True, blank=True, verbose_name='开始时间')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')
    last_heartbeat = models.DateTimeField(null=True, blank=True, verbose_name='最后心跳')

    class Meta:
        verbose_name = 'Agent 任务'
        verbose_name_plural = 'Agent 任务'
        ordering = ['-created_at']

    def __str__(self):
        return f"Task {self.id} - {self.agent.name} ({self.get_status_display()})"
