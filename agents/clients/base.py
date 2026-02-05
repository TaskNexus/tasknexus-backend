"""
Base AI Client Interface

Defines the abstract interface for all AI clients.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAIClient(ABC):
    """
    Abstract base class for AI clients.
    
    All AI provider clients should inherit from this class
    and implement the abstract methods.
    """
    
    def __init__(self, api_key: str, config: Optional[Dict] = None):
        """
        Initialize the AI client.
        
        Args:
            api_key: The API key for authentication
            config: Optional configuration dictionary from project settings
        """
        self.api_key = api_key
        self.config = config or {}
    
    @abstractmethod
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict]] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a chat completion response.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            model: The model name to use
            tools: Optional list of tool definitions
            tool_choice: How to handle tool selection ('auto', 'none', etc.)
            temperature: Sampling temperature (0.0 to 2.0)
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Dictionary containing the completion response with structure:
            {
                'content': str or None,
                'tool_calls': list or None,
                'raw_response': original response object
            }
        """
        pass
    
    @abstractmethod
    def generate_image(
        self,
        prompt: str,
        width: int,
        height: int,
        model: Optional[str] = None,
        **kwargs
    ) -> bytes:
        """
        Generate an image from a text prompt.
        
        Args:
            prompt: The text description of the image to generate
            width: Desired image width in pixels
            height: Desired image height in pixels
            model: Optional specific model to use
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Image data as bytes
        """
        pass
    
    @abstractmethod
    def generate_text(
        self,
        message: str,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Generate a simple text response (single-turn, no tools).
        
        Args:
            message: The input message/prompt
            model: Optional specific model to use
            **kwargs: Additional provider-specific parameters
            
        Returns:
            Generated text response
        """
        pass
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """
        Get list of available models from configuration.
        
        Returns:
            List of model dictionaries with 'name' and 'enabled' keys
        """
        return self.config.get('models', [])
    
    def validate_model(self, model_name: str) -> bool:
        """
        Check if a model is available and enabled.
        
        Args:
            model_name: Name of the model to validate
            
        Returns:
            True if model is valid and enabled
        """
        available_models = [
            m.get('name') for m in self.get_available_models() 
            if m.get('enabled', True)
        ]
        return model_name in available_models
