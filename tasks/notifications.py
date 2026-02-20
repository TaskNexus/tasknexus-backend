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
    Supports both platform users (via notify_user_ids) and direct Feishu users (via feishu_notify_open_ids).
    
    Runs in a background thread to avoid blocking the signal handler.
    """
    has_platform = task.notify_enabled and task.notify_user_ids
    has_feishu = task.feishu_notify_enabled and task.feishu_notify_open_ids
    
    if not has_platform and not has_feishu:
        return
    
    # Read template from workflow
    notify_template = ''
    if task.workflow:
        notify_template = getattr(task.workflow, 'notify_template', '') or ''
    
    # Collect pipeline context variables (includes spliced outputs like ${news})
    pipeline_vars = _collect_pipeline_context(task)
    
    # Run in background thread
    thread = threading.Thread(
        target=_do_send_notification,
        args=(
            task.id,
            task.name,
            task.status,
            task.notify_user_ids if has_platform else [],
            task.workflow.name if task.workflow else 'Unknown',
            task.context or {},
            notify_template,
            task.feishu_notify_open_ids if has_feishu else [],
            pipeline_vars,
        ),
        daemon=True
    )
    thread.start()


def _collect_pipeline_context(task):
    """
    Collect all context variables from the pipeline execution.
    These include spliced output variables (e.g. ${news} from component outputs).
    Returns a flat dict: {variable_name: value}.
    """
    result = {}
    try:
        if not task.pipeline_id:
            return result
        
        from pipeline.eri.models import ContextValue as DBContextValue
        from pipeline.eri.imp.context import ContextMixin
        
        mixin = ContextMixin()
        qs = DBContextValue.objects.filter(
            pipeline_id=task.pipeline_id
        ).only('key', 'value', 'serializer')
        
        for cv in qs:
            try:
                # Strip ${} wrapper from key, e.g. "${news}" -> "news"
                key = cv.key
                if key.startswith('${') and key.endswith('}'):
                    key = key[2:-1]
                result[key] = mixin._deserialize(cv.value, cv.serializer)
            except Exception:
                result[cv.key] = str(cv.value)
    except Exception as e:
        logger.warning(f"Failed to collect pipeline context for task {task.id}: {e}")
    
    return result


def _do_send_notification(task_id, task_name, status, notify_user_ids, workflow_name, context, notify_template, feishu_open_ids=None, pipeline_vars=None):
    """
    Actually send notifications. Runs in a background thread.
    Sends to both platform users (by user ID lookup) and direct Feishu open_ids.
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
            'vars': pipeline_vars or {},  # pipeline context variables (spliced outputs)
        }
        
        # Use custom template or default
        template = notify_template.strip() if notify_template else DEFAULT_TEMPLATE
        message = render_template(template, variables)
        
        import os
        app_id = os.environ.get('FEISHU_APP_ID')
        app_secret = os.environ.get('FEISHU_APP_SECRET')
        
        if not app_id or not app_secret:
            logger.error("Cannot send notification: missing Feishu app credentials")
            return
        
        # Build lark client
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
        
        # Format as card
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
        
        def send_to_open_id(open_id, label_name):
            """Send card to a single open_id."""
            try:
                request = CreateMessageRequest.builder() \
                    .receive_id_type("open_id") \
                    .request_body(
                        CreateMessageRequestBody.builder()
                            .receive_id(open_id)
                            .msg_type("interactive")
                            .content(content)
                            .build()
                    ) \
                    .build()
                
                response = client.im.v1.message.create(request)
                
                if response.success():
                    logger.info(f"Sent task notification to {label_name} (open_id: {open_id})")
                else:
                    logger.warning(f"Failed to send notification to {label_name}: {response.msg}")
            except Exception as e:
                logger.exception(f"Failed to send notification to {label_name}: {e}")
        
        # 1) Send to platform users (lookup feishu_openid from DB)
        if notify_user_ids:
            users = User.objects.filter(
                id__in=notify_user_ids,
                feishu_openid__isnull=False
            ).exclude(feishu_openid='')
            
            for user in users:
                send_to_open_id(user.feishu_openid, user.username)
        
        # 2) Send to direct Feishu open_ids (no platform account needed)
        if feishu_open_ids:
            for open_id in feishu_open_ids:
                send_to_open_id(open_id, f"feishu:{open_id[:8]}...")
            
    except Exception as e:
        logger.exception(f"Error in task notification for task {task_id}: {e}")

