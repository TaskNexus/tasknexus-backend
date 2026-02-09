"""
Channel Plugin Base Classes

Defines the interface for messaging channel plugins (Feishu, Telegram, etc.)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class ChannelMessage:
    """
    Message received from or sent to a channel.
    
    Attributes:
        channel_id: Channel plugin identifier (e.g., 'feishu', 'telegram')
        chat_id: Conversation/chat identifier in the channel
        sender_id: Sender's ID in the channel
        sender_name: Sender's display name
        content: Message text content
        raw: Original raw message data from the channel
    """
    channel_id: str
    chat_id: str
    sender_id: str
    sender_name: str = ""
    content: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MessagePayload:
    """
    Payload for sending a message to a channel.
    
    Attributes:
        chat_id: Target conversation/chat identifier
        content: Message content to send
        msg_type: Message type (default: 'text')
    """
    chat_id: str
    content: str
    msg_type: str = "text"


class ChannelPlugin(ABC):
    """
    Abstract base class for messaging channel plugins.
    
    Plugins must implement this interface to integrate with TaskNexus.
    
    Example:
        class FeishuChannel(ChannelPlugin):
            @property
            def id(self) -> str:
                return "feishu"
            
            @property
            def label(self) -> str:
                return "飞书"
            
            async def start(self, config: dict):
                # Start WebSocket connection
                ...
    """
    
    @property
    @abstractmethod
    def id(self) -> str:
        """Unique channel identifier (e.g., 'feishu', 'telegram')"""
        pass
    
    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable channel name"""
        pass
    
    @abstractmethod
    async def start(self, config: Dict[str, Any]) -> None:
        """
        Start the channel service (e.g., WebSocket connection).
        
        Args:
            config: Channel configuration from environment/settings
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel service gracefully."""
        pass
    
    @abstractmethod
    async def send(self, payload: MessagePayload) -> bool:
        """
        Send a message to the channel.
        
        Args:
            payload: Message payload containing target and content
            
        Returns:
            True if sent successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def on_message(self, callback: Callable[[ChannelMessage], None]) -> None:
        """
        Register a callback for incoming messages.
        
        Args:
            callback: Function to call when a message is received
        """
        pass
