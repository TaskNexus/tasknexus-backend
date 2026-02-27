"""
MCP Tool Bridge

Bridges MCP tools to OpenAI function-calling format.
Reads project config to discover MCP servers,
fetches their tools (with caching), and converts them.

Provides persistent MCP connections for efficient multi-call sessions.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from .mcp_client import MCPClient

logger = logging.getLogger('django')

# Module-level cache for tool lists: {server_url: {"tools": [...], "expire": timestamp}}
_tools_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 300  # 5 minutes


class MCPToolBridge:
    """
    Fetches tools from all configured MCP servers for a project
    and provides unified tool calling interface.
    
    Supports two modes:
    - Discovery: get_mcp_tools() uses cached tool lists (one-shot connections)
    - Execution: connect()/close() manages persistent connections for tool calls
    """
    
    def __init__(self):
        self._server_configs: Dict[str, Dict] = {}
        # Persistent connections for tool calls (created on connect())
        self._connected_clients: Dict[str, MCPClient] = {}
        self._is_connected = False
    
    # --- Context Manager ---
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    
    # --- Tool Discovery (with caching) ---
    
    def get_mcp_tools(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Get all MCP tools from enabled servers configured in the project.
        Uses a module-level cache to avoid repeated SSE connections.
        
        Args:
            project_id: The project ID
            
        Returns:
            List of tool definitions in OpenAI function-calling format
        """
        from projects.models import Project
        
        try:
            project = Project.objects.get(id=project_id)
            extra_config = project.extra_config or {}
            mcp_servers = extra_config.get('mcp_servers', [])
        except Project.DoesNotExist:
            logger.warning(f"Project {project_id} not found for MCP tools")
            return []
        
        all_tools = []
        now = time.time()
        
        for server_config in mcp_servers:
            if not server_config.get('enabled', True):
                continue
                
            server_id = server_config.get('id', '')
            server_url = server_config.get('url', '')
            
            if not server_id or not server_url:
                continue
            
            # Store config for later use by call_tool
            self._server_configs[server_id] = server_config
            
            try:
                # Check cache
                cached = _tools_cache.get(server_url)
                if cached and cached['expire'] > now:
                    mcp_tools = cached['tools']
                    logger.debug(f"MCP tools cache hit for '{server_id}' ({len(mcp_tools)} tools)")
                else:
                    # Cache miss — fetch via one-shot connection
                    client = MCPClient(server_url)
                    mcp_tools = client.list_tools()
                    _tools_cache[server_url] = {
                        'tools': mcp_tools,
                        'expire': now + _CACHE_TTL
                    }
                    logger.info(
                        f"Loaded {len(mcp_tools)} tools from MCP server "
                        f"'{server_config.get('name', server_id)}' ({server_url})"
                    )
                
                openai_tools = self._to_openai_format(mcp_tools, server_id)
                all_tools.extend(openai_tools)
                
            except Exception as e:
                logger.error(
                    f"Failed to load tools from MCP server '{server_id}': {e}"
                )
        
        return all_tools
    
    # --- Skill-based Tool Filtering ---
    
    # Only read_skill stays as MCP meta-tool (list_skills/activate_skill are now built-in)
    SKILL_META_TOOLS = {'read_skill'}
    
    def get_mcp_tools_by_skill(self, project_id: int):
        """
        Get MCP tools split into meta-tools and content tools.
        
        Meta-tools (list_skills, read_skill, activate_skill) are always
        sent to the AI. Content tools (browser_*, etc.) are held back
        and only injected when the AI calls activate_skill.
        
        Args:
            project_id: The project ID
            
        Returns:
            Tuple of (meta_tools, content_tools_pool)
            - meta_tools: list of tool defs to include initially
            - content_tools_pool: dict of full_name -> tool_def (held back)
        """
        all_tools = self.get_mcp_tools(project_id)
        
        meta_tools = []
        content_pool = {}
        
        for tool_def in all_tools:
            func_name = tool_def.get('function', {}).get('name', '')
            base_name = func_name.split('__', 1)[1] if '__' in func_name else func_name
            if base_name in self.SKILL_META_TOOLS:
                meta_tools.append(tool_def)
            else:
                content_pool[func_name] = tool_def
        
        # Store pool for activate_skill_tools()
        self._content_tools_pool = content_pool
        
        logger.info(
            f"Skill mode: {len(meta_tools)} meta tools, "
            f"{len(content_pool)} content tools held back"
        )
        
        return meta_tools, content_pool
    
    def activate_skill_tools(self, tool_names: list) -> List[Dict[str, Any]]:
        """
        Get tool definitions for activated skill tools.
        
        Args:
            tool_names: Base tool names from activate_skill response
                        (e.g. ['browser_open', 'browser_close', ...])
        
        Returns:
            List of tool definitions to inject into the active tools list
        """
        pool = getattr(self, '_content_tools_pool', {})
        activated = []
        
        for full_name, tool_def in pool.items():
            base_name = full_name.split('__', 1)[1] if '__' in full_name else full_name
            if base_name in tool_names:
                activated.append(tool_def)
        
        return activated
    
    # --- Persistent Connection for Tool Calls ---
    
    def connect(self):
        """
        Establish persistent SSE connections to all configured MCP servers.
        Call this before the multi-turn tool call loop in chat_service.
        """
        for server_id, config in self._server_configs.items():
            if not config.get('enabled', True):
                continue
            try:
                client = MCPClient(config['url'])
                client.connect()
                self._connected_clients[server_id] = client
                logger.info(f"MCP persistent connection established for '{server_id}'")
            except Exception as e:
                logger.error(f"Failed to connect to MCP server '{server_id}': {e}")
        self._is_connected = True
    
    def close(self):
        """Close all persistent MCP connections."""
        for server_id, client in self._connected_clients.items():
            try:
                client.close()
            except Exception as e:
                logger.debug(f"Error closing MCP client '{server_id}': {e}")
        self._connected_clients.clear()
        self._is_connected = False
    
    def call_tool(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Call a tool on a specific MCP server.
        Uses persistent connection if available, falls back to one-shot.
        
        Args:
            server_id: MCP server identifier
            tool_name: Name of the tool on the MCP server
            arguments: Tool arguments
            
        Returns:
            Tool result as string
        """
        # Try persistent connection first
        connected_client = self._connected_clients.get(server_id)
        if connected_client:
            try:
                return connected_client.call_tool_connected(tool_name, arguments)
            except Exception as e:
                logger.warning(
                    f"Persistent MCP call failed for '{server_id}', "
                    f"falling back to one-shot: {e}"
                )
        
        # Fallback to one-shot connection
        config = self._server_configs.get(server_id)
        if not config:
            return json.dumps({"error": f"MCP server '{server_id}' not found"})
        
        client = MCPClient(config['url'])
        return client.call_tool(tool_name, arguments)
    
    # --- Format Conversion ---
    
    def _to_openai_format(
        self, mcp_tools: List[Dict[str, Any]], server_id: str
    ) -> List[Dict[str, Any]]:
        """
        Convert MCP tool definitions to OpenAI function-calling format.
        
        Tool names are prefixed with server_id to avoid conflicts:
        e.g., "browser_open" -> "browser__browser_open"
        """
        openai_tools = []
        
        for tool in mcp_tools:
            tool_name = tool.get('name', '')
            if not tool_name:
                continue
            
            input_schema = tool.get('inputSchema', {})
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}, "required": []}
            
            # Remove session_id from properties (we inject it server-side)
            properties = input_schema.get('properties', {})
            properties.pop('session_id', None)
            required = [r for r in input_schema.get('required', []) if r != 'session_id']
            
            openai_tool = {
                "type": "function",
                "function": {
                    "name": f"{server_id}__{tool_name}",
                    "description": tool.get('description', ''),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            }
            
            openai_tools.append(openai_tool)
        
        return openai_tools
