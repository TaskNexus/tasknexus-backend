import logging
import json
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import TaskInstance
from .serializers import TaskInstanceSerializer, CreateTaskSerializer
from .filters import TaskInstanceFilter
from bamboo_engine import api as bamboo_api
from pipeline.eri.runtime import BambooDjangoRuntime
from pipeline.core.data.library import VariableLibrary
from config.permissions import check_project_permission
from config.pagination import StandardResultsSetPagination

logger = logging.getLogger('django')

class TaskViewSet(viewsets.ModelViewSet):
    queryset = TaskInstance.objects.all()
    serializer_class = TaskInstanceSerializer
    filterset_class = TaskInstanceFilter
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateTaskSerializer
        return TaskInstanceSerializer

    def create(self, request, *args, **kwargs):
        """
        Create and start a new task instance
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Permission check: Reporter+ can create tasks
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(request.user, workflow.project, 'task.create')

        task = serializer.save()

        try:
            # New centralized execution logic
            from tasks.tasks import start_task_execution
            success, error = start_task_execution(task)
            
            if not success:
                # Error already saved in start_task_execution
                raise RuntimeError(error)

            # Return full details
            read_serializer = TaskInstanceSerializer(task)
            return Response(read_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            # logger.exception("Failed to start task") # Already logged in start_task_execution
            return Response(
                {'error': str(e), 'detail': 'Failed to start workflow execution'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        task = self.get_object()
        # Permission: Maintainer+ for all, others for own
        if task.workflow and task.workflow.project:
            check_project_permission(request.user, task.workflow.project, 'task.operate', task)
        if not task.pipeline_id:
            return Response({'error': 'Task has no pipeline_id'}, status=status.HTTP_400_BAD_REQUEST)
        
        runtime = BambooDjangoRuntime()
        result = bamboo_api.pause_pipeline(runtime=runtime, pipeline_id=task.pipeline_id)
        if result.result:
            task.status = 'PAUSED'
            task.save()
            return Response({'status': 'paused'})
        return Response({'error': result.message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        task = self.get_object()
        # Permission: Maintainer+ for all, others for own
        if task.workflow and task.workflow.project:
            check_project_permission(request.user, task.workflow.project, 'task.operate', task)
        if not task.pipeline_id:
            return Response({'error': 'Task has no pipeline_id'}, status=status.HTTP_400_BAD_REQUEST)
            
        runtime = BambooDjangoRuntime()
        result = bamboo_api.resume_pipeline(runtime=runtime, pipeline_id=task.pipeline_id)
        if result.result:
            task.status = 'RUNNING'
            task.save()
            return Response({'status': 'resumed'})
        return Response({'error': result.message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        task = self.get_object()
        # Permission: Maintainer+ for all, others for own
        if task.workflow and task.workflow.project:
            check_project_permission(request.user, task.workflow.project, 'task.operate', task)
        if not task.pipeline_id:
            return Response({'error': 'Task has no pipeline_id'}, status=status.HTTP_400_BAD_REQUEST)
            
        runtime = BambooDjangoRuntime()
        result = bamboo_api.revoke_pipeline(runtime=runtime, pipeline_id=task.pipeline_id)
        if result.result:
            task.status = 'REVOKED'
            task.finished_at = timezone.now()
            task.save()
            return Response({'status': 'revoked'})
        return Response({'error': result.message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



    @action(detail=True, methods=['get'])
    def node_states(self, request, pk=None):
        """Get states of all nodes in the pipeline"""
        task = self.get_object()
        if not task.pipeline_id:
            return Response({})
            
        # Get status from bamboo-engine ERI State model
        try:
             from pipeline.eri.models import State
             from tasks.models import NodeExecutionRecord
             from django.db.models import Avg
             
             # Support querying specific subprocess
             subprocess_node_id = request.query_params.get('subprocess_node_id')
             target_pipeline_id = task.pipeline_id # Default to root

             id_map = (task.execution_data or {}).get('node_id_map', {})
             subprocess_maps = (task.execution_data or {}).get('subprocess_maps', {})

             if subprocess_node_id:
                 # Map frontend (original) ID to backend runtime ID
                 backend_subprocess_id = id_map.get(subprocess_node_id, subprocess_node_id)
                 
                 # Check if we have a specific map for this instance
                 if backend_subprocess_id in subprocess_maps:
                     # This is a SubProcess in our map
                     # The KEYS in this sub-map are the Original IDs from the SubProcess Template
                     # The VALUES are the Runtime IDs
                     id_map = subprocess_maps[backend_subprocess_id]
                     target_pipeline_id = backend_subprocess_id
                 else:
                     logger.warning(f"Subprocess map not found for {backend_subprocess_id}")
             
             # Query states using ERI State model
             # For root pipeline, use root_id; for subprocess, use parent_id
             if subprocess_node_id:
                 states = State.objects.filter(parent_id=target_pipeline_id)
             else:
                 states = State.objects.filter(root_id=target_pipeline_id)
             
             # Map: Runtime node_id -> State info (including skip and error_ignored)
             runtime_state_map = {
                 s.node_id: {
                     'state': s.name,
                     'skip': s.skip,
                     'error_ignored': s.error_ignored,
                     'started_time': s.started_time,  # Use started_time for loop progress updates
                     'loop': s.loop,
                     'inner_loop': s.inner_loop
                 }
                 for s in states
             }
             
             final_state_map = {}
             cache_duration = {}

             # Iterate over the map to find state for each frontend node
             for old_id, new_id in id_map.items():
                 if new_id in runtime_state_map:
                     state_info = runtime_state_map[new_id]
                     actual_state = state_info['state']
                     
                     # Use started_time - updates each loop iteration for accurate progress
                     start_time = state_info['started_time']
                     expected_duration = 10 # default 10s

                     if actual_state == 'RUNNING':
                         if old_id not in cache_duration:
                             avg_time = NodeExecutionRecord.objects.filter(
                                 workflow=task.workflow, 
                                 node_id=old_id
                             ).aggregate(Avg('duration'))['duration__avg']
                             cache_duration[old_id] = int(avg_time) if avg_time is not None else 10
                         expected_duration = cache_duration[old_id]

                     # Determine display state
                     display_state = actual_state
                     flow_state = actual_state
                     
                     if actual_state == 'FINISHED' and (state_info['skip'] or state_info['error_ignored']):
                        display_state = 'FAILED'
                        flow_state = 'FINISHED'
                        
                     final_state_map[old_id] = {
                         'state': display_state,
                         'flow_state': flow_state,
                         'start_time': start_time,
                         'expected_duration': expected_duration,
                         'loop': state_info['loop'],
                         'inner_loop': state_info['inner_loop']
                     }
            
             # If querying root, include root pipeline status
             if not subprocess_node_id:
                 root_state = State.objects.filter(node_id=task.pipeline_id).first()
                 if root_state:
                     final_state_map[task.pipeline_id] = {
                         'state': root_state.name,
                         'flow_state': root_state.name
                     }
                 
             return Response(final_state_map)
        except Exception as e:
            logger.exception("Failed to get node states")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def node_history(self, request, pk=None):
        """Get execution history for a specific node"""
        task = self.get_object()
        node_id = request.query_params.get('node_id')
        
        if not node_id:
             return Response({'error': 'Missing node_id'}, status=status.HTTP_400_BAD_REQUEST)
             
        try:
            from tasks.models import NodeExecutionRecord
            
            # Use original node_id from query params.
            # We assume the frontend passes the template node ID.
            
            records = NodeExecutionRecord.objects.filter(
                workflow=task.workflow,
                node_id=node_id
            ).order_by('-finished_at')[:5]
            
            data = [
                {
                    'finished_at': r.finished_at,
                    'duration': r.duration,
                    'pipeline_id': r.pipeline_id
                }
                for r in records
            ]
            
            return Response(data)
        except Exception as e:
             logger.exception("Failed to get node history")
             return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'])
    def node_detail(self, request, pk=None):
        """Get details (inputs/outputs) of a specific node"""
        task = self.get_object()
        node_id = request.query_params.get('node_id')
        
        if not task.pipeline_id or not node_id:
            return Response({'error': 'Missing pipeline_id or node_id'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Handle ID mapping with support for subprocess
            subprocess_node_id = request.query_params.get('subprocess_node_id')
            
            id_map = (task.execution_data or {}).get('node_id_map', {})
            subprocess_maps = (task.execution_data or {}).get('subprocess_maps', {})
            
            if subprocess_node_id:
                # Map frontend (original) subprocess ID to backend runtime ID
                backend_subprocess_id = id_map.get(subprocess_node_id, subprocess_node_id)
                
                # Check if we have a specific map for this subprocess
                if backend_subprocess_id in subprocess_maps:
                    # Use the subprocess ID map
                    id_map = subprocess_maps[backend_subprocess_id]
                else:
                    logger.warning(f"Subprocess map not found for {backend_subprocess_id}")

            backend_id = id_map.get(node_id, node_id)
            
            logger.info(f"node_detail: node_id={node_id}, subprocess_node_id={subprocess_node_id}, backend_id={backend_id}")

            # Use bamboo_engine.api to get execution data
            runtime = BambooDjangoRuntime()
            
            inputs = {}
            outputs = {}
            
            # Try to get execution data first (this contains rendered inputs and outputs)
            result = bamboo_api.get_execution_data(runtime=runtime, node_id=backend_id)
            
            if result.result and result.data:
                inputs = result.data.get('inputs', {})
                outputs = result.data.get('outputs', {})
            else:
                # Fallback to get_data (raw inputs, not rendered)
                # This helps for subprocess nodes that only have inputs stored
                logger.info(f"Execution data not found for {backend_id}, trying get_data")
                data_result = bamboo_api.get_data(runtime=runtime, node_id=backend_id)
                
                if data_result.result and data_result.data:
                    # Extract values from raw data format
                    raw_inputs = data_result.data.get('inputs', {})
                    inputs = {k: v.get('value', v) if isinstance(v, dict) else v for k, v in raw_inputs.items()}
                    outputs = data_result.data.get('outputs', {})
                else:
                    logger.warning(f"Data not found for {backend_id}: {data_result.message}")
                 
            return Response({
                'id': node_id,
                'backend_id': backend_id,
                'inputs': inputs,
                'outputs': outputs
            })
            
        except Exception as e:
            logger.exception(f"Failed to get node detail for {node_id}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def bulk_delete(self, request):
        """Batch delete tasks"""
        ids = request.data.get('ids', [])
        if not ids:
            return Response({'error': 'No ids provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            tasks = TaskInstance.objects.filter(id__in=ids)
            for task in tasks:
                # Permission: Maintainer+ for all, others for own
                if task.workflow and task.workflow.project:
                    check_project_permission(
                        request.user, task.workflow.project, 'task.delete', task
                    )
            tasks.delete()
            return Response({'status': 'success', 'message': f'Deleted {len(ids)} tasks'})
        except Exception as e:
            logger.exception("Failed to bulk delete tasks")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from .models import PeriodicTask
from .serializers import PeriodicTaskSerializer

class PeriodicTaskViewSet(viewsets.ModelViewSet):
    queryset = PeriodicTask.objects.all()
    serializer_class = PeriodicTaskSerializer
    pagination_class = StandardResultsSetPagination
    
    def perform_create(self, serializer):
        # Reporter+ can create
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(self.request.user, workflow.project, 'task.create')
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.workflow and instance.workflow.project:
            check_project_permission(
                self.request.user, instance.workflow.project, 'task.operate', instance
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.workflow and instance.workflow.project:
            check_project_permission(
                self.request.user, instance.workflow.project, 'task.delete', instance
            )
        instance.delete()

    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        task = self.get_object()
        # Permission: Maintainer+ for all, others for own
        if task.workflow and task.workflow.project:
            check_project_permission(request.user, task.workflow.project, 'task.operate', task)
        task.enabled = not task.enabled
        task.save()
        
        # Update Celery Task
        if task.celery_task:
            task.celery_task.enabled = task.enabled
            task.celery_task.save()
            
        return Response({'status': 'success', 'enabled': task.enabled})
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get execution history for this periodic task"""
        # We stored periodic_task_id in execution_data
        
        # Note: Filtering JSONField can be database dependent and slow. 
        # Ideally we should have a ForeignKey or an indexed field if volume is high.
        # But for MVP, JSON filter is okay.
        
        # Django 4.2+ supports lookups in JSONField
        history = TaskInstance.objects.filter(execution_data__periodic_task_id=int(pk)).order_by('-created_at')[:50]
        
        page = self.paginate_queryset(history)
        if page is not None:
            serializer = TaskInstanceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = TaskInstanceSerializer(history, many=True)
        return Response(serializer.data)


