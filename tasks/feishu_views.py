# -*- coding: utf-8 -*-
"""
Feishu API Views

Provides endpoints for interacting with Feishu (Lark) APIs,
using direct HTTP requests for reliability and transparency.
"""

import logging

import requests as http_requests
from django.http import JsonResponse
from django.views import View

logger = logging.getLogger('django')

FEISHU_BASE_URL = 'https://open.feishu.cn/open-apis'


def get_tenant_access_token():
    """
    Get a fresh tenant_access_token from Feishu.
    """
    from config.models import PlatformConfig
    feishu_config = PlatformConfig.get_feishu_config()
    app_id = feishu_config['app_id']
    app_secret = feishu_config['app_secret']
    
    if not app_id or not app_secret:
        return None, 'FEISHU_APP_ID 或 FEISHU_APP_SECRET 未配置，请在平台设置中配置'
    
    resp = http_requests.post(
        f'{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal',
        json={'app_id': app_id, 'app_secret': app_secret},
        timeout=10,
    )
    data = resp.json()
    
    if data.get('code') != 0:
        return None, f"获取 Token 失败: {data.get('msg')}"
    
    return data.get('tenant_access_token'), None


class FeishuUsersView(View):
    """
    GET /api/feishu/users/
    
    Fetches all visible users from Feishu contact API.
    Returns list of {open_id, name} for each user.
    
    If the API returns a permission error, the error detail is returned 
    so the frontend can display it to the user.
    """
    
    def get(self, request):
        token, err = get_tenant_access_token()
        if err:
            logger.error(f"Feishu token error: {err}")
            return JsonResponse({'error': err, 'users': []}, status=200)
        
        headers = {'Authorization': f'Bearer {token}'}
        all_users = []
        page_token = None
        
        try:
            while True:
                params = {
                    'department_id': '0',
                    'page_size': 50,
                }
                if page_token:
                    params['page_token'] = page_token
                
                resp = http_requests.get(
                    f'{FEISHU_BASE_URL}/contact/v3/users/find_by_department',
                    headers=headers,
                    params=params,
                    timeout=10,
                )
                data = resp.json()
                
                if data.get('code') != 0:
                    code = data.get('code')
                    msg = data.get('msg', 'Unknown error')
                    logger.warning(f"Feishu contact API: code={code} msg={msg}")
                    
                    # Return user-friendly error with empty user list
                    # Frontend will show error hint and allow manual input
                    if code == 99991672:
                        return JsonResponse({
                            'users': [],
                            'error': '飞书应用缺少通讯录权限',
                            'hint': '请在飞书开放平台开通 contact:contact.base:readonly 权限，并发布新版本',
                        })
                    
                    return JsonResponse({
                        'users': [],
                        'error': msg,
                    })
                
                items = data.get('data', {}).get('items', [])
                for user in items:
                    all_users.append({
                        'open_id': user.get('open_id'),
                        'name': user.get('name'),
                    })
                
                if data.get('data', {}).get('has_more'):
                    page_token = data['data'].get('page_token')
                else:
                    break
            
            return JsonResponse({'users': all_users})
            
        except Exception as e:
            logger.exception(f"Error fetching Feishu users: {e}")
            return JsonResponse({'error': str(e), 'users': []}, status=200)


import json
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone


