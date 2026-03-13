import logging
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .consumers import AGENT_LOG_DIR

logger = logging.getLogger('django')


class AgentLogConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer for streaming agent task logs to the frontend.
    
    Frontend connects to ws/agent-log/<task_id>/ to receive real-time logs.
    On connect, sends existing log history, then streams new lines.
    """
    
    task_id = None
    log_group = None

    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs'].get('task_id')
        
        if not self.task_id:
            await self.close(code=4001)
            return
        
        await self.accept()
        
        # Join task-specific log group
        self.log_group = f"agent_task_log_{self.task_id}"
        await self.channel_layer.group_add(self.log_group, self.channel_name)

        history_enabled = self._should_send_history()
        task_status = await self._get_task_status()

        if history_enabled:
            history = await self._read_log_history()
            await self.send_json({
                "type": "log_history",
                "content": history,
                "task_status": task_status,
            })
        else:
            await self.send_json({
                "type": "log_init",
                "task_status": task_status,
            })
        
        logger.info(f"Log viewer connected for task {self.task_id}")

    async def disconnect(self, close_code):
        if self.log_group:
            await self.channel_layer.group_discard(self.log_group, self.channel_name)
        logger.info(f"Log viewer disconnected for task {self.task_id}")

    async def log_dispatch(self, event):
        """Receive log broadcast from AgentConsumer and forward to frontend."""
        await self.send_json({
            "type": "log",
            "line": event.get("line", ""),
            "is_stderr": event.get("is_stderr", False),
            "replace_last": event.get("replace_last", False),
            "line_complete": event.get("line_complete", False),
            "finished": event.get("finished", False),
            "exit_code": event.get("exit_code", None),
        })

    @database_sync_to_async
    def _read_log_history(self):
        """Read existing log file content."""
        log_path = AGENT_LOG_DIR / f"task_{self.task_id}.log"
        try:
            if log_path.exists():
                return log_path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            logger.error(f"Failed to read log history for task {self.task_id}: {e}")
        return ""

    def _should_send_history(self):
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        if not query_string:
            return True

        params = {}
        for pair in query_string.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                params[key] = value
            elif pair:
                params[pair] = ''

        history_value = params.get('history')
        if history_value is None:
            return True
        return history_value not in {'0', 'false', 'False'}

    @database_sync_to_async
    def _get_task_status(self):
        """Get the current task status."""
        from .models import AgentTask
        try:
            task = AgentTask.objects.get(id=self.task_id)
            return task.status
        except AgentTask.DoesNotExist:
            return "UNKNOWN"
