import json
import logging
import os
from datetime import datetime
from pathlib import Path
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger('django')

# Log directory for agent task logs
AGENT_LOG_DIR = Path(settings.BASE_DIR) / 'agent_logs'
AGENT_LOG_DIR.mkdir(exist_ok=True)


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
        elif message_type == 'task_heartbeat':
            await self.handle_task_heartbeat(content)
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
            # Create/clear log file
            await self._init_log_file(task_id)
            logger.info(f"Agent {self.agent.name} started task {task_id}")

    async def handle_task_progress(self, content):
        """Process task progress updates."""
        task_id = content.get('task_id')
        output = content.get('output', '')
        is_stderr = content.get('is_stderr', False)
        
        if task_id:
            # 更新心跳时间 — 日志输出本身就是活跃信号
            await self.update_agent_task_status(task_id, last_heartbeat=timezone.now())
            # Write to log file
            await self._append_log_file(task_id, output)
            # Broadcast to frontend log subscribers
            await self.channel_layer.group_send(
                f"agent_task_log_{task_id}",
                {
                    "type": "log_dispatch",
                    "line": output,
                    "is_stderr": is_stderr,
                }
            )

    async def handle_task_completed(self, content):
        """Process task completion notification."""
        task_id = content.get('task_id')
        exit_code = content.get('exit_code', 0)
        stderr = content.get('stderr', '')
        result = self._normalize_task_result(content.get('result'))
        
        if task_id:
            # Determine status based on exit code
            status = 'COMPLETED' if exit_code == 0 else 'FAILED'
            
            await self.update_agent_task_status(
                task_id,
                status=status,
                exit_code=exit_code,
                stderr=stderr,
                result=result,
                finished_at=timezone.now()
            )
            # Write final status to log file
            status_line = f"\n===== Task {status} (exit code: {exit_code}) ====="
            await self._append_log_file(task_id, status_line)
            # Notify frontend log subscribers that task is done
            await self.channel_layer.group_send(
                f"agent_task_log_{task_id}",
                {
                    "type": "log_dispatch",
                    "line": status_line,
                    "is_stderr": False,
                    "finished": True,
                    "exit_code": exit_code,
                }
            )
            logger.info(f"Agent {self.agent.name} completed task {task_id} with exit code {exit_code}")

    @staticmethod
    def _normalize_task_result(raw_result):
        if isinstance(raw_result, dict):
            return raw_result
        return {}

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
            # Write error to log file
            error_line = f"\n===== Task FAILED: {error} ====="
            await self._append_log_file(task_id, error_line)
            # Notify frontend
            await self.channel_layer.group_send(
                f"agent_task_log_{task_id}",
                {
                    "type": "log_dispatch",
                    "line": error_line,
                    "is_stderr": True,
                    "finished": True,
                }
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
            "client_repo_token": event.get("client_repo_token", ""),
            "execution_mode": event.get("execution_mode", "command"),
            "command": event["command"],
            "code": event.get("code", {}),
            "timeout": event.get("timeout", 3600),
            "environment": event.get("environment", {}),
        })

    async def task_cancel(self, event):
        """Send task cancel message to agent."""
        await self.send_json({
            "type": "task_cancel",
            "task_id": event["task_id"],
        })

    async def agent_update(self, event):
        """Send self-update instruction to agent."""
        await self.send_json({
            "type": "agent_update",
            "task_id": event["task_id"],
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
    

    async def handle_task_heartbeat(self, content):
        """Process task heartbeat from agent."""
        task_id = content.get('task_id')
        if task_id:
            await self.update_agent_task_status(
                task_id,
                last_heartbeat=timezone.now()
            )
            logger.debug(f"Received heartbeat for task {task_id} from agent {self.agent.name}")

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

    # ===== Log File Operations =====

    @staticmethod
    def _get_log_path(task_id):
        """Get the log file path for a given task."""
        return AGENT_LOG_DIR / f"task_{task_id}.log"

    @database_sync_to_async
    def _init_log_file(self, task_id):
        """Create or clear the log file for a task."""
        log_path = self._get_log_path(task_id)
        try:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"===== Task {task_id} started at {timezone.now().isoformat()} =====\n")
        except Exception as e:
            logger.error(f"Failed to init log file for task {task_id}: {e}")

    @database_sync_to_async
    def _append_log_file(self, task_id, content):
        """Append content to the log file for a task."""
        log_path = self._get_log_path(task_id)
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(content + '\n')
        except Exception as e:
            logger.error(f"Failed to append to log file for task {task_id}: {e}")
