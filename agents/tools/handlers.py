import json
import logging
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from workflows.models import WorkflowDefinition
from .definitions import BUILTIN_SKILLS, get_builtin_skill_tools

logger = logging.getLogger('django')


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
    
    factory = APIRequestFactory()
    request = factory.post('/')
    request.user = user
    
    from tasks.serializers import CreateTaskSerializer
    data = {
        "workflow": workflow_id,
        "name": name,
        "context": variables or {}
    }
    
    serializer = CreateTaskSerializer(data=data, context={'request': request})
    if serializer.is_valid():
        task = serializer.save()
        
        from tasks.tasks import start_task_execution
        success, error = start_task_execution(task)
        
        if success:
             return f"Task '{task.name}' (ID: {task.id}) created and started successfully."
        else:
             return f"Task '{task.name}' (ID: {task.id}) created but failed to start: {error}"
             
    return f"Error creating task: {serializer.errors}"

def create_periodic_task(workflow_id, name, cron_expression, variables=None, enabled=True, project_id=None, user=None, **kwargs):
    if not user: return "Error: User context required."
    
    parts = cron_expression.split()
    if len(parts) != 5:
        return "Error: Invalid cron expression. Must have 5 parts (minute hour day month day_of_week)."
        
    minute, hour, day_of_month, month_of_year, day_of_week = parts
    
    factory = APIRequestFactory()
    request = factory.post('/')
    request.user = user
    
    from tasks.serializers import PeriodicTaskSerializer
    data = {
        "workflow": workflow_id,
        "name": name,
        "cron_expression": cron_expression,
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
    
    from tasks.serializers import ScheduledTaskSerializer
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


# === Skill Meta-Tool Handlers ===

def list_skills(mcp_bridge=None, project_id=None, **kwargs):
    """List all available skills (built-in + MCP)."""
    skills = []
    
    # Built-in skills
    for skill_id, skill in BUILTIN_SKILLS.items():
        tool_names = [t['function']['name'] for t in skill['tools']]
        skills.append({
            "id": skill_id,
            "name": skill["name"],
            "description": skill["description"],
            "source": "builtin",
            "tools_count": len(skill["tools"]),
            "tools": tool_names,
            "auto_activate": skill.get("auto_activate", False),
        })
    
    # MCP skills (via mcp_bridge)
    if mcp_bridge:
        try:
            # Find the server_id for the MCP server that has list_skills
            for server_id in mcp_bridge._server_configs:
                try:
                    result = mcp_bridge.call_tool(server_id, "list_skills", {})
                    # Parse MCP list_skills response and add source info
                    skills.append({
                        "source": "mcp",
                        "server_id": server_id,
                        "raw": result,
                    })
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Failed to list MCP skills: {e}")
    
    return skills


def activate_skill(skill_id, mcp_bridge=None, **kwargs):
    """Activate a skill (built-in or MCP)."""
    # Check built-in skills first
    tools = get_builtin_skill_tools(skill_id)
    if tools is not None:
        tool_names = [t['function']['name'] for t in tools]
        return {
            "activated": True,
            "skill_id": skill_id,
            "source": "builtin",
            "tools": tool_names,
            "message": f"内置技能包 '{BUILTIN_SKILLS[skill_id]['name']}' 已激活，"
                       f"包含 {len(tool_names)} 个工具: {', '.join(tool_names)}"
        }
    
    # Try MCP skills
    if mcp_bridge:
        for server_id in mcp_bridge._server_configs:
            try:
                result = mcp_bridge.call_tool(server_id, "activate_skill", {"skill_id": skill_id})
                activation = json.loads(result)
                if activation.get('activated'):
                    activation['source'] = 'mcp'
                    return activation
            except Exception:
                continue
    
    return {
        "activated": False,
        "error": f"技能包 '{skill_id}' 不存在。请先调用 list_skills 查看可用技能包。"
    }


# Registry of available functions
available_functions = {
    "get_current_time": get_current_time,
    "list_workflows": list_workflows,
    "get_workflow_info": get_workflow_info,
    "create_normal_task": create_normal_task,
    "create_periodic_task": create_periodic_task,
    "create_scheduled_task": create_scheduled_task,
    "list_skills": list_skills,
    "activate_skill": activate_skill,
}
