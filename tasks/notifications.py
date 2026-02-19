# -*- coding: utf-8 -*-
"""
Task Notification Module

Sends task execution result notifications via channel plugins (e.g., Feishu).
Supports custom templates with {{variable}} syntax.
"""

import re
import logging
import threading

from django.contrib.auth import get_user_model

logger = logging.getLogger('django')

User = get_user_model()

# Status display mapping
STATUS_EMOJI = {
    'FINISHED': '✅',
    'FAILED': '❌',
    'REVOKED': '⏹',
}

STATUS_LABEL = {
    'FINISHED': '执行完成',
    'FAILED': '执行失败',
    'REVOKED': '已撤销',
}

DEFAULT_TEMPLATE = (
    "{{status_emoji}} **任务{{status_label}}**\n\n"
    "**任务名称**: {{task_name}}\n"
    "**工作流**: {{workflow_name}}\n"
    "**状态**: {{status_label}}"
)


def render_template(template: str, variables: dict) -> str:
    """
    Render a template string by replacing {{key}} or {{key.subkey}} 
    with values from the variables dict.
    
    Supports nested path lookup like {{params.branch_name}}.
    Unknown variables are replaced with empty string.
    """
    def replacer(match):
        path = match.group(1).strip()
        value = variables
        for part in path.split('.'):
            if isinstance(value, dict):
                value = value.get(part, '')
            else:
                return ''
            if value == '':
                break
        return str(value)
    
    return re.sub(r'\{\{(.+?)\}\}', replacer, template)


def send_task_notification(task):
    """
    Send notification to configured users when a task finishes.
    
    Runs in a background thread to avoid blocking the signal handler.
    """
    if not task.notify_enabled:
        return
    
    if not task.notify_user_ids:
        return
    
    # Read template from workflow
    notify_template = ''
    if task.workflow:
        notify_template = getattr(task.workflow, 'notify_template', '') or ''
    
    # Run in background thread
    thread = threading.Thread(
        target=_do_send_notification,
        args=(
            task.id,
            task.name,
            task.status,
            task.notify_user_ids,
            task.workflow.name if task.workflow else 'Unknown',
            task.context or {},
            notify_template,
        ),
        daemon=True
    )
    thread.start()


def _do_send_notification(task_id, task_name, status, notify_user_ids, workflow_name, context, notify_template):
    """
    Actually send notifications. Runs in a background thread.
    Uses lark_oapi directly to send messages via open_id.
    """
    try:
        # Build variables for template rendering
        emoji = STATUS_EMOJI.get(status, '📋')
        label = STATUS_LABEL.get(status, status)
        
        variables = {
            'task_name': task_name,
            'status': status,
            'status_emoji': emoji,
            'status_label': label,
            'workflow_name': workflow_name,
            'params': context,  # task.context = runtime params
        }
        
        # Use custom template or default
        template = notify_template.strip() if notify_template else DEFAULT_TEMPLATE
        message = render_template(template, variables)
        
        # Get users with feishu_openid
        users = User.objects.filter(
            id__in=notify_user_ids,
            feishu_openid__isnull=False
        ).exclude(feishu_openid='')
        
        if not users.exists():
            logger.info(f"No users with feishu_openid found for task {task_id} notification")
            return
        
        # Use OAuth app credentials (same app that generated the user's open_id)
        # Falls back to channel bot credentials if OAuth ones aren't available
        import os
        app_id = os.environ.get('FEISHU_APP_ID')
        app_secret = os.environ.get('FEISHU_APP_SECRET')
        
        if not app_id or not app_secret:
            logger.error("Cannot send notification: missing Feishu app credentials")
            return
        
        # Build lark client directly
        import json
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import (
            CreateMessageRequest,
            CreateMessageRequestBody,
        )
        
        client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()
        # Status-based card color
        CARD_COLOR = {
            'FINISHED': 'green',
            'FAILED': 'red',
            'REVOKED': 'grey',
        }
        card_color = CARD_COLOR.get(status, 'blue')
        
        # Format as card for better display in Feishu
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"{emoji} 任务{label}"},
                "template": card_color
            },
            "elements": [
                {"tag": "markdown", "content": message}
            ]
        }
        content = json.dumps(card)
        
        # Send to each user via open_id
        for user in users:
            try:
                request = CreateMessageRequest.builder() \
                    .receive_id_type("open_id") \
                    .request_body(
                        CreateMessageRequestBody.builder()
                            .receive_id(user.feishu_openid)
                            .msg_type("interactive")
                            .content(content)
                            .build()
                    ) \
                    .build()
                
                response = client.im.v1.message.create(request)
                
                if response.success():
                    logger.info(f"Sent task notification to user {user.username} (open_id: {user.feishu_openid})")
                else:
                    logger.warning(f"Failed to send notification to {user.username}: {response.msg}")
            except Exception as e:
                logger.exception(f"Failed to send notification to user {user.username}: {e}")
            
    except Exception as e:
        logger.exception(f"Error in task notification for task {task_id}: {e}")
