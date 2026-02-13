# -*- coding: utf-8 -*-
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.dispatch import receiver
from django.utils import timezone

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

    # 2. Cancel running agent tasks for this pipeline
    running_tasks = AgentTask.objects.filter(
        pipeline_id=pipeline_id,
        status__in=['PENDING', 'DISPATCHED', 'RUNNING']
    ).select_related('agent')

    if not running_tasks.exists():
        return

    channel_layer = get_channel_layer()
    for task in running_tasks:
        task.status = 'CANCELLED'
        task.error_message = f'Pipeline {event_type}'
        task.finished_at = timezone.now()
        task.save(update_fields=['status', 'error_message', 'finished_at'])

        # Send WebSocket cancel message to the agent
        try:
            async_to_sync(channel_layer.group_send)(
                f"agent_{task.agent_id}",
                {"type": "task_cancel", "task_id": task.id}
            )
            logger.info(f"[AgentSignal] Sent cancel for task {task.id} to agent {task.agent_id}")
        except Exception as e:
            logger.error(f"[AgentSignal] Failed to send cancel for task {task.id}: {e}")
