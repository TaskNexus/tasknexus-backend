from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger('django')

@shared_task
def execute_periodic_task(periodic_task_id):
    """
    Execute a periodic task instance.
    This task is triggered by Celery Beat.
    """
    from tasks.models import PeriodicTask, TaskInstance
    
    logger.info(f"Starting execution of periodic task: {periodic_task_id}")
    
    try:
        periodic_task = PeriodicTask.objects.get(id=periodic_task_id)
        if not periodic_task.enabled:
            logger.info(f"Periodic task {periodic_task.name} is disabled, skipping")
            return
        
        # 1. Create Task Instance (uses workflow directly, no snapshot)
        instance = TaskInstance.objects.create(
            name=f"{periodic_task.name} - {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')}",
            workflow=periodic_task.workflow,
            context=periodic_task.context or {},
            execution_data={'periodic_task_id': periodic_task.id},
            created_by=periodic_task.creator,
            status='CREATED',
            notify_enabled=periodic_task.notify_enabled,
            notify_user_ids=periodic_task.notify_user_ids or [],
            feishu_notify_enabled=periodic_task.feishu_notify_enabled,
            feishu_notify_open_ids=periodic_task.feishu_notify_open_ids or [],
        )
        
        # 2. Execute using unified logic
        success, error = start_task_execution(instance)
        
        if not success:
            raise RuntimeError(f"Failed to run pipeline: {error}")
        
        # 3. Update Periodic Task Stats
        periodic_task.last_run_at = timezone.now()
        periodic_task.total_run_count += 1
        periodic_task.save()
        
        logger.info(f"Successfully started periodic task instance: {instance.id}")
        
    except Exception as e:
        logger.exception(f"Failed to execute periodic task {periodic_task_id}")

@shared_task
def execute_scheduled_task(scheduled_task_id):
    """
    Execute a one-off scheduled task instance.
    """
    from tasks.models import ScheduledTask, TaskInstance
    
    logger.info(f"Starting execution of scheduled task: {scheduled_task_id}")
    
    try:
        scheduled_task = ScheduledTask.objects.get(id=scheduled_task_id)
        if scheduled_task.status != 'PENDING':
            logger.info(f"Scheduled task {scheduled_task.name} is not PENDING ({scheduled_task.status}), skipping")
            return
        
        # 1. Create Task Instance (uses workflow directly, no snapshot)
        instance = TaskInstance.objects.create(
            name=f"{scheduled_task.name} (Scheduled)",
            workflow=scheduled_task.workflow,
            context=scheduled_task.context or {},
            execution_data={'scheduled_task_id': scheduled_task.id},
            created_by=scheduled_task.creator,
            status='CREATED',
            notify_enabled=scheduled_task.notify_enabled,
            notify_user_ids=scheduled_task.notify_user_ids or [],
            feishu_notify_enabled=scheduled_task.feishu_notify_enabled,
            feishu_notify_open_ids=scheduled_task.feishu_notify_open_ids or [],
        )
        
        # 2. Execute using unified logic
        success, error = start_task_execution(instance)
        
        if not success:
            raise RuntimeError(f"Failed to run pipeline: {error}")
        
        # 3. Update Scheduled Task Status
        scheduled_task.status = 'EXECUTED'
        scheduled_task.save()
        
        logger.info(f"Successfully started scheduled task instance: {instance.id}")
        
    except Exception as e:
        logger.exception(f"Failed to execute scheduled task {scheduled_task_id}")
        # Try to update status if possible
        try:
            scheduled_task = ScheduledTask.objects.get(id=scheduled_task_id)
            scheduled_task.status = 'FAILED'
            scheduled_task.save()
        except:
            pass

@shared_task
def execute_webhook_task(webhook_task_id, payload=None):
    """
    Execute a webhook-triggered task instance.
    """
    from tasks.models import WebhookTask, TaskInstance
    
    logger.info(f"Starting execution of webhook task: {webhook_task_id}")
    
    try:
        webhook_task = WebhookTask.objects.get(id=webhook_task_id)
        if not webhook_task.enabled:
            logger.info(f"Webhook task {webhook_task.name} is disabled, skipping")
            return
        
        # Merge context
        context = {**(webhook_task.context or {}), **(payload or {})}
        
        # 1. Create TaskInstance
        instance = TaskInstance.objects.create(
            name=f"{webhook_task.name} - {timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')}",
            workflow=webhook_task.workflow,
            context=context,
            execution_data={'webhook_task_id': webhook_task.id, 'payload': payload},
            created_by=webhook_task.creator,
            status='CREATED',
            notify_enabled=webhook_task.notify_enabled,
            notify_user_ids=webhook_task.notify_user_ids or [],
            feishu_notify_enabled=webhook_task.feishu_notify_enabled,
            feishu_notify_open_ids=webhook_task.feishu_notify_open_ids or [],
        )
        
        # 2. Execute using unified logic
        success, error = start_task_execution(instance)
        
        if not success:
            raise RuntimeError(f"Failed to run pipeline: {error}")
        
        # 3. Update statistics
        webhook_task.last_run_at = timezone.now()
        webhook_task.total_run_count += 1
        webhook_task.save()
        
        logger.info(f"Successfully started webhook task instance: {instance.id}")
        return instance.id
        
    except Exception as e:
        logger.exception(f"Failed to execute webhook task {webhook_task_id}")
        raise

