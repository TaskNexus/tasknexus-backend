#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TaskNexus 平台数据库清理脚本

用法:
    # 交互式运行
    python scripts/clean_database.py
    
    # 非交互式运行（Docker 环境推荐）
    python scripts/clean_database.py --yes                    # 清理所有业务数据
    python scripts/clean_database.py --yes --clean-users      # 同时清理账号
    python scripts/clean_database.py --yes --clean-projects   # 同时清理项目
    python scripts/clean_database.py --yes --clean-users --clean-projects  # 清理全部

选项说明:
    --yes, -y           跳过确认提示
    --clean-users       清理账号信息 (User, TelegramUser)，保留 admin
    --clean-projects    清理项目信息 (Project, ProjectMember)
"""

import os
import sys
import argparse

# 设置 Django 环境
if __name__ == "__main__":
    # 获取脚本所在目录的父目录（backend）
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, backend_dir)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    
    import django
    django.setup()

from django.db import connection, transaction
from django.contrib.auth import get_user_model


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='TaskNexus 平台数据库清理脚本')
    parser.add_argument('--yes', '-y', action='store_true', 
                        help='跳过确认提示，直接执行清理')
    parser.add_argument('--clean-users', action='store_true',
                        help='清理账号信息 (User, TelegramUser)，保留 admin')
    parser.add_argument('--clean-projects', action='store_true',
                        help='清理项目信息 (Project, ProjectMember)')
    return parser.parse_args()


def clean_chat_data():
    """清理聊天数据"""
    from chat.models import ChatSession, ChatMessage
    
    message_count = ChatMessage.objects.count()
    session_count = ChatSession.objects.count()
    
    ChatMessage.objects.all().delete()
    ChatSession.objects.all().delete()
    
    print(f"  ✓ 已删除 {message_count} 条聊天消息")
    print(f"  ✓ 已删除 {session_count} 个聊天会话")


def clean_task_data():
    """清理任务数据"""
    from tasks.models import (
        TaskInstance, PeriodicTask, ScheduledTask, 
        WebhookTask, NodeExecutionRecord
    )
    from django_celery_beat.models import PeriodicTask as CeleryPeriodicTask
    
    # 删除任务记录
    node_record_count = NodeExecutionRecord.objects.count()
    NodeExecutionRecord.objects.all().delete()
    print(f"  ✓ 已删除 {node_record_count} 条节点执行记录")
    
    task_count = TaskInstance.objects.count()
    TaskInstance.objects.all().delete()
    print(f"  ✓ 已删除 {task_count} 个任务实例")
    
    # 删除周期任务（先删除关联的 Celery 任务）
    periodic_count = PeriodicTask.objects.count()
    for pt in PeriodicTask.objects.all():
        if pt.celery_task:
            pt.celery_task.delete()
    PeriodicTask.objects.all().delete()
    print(f"  ✓ 已删除 {periodic_count} 个周期任务")
    
    # 删除定时任务
    scheduled_count = ScheduledTask.objects.count()
    for st in ScheduledTask.objects.all():
        if st.celery_task:
            st.celery_task.delete()
    ScheduledTask.objects.all().delete()
    print(f"  ✓ 已删除 {scheduled_count} 个定时任务")
    
    # 删除 Webhook 任务
    webhook_count = WebhookTask.objects.count()
    WebhookTask.objects.all().delete()
    print(f"  ✓ 已删除 {webhook_count} 个 Webhook 任务")
    
    # 清理剩余的 Celery 周期任务（与 TaskNexus 相关的）
    remaining_celery = CeleryPeriodicTask.objects.filter(
        task__in=[
            'tasks.tasks.execute_periodic_task',
            'tasks.tasks.execute_scheduled_task'
        ]
    )
    celery_count = remaining_celery.count()
    remaining_celery.delete()
    print(f"  ✓ 已删除 {celery_count} 个关联的 Celery 任务")


def clean_workflow_data():
    """清理工作流数据"""
    from workflows.models import WorkflowDefinition
    
    workflow_count = WorkflowDefinition.objects.count()
    WorkflowDefinition.objects.all().delete()
    print(f"  ✓ 已删除 {workflow_count} 个工作流定义")


def clean_client_agent_data():
    """清理客户端 Agent 数据"""
    from client_agents.models import ClientAgent, AgentWorkspace, AgentTask
    
    agent_task_count = AgentTask.objects.count()
    AgentTask.objects.all().delete()
    print(f"  ✓ 已删除 {agent_task_count} 个 Agent 任务")
    
    workspace_count = AgentWorkspace.objects.count()
    AgentWorkspace.objects.all().delete()
    print(f"  ✓ 已删除 {workspace_count} 个 Agent 工作空间")
    
    agent_count = ClientAgent.objects.count()
    ClientAgent.objects.all().delete()
    print(f"  ✓ 已删除 {agent_count} 个客户端 Agent")


def clean_bamboo_engine_data():
    """清理 Bamboo Engine 运行时数据"""
    from pipeline.eri.models import (
        Process, Node, State, Schedule, Data, 
        ExecutionData, CallbackData, ContextValue, 
        ContextOutputs, ExecutionHistory, LogEntry
    )
    
    # 按顺序清理各个表
    tables = [
        (LogEntry, "日志条目"),
        (ExecutionHistory, "执行历史"),
        (ContextOutputs, "上下文输出"),
        (ContextValue, "上下文变量"),
        (CallbackData, "回调数据"),
        (ExecutionData, "执行数据"),
        (Data, "节点数据"),
        (Schedule, "调度"),
        (State, "状态"),
        (Node, "节点"),
        (Process, "进程"),
    ]
    
    for model, name in tables:
        count = model.objects.count()
        model.objects.all().delete()
        print(f"  ✓ 已删除 {count} 条 {name}")


def clean_pipeline_data():
    """清理 Pipeline 层数据（模板、实例、快照等）"""
    from pipeline.models import (
        PipelineInstance, PipelineTemplate, Snapshot, TreeInfo,
        TemplateRelationship, TemplateCurrentVersion, TemplateVersion,
        TemplateScheme
    )
    from pipeline.log.models import LogEntry as PipelineLogEntry
    
    # 清理旧版日志
    try:
        log_count = PipelineLogEntry.objects.count()
        PipelineLogEntry.objects.all().delete()
        print(f"  ✓ 已删除 {log_count} 条 Pipeline 日志")
    except Exception:
        print("  ⚠ Pipeline 日志表不存在，跳过")
    
    # 清理模板方案
    scheme_count = TemplateScheme.objects.count()
    TemplateScheme.objects.all().delete()
    print(f"  ✓ 已删除 {scheme_count} 个模板方案")
    
    # 清理模板版本
    version_count = TemplateVersion.objects.count()
    TemplateVersion.objects.all().delete()
    print(f"  ✓ 已删除 {version_count} 条模板版本")
    
    # 清理模板当前版本
    current_version_count = TemplateCurrentVersion.objects.count()
    TemplateCurrentVersion.objects.all().delete()
    print(f"  ✓ 已删除 {current_version_count} 条模板当前版本")
    
    # 清理模板关系
    relationship_count = TemplateRelationship.objects.count()
    TemplateRelationship.objects.all().delete()
    print(f"  ✓ 已删除 {relationship_count} 条模板关系")
    
    # 清理 Pipeline 实例
    instance_count = PipelineInstance.objects.count()
    PipelineInstance.objects.all().delete()
    print(f"  ✓ 已删除 {instance_count} 个 Pipeline 实例")
    
    # 清理 Pipeline 模板
    template_count = PipelineTemplate.objects.count()
    PipelineTemplate.objects.all().delete()
    print(f"  ✓ 已删除 {template_count} 个 Pipeline 模板")
    
    # 清理流程树信息
    tree_count = TreeInfo.objects.count()
    TreeInfo.objects.all().delete()
    print(f"  ✓ 已删除 {tree_count} 条流程树信息")
    
    # 清理快照
    snapshot_count = Snapshot.objects.count()
    Snapshot.objects.all().delete()
    print(f"  ✓ 已删除 {snapshot_count} 个快照")


def clean_project_data():
    """清理项目数据（可选）"""
    from projects.models import Project, ProjectMember
    
    member_count = ProjectMember.objects.count()
    ProjectMember.objects.all().delete()
    print(f"  ✓ 已删除 {member_count} 个项目成员")
    
    project_count = Project.objects.count()
    Project.objects.all().delete()
    print(f"  ✓ 已删除 {project_count} 个项目")


def clean_user_data():
    """清理用户数据（可选）"""
    from users.models import TelegramUser
    
    User = get_user_model()
    
    telegram_count = TelegramUser.objects.count()
    TelegramUser.objects.all().delete()
    print(f"  ✓ 已删除 {telegram_count} 个 Telegram 绑定")
    
    # 保留 admin 用户
    user_count = User.objects.exclude(username='admin').count()
    User.objects.exclude(username='admin').delete()
    print(f"  ✓ 已删除 {user_count} 个用户（保留 admin）")


def reset_sequences():
    """重置数据库序列（自增ID）"""
    # 获取数据库引擎
    db_engine = connection.vendor
    
    if db_engine == 'sqlite':
        # SQLite 使用 sqlite_sequence 表
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name != 'django_migrations';")
        print("  ✓ 已重置 SQLite 序列")
    elif db_engine == 'postgresql':
        # PostgreSQL 重置序列
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 'SELECT SETVAL(' || quote_literal(sequence_name) || ', 1, false);'
                FROM information_schema.sequences
                WHERE sequence_schema = 'public';
            """)
            for row in cursor.fetchall():
                cursor.execute(row[0])
        print("  ✓ 已重置 PostgreSQL 序列")
    elif db_engine == 'mysql':
        # MySQL 需要针对每个表重置
        print("  ⚠ MySQL 序列将在下次插入时自动处理")
    else:
        print(f"  ⚠ 未知数据库引擎: {db_engine}，跳过序列重置")


