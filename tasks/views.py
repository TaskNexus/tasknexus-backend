import logging
import json
from urllib.parse import quote, urlparse
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone
import requests as http_requests
from .models import TaskInstance
from .serializers import TaskInstanceSerializer, CreateTaskSerializer
from .filters import TaskInstanceFilter
from bamboo_engine import api as bamboo_api
from pipeline.eri.runtime import BambooDjangoRuntime
from pipeline.core.data.library import VariableLibrary
from config.permissions import check_project_permission
from config.pagination import StandardResultsSetPagination
from workflows.visibility import assert_user_can_view_workflow, get_visible_workflow_queryset

logger = logging.getLogger('django')

class TaskViewSet(viewsets.ModelViewSet):
    queryset = TaskInstance.objects.all()
    serializer_class = TaskInstanceSerializer
    filterset_class = TaskInstanceFilter
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        visible_workflow_ids = get_visible_workflow_queryset(
            self.request.user
        ).values_list('id', flat=True)
        return super().get_queryset().filter(workflow_id__in=visible_workflow_ids).distinct()

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
        if workflow:
            assert_user_can_view_workflow(request.user, workflow)

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
            tasks = self.get_queryset().filter(id__in=ids)
            for task in tasks:
                # Permission: Maintainer+ for all, others for own
                if task.workflow and task.workflow.project:
                    check_project_permission(
                        request.user, task.workflow.project, 'task.delete', task
                    )
            deleted_count = tasks.count()
            tasks.delete()
            return Response({'status': 'success', 'message': f'Deleted {deleted_count} tasks'})
        except Exception as e:
            logger.exception("Failed to bulk delete tasks")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from .models import PeriodicTask
from .serializers import PeriodicTaskSerializer

class PeriodicTaskViewSet(viewsets.ModelViewSet):
    queryset = PeriodicTask.objects.all()
    serializer_class = PeriodicTaskSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        visible_workflow_ids = get_visible_workflow_queryset(
            self.request.user
        ).values_list('id', flat=True)
        return super().get_queryset().filter(workflow_id__in=visible_workflow_ids).distinct()

    def perform_create(self, serializer):
        # Reporter+ can create
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(self.request.user, workflow.project, 'task.create')
        if workflow:
            assert_user_can_view_workflow(self.request.user, workflow)
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
        periodic_task = self.get_object()
        # We stored periodic_task_id in execution_data
        
        # Note: Filtering JSONField can be database dependent and slow. 
        # Ideally we should have a ForeignKey or an indexed field if volume is high.
        # But for MVP, JSON filter is okay.
        
        # Django 4.2+ supports lookups in JSONField
        history = TaskInstance.objects.filter(
            workflow=periodic_task.workflow,
            execution_data__periodic_task_id=int(pk),
        ).order_by('-created_at')[:50]
        
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

    def get_queryset(self):
        visible_workflow_ids = get_visible_workflow_queryset(
            self.request.user
        ).values_list('id', flat=True)
        return super().get_queryset().filter(workflow_id__in=visible_workflow_ids).distinct()

    def perform_create(self, serializer):
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(self.request.user, workflow.project, 'task.create')
        if workflow:
            assert_user_can_view_workflow(self.request.user, workflow)
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
        scheduled_task = self.get_object()
        # Should be only one, but theoretically can fail and retry? 
        # Usually one-off.
        
        history = TaskInstance.objects.filter(
            workflow=scheduled_task.workflow,
            execution_data__scheduled_task_id=int(pk),
        ).order_by('-created_at')
        
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

    def get_queryset(self):
        visible_workflow_ids = get_visible_workflow_queryset(
            self.request.user
        ).values_list('id', flat=True)
        return super().get_queryset().filter(workflow_id__in=visible_workflow_ids).distinct()

    def perform_create(self, serializer):
        workflow = serializer.validated_data.get('workflow')
        if workflow and workflow.project:
            check_project_permission(self.request.user, workflow.project, 'task.create')
        if workflow:
            assert_user_can_view_workflow(self.request.user, workflow)
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
        webhook_task = self.get_object()
        history = TaskInstance.objects.filter(
            workflow=webhook_task.workflow,
            execution_data__webhook_task_id=int(pk)
        ).order_by('-created_at')[:50]
        
        page = self.paginate_queryset(history)
        if page is not None:
            serializer = TaskInstanceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = TaskInstanceSerializer(history, many=True)
        return Response(serializer.data)

def _normalize_repo_url(repo_url: str) -> str:
    url = (repo_url or '').strip()
    if not url:
        return ''
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    return url.rstrip('/')


