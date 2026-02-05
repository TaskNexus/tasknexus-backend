# -*- coding: utf-8 -*-
from django.dispatch import receiver
from django.utils import timezone

from pipeline.eri.signals import pipeline_event

from tasks.models import TaskInstance

import logging

logger = logging.getLogger('django')

class PipelineEventType:
    PIPELINE_FINISH = 'pipeline_finish'
    POST_REVOKE_PIPELINE = 'post_revoke_pipeline'
    NODE_EXECUTE_FAIL = 'node_execute_fail'
    NODE_EXECUTE_EXCEPTION = 'node_execute_exception'
    NODE_SCHEDULE_FAIL = 'node_schedule_fail'
    NODE_SCHEDULE_EXCEPTION = 'node_schedule_exception'


def _update_task_status(pipeline_id: str, status: str, log_prefix: str = ""):
    try:
        task = TaskInstance.objects.get(pipeline_id=pipeline_id)
        task.status = status
        task.finished_at = timezone.now()
        task.save(update_fields=['status', 'finished_at'])
        logger.info(f"{log_prefix}Updated TaskInstance {task.id} status to {status}")
    except TaskInstance.DoesNotExist:
        logger.warning(f"{log_prefix}TaskInstance not found for pipeline_id: {pipeline_id}")
    except Exception as e:
        logger.exception(f"{log_prefix}Error updating task status for pipeline {pipeline_id}: {e}")


@receiver(pipeline_event)
def handle_pipeline_event(sender, event, **kwargs):
    event_type = event.event_type
    event_data = event.data
    
    logger.debug(f"pipeline_event received: type={event_type}, data={event_data}")
    
    if event_type == PipelineEventType.PIPELINE_FINISH:
        pipeline_id = event_data.get('pipeline_id')
        if pipeline_id:
            logger.info(f"Pipeline {pipeline_id} finished successfully")
            _update_task_status(pipeline_id, 'FINISHED', "[pipeline_finish] ")
    
    elif event_type == PipelineEventType.POST_REVOKE_PIPELINE:
        pipeline_id = event_data.get('pipeline_id')
        if pipeline_id:
            logger.info(f"Pipeline {pipeline_id} was revoked")
            _update_task_status(pipeline_id, 'REVOKED', "[post_revoke_pipeline] ")
    
    elif event_type in (
        PipelineEventType.NODE_EXECUTE_FAIL,
        PipelineEventType.NODE_EXECUTE_EXCEPTION,
        PipelineEventType.NODE_SCHEDULE_FAIL,
        PipelineEventType.NODE_SCHEDULE_EXCEPTION,
    ):
        node_id = event_data.get('node_id')
        root_pipeline_id = event_data.get('root_pipeline_id')
        if root_pipeline_id:
            logger.info(f"Node {node_id} failed in pipeline {root_pipeline_id}, event: {event_type}")
            _update_task_status(root_pipeline_id, 'FAILED', f"[{event_type}] ")


from pipeline.eri.signals import post_set_state
from pipeline.eri.models import State
from tasks.models import NodeExecutionRecord

@receiver(post_set_state)
def handle_node_state_change(sender, node_id, to_state, version, root_id, parent_id, loop, **kwargs):
    """
    Handle node state change to record execution duration
    """
    if to_state != 'FINISHED':
        return

    try:
        # Get State to calculate duration
        state = State.objects.filter(node_id=node_id).first()
        if not state:
            return

        finish_time = timezone.now()
        # Prefer started_time, fallback to created_time
        start_time = state.started_time or state.created_time
        
        if start_time:
            duration = (finish_time - start_time).total_seconds()
        else:
            duration = 0

        # Find the TaskInstance
        task = TaskInstance.objects.filter(pipeline_id=root_id).first()
        if not task:
            return

        # Resolve original node_id (template ID) from runtime node_id
        # The map is structured as { original_id: runtime_id }
        id_map = (task.execution_data or {}).get('node_id_map', {})
        subprocess_maps = (task.execution_data or {}).get('subprocess_maps', {})
        
        original_node_id = None
        
        # Check main map
        # Optimization: Create reverse lookup if needed, but linear scan is okay for typical workflow size
        for k, v in id_map.items():
            if v == node_id:
                original_node_id = k
                break
        
        # Check subprocess maps if not found
        if not original_node_id:
            for sub_map in subprocess_maps.values():
                for k, v in sub_map.items():
                    if v == node_id:
                        original_node_id = k
                        break
                if original_node_id:
                    break

        if original_node_id:
            NodeExecutionRecord.objects.create(
                workflow=task.workflow,
                node_id=original_node_id,
                duration=max(0, int(duration)),
                pipeline_id=root_id,
                finished_at=finish_time
            )
            logger.info(f"Recorded execution for node {original_node_id}: {int(duration)}s")

    except Exception as e:
        logger.exception(f"Error recording node execution: {e}")

# Re-implementing correctly after checking State model

