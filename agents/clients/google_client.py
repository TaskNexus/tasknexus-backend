"""
Google GenAI Client

Supports Google's Generative AI services including Gemini and Imagen.
"""

from typing import Any, Dict, List, Optional

from .base import BaseAIClient

try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    genai = None
    types = None


class GoogleAIClient(BaseAIClient):
    """
    Google GenAI API client.
    
    Supports:
    - Gemini models for text generation and chat
    - Imagen models for image generation
    """
    
    def __init__(self, api_key: str, config: Optional[Dict] = None):
        super().__init__(api_key, config)
        
        if genai is None:
            raise ImportError("google-genai library is not installed")
            
        self._client = genai.Client(api_key=api_key)
    
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
        Generate chat completion using Google GenAI.
        
        Note: Google GenAI has different tool calling format.
        This method provides a unified interface but may need adaptation
        for complex tool scenarios.
        """
        
        # Convert messages to Google GenAI format
        contents = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            # Map roles
            if role == 'assistant':
                role = 'model'
            elif role == 'system':
                # System messages can be prepended to first user message
                # or handled separately based on use case
                role = 'user'
            
            contents.append({
                'role': role,
                'parts': [{'text': content}]
            })
        
        # Generate content
        effective_model = model or "gemini-2.0-flash-exp"
        
        generation_config = {
            'temperature': temperature,
        }
        
        response = self._client.models.generate_content(
            model=effective_model,
            contents=contents,
            config=types.GenerateContentConfig(**generation_config) if types else generation_config
        )
        
        return {
            'content': response.text if response.text else None,
            'tool_calls': None,  # Google uses different format
            'raw_response': response,
            'finish_reason': 'stop'
        }
    
    def generate_image(
        self,
        prompt: str,
        width: int,
        height: int,
        model: Optional[str] = None,
        **kwargs
    ) -> bytes:
        """Generate image using Google Imagen."""
        
        imagen_model = model or "imagen-3.0-generate-002"
        
        # Calculate aspect ratio from dimensions
        aspect_ratio = self._calculate_aspect_ratio(width, height)
        
        config_params = {
            "number_of_images": 1
        }
        
        if aspect_ratio:
            config_params["aspect_ratio"] = aspect_ratio
        
        response = self._client.models.generate_images(
            model=imagen_model,
            prompt=prompt,
            config=types.GenerateImagesConfig(**config_params) if types else config_params
        )
        
        if not response.generated_images:
            raise Exception('No image returned from Google API')
        
        return response.generated_images[0].image.image_bytes
    
    def generate_text(
        self,
        message: str,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        """Generate simple text response using Gemini."""
        
        effective_model = model or "gemini-2.0-flash-exp"
        
        response = self._client.models.generate_content(
            model=effective_model,
            contents=[message]
        )
        
        if not response.text:
            raise Exception('No text returned from Google API')
        
        return response.text
    
    def _calculate_aspect_ratio(self, width: int, height: int) -> Optional[str]:
        """
        Calculate aspect ratio string from dimensions.
        
        Google GenAI expects aspect_ratio as string like '1:1', '16:9', etc.
        """
        try:
            w = int(width)
            h = int(height)
            
            if w == h:
                return "1:1"
            elif w > h:
                # Landscape
                ratio = w / h
                if abs(ratio - 16/9) < 0.1:
                    return "16:9"
                elif abs(ratio - 4/3) < 0.1:
                    return "4:3"
            else:
                # Portrait
                ratio = h / w
                if abs(ratio - 16/9) < 0.1:
                    return "9:16"
                elif abs(ratio - 4/3) < 0.1:
                    return "3:4"
            
            return None
            
        except (ValueError, ZeroDivisionError):
            return None
