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


def _normalize_users(items):
    """
    Normalize Feishu user payloads to [{open_id, name}].
    """
    result = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue

        open_id = str(item.get('open_id') or '').strip()
        if not open_id:
            continue

        if open_id in seen:
            continue
        seen.add(open_id)

        name = str(item.get('name') or '').strip() or open_id
        result.append({'open_id': open_id, 'name': name})
    return result


def _is_no_dept_authority(code, msg):
    text = f'{code} {msg}'.lower()
    keywords = (
        'no dept authority',
        'no department authority',
        '无部门权限',
        '部门权限',
    )
    return any(k in text for k in keywords)


def _fetch_users_by_department(headers, department_id, department_id_type=None):
    """
    Fetch users under a specific department with pagination.
    Returns (users, error_data_or_none)
    """
    all_users = []
    page_token = None

    while True:
        params = {
            'department_id': department_id,
            'page_size': 50,
            'user_id_type': 'open_id',
            # Include users from child departments.
            'fetch_child': 'true',
        }
        if department_id_type:
            params['department_id_type'] = department_id_type
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
            return None, data

        items = data.get('data', {}).get('items', [])
        all_users.extend(_normalize_users(items))

        if data.get('data', {}).get('has_more'):
            page_token = data.get('data', {}).get('page_token')
            if not page_token:
                break
        else:
            break

    return all_users, None


def _fetch_contact_scopes(headers):
    """
    Query app-authorized contact scopes.
    Returns (scope_data, error_data_or_none).
    """
    resp = http_requests.get(
        f'{FEISHU_BASE_URL}/contact/v3/scopes',
        headers=headers,
        timeout=10,
    )
    data = resp.json()
    if data.get('code') != 0:
        return None, data
    return data.get('data', {}) or {}, None


def _fetch_visible_department_roots(headers):
    """
    Fetch visible departments and infer root departments within visible scope.
    Returns (root_open_department_ids, error_data_or_none)
    """
    page_token = None
    departments = []

    while True:
        params = {
            'department_id_type': 'open_department_id',
            'fetch_child': 'true',
            'page_size': 50,
        }
        if page_token:
            params['page_token'] = page_token

        resp = http_requests.get(
            f'{FEISHU_BASE_URL}/contact/v3/departments',
            headers=headers,
            params=params,
            timeout=10,
        )
        data = resp.json()
        if data.get('code') != 0:
            return None, data

        items = data.get('data', {}).get('items', []) or []
        for item in items:
            if not isinstance(item, dict):
                continue
            open_dep_id = str(item.get('open_department_id') or '').strip()
            if not open_dep_id:
                continue

            parent_open_dep_id = str(item.get('open_parent_department_id') or '').strip()
            if not parent_open_dep_id:
                parent_ids = item.get('parent_department_ids')
                if isinstance(parent_ids, list):
                    for parent_id in parent_ids:
                        parent_str = str(parent_id).strip()
                        # Prefer open-department style parent id when available.
                        if parent_str.startswith('od-'):
                            parent_open_dep_id = parent_str
                            break

            departments.append({
                'open_department_id': open_dep_id,
                'open_parent_department_id': parent_open_dep_id,
            })

        if data.get('data', {}).get('has_more'):
            page_token = data.get('data', {}).get('page_token')
            if not page_token:
                break
        else:
            break

    if not departments:
        return [], None

    all_ids = {d['open_department_id'] for d in departments}
    roots = []
    seen = set()
    for dep in departments:
        dep_id = dep['open_department_id']
        parent_id = dep['open_parent_department_id']
        if not parent_id or parent_id not in all_ids:
            if dep_id not in seen:
                roots.append(dep_id)
                seen.add(dep_id)

    return roots, None


def _extract_scope_department_ids(scope_data):
    """
    Extract both department_id and open_department_id lists from scope payload.
    """
    dept_ids = []
    open_dept_ids = []

    for key in ('department_ids', 'authed_department_ids'):
        vals = scope_data.get(key)
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, dict):
                    dep = str(v.get('department_id') or '').strip()
                    open_dep = str(v.get('open_department_id') or '').strip()
                    if dep:
                        dept_ids.append(dep)
                    if open_dep:
                        open_dept_ids.append(open_dep)
                else:
                    dep = str(v).strip()
                    if dep:
                        dept_ids.append(dep)

    for key in ('open_department_ids', 'authed_open_department_ids'):
        vals = scope_data.get(key)
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, dict):
                    open_dep = str(v.get('open_department_id') or '').strip()
                    dep = str(v.get('department_id') or '').strip()
                    if open_dep:
                        open_dept_ids.append(open_dep)
                    if dep:
                        dept_ids.append(dep)
                else:
                    open_dep = str(v).strip()
                    if open_dep:
                        open_dept_ids.append(open_dep)

    for key in ('authed_departments', 'departments'):
        vals = scope_data.get(key)
        if isinstance(vals, list):
            for item in vals:
                if isinstance(item, dict):
                    dep = str(item.get('department_id') or '').strip()
                    if dep:
                        dept_ids.append(dep)

    for key in ('authed_open_departments', 'open_departments'):
        vals = scope_data.get(key)
        if isinstance(vals, list):
            for item in vals:
                if isinstance(item, dict):
                    dep = str(item.get('open_department_id') or '').strip()
                    if dep:
                        open_dept_ids.append(dep)

    # Keep order while deduplicating
    dept_ids = list(dict.fromkeys(dept_ids))
    open_dept_ids = list(dict.fromkeys(open_dept_ids))
    return dept_ids, open_dept_ids


