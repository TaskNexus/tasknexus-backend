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


@method_decorator(csrf_exempt, name='dispatch')
class FeishuCardCallbackView(View):
    """
    POST /api/feishu/approval-callback/

    Generic forwarder for Feishu card callbacks.
    This endpoint only validates payload and forwards callback data to
    bamboo_engine by node_id/node_version contained in action.value.

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
        callback_node_id = value.get('node_id', '')
        callback_node_version = value.get('node_version', '')
        action_type = value.get('action_type', '')

        if not callback_node_id or not callback_node_version:
            return JsonResponse({'toast': {'type': 'error', 'content': '回调缺少 node_id 或 node_version'}})

        logger.info(
            f"FeishuCardCallback: action_type={action_type!r} "
            f"node={callback_node_id} version={callback_node_version} "
            f"clicker={clicker_open_id} msg={message_id}"
        )

        callback_payload = dict(value)
        callback_payload['clicker_open_id'] = clicker_open_id
        callback_payload['message_id'] = message_id

        ok, err = self._callback_node(
            callback_node_id=callback_node_id,
            callback_node_version=callback_node_version,
            callback_payload=callback_payload,
        )
        if not ok:
            logger.error(
                'FeishuCardCallback: bamboo callback failed '
                f'node={callback_node_id} version={callback_node_version} err={err}'
            )
            return JsonResponse({'toast': {'type': 'error', 'content': '交互已接收，但流程回调失败'}})

        return JsonResponse({'toast': {'type': 'success', 'content': '已接收您的操作'}})

    @staticmethod
    def _callback_node(callback_node_id: str, callback_node_version: str, callback_payload: dict):
        try:
            from bamboo_engine import api as bamboo_api
            from pipeline.eri.runtime import BambooDjangoRuntime

            runtime = BambooDjangoRuntime()
            callback_result = bamboo_api.callback(
                runtime=runtime,
                node_id=callback_node_id,
                version=callback_node_version,
                data=callback_payload,
            )
            if callback_result.result:
                return True, ''
            return False, callback_result.message or 'callback result=false'
        except Exception as e:
            return False, str(e)
