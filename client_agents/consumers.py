import logging
from pathlib import Path
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django.conf import settings

from .log_state import clear_active_line, set_active_line

logger = logging.getLogger('django')

# Log directory for agent task logs
AGENT_LOG_DIR = Path(settings.BASE_DIR) / 'agent_logs'
AGENT_LOG_DIR.mkdir(exist_ok=True)
TASK_LOG_HEARTBEAT_INTERVAL_SECONDS = 5


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
        self._task_log_stream_states = {}
        self._task_log_heartbeat_at = {}
        
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
        elif message_type == 'task_log_append':
            await self.handle_task_log_append(content)
        elif message_type == 'task_log_active':
            await self.handle_task_log_active(content)
        elif message_type == 'task_log_active_clear':
            await self.handle_task_log_active_clear(content)
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
        task_id = self._to_int(content.get('task_id'))
        if task_id:
            await self.update_agent_task_status(
                task_id, 
                status='RUNNING',
                started_at=timezone.now()
            )
            # Create/clear log file
            await self._init_log_file(task_id)
            await self._clear_active_line_state(task_id)
            self._reset_task_log_state(task_id)
            self._clear_task_heartbeat_marker(task_id)
            logger.info(f"Agent {self.agent.name} started task {task_id}")

    async def handle_task_progress(self, content):
        """Process task progress updates."""
        task_id = self._to_int(content.get('task_id'))
        output = content.get('output', '')
        is_stderr = content.get('is_stderr', False)
        
        if task_id and output is not None:
            # 更新心跳时间 — 日志输出本身就是活跃信号
            await self._refresh_task_heartbeat_if_due(task_id)
            await self._process_task_output(task_id, str(output), bool(is_stderr))

    async def handle_task_log_append(self, content):
        """Append a committed log chunk to the backend log file."""
        task_id = self._to_int(content.get('task_id'))
        start_offset = self._to_int(content.get('start_offset'))
        chunk = content.get('content', '')

        if not task_id or start_offset is None or chunk is None:
            return

        await self._refresh_task_heartbeat_if_due(task_id)
        append_result = await self._append_log_chunk(task_id, start_offset, str(chunk))
        if append_result.get('appended'):
            await self._broadcast_log_file_update(
                task_id=task_id,
                file_size=append_result.get('file_size', 0),
            )

    async def handle_task_log_active(self, content):
        """Store and broadcast the current active line."""
        task_id = self._to_int(content.get('task_id'))
        seq = self._to_int(content.get('seq'))
        base_offset = self._to_int(content.get('base_offset'))
        line = content.get('line', '')

        if not task_id or seq is None or base_offset is None or line is None:
            return

        await self._refresh_task_heartbeat_if_due(task_id)
        payload = {
            "task_id": task_id,
            "seq": seq,
            "base_offset": base_offset,
            "line": str(line),
            "is_stderr": bool(content.get('is_stderr', False)),
            "updated_at": timezone.now().isoformat(),
        }
        await self._set_active_line_state(task_id, payload)
        await self.channel_layer.group_send(
            f"agent_task_log_{task_id}",
            {
                "type": "log_active",
                "seq": seq,
                "base_offset": base_offset,
                "line": payload["line"],
                "is_stderr": payload["is_stderr"],
            },
        )

    async def handle_task_log_active_clear(self, content):
        """Clear the shared active line state."""
        task_id = self._to_int(content.get('task_id'))
        seq = self._to_int(content.get('seq'))
        base_offset = self._to_int(content.get('base_offset'))

        if not task_id or seq is None or base_offset is None:
            return

        await self._clear_active_line_state(task_id)
        await self.channel_layer.group_send(
            f"agent_task_log_{task_id}",
            {
                "type": "log_active_clear",
                "seq": seq,
                "base_offset": base_offset,
            },
        )

    async def handle_task_completed(self, content):
        """Process task completion notification."""
        task_id = self._to_int(content.get('task_id'))
        exit_code = content.get('exit_code', 0)
        stderr = content.get('stderr', '')
        result = self._normalize_task_result(content.get('result'))
        
        if task_id:
            await self._flush_pending_log_line(task_id)
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
            await self._clear_active_line_state(task_id)
            # Write final status to log file
            status_line = f"===== Task {status} (exit code: {exit_code}) ====="
            file_size = await self._append_log_file(task_id, status_line + '\n')
            await self._broadcast_log_file_update(
                task_id=task_id,
                file_size=file_size or 0,
                task_status=status,
                finished=True,
                exit_code=exit_code,
            )
            self._clear_task_log_state(task_id)
            self._clear_task_heartbeat_marker(task_id)
            logger.info(f"Agent {self.agent.name} completed task {task_id} with exit code {exit_code}")

    @staticmethod
    def _normalize_task_result(raw_result):
        if isinstance(raw_result, dict):
            return raw_result
        return {}

    async def handle_task_failed(self, content):
        """Process task failure notification."""
        task_id = self._to_int(content.get('task_id'))
        error = content.get('error', 'Unknown error')
        
        if task_id:
            await self._flush_pending_log_line(task_id)
            await self.update_agent_task_status(
                task_id,
                status='FAILED',
                error_message=error,
                finished_at=timezone.now()
            )
            await self._clear_active_line_state(task_id)
            # Write error to log file
            error_line = f"===== Task FAILED: {error} ====="
            file_size = await self._append_log_file(task_id, error_line + '\n')
            await self._broadcast_log_file_update(
                task_id=task_id,
                file_size=file_size or 0,
                task_status='FAILED',
                finished=True,
            )
            self._clear_task_log_state(task_id)
            self._clear_task_heartbeat_marker(task_id)
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
            "prepare_repo_before_execute": event.get("prepare_repo_before_execute", False),
            "cleanup_workspace_on_success": event.get("cleanup_workspace_on_success", False),
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

    @staticmethod
    def _to_int(value, default=None):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    async def _refresh_task_heartbeat_if_due(self, task_id):
        if not hasattr(self, '_task_log_heartbeat_at'):
            self._task_log_heartbeat_at = {}
        now = timezone.now()
        task_key = int(task_id)
        last = self._task_log_heartbeat_at.get(task_key)
        if last is not None and (now - last).total_seconds() < TASK_LOG_HEARTBEAT_INTERVAL_SECONDS:
            return

        await self.update_agent_task_status(task_id, last_heartbeat=now)
        self._task_log_heartbeat_at[task_key] = now

    def _clear_task_heartbeat_marker(self, task_id):
        if not hasattr(self, '_task_log_heartbeat_at'):
            self._task_log_heartbeat_at = {}
        self._task_log_heartbeat_at.pop(int(task_id), None)

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
            with open(log_path, 'wb') as f:
                f.write(b'')
        except Exception as e:
            logger.error(f"Failed to init log file for task {task_id}: {e}")

    @database_sync_to_async
    def _append_log_file(self, task_id, content):
        """Append raw content to the log file for a task."""
        log_path = self._get_log_path(task_id)
        try:
            with open(log_path, 'ab') as f:
                f.write(content.encode('utf-8'))
            return log_path.stat().st_size
        except Exception as e:
            logger.error(f"Failed to append to log file for task {task_id}: {e}")
        return None

    @database_sync_to_async
    def _append_log_chunk(self, task_id, start_offset, content):
        log_path = self._get_log_path(task_id)
        try:
            current_size = log_path.stat().st_size if log_path.exists() else 0
            if current_size != int(start_offset):
                logger.warning(
                    "Rejected log append for task %s due to offset mismatch: expected=%s actual=%s",
                    task_id,
                    start_offset,
                    current_size,
                )
                return {"appended": False, "file_size": current_size}

            with open(log_path, 'ab') as f:
                f.write(content.encode('utf-8'))
            return {"appended": True, "file_size": log_path.stat().st_size}
        except Exception as e:
            logger.error(f"Failed to append log chunk for task {task_id}: {e}")
        return {"appended": False, "file_size": 0}

    @database_sync_to_async
    def _set_active_line_state(self, task_id, payload):
        set_active_line(task_id, payload)

    @database_sync_to_async
    def _clear_active_line_state(self, task_id):
        clear_active_line(task_id)

    def _reset_task_log_state(self, task_id):
        task_key = int(task_id)
        self._task_log_stream_states[task_key] = {
            'line_buffer': '',
            'line_is_stderr': False,
            'frontend_active': False,
            'frontend_line': '',
            'frontend_is_stderr': False,
        }

    def _get_task_log_state(self, task_id):
        task_key = int(task_id)
        if not hasattr(self, '_task_log_stream_states'):
            self._task_log_stream_states = {}
        if task_key not in self._task_log_stream_states:
            self._reset_task_log_state(task_key)
        return self._task_log_stream_states[task_key]

    def _clear_task_log_state(self, task_id):
        if not hasattr(self, '_task_log_stream_states'):
            return
        self._task_log_stream_states.pop(int(task_id), None)

    @staticmethod
    def _is_frontend_line_changed(state, line, is_stderr):
        if not state['frontend_active']:
            return True
        return state['frontend_line'] != line or state['frontend_is_stderr'] != is_stderr

    async def _dispatch_log_line(
        self,
        task_id,
        line,
        is_stderr,
        replace_last,
        line_complete,
        finished=False,
        exit_code=None,
    ):
        payload = {
            "type": "log_dispatch",
            "line": line,
            "is_stderr": is_stderr,
            "replace_last": replace_last,
            "line_complete": line_complete,
        }
        if finished:
            payload["finished"] = True
        if exit_code is not None:
            payload["exit_code"] = exit_code

        await self.channel_layer.group_send(
            f"agent_task_log_{task_id}",
            payload
        )

    async def _broadcast_log_file_update(
        self,
        task_id,
        file_size,
        task_status=None,
        finished=False,
        exit_code=None,
    ):
        payload = {
            "type": "log_file_update",
            "file_size": file_size,
        }
        if task_status:
            payload["task_status"] = task_status
        if finished:
            payload["finished"] = True
        if exit_code is not None:
            payload["exit_code"] = exit_code

        await self.channel_layer.group_send(
            f"agent_task_log_{task_id}",
            payload,
        )

    async def _emit_incomplete_line(self, task_id, state, line, is_stderr):
        await self._dispatch_log_line(
            task_id=task_id,
            line=line,
            is_stderr=is_stderr,
            replace_last=state['frontend_active'],
            line_complete=False,
        )
        state['frontend_active'] = True
        state['frontend_line'] = line
        state['frontend_is_stderr'] = is_stderr

    async def _commit_line(self, task_id, state, line, is_stderr):
        await self._append_log_file(task_id, line + '\n')
        await self._dispatch_log_line(
            task_id=task_id,
            line=line,
            is_stderr=is_stderr,
            replace_last=state['frontend_active'],
            line_complete=True,
        )
        state['line_buffer'] = ''
        state['line_is_stderr'] = False
        state['frontend_active'] = False
        state['frontend_line'] = ''
        state['frontend_is_stderr'] = False

    async def _process_task_output(self, task_id, output, is_stderr):
        state = self._get_task_log_state(task_id)

        for ch in output:
            if ch == '\r':
                if state['line_buffer'] and self._is_frontend_line_changed(
                    state, state['line_buffer'], state['line_is_stderr']
                ):
                    await self._emit_incomplete_line(
                        task_id,
                        state,
                        state['line_buffer'],
                        state['line_is_stderr'],
                    )
                state['line_buffer'] = ''
                state['line_is_stderr'] = is_stderr
                continue

            if ch == '\n':
                if state['line_buffer']:
                    await self._commit_line(
                        task_id,
                        state,
                        state['line_buffer'],
                        state['line_is_stderr'],
                    )
                    continue

                if state['frontend_active']:
                    await self._commit_line(
                        task_id,
                        state,
                        state['frontend_line'],
                        state['frontend_is_stderr'],
                    )
                    continue

                await self._commit_line(task_id, state, '', is_stderr)
                continue

            if not state['line_buffer']:
                state['line_is_stderr'] = is_stderr
            state['line_buffer'] += ch

        if state['line_buffer'] and self._is_frontend_line_changed(
            state,
            state['line_buffer'],
            state['line_is_stderr'],
        ):
            await self._emit_incomplete_line(
                task_id,
                state,
                state['line_buffer'],
                state['line_is_stderr'],
            )

    async def _flush_pending_log_line(self, task_id):
        state = self._get_task_log_state(task_id)

        if state['line_buffer']:
            await self._commit_line(
                task_id,
                state,
                state['line_buffer'],
                state['line_is_stderr'],
            )
            return

        if state['frontend_active']:
            await self._commit_line(
                task_id,
                state,
                state['frontend_line'],
                state['frontend_is_stderr'],
            )
