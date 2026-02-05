"""
Tool Executor Service

Handles the execution of tools called by the AI agent.
"""

import json
import logging
import inspect
from typing import Any, Dict, List, Optional, Union

from ..tools.handlers import available_functions

logger = logging.getLogger('django')


class ToolExecutor:
    """
    Executes tools requested by the AI.
    """
    
    def __init__(self, project_id: int, user: Any):
        self.project_id = project_id
        self.user = user
        self.functions = available_functions

    def execute_calls(self, tool_calls: List[Any]) -> List[Dict[str, Any]]:
        """
        Execute a list of tool calls and return the results.
        
        Args:
            tool_calls: List of tool call objects from the AI client
            
        Returns:
            List of tool result dictionaries ready for context injection
        """
        results = []
        
        for tool_call in tool_calls:
            # Handle different tool call formats (object vs dict)
            if hasattr(tool_call, 'function'):
                function_name = tool_call.function.name
                arguments_str = tool_call.function.arguments
                tool_call_id = tool_call.id
            elif isinstance(tool_call, dict):
                function_name = tool_call.get('function', {}).get('name')
                arguments_str = tool_call.get('function', {}).get('arguments')
                tool_call_id = tool_call.get('id')
            else:
                logger.error(f"Unknown tool call format: {tool_call}")
                continue
                
            try:
                # Parse arguments
                function_args = json.loads(arguments_str) if isinstance(arguments_str, str) else (arguments_str or {})
            except json.JSONDecodeError:
                function_args = {}
                
            logger.info(f"Executing tool: {function_name} with args: {function_args}")
            
            # Execute
            response_content = self._execute_single(function_name, function_args)
            
            # Format result
            results.append({
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": function_name,
                "content": str(response_content),
            })
            
        return results

    def _execute_single(self, function_name: str, args: Dict[str, Any]) -> str:
        """Execute a single function with context injection."""
        function_to_call = self.functions.get(function_name)
        
        if not function_to_call:
            return f"Error: Function {function_name} not found"
            
        # Inject context parameters if required by signature
        sig = inspect.signature(function_to_call)
        
        if 'project_id' in sig.parameters:
            args['project_id'] = self.project_id
            
        if 'user' in sig.parameters:
            args['user'] = self.user
            
        try:
            result = function_to_call(**args)
            
            # Standardize output for list/queryset
            if hasattr(result, 'values') and not isinstance(result, dict):
                # It's a queryset
                result = list(result.values('id', 'name', 'description'))
                
            return json.dumps(result, default=str)
            
        except Exception as e:
            logger.exception(f"Tool execution failed: {function_name}")
            return f"Error executing function: {str(e)}"
