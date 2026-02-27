"""
MCP Client

Communicates with MCP Servers via SSE (Server-Sent Events) transport.
Uses httpx for HTTP connections with threading for concurrent SSE reading.

Supports two modes:
1. One-shot: list_tools() / call_tool() each create a temporary connection
2. Persistent: connect() → multiple call_tool_connected() → close()

MCP SSE Protocol:
1. GET /sse  -> Opens SSE stream, receives "endpoint" event with messages URL
2. POST /messages?sessionId=xxx -> Sends JSON-RPC requests  
3. Responses come back on the SAME SSE stream (not as HTTP responses)
"""

import json
import logging
import threading
import queue
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger('django')


class MCPClient:
    """
    Client for communicating with MCP Servers over SSE transport.
    
    Usage (one-shot):
        client = MCPClient(url)
        tools = client.list_tools()
        
    Usage (persistent, for multi-call sessions):
        with MCPClient(url) as client:
            client.call_tool_connected("browser_open", {"url": "..."})
            client.call_tool_connected("browser_snapshot", {})
    """
    
    def __init__(self, server_url: str, timeout: int = 30):
        # Strip /sse suffix if provided — we add it ourselves
        self.server_url = server_url.rstrip('/').removesuffix('/sse')
        self.timeout = timeout
        
        # Persistent connection state
        self._connected = False
        self._message_url: Optional[str] = None
        self._result_queue: Optional[queue.Queue] = None
        self._stop_event: Optional[threading.Event] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._http_client: Optional[httpx.Client] = None
        self._next_id = 1
        self._lock = threading.Lock()
    
    # --- Context Manager ---
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
    
    # --- Persistent Connection ---
    
    def connect(self):
        """
        Establish a persistent SSE connection and perform MCP handshake.
        After this, use call_tool_connected() for efficient multi-call sessions.
        """
        if self._connected:
            return
        
        self._result_queue = queue.Queue()
        self._stop_event = threading.Event()
        message_url_queue = queue.Queue()
        
        # Start SSE reader
        self._reader_thread = self._start_sse_reader(
            self._result_queue, message_url_queue, self._stop_event
        )
        
        # Wait for endpoint
        self._message_url = message_url_queue.get(timeout=self.timeout)
        if self._message_url is None:
            raise ConnectionError("Failed to get message endpoint from MCP server")
        
        self._http_client = httpx.Client(timeout=self.timeout)
        
        # Initialize handshake
        self._next_id = 1
        self._http_client.post(self._message_url, json={
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "tasknexus", "version": "1.0.0"}
            }
        })
        
        init_resp = self._wait_response(self._result_queue, self._next_id, timeout=10)
        if not init_resp:
            self.close()
            raise ConnectionError("MCP server initialize failed")
        
        # Send initialized notification
        self._http_client.post(self._message_url, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        })
        time.sleep(0.1)
        
        self._next_id = 2
        self._connected = True
        logger.info(f"MCP persistent connection established to {self.server_url}")
    
    def close(self):
        """Close the persistent SSE connection."""
        self._connected = False
        if self._stop_event:
            self._stop_event.set()
        if self._http_client:
            try:
                self._http_client.close()
            except Exception:
                pass
            self._http_client = None
        if self._reader_thread:
            self._reader_thread.join(timeout=3)
            self._reader_thread = None
        self._message_url = None
        self._result_queue = None
    
    def call_tool_connected(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Call a tool using the persistent connection.
        Must call connect() first or use context manager.
        """
        if not self._connected or not self._http_client:
            raise RuntimeError("Not connected. Call connect() first or use context manager.")
        
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
        
        self._http_client.post(self._message_url, json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        })
        
        tool_resp = self._wait_response(self._result_queue, req_id, timeout=self.timeout)
        
        if tool_resp and "result" in tool_resp:
            content = tool_resp["result"].get("content", [])
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else json.dumps(tool_resp["result"])
        elif tool_resp and "error" in tool_resp:
            return json.dumps({"error": tool_resp["error"]})
        
        return json.dumps({"error": "No response from MCP server"})
    
    # --- One-shot Methods (backwards compatible) ---
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Get the list of available tools (one-shot connection).
        Creates a temporary SSE connection, fetches tools, then closes.
        """
        result_queue = queue.Queue()
        message_url_queue = queue.Queue()
        stop_event = threading.Event()
        
        reader_thread = self._start_sse_reader(result_queue, message_url_queue, stop_event)
        
        try:
            message_url = message_url_queue.get(timeout=self.timeout)
            if message_url is None:
                logger.error("Failed to get message endpoint from SSE")
                return []
            
            with httpx.Client(timeout=self.timeout) as client:
                # Initialize
                client.post(message_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "tasknexus", "version": "1.0.0"}
                    }
                })
                
                init_resp = self._wait_response(result_queue, expected_id=1, timeout=10)
                if not init_resp:
                    logger.error("No initialize response from MCP server")
                    return []
                
                # Initialized notification
                client.post(message_url, json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {}
                })
                time.sleep(0.1)
                
                # List tools
                client.post(message_url, json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {}
                })
                
                tools_resp = self._wait_response(result_queue, expected_id=2, timeout=10)
                if tools_resp and "result" in tools_resp:
                    tools = tools_resp["result"].get("tools", [])
                    logger.info(f"Got {len(tools)} tools from MCP server")
                    return tools
                
                logger.warning(f"No tools/list response: {tools_resp}")
                return []
                    
        except Exception as e:
            logger.exception(f"Failed to list tools from MCP server {self.server_url}: {e}")
            return []
        finally:
            stop_event.set()
            reader_thread.join(timeout=3)

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Call a tool (one-shot connection).
        For multi-call sessions, use connect() + call_tool_connected() instead.
        """
        result_queue = queue.Queue()
        message_url_queue = queue.Queue()
        stop_event = threading.Event()
        
        reader_thread = self._start_sse_reader(result_queue, message_url_queue, stop_event)
        
        try:
            message_url = message_url_queue.get(timeout=self.timeout)
            if message_url is None:
                return json.dumps({"error": "Failed to connect to MCP server"})
            
            with httpx.Client(timeout=self.timeout) as client:
                # Initialize
                client.post(message_url, json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "tasknexus", "version": "1.0.0"}
                    }
                })
                
                init_resp = self._wait_response(result_queue, expected_id=1, timeout=10)
                if not init_resp:
                    return json.dumps({"error": "MCP server initialize failed"})
                
                client.post(message_url, json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {}
                })
                time.sleep(0.1)
                
                # Call tool
                client.post(message_url, json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": arguments
                    }
                })
                
                tool_resp = self._wait_response(result_queue, expected_id=2, timeout=self.timeout)
                
                if tool_resp and "result" in tool_resp:
                    content = tool_resp["result"].get("content", [])
                    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                    return "\n".join(texts) if texts else json.dumps(tool_resp["result"])
                elif tool_resp and "error" in tool_resp:
                    return json.dumps({"error": tool_resp["error"]})
                
                return json.dumps({"error": "No response from MCP server"})
                
        except httpx.TimeoutException:
            return json.dumps({"error": f"MCP server timeout ({self.timeout}s)"})
        except Exception as e:
            logger.exception(f"Failed to call MCP tool {tool_name}: {e}")
            return json.dumps({"error": str(e)})
        finally:
            stop_event.set()
            reader_thread.join(timeout=3)
    
    # --- Internal Helpers ---
    
    def _start_sse_reader(self, result_queue, message_url_queue, stop_event):
        """Start a background thread to read SSE events."""
        
        def sse_reader():
            try:
                with httpx.Client(timeout=httpx.Timeout(self.timeout * 3, connect=10)) as client:
                    with client.stream("GET", f"{self.server_url}/sse") as response:
                        event_type = None
                        for line in response.iter_lines():
                            if stop_event.is_set():
                                break
                            
                            if line.startswith("event: "):
                                event_type = line[7:].strip()
                                continue
                            
                            if line.startswith("data: "):
                                data = line[6:]
                                
                                if event_type == "endpoint":
                                    full_url = f"{self.server_url}{data}" if data.startswith("/") else data
                                    message_url_queue.put(full_url)
                                    event_type = None
                                    continue
                                
                                if event_type == "message":
                                    try:
                                        parsed = json.loads(data)
                                        if "id" in parsed:
                                            result_queue.put(parsed)
                                    except json.JSONDecodeError:
                                        pass
                                    event_type = None
                                    continue
                                
                                # Fallback
                                try:
                                    parsed = json.loads(data)
                                    if "id" in parsed:
                                        result_queue.put(parsed)
                                except json.JSONDecodeError:
                                    if "/messages" in data and message_url_queue.empty():
                                        full_url = f"{self.server_url}{data}" if data.startswith("/") else data
                                        message_url_queue.put(full_url)
                                
                                event_type = None
                            
                            if not line:
                                event_type = None
                                
            except Exception as e:
                logger.debug(f"SSE reader ended: {e}")
            finally:
                if message_url_queue.empty():
                    message_url_queue.put(None)
        
        thread = threading.Thread(target=sse_reader, daemon=True)
        thread.start()
        return thread

    def _wait_response(self, result_queue, expected_id, timeout=10):
        """Wait for a specific response ID from the result queue."""
        deadline = time.time() + timeout
        stashed = []
        try:
            while time.time() < deadline:
                try:
                    data = result_queue.get(timeout=1)
                    if data.get("id") == expected_id:
                        return data
                    stashed.append(data)
                except queue.Empty:
                    continue
            return None
        finally:
            # Put back any items that weren't for us
            for item in stashed:
                result_queue.put(item)
