"""
AI Clients Module

Provides unified interface for different AI providers:
- OpenAI (and compatible APIs)
- Google GenAI (Gemini, Imagen)
"""

from .base import BaseAIClient
from .openai_client import OpenAIClient
from .google_client import GoogleAIClient


def get_ai_client(project_id: int, model_group_name: str, use_sdk: bool = True) -> BaseAIClient:
    """
    Factory function to create the appropriate AI client based on configuration.
    
    Args:
        project_id: The project ID to load configuration from
        model_group_name: The name of the model group in project config
        use_sdk: Whether to use SDK client (True) or HTTP client (False) for OpenAI
        
    Returns:
        An AI client instance
    """
    from projects.models import Project
    
    try:
        project = Project.objects.get(id=project_id)
        extra_config = project.extra_config or {}
        model_groups = extra_config.get('model_groups', [])
        target_group = None
        for group in model_groups:
            if group.get('title') == model_group_name and group.get('enabled', True):
                target_group = group
                break
        
        if not target_group:
            raise ValueError(f"Model group '{model_group_name}' not found or disabled")
        
        api_url = target_group.get('api_url', '')
        api_key = target_group.get('api_key', '')
        
        if not api_key:
            raise ValueError(f"API Key not configured for group '{model_group_name}'")
        
        # Determine client type based on API URL presence
        if api_url:
            return OpenAIClient(
                api_key=api_key,
                api_url=api_url,
                config=target_group,
                use_sdk=use_sdk,
            )
        else:
            return GoogleAIClient(
                api_key=api_key,
                config=target_group
            )
            
    except Project.DoesNotExist:
        raise ValueError(f"Project {project_id} not found")


__all__ = [
    'BaseAIClient',
    'OpenAIClient', 
    'GoogleAIClient',
    'get_ai_client',
]
