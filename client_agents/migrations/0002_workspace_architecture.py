# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('client_agents', '0001_initial'),
    ]

    operations = [
        # 1. 移除 ClientAgent 的 token 和 labels 字段
        migrations.RemoveField(
            model_name='clientagent',
            name='token',
        ),
        migrations.RemoveField(
            model_name='clientagent',
            name='labels',
        ),
        # 2. 修改 ClientAgent 的 status choices（移除 BUSY）
        migrations.AlterField(
            model_name='clientagent',
            name='status',
            field=models.CharField(
                choices=[('ONLINE', '在线'), ('OFFLINE', '离线')],
                default='OFFLINE',
                max_length=20,
                verbose_name='状态'
            ),
        ),
        # 3. 创建 AgentWorkspace 模型
        migrations.CreateModel(
            name='AgentWorkspace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='名称')),
                ('labels', models.JSONField(blank=True, default=list, verbose_name='标签')),
                ('status', models.CharField(
                    choices=[('IDLE', '空闲'), ('RUNNING', '运行中')],
                    default='IDLE',
                    max_length=20,
                    verbose_name='状态'
                )),
                ('agent', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='workspaces',
                    to='client_agents.clientagent',
                    verbose_name='Agent'
                )),
                ('current_task', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='client_agents.agenttask',
                    verbose_name='当前任务'
                )),
            ],
            options={
                'verbose_name': 'Agent 工作空间',
                'verbose_name_plural': 'Agent 工作空间',
                'ordering': ['agent', 'name'],
                'unique_together': {('agent', 'name')},
            },
        ),
        # 4. 给 AgentTask 添加 workspace 外键
        migrations.AddField(
            model_name='agenttask',
            name='workspace',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='tasks',
                to='client_agents.agentworkspace',
                verbose_name='工作空间'
            ),
        ),
    ]