from .models import ScheduledTask
from .serializers import ScheduledTaskSerializer

class ScheduledTaskViewSet(viewsets.ModelViewSet):
    queryset = ScheduledTask.objects.all()
    serializer_class = ScheduledTaskSerializer
    pagination_class = StandardResultsSetPagination

    def perform_create(self, serializer):
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(self.request.user, workflow.project, 'task.create')
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.workflow and instance.workflow.project:
            check_project_permission(
                self.request.user, instance.workflow.project, 'task.operate', instance
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.workflow and instance.workflow.project:
            check_project_permission(
                self.request.user, instance.workflow.project, 'task.delete', instance
            )
        instance.delete()
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get execution record for this scheduled task"""
        # Should be only one, but theoretically can fail and retry? 
        # Usually one-off.
        
        history = TaskInstance.objects.filter(execution_data__scheduled_task_id=int(pk)).order_by('-created_at')
        
        page = self.paginate_queryset(history)
        if page is not None:
            serializer = TaskInstanceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = TaskInstanceSerializer(history, many=True)
        return Response(serializer.data)


from .models import WebhookTask
from .serializers import WebhookTaskSerializer

class WebhookTaskViewSet(viewsets.ModelViewSet):
    queryset = WebhookTask.objects.all()
    serializer_class = WebhookTaskSerializer
    pagination_class = StandardResultsSetPagination

    def perform_create(self, serializer):
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(self.request.user, workflow.project, 'task.create')
        serializer.save()

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.workflow and instance.workflow.project:
            check_project_permission(
                self.request.user, instance.workflow.project, 'task.operate', instance
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.workflow and instance.workflow.project:
            check_project_permission(
                self.request.user, instance.workflow.project, 'task.delete', instance
            )
        instance.delete()

    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        """Enable/Disable Webhook"""
        task = self.get_object()
        if task.workflow and task.workflow.project:
            check_project_permission(request.user, task.workflow.project, 'task.operate', task)
        task.enabled = not task.enabled
        task.save()
        return Response({'status': 'success', 'enabled': task.enabled})
    
    @action(detail=True, methods=['post'])
    def regenerate_token(self, request, pk=None):
        """Regenerate Token"""
        task = self.get_object()
        if task.workflow and task.workflow.project:
            check_project_permission(request.user, task.workflow.project, 'task.operate', task)
        task.regenerate_token()
        serializer = self.get_serializer(task)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get execution history"""
        history = TaskInstance.objects.filter(
            execution_data__webhook_task_id=int(pk)
        ).order_by('-created_at')[:50]
        
        page = self.paginate_queryset(history)
        if page is not None:
            serializer = TaskInstanceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = TaskInstanceSerializer(history, many=True)
        return Response(serializer.data)


from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny

@api_view(['POST', 'GET'])  # GET supported for testing
@authentication_classes([])  # No authentication required
@permission_classes([AllowAny])
def webhook_trigger(request, token):
    """
    Webhook trigger endpoint
    POST /api/tasks/webhook/{token}/trigger/
    
    Optional Header: X-Webhook-Secret
    Optional Body: JSON data will be merged into context
    """
    try:
        webhook_task = WebhookTask.objects.get(token=token)
    except WebhookTask.DoesNotExist:
        return Response({'error': 'Webhook not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if not webhook_task.enabled:
        return Response({'error': 'Webhook is disabled'}, status=status.HTTP_403_FORBIDDEN)
    
    # Verify Secret (if configured)
    if webhook_task.secret:
        provided_secret = request.headers.get('X-Webhook-Secret', '')
        if provided_secret != webhook_task.secret:
            return Response({'error': 'Invalid secret'}, status=status.HTTP_401_UNAUTHORIZED)
    
    # Merge request data into context
    payload = {}
    if request.data and isinstance(request.data, dict):
        payload = request.data
    
    # Async execution
    from tasks.tasks import execute_webhook_task
    result = execute_webhook_task.delay(webhook_task.id, payload)
    
    return Response({
        'status': 'accepted',
        'webhook_task_id': webhook_task.id,
        'celery_task_id': result.id
    }, status=status.HTTP_202_ACCEPTED)