def start_task_execution(task):
    """
    Encapsulate the logic to start a task instance's pipeline execution.
    Should be called after TaskInstance is created.
    """
    from django.utils import timezone
    from bamboo_engine import api as bamboo_api
    from pipeline.eri.runtime import BambooDjangoRuntime
    from tasks.utils import expand_pipeline_tree, regenerate_pipeline_ids_full
    
    try:
        # 1. Prepare pipeline data
        workflow = task.workflow
        if not workflow:
            raise ValueError("Task has no workflow associated")
            
        pipeline_tree = workflow.pipeline_tree
        if not pipeline_tree:
            raise ValueError("Workflow has no valid pipeline_tree")

        # 1.5 Expand SubProcess nodes
        pipeline_tree = expand_pipeline_tree(pipeline_tree)

        # 2. Regenerate IDs for new execution instance
        pipeline_tree, id_map, subprocess_maps = regenerate_pipeline_ids_full(pipeline_tree)
        
        # Save ID map for status mapping
        if not task.execution_data:
            task.execution_data = {}
        task.execution_data['node_id_map'] = id_map
        task.execution_data['subprocess_maps'] = subprocess_maps
        task.started_at = timezone.now()

        # 3. Apply context overrides (if any) - params are already in pipeline_tree from frontend
        apply_task_inputs(pipeline_tree, task, workflow)

        # 4. Run pipeline with bamboo-engine API
        # project_id is passed here for components to access via parent_data.get_one_of_inputs('project_id')
        root_pipeline_data = {
            'project_id': workflow.project_id,
            'pipeline_id': pipeline_tree['id'],
            'task_created_by': task.created_by.id,
            'task_started_at': task.started_at.isoformat() if task.started_at else None,
        }

        # Merge project extra_config global_params into root_pipeline_data
        if workflow.project and workflow.project.extra_config:
            for param in workflow.project.extra_config.get('global_params', []):
                root_pipeline_data[param['key']] = param['value']

        runtime = BambooDjangoRuntime()
        bamboo_api.run_pipeline(
            runtime=runtime,
            pipeline=pipeline_tree,
            root_pipeline_data=root_pipeline_data,
            cycle_tolerate=True  # Enable loop support with ExclusiveGateway
        )
        
        # 5. Update task instance
        task.pipeline_id = pipeline_tree['id']
        task.status = 'RUNNING'
        task.save()
        
        return True, None

    except Exception as e:
        task.status = 'FAILED'
        task.execution_data = {**(task.execution_data or {}), 'error': str(e)}
        task.save()
        import logging
        logger = logging.getLogger('django')
        logger.exception(f"Failed to start task {task.id}")
        return False, str(e)

def apply_context_inputs(pipeline_tree, context=None):
    if not context:
        return
    
    # Ensure data.inputs exists
    if 'data' not in pipeline_tree:
        pipeline_tree['data'] = {}
    if 'inputs' not in pipeline_tree['data']:
        pipeline_tree['data']['inputs'] = {}
    
    inputs = pipeline_tree['data']['inputs']
    
    overridden = 0
    for key, value in context.items():
        formatted_key = f'${{{key}}}'
        inputs[formatted_key] = {'type': 'splice', 'value': value}
        overridden += 1
    
    if overridden > 0:
        logger.info(f"Applied {overridden} context overrides to pipeline_tree")

def apply_task_inputs(pipeline_tree, task, workflow=None):
    if 'data' not in pipeline_tree:
        pipeline_tree['data'] = {}
    if 'inputs' not in pipeline_tree['data']:
        pipeline_tree['data']['inputs'] = {}

    # Apply root_pipeline_data variables (project_id, pipeline_id, etc.)
    # Note: task_started_at is passed as a datetime object so Mako splice
    # expressions like ${task_started_at.strftime("%Y%m%d")} work correctly.
    root_vars = {
        'project_id': workflow.project_id if workflow else None,
        'pipeline_id': pipeline_tree.get('id', ''),
        'task_created_by': task.created_by.id if task.created_by else None,
        'task_started_at': task.started_at,
    }
    apply_context_inputs(pipeline_tree, root_vars)

    # Apply project global_params as pipeline global variables
    if workflow and workflow.project and workflow.project.extra_config:
        global_params = {}
        for param in workflow.project.extra_config.get('global_params', []):
            global_params[param['key']] = param['value']
        apply_context_inputs(pipeline_tree, global_params)

    apply_context_inputs(pipeline_tree, task.context)
