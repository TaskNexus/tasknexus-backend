# Squashed migration - Generated for fresh database deployment

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ClientAgent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True, verbose_name='名称')),
                ('status', models.CharField(choices=[('ONLINE', '在线'), ('OFFLINE', '离线')], default='OFFLINE', max_length=20, verbose_name='状态')),
                ('last_heartbeat', models.DateTimeField(blank=True, null=True, verbose_name='最后心跳')),
                ('hostname', models.CharField(blank=True, max_length=255, verbose_name='主机名')),
                ('platform', models.CharField(blank=True, max_length=50, verbose_name='平台')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP 地址')),
                ('agent_version', models.CharField(blank=True, max_length=50, verbose_name='Agent 版本')),
                ('description', models.TextField(blank=True, verbose_name='描述')),
                ('environment', models.JSONField(blank=True, default=dict, verbose_name='环境变量配置')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='创建者')),
            ],
            options={
                'verbose_name': '客户端 Agent',
                'verbose_name_plural': '客户端 Agent',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='AgentWorkspace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='名称')),
                ('labels', models.JSONField(blank=True, default=list, verbose_name='标签')),
                ('status', models.CharField(choices=[('IDLE', '空闲'), ('RUNNING', '运行中')], default='IDLE', max_length=20, verbose_name='状态')),
                ('pipeline_id', models.CharField(blank=True, default='', max_length=64, verbose_name='Pipeline ID')),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspaces', to='client_agents.clientagent', verbose_name='Agent')),
            ],
            options={
                'verbose_name': 'Agent 工作空间',
                'verbose_name_plural': 'Agent 工作空间',
                'ordering': ['agent', 'name'],
                'unique_together': {('agent', 'name')},
            },
        ),
        migrations.CreateModel(
            name='AgentTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('client_repo_url', models.CharField(blank=True, max_length=500, verbose_name='脚本仓库地址')),
                ('client_repo_ref', models.CharField(default='main', max_length=255, verbose_name='仓库分支/Commit')),
                ('command', models.TextField(verbose_name='执行命令')),
                ('timeout', models.IntegerField(default=3600, verbose_name='超时时间（秒）')),
                ('pipeline_id', models.CharField(blank=True, default='', max_length=64, verbose_name='Pipeline ID')),
                ('status', models.CharField(choices=[('PENDING', '待分发'), ('DISPATCHED', '已分发'), ('RUNNING', '执行中'), ('COMPLETED', '已完成'), ('FAILED', '失败'), ('TIMEOUT', '超时'), ('CANCELLED', '已取消')], default='PENDING', max_length=20, verbose_name='状态')),
                ('exit_code', models.IntegerField(blank=True, null=True, verbose_name='退出码')),
                ('stdout', models.TextField(blank=True, verbose_name='标准输出')),
                ('stderr', models.TextField(blank=True, verbose_name='错误输出')),
                ('result', models.JSONField(blank=True, default=dict, verbose_name='执行结果')),
                ('error_message', models.TextField(blank=True, verbose_name='错误信息')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('dispatched_at', models.DateTimeField(blank=True, null=True, verbose_name='分发时间')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='开始时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='完成时间')),
                ('last_heartbeat', models.DateTimeField(blank=True, null=True, verbose_name='最后心跳')),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='client_agents.clientagent', verbose_name='Agent')),
                ('workspace', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to='client_agents.agentworkspace', verbose_name='工作空间')),
            ],
            options={
                'verbose_name': 'Agent 任务',
                'verbose_name_plural': 'Agent 任务',
                'ordering': ['-created_at'],
            },
        ),
    ]