@method_decorator(csrf_exempt, name='dispatch')
class FeishuCardCallbackView(View):
    """
    POST /api/feishu/approval-callback/

    Generic dispatcher for Feishu Card interaction callbacks (Card JSON v2, behavior type=callback).
    Must respond within 3 seconds with HTTP 200.

    Routing:
      The button's `behaviors[0].value` dict MUST contain an `action_type` field that
      identifies the handler to invoke.  Example button value:
          {"action_type": "feishu_approval", "token": "...", "decision": "approved", ...}

    Adding a new interaction type:
      1. Add an `action_type` key to your button's value dict.
      2. Register a handler in HANDLERS below – signature:
             handler(self, value, clicker_open_id, message_id) -> JsonResponse

    Payload forwarded by feishu_agent Go service:
      {
        "type": "card",
        "open_message_id": "om_xxx",
        "action": {
          "value":   { "action_type": "...", ...custom fields... },
          "open_id": "<clicker open_id>"
        }
      }
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'error': 'invalid json'}, status=400)

        # URL verification challenge (first-time setup)
        challenge = body.get('challenge')
        if challenge:
            return JsonResponse({'challenge': challenge})

        action = body.get('action') or {}
        value = action.get('value') or {}
        clicker_open_id = action.get('open_id', '')
        message_id = body.get('open_message_id', '')
        action_type = value.get('action_type', '')

        logger.info(
            f"FeishuCardCallback: action_type={action_type!r} "
            f"clicker={clicker_open_id} msg={message_id}"
        )

        # Route to the appropriate handler
        handler = self.HANDLERS.get(action_type)
        if handler is None:
            logger.warning(f"FeishuCardCallback: unknown action_type={action_type!r}, value={value}")
            return JsonResponse({'toast': {'type': 'error', 'content': f'未知的交互类型: {action_type}'}})

        return handler(self, value, clicker_open_id, message_id)

    # ------------------------------------------------------------------
    # Handler registry — maps action_type → bound method
    # ------------------------------------------------------------------

    def _handle_approval(self, value: dict, clicker_open_id: str, message_id: str):
        """Handle feishu_approval card button clicks."""
        token = value.get('token', '')
        decision = value.get('decision', '')
        open_id_from_value = value.get('open_id', '')
        callback_node_id = value.get('node_id', '')
        callback_node_version = value.get('node_version', '')

        if not token or decision not in ('approved', 'rejected'):
            return JsonResponse({'toast': {'type': 'error', 'content': '无效的审核请求'}})

        # Identity cross-check
        if clicker_open_id and open_id_from_value and clicker_open_id != open_id_from_value:
            logger.warning(
                f"Approval open_id mismatch: clicker={clicker_open_id}, "
                f"value={open_id_from_value}, token={token}"
            )
            return JsonResponse({'toast': {'type': 'error', 'content': '身份校验失败'}})

        effective_open_id = open_id_from_value or clicker_open_id

        try:
            from tasks.models import FeishuApprovalRecord
            record = FeishuApprovalRecord.objects.get(token=token)
        except FeishuApprovalRecord.DoesNotExist:
            return JsonResponse({'toast': {'type': 'error', 'content': '审核记录不存在或已过期'}})

        if effective_open_id in record.decisions:
            return JsonResponse({'toast': {'type': 'info', 'content': '您已完成审核，无需重复操作'}})

        if record.status != FeishuApprovalRecord.STATUS_PENDING:
            return JsonResponse({'toast': {'type': 'info', 'content': '审核已结束，无需重复操作'}})

        approval_completed = record.record_decision(effective_open_id, decision)
        if effective_open_id not in record.decisions:
            return JsonResponse({'toast': {'type': 'error', 'content': '您不在审核成员列表中'}})

        decision_label = '通过 ✅' if decision == 'approved' else '不通过 ❌'
        toast = {'type': 'success', 'content': f'已记录：{decision_label}，感谢审核'}

        if approval_completed:
            final_result = (
                'approved'
                if record.status == FeishuApprovalRecord.STATUS_APPROVED
                else 'rejected'
            )
            callback_ok, callback_err = self._callback_approval_node(
                token=token,
                result=final_result,
                callback_node_id=callback_node_id or record.callback_node_id,
                callback_node_version=callback_node_version or record.callback_node_version,
            )
            if not callback_ok:
                logger.error(
                    'Feishu approval callback failed: '
                    f'token={token} node={callback_node_id or record.callback_node_id} '
                    f'version={callback_node_version or record.callback_node_version} '
                    f'err={callback_err}'
                )
                toast = {
                    'type': 'warning',
                    'content': '已记录审核结果，但流程回调失败，请联系管理员',
                }

        resp_data = {'toast': toast}
        if message_id:
            resp_data['card_update'] = {
                'message_id': message_id,
                'card': self._build_decided_card(decision),
            }
        return JsonResponse(resp_data)

    @staticmethod
    def _callback_approval_node(
        token: str,
        result: str,
        callback_node_id: str,
        callback_node_version: str,
    ):
        if not callback_node_id or not callback_node_version:
            return False, 'missing callback node metadata'

        try:
            from bamboo_engine import api as bamboo_api
            from pipeline.eri.runtime import BambooDjangoRuntime

            runtime = BambooDjangoRuntime()
            callback_result = bamboo_api.callback(
                runtime=runtime,
                node_id=callback_node_id,
                version=callback_node_version,
                data={
                    'action_type': 'feishu_approval',
                    'token': token,
                    'result': result,
                },
            )
            if callback_result.result:
                return True, ''
            return False, callback_result.message or 'callback result=false'
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _build_decided_card(decision: str) -> dict:
        """Build the static 'already decided' card (no buttons)."""
        now_str = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M')
        decision_text = '通过 ✅' if decision == 'approved' else '不通过 ❌'
        return {
            'schema': '2.0',
            'config': {'update_multi': True},
            'header': {
                'title': {'tag': 'plain_text', 'content': '📋 审核完成'},
                'template': 'green' if decision == 'approved' else 'red',
            },
            'body': {
                'elements': [
                    {
                        'tag': 'markdown',
                        'content': f'您已于 **{now_str}** 作出决定：**{decision_text}**\n\n感谢审核！',
                    }
                ]
            },
        }

    # Maps action_type string → handler method
    HANDLERS = {
        'feishu_approval': _handle_approval,
    }
