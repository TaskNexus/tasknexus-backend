from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from workflows.models import WorkflowDefinition
from projects.models import Project
from tasks.serializers import CreateTaskSerializer, PeriodicTaskSerializer, ScheduledTaskSerializer


def get_current_time(**kwargs):
    """Get the current server time."""
    now = timezone.localtime(timezone.now())
    return {
        "current_time": now.isoformat(),
        "weekday": now.strftime("%A"),
        "is_weekend": now.weekday() >= 5
    }

def list_workflows(project_id=None, **kwargs):
    queryset = WorkflowDefinition.objects.all()
    if project_id:
        queryset = queryset.filter(project_id=project_id)
    return queryset

def get_workflow_info(workflow_id, project_id=None, **kwargs):
    try:
        workflow = WorkflowDefinition.objects.get(id=workflow_id)
        if project_id and workflow.project_id != int(project_id):
             return "Error: Workflow does not belong to the current project."
             
        # Extract variables
        variables = []
        
        # 1. Project Global Params (if enabled)
        if workflow.project and workflow.project.extra_config:
            project_params = workflow.project.extra_config.get('global_params', [])
            enabled_keys = (workflow.graph_data or {}).get('global_params_enabled', [])
            
            for param in project_params:
                if param.get('key') in enabled_keys:
                    variables.append({
                        "key": param.get('key'),
                        "type": "Global (Project)",
                        "description": param.get('description', ''),
                        "default_value": param.get('value')
                    })
                    
        # 2. Workflow Local Params
        workflow_params = (workflow.graph_data or {}).get('workflow_params', [])
        for param in workflow_params:
            variables.append({
                "key": param.get('key'),
                "type": "Local (Workflow)",
                "description": param.get('description', ''),
                "default_value": param.get('value')
            })
            
        return {
            "name": workflow.name,
            "description": workflow.description,
            "required_variables": variables
        }
    except WorkflowDefinition.DoesNotExist:
        return "Error: Workflow not found."

def create_normal_task(workflow_id, name, variables=None, project_id=None, user=None, **kwargs):
    if not user: return "Error: User context required."
    
    # Mock request for serializer context
    factory = APIRequestFactory()
    request = factory.post('/')
    request.user = user
    
    data = {
        "workflow": workflow_id,
        "name": name,
        "context": variables or {}
    }
    
    serializer = CreateTaskSerializer(data=data, context={'request': request})
    if serializer.is_valid():
        task = serializer.save()
        
        # Start execution
        from tasks.tasks import start_task_execution
        success, error = start_task_execution(task)
        
        if success:
             return f"Task '{task.name}' (ID: {task.id}) created and started successfully."
        else:
             return f"Task '{task.name}' (ID: {task.id}) created but failed to start: {error}"
             
    return f"Error creating task: {serializer.errors}"

def create_periodic_task(workflow_id, name, cron_expression, variables=None, enabled=True, project_id=None, user=None, **kwargs):
    if not user: return "Error: User context required."
    
    # Parse cron
    parts = cron_expression.split()
    if len(parts) != 5:
        return "Error: Invalid cron expression. Must have 5 parts (minute hour day month day_of_week)."
        
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    
    factory = APIRequestFactory()
    request = factory.post('/')
    request.user = user
    
    data = {
        "workflow": workflow_id,
        "name": name,
        "cron_expression": cron_expression, # Not directly used by serializer logic we wrote earlier, but we need to map it
        "minute": minute,
        "hour": hour,
        "day_of_month": day_of_month,
        "month_of_year": month_of_year,
        "day_of_week": day_of_week,
        "enabled": enabled,
        "context": variables or {}
    }
    
    serializer = PeriodicTaskSerializer(data=data, context={'request': request})
    if serializer.is_valid():
        task = serializer.save()
        return f"Periodic Task '{task.name}' (ID: {task.id}) created successfully."
    return f"Error creating periodic task: {serializer.errors}"

def create_scheduled_task(workflow_id, name, execution_time, variables=None, project_id=None, user=None, **kwargs):
    if not user: return "Error: User context required."
    
    factory = APIRequestFactory()
    request = factory.post('/')
    request.user = user
    
    data = {
        "workflow": workflow_id,
        "name": name,
        "execution_time": execution_time,
        "context": variables or {}
    }
    
    serializer = ScheduledTaskSerializer(data=data, context={'request': request})
    if serializer.is_valid():
        task = serializer.save()
        return f"Scheduled Task '{task.name}' (ID: {task.id}) created for {task.execution_time}."
    return f"Error creating scheduled task: {serializer.errors}"


# Registry of available functions for easy lookup
available_functions = {
    "get_current_time": get_current_time,
    "list_workflows": list_workflows,
    "get_workflow_info": get_workflow_info,
    "create_normal_task": create_normal_task,
    "create_periodic_task": create_periodic_task,
    "create_scheduled_task": create_scheduled_task,
}