def _detect_provider(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    host = (parsed.netloc or '').lower()
    if 'github.com' in host:
        return 'github'
    return 'gitlab'


def _extract_repo_path(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    path = (parsed.path or '').strip('/')
    if path.endswith('.git'):
        path = path[:-4]
    return path


def _fetch_github_branches(repo_url: str, token: str):
    repo_path = _extract_repo_path(repo_url)
    segments = [seg for seg in repo_path.split('/') if seg]
    if len(segments) < 2:
        raise ValueError('GitHub 仓库地址格式错误，应为 github.com/<owner>/<repo>')

    owner, repo = segments[0], segments[1]
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'token {token}',
    }

    default_branch = ''
    repo_resp = http_requests.get(f'https://api.github.com/repos/{owner}/{repo}', headers=headers, timeout=15)
    if repo_resp.status_code == 200:
        default_branch = str((repo_resp.json() or {}).get('default_branch') or '')
    elif repo_resp.status_code in (401, 403):
        raise PermissionError('认证失败或无权限访问仓库')
    elif repo_resp.status_code == 404:
        raise FileNotFoundError('仓库不存在或不可访问')
    else:
        raise RuntimeError('无法访问 GitHub 仓库信息')

    branches: list[dict] = []
    page = 1
    while page <= 10:
        resp = http_requests.get(
            f'https://api.github.com/repos/{owner}/{repo}/branches',
            headers=headers,
            params={'per_page': 100, 'page': page},
            timeout=15,
        )
        if resp.status_code in (401, 403):
            raise PermissionError('认证失败或无权限访问仓库')
        if resp.status_code == 404:
            raise FileNotFoundError('仓库不存在或不可访问')
        if resp.status_code != 200:
            raise RuntimeError('无法获取 GitHub 分支列表')

        items = resp.json() or []
        if not isinstance(items, list):
            raise RuntimeError('GitHub 分支响应格式错误')

        for item in items:
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            branches.append({
                'name': name,
                'is_default': name == default_branch,
            })

        if len(items) < 100:
            break
        page += 1

    branch_map = {}
    for branch in branches:
        current = branch_map.get(branch['name'])
        if not current or branch.get('is_default'):
            branch_map[branch['name']] = branch

    return sorted(branch_map.values(), key=lambda x: (not x.get('is_default', False), x.get('name', '')))


def _fetch_gitlab_branches(repo_url: str, token: str):
    parsed = urlparse(repo_url)
    repo_path = _extract_repo_path(repo_url)
    segments = [seg for seg in repo_path.split('/') if seg]
    if len(segments) < 2:
        raise ValueError('GitLab 仓库地址格式错误，应为 <host>/<group>/<repo>')

    if not parsed.scheme or not parsed.netloc:
        raise ValueError('GitLab 仓库地址格式错误')

    api_base = f'{parsed.scheme}://{parsed.netloc}'
    encoded_project = quote(repo_path, safe='')
    headers = {
        'PRIVATE-TOKEN': token,
    }

    default_branch = ''
    repo_resp = http_requests.get(f'{api_base}/api/v4/projects/{encoded_project}', headers=headers, timeout=15)
    if repo_resp.status_code == 200:
        default_branch = str((repo_resp.json() or {}).get('default_branch') or '')
    elif repo_resp.status_code in (401, 403):
        raise PermissionError('认证失败或无权限访问仓库')
    elif repo_resp.status_code == 404:
        raise FileNotFoundError('仓库不存在或不可访问')
    else:
        raise RuntimeError('无法访问 GitLab 仓库信息')

    branches: list[dict] = []
    page = 1
    while page <= 10:
        resp = http_requests.get(
            f'{api_base}/api/v4/projects/{encoded_project}/repository/branches',
            headers=headers,
            params={'per_page': 100, 'page': page},
            timeout=15,
        )
        if resp.status_code in (401, 403):
            raise PermissionError('认证失败或无权限访问仓库')
        if resp.status_code == 404:
            raise FileNotFoundError('仓库不存在或不可访问')
        if resp.status_code != 200:
            raise RuntimeError('无法获取 GitLab 分支列表')

        items = resp.json() or []
        if not isinstance(items, list):
            raise RuntimeError('GitLab 分支响应格式错误')

        for item in items:
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            branches.append({
                'name': name,
                'is_default': bool(item.get('default')) or name == default_branch,
            })

        if len(items) < 100:
            break
        page += 1

    branch_map = {}
    for branch in branches:
        current = branch_map.get(branch['name'])
        if not current or branch.get('is_default'):
            branch_map[branch['name']] = branch

    return sorted(branch_map.values(), key=lambda x: (not x.get('is_default', False), x.get('name', '')))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def git_branches(request):
    repo_url = _normalize_repo_url(str(request.data.get('repo_url') or ''))
    token = str(request.data.get('token') or '').strip()

    if not repo_url:
        return Response({'error': 'repo_url 不能为空'}, status=status.HTTP_400_BAD_REQUEST)
    if not token:
        return Response({'error': 'token 不能为空'}, status=status.HTTP_400_BAD_REQUEST)

    provider = _detect_provider(repo_url)
    try:
        if provider == 'github':
            branches = _fetch_github_branches(repo_url, token)
        else:
            branches = _fetch_gitlab_branches(repo_url, token)
        return Response({
            'provider': provider,
            'branches': branches,
        })
    except ValueError as exc:
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except PermissionError:
        return Response({'error': '认证失败或无权限访问仓库'}, status=status.HTTP_400_BAD_REQUEST)
    except FileNotFoundError:
        return Response({'error': '仓库不存在或不可访问'}, status=status.HTTP_400_BAD_REQUEST)
    except http_requests.RequestException:
        return Response({'error': '请求代码仓库失败，请稍后重试'}, status=status.HTTP_502_BAD_GATEWAY)
    except RuntimeError as exc:
        logger.warning('Failed to fetch git branches: %s', exc)
        return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

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