def _list_scope_seed_departments(scope_data):
    """
    List all authorized seed departments from scopes.
    Returns [(department_id, department_id_type), ...]
    """
    dept_ids, open_dept_ids = _extract_scope_department_ids(scope_data)
    result = []
    seen = set()

    for dep in open_dept_ids:
        key = f'open_department_id:{dep}'
        if key in seen:
            continue
        seen.add(key)
        result.append((dep, 'open_department_id'))

    for dep in dept_ids:
        dep_type = 'open_department_id' if dep.startswith('od-') else 'department_id'
        key = f'{dep_type}:{dep}'
        if key in seen:
            continue
        seen.add(key)
        result.append((dep, dep_type))

    return result


def _extract_scope_users(scope_data):
    """
    Some scope payloads include directly authorized open users.
    """
    users = []

    for key in ('authed_open_users', 'open_users'):
        vals = scope_data.get(key)
        if isinstance(vals, list):
            for item in vals:
                if isinstance(item, dict):
                    users.append({
                        'open_id': item.get('open_id'),
                        'name': item.get('name') or item.get('open_id'),
                    })

    open_ids = []
    for key in ('open_ids', 'authed_open_ids'):
        vals = scope_data.get(key)
        if isinstance(vals, list):
            for open_id in vals:
                v = str(open_id).strip()
                if v:
                    open_ids.append(v)

    open_ids = list(dict.fromkeys(open_ids))
    for open_id in open_ids:
        users.append({'open_id': open_id, 'name': open_id})

    return _normalize_users(users)


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
        
        try:
            # Primary path: root department for apps with full org visibility.
            all_users, fetch_err = _fetch_users_by_department(headers, department_id='0')
            if not fetch_err:
                return JsonResponse({'users': _normalize_users(all_users)})

            code = fetch_err.get('code')
            msg = fetch_err.get('msg', 'Unknown error')
            logger.warning(f"Feishu contact API: code={code} msg={msg}")

            # Missing contact permission.
            if str(code) == '99991672':
                return JsonResponse({
                    'users': [],
                    'error': '飞书应用缺少通讯录权限',
                    'hint': '请在飞书开放平台开通 contact:contact.base:readonly 权限，并发布新版本',
                })

            # App only has partial department visibility: fetch by authorized scopes.
            if _is_no_dept_authority(code, msg):
                scope_data, scope_err = _fetch_contact_scopes(headers)
                if scope_err:
                    scope_code = scope_err.get('code')
                    scope_msg = scope_err.get('msg', 'Unknown error')
                    logger.warning(f"Feishu scope API: code={scope_code} msg={scope_msg}")
                    return JsonResponse({
                        'users': [],
                        'error': '无法获取飞书通讯录授权范围',
                        'hint': f'请检查飞书应用可见范围与通讯录权限后重试（{scope_msg}）',
                    })

                # Prefer visible-scope roots from departments API,
                # then recursively fetch users by each root via official API.
                root_seeds = []
                roots, roots_err = _fetch_visible_department_roots(headers)
                if roots_err:
                    logger.warning(
                        "Feishu departments API failed: "
                        f"code={roots_err.get('code')} msg={roots_err.get('msg')}"
                    )
                else:
                    root_seeds = [(dep_id, 'open_department_id') for dep_id in roots]

                scope_seeds = root_seeds or _list_scope_seed_departments(scope_data)
                if scope_seeds:
                    merged_users = []
                    fetch_errors = []
                    for dep_id, dep_type in scope_seeds:
                        scoped_users, scoped_err = _fetch_users_by_department(
                            headers=headers,
                            department_id=dep_id,
                            department_id_type=dep_type,
                        )
                        if scoped_err:
                            fetch_errors.append(f'{dep_type}:{dep_id}:{scoped_err.get("msg")}')
                            logger.warning(
                                "Feishu scoped recursive fetch failed: "
                                f"type={dep_type} dep={dep_id} "
                                f"code={scoped_err.get('code')} msg={scoped_err.get('msg')}"
                            )
                            continue
                        merged_users.extend(scoped_users or [])

                    merged_users = _normalize_users(merged_users)
                    if merged_users:
                        return JsonResponse({'users': merged_users})

                    if fetch_errors:
                        return JsonResponse({
                            'users': [],
                            'error': '飞书用户递归拉取失败',
                            'hint': f"seeds={len(scope_seeds)}; " + '; '.join(fetch_errors[:3]),
                        })

                # Fallback: directly authorized users in scope payload
                users = _extract_scope_users(scope_data)
                if users:
                    return JsonResponse({'users': users})

                return JsonResponse({
                    'users': [],
                    'error': '当前飞书应用可访问范围内没有可用用户',
                    'hint': '请检查飞书应用可见范围是否包含目标部门/成员，并确认已发布新版本',
                })

            return JsonResponse({
                'users': [],
                'error': msg,
            })
            
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
