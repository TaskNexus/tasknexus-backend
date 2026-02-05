import json
import logging
from datetime import datetime
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone

logger = logging.getLogger('django')


class AgentConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for client agent communication.
    
    Handles:
    - Agent authentication via name
    - Heartbeat messages
    - Task dispatch and result collection
    """
    
    agent = None
    agent_group = None

    async def connect(self):
        """
        Handle WebSocket connection.
        Authenticate agent via name in query string.
        """
        # Get name from query string
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        params = dict(p.split('=') for p in query_string.split('&') if '=' in p)
        name = params.get('name', '')
        
        if not name:
            logger.warning("Agent connection rejected: no name provided")
            await self.close(code=4001)
            return
        
        # Get or create agent by name
        self.agent = await self.get_or_create_agent_by_name(name)
        if not self.agent:
            logger.warning(f"Agent connection rejected: could not get/create agent {name}")
            await self.close(code=4002)
            return
        
        # Accept connection
        await self.accept()
        
        # Update agent status
        await self.update_agent_status('ONLINE')
        
        # Join agent-specific group for targeted task dispatch
        self.agent_group = f"agent_{self.agent.id}"
        await self.channel_layer.group_add(self.agent_group, self.channel_name)
        
        # Join global agents group for broadcasts
        await self.channel_layer.group_add("all_agents", self.channel_name)
        
        logger.info(f"Agent connected: {self.agent.name} (ID: {self.agent.id})")
        
        # Send welcome message
        await self.send_json({
            "type": "connected",
            "agent_id": self.agent.id,
            "agent_name": self.agent.name,
            "message": "Successfully connected to TaskNexus"
        })

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if self.agent:
            await self.update_agent_status('OFFLINE')
            
            # Leave groups
            if self.agent_group:
                await self.channel_layer.group_discard(self.agent_group, self.channel_name)
            await self.channel_layer.group_discard("all_agents", self.channel_name)
            
            logger.info(f"Agent disconnected: {self.agent.name} (code: {close_code})")

    async def receive_json(self, content):
        """Handle incoming JSON messages from agent."""
        message_type = content.get('type', '')
        
        if message_type == 'heartbeat':
            await self.handle_heartbeat(content)
        elif message_type == 'task_started':
            await self.handle_task_started(content)
        elif message_type == 'task_progress':
            await self.handle_task_progress(content)
        elif message_type == 'task_completed':
            await self.handle_task_completed(content)
        elif message_type == 'task_failed':
            await self.handle_task_failed(content)
        else:
            logger.warning(f"Unknown message type from agent {self.agent.name}: {message_type}")

    async def handle_heartbeat(self, content):
        """Process heartbeat message from agent."""
        system_info = content.get('system_info', {})
        
        await self.update_agent_heartbeat(system_info)
        
        # Acknowledge heartbeat
        await self.send_json({
            "type": "heartbeat_ack",
            "server_time": timezone.now().isoformat()
        })

    async def handle_task_started(self, content):
        """Process task started notification."""
        task_id = content.get('task_id')
        if task_id:
            await self.update_agent_task_status(
                task_id, 
                status='RUNNING',
                started_at=timezone.now()
            )
            logger.info(f"Agent {self.agent.name} started task {task_id}")

    async def handle_task_progress(self, content):
        """Process task progress updates."""
        task_id = content.get('task_id')
        output = content.get('output', '')
        
        if task_id:
            await self.append_agent_task_output(task_id, output)

    async def handle_task_completed(self, content):
        """Process task completion notification."""
        task_id = content.get('task_id')
        exit_code = content.get('exit_code', 0)
        stdout = content.get('stdout', '')
        stderr = content.get('stderr', '')
        
        if task_id:
            # Determine status based on exit code
            status = 'COMPLETED' if exit_code == 0 else 'FAILED'
            
            await self.update_agent_task_status(
                task_id,
                status=status,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                result={'exit_code': exit_code},
                finished_at=timezone.now()
            )
            logger.info(f"Agent {self.agent.name} completed task {task_id} with exit code {exit_code}")

    async def handle_task_failed(self, content):
        """Process task failure notification."""
        task_id = content.get('task_id')
        error = content.get('error', 'Unknown error')
        
        if task_id:
            await self.update_agent_task_status(
                task_id,
                status='FAILED',
                error_message=error,
                finished_at=timezone.now()
            )
            logger.error(f"Agent {self.agent.name} failed task {task_id}: {error}")

    # ===== Channel Layer Message Handlers =====
    
    async def task_dispatch(self, event):
        """Send task dispatch message to agent."""
        await self.send_json({
            "type": "task_dispatch",
            "task_id": event["task_id"],
            "workspace_name": event.get("workspace_name", ""),
            "client_repo_url": event.get("client_repo_url", ""),
            "client_repo_ref": event.get("client_repo_ref", "main"),
            "command": event["command"],
            "timeout": event.get("timeout", 3600),
            "environment": event.get("environment", {}),
        })

    # ===== AgentTask Database Operations =====
    
    @database_sync_to_async
    def update_agent_task_status(self, task_id, **kwargs):
        """Update AgentTask status and fields in database."""
        from .models import AgentTask
        try:
            AgentTask.objects.filter(id=task_id).update(**kwargs)
            logger.info(f"Updated AgentTask {task_id}: {list(kwargs.keys())}")
        except Exception as e:
            logger.error(f"Failed to update AgentTask {task_id}: {e}")
    
    @database_sync_to_async
    def append_agent_task_output(self, task_id, output):
        """Append output to AgentTask stdout."""
        from .models import AgentTask
        from django.db.models import F
        from django.db.models.functions import Concat
        from django.db.models import Value
        try:
            AgentTask.objects.filter(id=task_id).update(
                stdout=Concat(F('stdout'), Value(output))
            )
        except Exception as e:
            logger.error(f"Failed to append output to AgentTask {task_id}: {e}")

    # ===== Database Operations =====
    
    @database_sync_to_async
    def get_or_create_agent_by_name(self, name):
        """Get agent by name, creating if it doesn't exist."""
        from .models import ClientAgent
        try:
            agent, created = ClientAgent.objects.get_or_create(
                name=name,
                defaults={'status': 'OFFLINE'}
            )
            if created:
                logger.info(f"Created new agent: {name}")
            return agent
        except Exception as e:
            logger.error(f"Error getting/creating agent {name}: {e}")
            return None

    @database_sync_to_async
    def update_agent_status(self, status):
        """Update agent online/offline status."""
        from .models import ClientAgent
        if self.agent:
            ClientAgent.objects.filter(id=self.agent.id).update(
                status=status,
                last_heartbeat=timezone.now() if status == 'ONLINE' else None
            )

    @database_sync_to_async
    def update_agent_heartbeat(self, system_info):
        """Update agent heartbeat and system info."""
        from .models import ClientAgent
        if self.agent:
            update_fields = {
                'last_heartbeat': timezone.now(),
                'status': 'ONLINE',
            }
            if system_info:
                if 'hostname' in system_info:
                    update_fields['hostname'] = system_info['hostname']
                if 'platform' in system_info:
                    update_fields['platform'] = system_info['platform']
                if 'ip_address' in system_info:
                    update_fields['ip_address'] = system_info['ip_address']
                if 'agent_version' in system_info:
                    update_fields['agent_version'] = system_info['agent_version']
            
            ClientAgent.objects.filter(id=self.agent.id).update(**update_fields)