def confirm_action(message: str) -> bool:
    """确认操作"""
    response = input(f"{message} (y/N): ").strip().lower()
    return response == 'y'


def main():
    """主函数"""
    args = parse_args()
    
    print("=" * 60)
    print("TaskNexus 平台数据库清理脚本")
    print("=" * 60)
    print()
    
    # 确定是否清理账号和项目
    if args.yes:
        # 非交互模式，使用命令行参数
        clean_users = args.clean_users
        clean_projects = args.clean_projects
        print(f"[非交互模式] clean_users={clean_users}, clean_projects={clean_projects}")
    else:
        # 交互模式，询问用户
        clean_users = confirm_action("是否清理账号信息? (User, TelegramUser)")
        clean_projects = confirm_action("是否清理项目信息? (Project, ProjectMember)")
    
    print()
    print("将要清理的数据:")
    print("  - 聊天数据 (ChatSession, ChatMessage)")
    print("  - 任务数据 (TaskInstance, PeriodicTask, ScheduledTask, WebhookTask)")
    print("  - 工作流数据 (WorkflowDefinition)")
    print("  - 客户端 Agent 数据 (ClientAgent, AgentWorkspace, AgentTask)")
    print("  - Bamboo Engine 运行时数据 (Process, Node, State, ...)")
    print("  - Pipeline 数据 (PipelineInstance, PipelineTemplate, Snapshot, ...)")
    if clean_projects:
        print("  - 项目数据 (Project, ProjectMember)")
    if clean_users:
        print("  - 账号数据 (User, TelegramUser) [保留 admin]")
    print()
    
    if not args.yes and not confirm_action("确认开始清理?"):
        print("操作已取消")
        return
    
    print()
    print("-" * 60)
    
    try:
        with transaction.atomic():
            # 1. 清理聊天数据
            print("\n[1/8] 清理聊天数据...")
            clean_chat_data()
            
            # 2. 清理任务数据
            print("\n[2/8] 清理任务数据...")
            clean_task_data()
            
            # 3. 清理工作流数据
            print("\n[3/8] 清理工作流数据...")
            clean_workflow_data()
            
            # 4. 清理客户端 Agent 数据
            print("\n[4/8] 清理客户端 Agent 数据...")
            clean_client_agent_data()
            
            # 5. 清理 Bamboo Engine 数据
            print("\n[5/8] 清理 Bamboo Engine 运行时数据...")
            clean_bamboo_engine_data()
            
            # 6. 清理 Pipeline 数据
            print("\n[6/8] 清理 Pipeline 数据...")
            clean_pipeline_data()
            
            # 7. 可选：清理项目数据
            if clean_projects:
                print("\n[7/8] 清理项目数据...")
                clean_project_data()
            else:
                print("\n[7/8] 跳过项目数据清理")
            
            # 8. 可选：清理用户数据
            if clean_users:
                print("\n[8/8] 清理账号数据...")
                clean_user_data()
            else:
                print("\n[8/8] 跳过账号数据清理")
            
            # 重置序列
            print("\n[额外] 重置数据库序列...")
            reset_sequences()
            
        print()
        print("-" * 60)
        print("✅ 数据库清理完成!")
        print("=" * 60)
        
    except Exception as e:
        print()
        print("-" * 60)
        print(f"❌ 清理过程中发生错误: {e}")
        print("事务已回滚，数据未被修改")
        print("=" * 60)
        raise


if __name__ == "__main__":
    main()
