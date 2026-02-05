"""
OpenAI Client

Supports OpenAI API and compatible providers (like Azure OpenAI, etc.)
"""

import base64
import requests
import httpx
from typing import Any, Dict, List, Optional

from .base import BaseAIClient

try:
    import openai
except ImportError:
    openai = None


class OpenAIClient(BaseAIClient):
    """
    OpenAI API client supporting both SDK and HTTP modes.
    
    Attributes:
        api_url: Base URL for the API (for compatible providers)
        use_sdk: Whether to use the openai SDK or raw HTTP requests
    """
    
    def __init__(
        self, 
        api_key: str, 
        api_url: Optional[str] = None,
        config: Optional[Dict] = None,
        use_sdk: bool = True,
        timeout: float = 120.0,
    ):
        super().__init__(api_key, config)
        self.api_url = api_url
        
        self.use_sdk = use_sdk and openai is not None
        self.timeout = timeout
        
        if self.use_sdk:
            client_kwargs = {"api_key": api_key, "timeout": timeout}
            if api_url:
                client_kwargs["base_url"] = api_url
            
            self._client = openai.Client(**client_kwargs)
        else:
            self._client = None
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate chat completion using OpenAI API."""
        
        if self.use_sdk:
            return self._chat_completion_sdk(
                messages, model, tools, tool_choice, temperature, **kwargs
            )
        else:
            return self._chat_completion_http(
                messages, model, tools, tool_choice, temperature, **kwargs
            )
    
    def _chat_completion_sdk(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Chat completion using OpenAI SDK."""
        
        request_params = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs
        }
        
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = tool_choice
        
        response = self._client.chat.completions.create(**request_params)
        response_message = response.choices[0].message
        
        return {
            'content': response_message.content,
            'tool_calls': response_message.tool_calls,
            'raw_response': response_message,
            'finish_reason': response.choices[0].finish_reason
        }
    
    def _chat_completion_http(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """Chat completion using HTTP requests."""
        
        endpoint = self._build_endpoint("chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            **kwargs
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        
        response = requests.post(
            endpoint, 
            headers=headers, 
            json=payload, 
            timeout=self.timeout,
        )
        
        if response.status_code != 200:
            raise Exception(f"API Error {response.status_code}: {response.text}")
        
        resp_json = response.json()
        choices = resp_json.get('choices', [])
        
        if not choices:
            raise Exception('No choices in response')
        
        message = choices[0].get('message', {})
        
        return {
            'content': message.get('content'),
            'tool_calls': message.get('tool_calls'),
            'raw_response': message,
            'finish_reason': choices[0].get('finish_reason')
        }
    
    def generate_image(
        self,
        prompt: str,
        width: int,
        height: int,
        model: Optional[str] = None,
        **kwargs
    ) -> bytes:
        """Generate image using OpenAI-compatible API."""
        
        endpoint = self._build_endpoint("images/generations")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        effective_model = model or "dall-e-3"
        size = f"{width}x{height}"
        
        payload = {
            "prompt": prompt,
            "model": effective_model,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
            **kwargs
        }
        
        response = requests.post(
            endpoint, 
            headers=headers, 
            json=payload, 
            timeout=60,
        )
        
        if response.status_code != 200:
            raise Exception(f"API Error {response.status_code}: {response.text}")
        
        resp_json = response.json()
        
        if not resp_json.get('data'):
            raise Exception('No image data in response')
        
        data_item = resp_json['data'][0]
        image_b64 = data_item.get('b64_json')
        
        if image_b64:
            return base64.b64decode(image_b64)
        
        # Fallback to URL if b64 not available
        image_url = data_item.get('url')
        if image_url:
            img_resp = requests.get(image_url, timeout=60)
            if img_resp.status_code == 200:
                return img_resp.content
            else:
                raise Exception(f"Failed to download image from url: {img_resp.status_code}")
        
        raise Exception('No b64_json or url in response')
    
    def generate_text(
        self,
        message: str,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate simple text response."""
        
        effective_model = model or "gpt-3.5-turbo"
        messages = [{"role": "user", "content": message}]
        
        result = self.chat_completion(
            messages=messages,
            model=effective_model,
            temperature=kwargs.get('temperature', 0.7)
        )
        
        return result.get('content', '')
    
    def _build_endpoint(self, path: str) -> str:
        """Build the full API endpoint URL."""
        
        if not self.api_url:
            return f"https://api.openai.com/v1/{path}"
        
        base = self.api_url.rstrip('/')
        
        # Handle various base URL formats
        if base.endswith('/v1'):
            return f"{base}/{path}"
        else:
            return f"{base}/{path}"
