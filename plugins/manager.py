"""
Plugin Manager

Discovers and manages TaskNexus plugins via Python entry_points.
"""

import logging
import os
from importlib.metadata import entry_points
from typing import Callable, Dict, Optional

from .channel import ChannelPlugin

logger = logging.getLogger('django')


class PluginManager:
    """
    Manages plugin discovery and registration.
    
    Plugins are discovered via the 'tasknexus.plugins' entry_point group.
    Each plugin module should have a `register(manager)` function.
    
    Example pyproject.toml for a plugin:
        [project.entry-points."tasknexus.plugins"]
        feishu = "tasknexus_feishu:register"
    """
    
    ENTRY_POINT_GROUP = "tasknexus.plugins"
    
    def __init__(self):
        self.channels: Dict[str, ChannelPlugin] = {}
        self._discovered = False
    
    def discover(self) -> None:
        """
        Discover and load all installed plugins.
        
        Scans Python entry_points for 'tasknexus.plugins' group
        and calls each plugin's register() function.
        """
        if self._discovered:
            return
        
        try:
            eps = entry_points(group=self.ENTRY_POINT_GROUP)
        except TypeError:
            # Python < 3.10 compatibility
            eps = entry_points().get(self.ENTRY_POINT_GROUP, [])
        
        for ep in eps:
            try:
                logger.info(f"Loading plugin: {ep.name}")
                module = ep.load()
                if hasattr(module, 'register'):
                    module.register(self)
                    logger.info(f"Plugin registered: {ep.name}")
                else:
                    logger.warning(f"Plugin {ep.name} has no register() function")
            except Exception as e:
                logger.exception(f"Failed to load plugin {ep.name}: {e}")
        
        self._discovered = True
    
    def register_channel(self, channel: ChannelPlugin) -> None:
        """
        Register a channel plugin.
        
        Args:
            channel: Channel plugin instance implementing ChannelPlugin
        """
        if channel.id in self.channels:
            logger.warning(f"Channel {channel.id} already registered, overwriting")
        
        self.channels[channel.id] = channel
        logger.info(f"Channel registered: {channel.id} ({channel.label})")
    
    def get_channel(self, channel_id: str) -> Optional[ChannelPlugin]:
        """
        Get a registered channel by ID.
        
        Args:
            channel_id: Channel identifier (e.g., 'feishu', 'telegram')
            
        Returns:
            Channel plugin instance or None if not found
        """
        return self.channels.get(channel_id)
    
    def list_channels(self) -> Dict[str, str]:
        """
        List all registered channels.
        
        Returns:
            Dict mapping channel IDs to labels
        """
        return {cid: ch.label for cid, ch in self.channels.items()}
    
    def get_channel_config(self, channel_id: str) -> Dict:
        """
        Get configuration for a channel from environment.
        
        Configuration is read from environment variables with these prefixes
        (in order of priority):
        1. TASKNEXUS_PLUGIN_{CHANNEL_ID}_*  (e.g., TASKNEXUS_PLUGIN_FEISHU_APP_ID)
        2. {CHANNEL_ID}_*                    (e.g., FEISHU_APP_ID)
        
        Example:
            FEISHU_APP_ID -> config['app_id']
            TASKNEXUS_PLUGIN_FEISHU_APP_SECRET -> config['app_secret']
        
        Args:
            channel_id: Channel identifier
            
        Returns:
            Configuration dict for the channel
        """
        config = {}
        channel_upper = channel_id.upper()
        
        # Priority 1: Check TASKNEXUS_PLUGIN_{CHANNEL_ID}_* prefix
        prefix1 = f"TASKNEXUS_PLUGIN_{channel_upper}_"
        for key, value in os.environ.items():
            if key.startswith(prefix1):
                config_key = key[len(prefix1):].lower()
                config[config_key] = value
        
        # Priority 2: Check {CHANNEL_ID}_* prefix (only for keys not already set)
        prefix2 = f"{channel_upper}_"
        for key, value in os.environ.items():
            if key.startswith(prefix2):
                config_key = key[len(prefix2):].lower()
                if config_key not in config:
                    config[config_key] = value
        
        return config
