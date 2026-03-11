# -*- coding: utf-8 -*-
import logging

from django.dispatch import receiver
from django.utils import timezone

from client_agents.dispatch_stream import publish_cancel_event
from pipeline.eri.signals import pipeline_event

logger = logging.getLogger('django')


class PipelineEventType:
    POST_REVOKE_PIPELINE = 'post_revoke_pipeline'
    NODE_EXECUTE_FAIL = 'node_execute_fail'
    NODE_EXECUTE_EXCEPTION = 'node_execute_exception'
    NODE_SCHEDULE_FAIL = 'node_schedule_fail'
    NODE_SCHEDULE_EXCEPTION = 'node_schedule_exception'


@receiver(pipeline_event)
def handle_pipeline_event_for_agent(sender, event, **kwargs):
    """Pipeline 撤销或失败时，释放 workspace 并取消运行中的任务"""
    from client_agents.models import AgentTask, AgentWorkspace

    event_type = event.event_type
    event_data = event.data

    # Determine pipeline_id based on event type
    if event_type == PipelineEventType.POST_REVOKE_PIPELINE:
        pipeline_id = event_data.get('pipeline_id', '')
    elif event_type in (
        PipelineEventType.NODE_EXECUTE_FAIL,
        PipelineEventType.NODE_EXECUTE_EXCEPTION,
        PipelineEventType.NODE_SCHEDULE_FAIL,
        PipelineEventType.NODE_SCHEDULE_EXCEPTION,
    ):
        pipeline_id = event_data.get('root_pipeline_id', '')
    else:
        return

    if not pipeline_id:
        return

    logger.info(f"[AgentSignal] Handling {event_type} for pipeline {pipeline_id}")

    # 1. Release workspaces occupied by this pipeline
    updated_ws = AgentWorkspace.objects.filter(
        pipeline_id=pipeline_id,
        status='RUNNING'
    ).update(status='IDLE', pipeline_id='')
    if updated_ws:
        logger.info(f"[AgentSignal] Released {updated_ws} workspace(s) for pipeline {pipeline_id}")

    # 2. 将 bamboo 中属于此 pipeline 的 RUNNING 节点状态设为 REVOKED
    #    bamboo 的 revoke_pipeline 只设置 pipeline 级别状态，不设置节点状态
    #    使用 runtime.set_state() 确保状态转换验证和信号发送
    if event_type == PipelineEventType.POST_REVOKE_PIPELINE:
        try:
            from pipeline.eri.models import State as BambooState
            from pipeline.eri.runtime import BambooDjangoRuntime

            runtime = BambooDjangoRuntime()
            running_nodes = BambooState.objects.filter(
                root_id=pipeline_id,
                name='RUNNING'
            ).values_list('node_id', flat=True)
            for node_id in running_nodes:
                try:
                    runtime.set_state(
                        node_id=node_id,
                        to_state='REVOKED',
                        refresh_version=True,
                        set_archive_time=True,
                    )
                    logger.info(f"[AgentSignal] Set node {node_id} to REVOKED for pipeline {pipeline_id}")
                except Exception as e:
                    logger.error(f"[AgentSignal] Failed to set node {node_id} to REVOKED: {e}")
        except Exception as e:
            logger.error(f"[AgentSignal] Failed to update bamboo node states: {e}")

    # 2. Cancel running agent tasks for this pipeline
    running_tasks = AgentTask.objects.filter(
        pipeline_id=pipeline_id,
        status__in=['PENDING', 'DISPATCHED', 'RUNNING']
    ).select_related('agent')

    if not running_tasks.exists():
        return

    for task in running_tasks:
        previous_status = task.status
        task.status = 'CANCELLED'
        task.error_message = f'Pipeline {event_type}'
        task.finished_at = timezone.now()
        task.save(update_fields=['status', 'error_message', 'finished_at'])

        # Pending tasks may never have reached the agent process.
        if previous_status == 'PENDING':
            continue

        try:
            publish_cancel_event(
                task_id=task.id,
                agent_id=task.agent_id,
                reason=f'Pipeline {event_type}',
            )
            logger.info(f"[AgentSignal] Enqueued cancel for task {task.id} to agent {task.agent_id}")
        except Exception as e:
            logger.error(f"[AgentSignal] Failed to enqueue cancel for task {task.id}: {e}")
