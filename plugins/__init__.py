"""
TaskNexus Plugin System

Platform-level plugin architecture for extending TaskNexus with external integrations.
Plugins are discovered via Python entry_points ('tasknexus.plugins' group).

Usage:
    pip install git+https://github.com/<org>/tasknexus-feishu-plugin.git
    python manage.py channel_bot --channel feishu
"""

from .channel import ChannelPlugin, ChannelMessage, MessagePayload
from .manager import PluginManager

__all__ = [
    'PluginManager',
    'ChannelPlugin',
    'ChannelMessage',
    'MessagePayload',
]
