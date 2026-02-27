"""
Tool Definitions

Tools are organized into Skills (技能包) for on-demand loading.
Only auto_activate skills and meta-tools are included in initial context.
Other skills are loaded when the AI calls activate_skill.
"""


# === Meta Tools (always loaded) ===

_list_skills_tool = {
    "type": "function",
    "function": {
        "name": "list_skills",
        "description": "列出所有可用的技能包(Skills)及其描述摘要。当你需要使用某种能力但不确定是否已加载时，先调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}

_activate_skill_tool = {
    "type": "function",
    "function": {
        "name": "activate_skill",
        "description": "激活一个技能包，使其包含的工具可被调用。激活后这些工具将自动注入到当前对话中。",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "技能包 ID"
                }
            },
            "required": ["skill_id"]
        }
    }
}

META_TOOLS = [_list_skills_tool, _activate_skill_tool]


# === Built-in Skills ===

BUILTIN_SKILLS = {
    "utilities": {
        "name": "基础工具",
        "description": "获取当前时间等基础工具",
        "auto_activate": True,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "Get the current server time. Useful for scheduling tasks relative to now.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
        ]
    },
    "task_management": {
        "name": "任务管理",
        "description": "创建和管理工作流任务（查询工作流、创建普通/定时/计划任务）",
        "auto_activate": False,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "list_workflows",
                    "description": "List all workflows. Use this to find workflow IDs.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_workflow_info",
                    "description": "Get details of a workflow, including its description and required global variables (constants). Call this before creating a task to know what variables to ask the user for.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_id": {
                                "type": "integer",
                                "description": "The ID of the workflow to inspect"
                            }
                        },
                        "required": ["workflow_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_normal_task",
                    "description": "Create and start a new normal (one-off) task instance from a workflow.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_id": {
                                "type": "integer",
                                "description": "The ID of the workflow to execute"
                            },
                            "name": {
                                "type": "string",
                                "description": "Name of the task instance"
                            },
                            "variables": {
                                "type": "object",
                                "description": "Key-value pairs for workflow global variables/constants"
                            }
                        },
                        "required": ["workflow_id", "name"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_periodic_task",
                    "description": "Create a periodic task (recurring) from a workflow using a cron schedule.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_id": {
                                "type": "integer",
                                "description": "The ID of the workflow"
                            },
                            "name": {
                                "type": "string",
                                "description": "Name of the periodic task"
                            },
                            "cron_expression": {
                                "type": "string",
                                "description": "Cron expression (e.g., '0 3 * * *' for 3 AM daily). Standard 5-part cron format: minute hour day_of_month month_of_year day_of_week."
                            },
                            "enabled": {
                                "type": "boolean",
                                "description": "Whether the task is enabled upon creation",
                                "default": True
                            },
                            "variables": {
                                "type": "object",
                                "description": "Key-value pairs for workflow global variables/constants"
                            }
                        },
                        "required": ["workflow_id", "name", "cron_expression"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "create_scheduled_task",
                    "description": "Create a scheduled task (one-off future execution) from a workflow.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "workflow_id": {
                                "type": "integer",
                                "description": "The ID of the workflow"
                            },
                            "name": {
                                "type": "string",
                                "description": "Name of the scheduled task"
                            },
                            "execution_time": {
                                "type": "string",
                                "description": "ISO 8601 formatted datetime string for when to run the task (e.g., '2023-12-25T10:00:00Z')"
                            },
                            "variables": {
                                "type": "object",
                                "description": "Key-value pairs for workflow global variables/constants"
                            }
                        },
                        "required": ["workflow_id", "name", "execution_time"]
                    }
                }
            }
        ]
    }
}


def get_tools(mcp_tools: list = None):
    """
    Get initial tools: meta-tools + auto_activate skills + MCP meta-tools.
    
    Args:
        mcp_tools: Optional list of MCP meta-tool definitions (e.g. read_skill).
    
    Returns:
        List of tool definitions for the initial AI context.
    """
    tools = list(META_TOOLS)
    
    # Add auto_activate built-in skills
    for skill in BUILTIN_SKILLS.values():
        if skill.get('auto_activate', False):
            tools.extend(skill['tools'])
    
    if mcp_tools:
        tools.extend(mcp_tools)
    
    return tools


def get_builtin_skill_tools(skill_id: str):
    """Get tool definitions for a specific built-in skill."""
    skill = BUILTIN_SKILLS.get(skill_id)
    if not skill:
        return None
    return skill['tools']
