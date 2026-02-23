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
