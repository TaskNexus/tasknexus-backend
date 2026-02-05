def get_tools():
    """
    Get list of available tools for the AI agent.
    
    Returns:
        List of tool definitions in OpenAI/MCP format.
    """
    tools = [
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
    return tools
