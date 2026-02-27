"""
MCP Management Views

Provides API endpoints for testing MCP server connections.
"""

import json
import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

logger = logging.getLogger('django')


class MCPTestConnectionView(APIView):
    """
    Test connection to an MCP Server.
    
    POST /api/mcp/test/
    Body: {"url": "http://mcp-browser:3001"}
    Returns: {"success": true, "tools": [...]}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        server_url = request.data.get('url', '')
        if not server_url:
            return Response(
                {'detail': 'MCP Server URL is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            from agents.mcp.mcp_client import MCPClient
            
            client = MCPClient(server_url, timeout=10)
            tools = client.list_tools()
            
            return Response({
                'success': True,
                'tools_count': len(tools),
                'tools': [
                    {
                        'name': t.get('name', ''),
                        'description': t.get('description', '')[:100],
                    }
                    for t in tools
                ]
            })
            
        except Exception as e:
            logger.exception(f"MCP connection test failed for {server_url}")
            return Response({
                'success': False,
                'error': str(e),
            }, status=status.HTTP_200_OK)  # 200 with success=false for UI handling
