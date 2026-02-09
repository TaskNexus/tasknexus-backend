"""
Feishu OAuth2.0 Service

Handles all interactions with Feishu OAuth APIs:
- Authorization URL generation
- Code to token exchange
- User info retrieval
"""

import requests
import logging
from urllib.parse import urlencode
from django.conf import settings

logger = logging.getLogger(__name__)


class FeishuOAuthService:
    """
    Feishu OAuth2.0 service wrapper.
    
    API Documentation:
    - Authorization: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/authen-v1/authen/authorize
    - Token Exchange: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/authen-v2/oauth/token
    - User Info: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/authen-v1/authen/user_info
    """
    
    AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
    TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
    USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"
    
    def __init__(self):
        self.app_id = settings.FEISHU_APP_ID
        self.app_secret = settings.FEISHU_APP_SECRET
        self.redirect_uri = settings.FEISHU_REDIRECT_URI
    
    def get_authorize_url(self, state: str = None) -> str:
        """
        Generate Feishu authorization URL.
        
        Args:
            state: Optional state parameter for CSRF protection
            
        Returns:
            Full authorization URL to redirect user to
        """
        params = {
            'app_id': self.app_id,
            'redirect_uri': self.redirect_uri,
            'scope': 'contact:user.base:readonly',  # Basic user info scope
        }
        if state:
            params['state'] = state
            
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"
    
    def exchange_code_for_token(self, code: str) -> dict:
        """
        Exchange authorization code for user access token.
        
        Args:
            code: Authorization code from callback
            
        Returns:
            Dict containing access_token, refresh_token, etc.
            
        Raises:
            FeishuOAuthError: If token exchange fails
        """
        payload = {
            'grant_type': 'authorization_code',
            'client_id': self.app_id,
            'client_secret': self.app_secret,
            'code': code,
            'redirect_uri': self.redirect_uri,
        }
        
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
        }
        
        response = requests.post(self.TOKEN_URL, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        logger.info(f"Feishu token exchange response: status={response.status_code}, data={data}")
        
        # v2 API returns access_token directly if successful, or error code if failed
        if 'error' in data or data.get('code', 0) != 0:
            error_msg = data.get('error_description') or data.get('message') or 'Unknown error'
            error_code = data.get('error') or data.get('code')
            logger.error(f"Feishu token exchange failed: code={error_code}, msg={error_msg}")
            raise FeishuOAuthError(f"Token exchange failed: {error_msg}")
        
        # v2 API returns data at root level, not nested in 'data'
        return data if 'access_token' in data else data.get('data', {})
    
    def get_user_info(self, access_token: str) -> dict:
        """
        Get user info using access token.
        
        Args:
            access_token: User access token
            
        Returns:
            Dict containing open_id, union_id, name, avatar_url, etc.
            
        Raises:
            FeishuOAuthError: If user info retrieval fails
        """
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        
        response = requests.get(self.USER_INFO_URL, headers=headers, timeout=10)
        data = response.json()
        
        if response.status_code != 200 or data.get('code') != 0:
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Feishu get user info failed: {error_msg}")
            raise FeishuOAuthError(f"Get user info failed: {error_msg}")
        
        return data.get('data', {})


class FeishuOAuthError(Exception):
    """Exception raised for Feishu OAuth errors."""
    pass
