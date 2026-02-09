"""
Channel Bot Management Command

Runs channel plugin bots to receive and handle messages from external platforms.

Usage:
    python manage.py channel_bot --channel feishu
    python manage.py channel_bot --channel telegram
    python manage.py channel_bot --list  # List available channels
"""

import asyncio
import logging
import signal
import sys
from typing import Any, Dict

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

from plugins import PluginManager
from plugins.channel import ChannelMessage, MessagePayload

logger = logging.getLogger('django')

User = get_user_model()


class ChannelMessageHandler:
    """Handles incoming channel messages and integrates with ChatService."""
    
    def __init__(self, channel, config: Dict[str, Any]):
        self.channel = channel
        self.config = config
        # Get or create a system user for channel messages
        self._system_user = None
        # Default AI settings from config (convert project_id to int)
        project_id = config.get('project_id')
        self.default_project_id = int(project_id) if project_id else None
        self.default_model_group = config.get('model_group')
        self.default_model_name = config.get('model_name')
        # Session mapping: chat_id -> session_id
        self._sessions: Dict[str, int] = {}
    
    def get_system_user(self):
        """Get or create a system user for handling channel messages."""
        if self._system_user is None:
            self._system_user, _ = User.objects.get_or_create(
                username='channel_bot',
                defaults={
                    'email': 'channel_bot@tasknexus.local',
                    'is_active': True,
                }
            )
        return self._system_user
    
    def handle_message(self, message: ChannelMessage):
        """
        Handle incoming channel message.
        
        This callback is called from lark-oapi's async context, so we need to:
        1. Return immediately (non-blocking) to avoid SDK retry
        2. Process the message in a background thread
        
        Args:
            message: The incoming channel message
        """
        logger.info(f"Received message from {message.channel_id}: {message.content[:50]}...")
        
        # Check for special commands
        content = message.content.strip()
        
        # Handle /new command - start a new conversation
        if content.lower() in ['/new', '/新对话', '/重新开始']:
            # Clear the session mapping for this chat
            if message.chat_id in self._sessions:
                del self._sessions[message.chat_id]
            
            # Send confirmation in background
            def send_new_session_message():
                try:
                    payload = MessagePayload(
                        chat_id=message.chat_id,
                        content="✅ 已开始新对话。请发送您的问题。",
                    )
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self.channel.send(payload))
                    finally:
                        loop.close()
                except Exception as e:
                    logger.exception(f"Error sending new session message: {e}")
            
            import threading
            thread = threading.Thread(target=send_new_session_message, daemon=True)
            thread.start()
            return
        
        # Handle /help command
        if content.lower() in ['/help', '/帮助']:
            def send_help_message():
                try:
                    help_text = """📖 **可用命令**

• `/new` 或 `/新对话` - 开始新的对话
• `/help` 或 `/帮助` - 显示帮助信息

直接发送消息即可开始对话。"""
                    payload = MessagePayload(
                        chat_id=message.chat_id,
                        content=help_text,
                    )
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self.channel.send(payload))
                    finally:
                        loop.close()
                except Exception as e:
                    logger.exception(f"Error sending help message: {e}")
            
            import threading
            thread = threading.Thread(target=send_help_message, daemon=True)
            thread.start()
            return
        
        # Process message in a background thread (non-blocking)
        def process_and_respond():
            """Process message and send response - runs in background thread."""
            try:
                # Import here to avoid circular imports and ensure Django is ready
                from agents.services.chat_service import ChatService
                
                user = self.get_system_user()
                
                # Get or create session for this chat
                session_id = self._sessions.get(message.chat_id)
                
                logger.info(f"Processing message with session_id={session_id}, project_id={self.default_project_id}, model_group={self.default_model_group}, model_name={self.default_model_name}")
                
                # Create chat service instance
                service = ChatService(
                    user=user,
                    session_id=session_id,
                    project_id=self.default_project_id,
                    model_group=self.default_model_group,
                    model_name=self.default_model_name,
                )
                
                # Process the message (non-streaming for simplicity)
                result = service.process_message(user_content=content)
                
                # Store session ID for future messages in this chat
                if result.get('session_id'):
                    self._sessions[message.chat_id] = result['session_id']
                    logger.info(f"Stored session mapping: {message.chat_id} -> {result['session_id']}")
                
                response_content = result.get('result', '')
                
                if not response_content:
                    logger.warning("No response generated from ChatService")
                    return
                
                # Send response back to channel
                payload = MessagePayload(
                    chat_id=message.chat_id,
                    content=response_content,
                )
                
                # Run the async send in a new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self.channel.send(payload))
                    logger.info(f"Sent response to {message.chat_id}")
                finally:
                    loop.close()
                    
            except Exception as e:
                logger.exception(f"Error processing channel message: {e}")
                # Try to send error message
                try:
                    error_payload = MessagePayload(
                        chat_id=message.chat_id,
                        content=f"抱歉，处理消息时出错：{str(e)[:100]}",
                    )
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(self.channel.send(error_payload))
                    finally:
                        loop.close()
                except Exception:
                    pass
        
        # Submit to thread pool and return immediately (non-blocking!)
        # This allows the SDK callback to complete quickly
        import threading
        thread = threading.Thread(target=process_and_respond, daemon=True)
        thread.start()
        
        # Return immediately - don't wait for processing to complete


class Command(BaseCommand):
    help = 'Run channel plugin bots for messaging platforms'

    def add_arguments(self, parser):
        parser.add_argument(
            '--channel', '-c',
            type=str,
            help='Channel ID to run (e.g., feishu, telegram)',
        )
        parser.add_argument(
            '--list', '-l',
            action='store_true',
            help='List all available channels',
        )

    def handle(self, *args, **options):
        manager = PluginManager()
        manager.discover()
        
        # List channels
        if options.get('list'):
            channels = manager.list_channels()
            if not channels:
                self.stdout.write(self.style.WARNING('No channel plugins installed.'))
                self.stdout.write('\nInstall a channel plugin:')
                self.stdout.write('  pip install git+https://github.com/<org>/tasknexus-feishu-plugin.git')
                return
            
            self.stdout.write(self.style.SUCCESS('Available channels:'))
            for cid, label in channels.items():
                self.stdout.write(f'  - {cid}: {label}')
            return
        
        # Run channel
        channel_id = options.get('channel')
        if not channel_id:
            raise CommandError(
                'Please specify a channel with --channel or use --list to see available channels'
            )
        
        channel = manager.get_channel(channel_id)
        if not channel:
            available = ', '.join(manager.channels.keys()) or 'none installed'
            raise CommandError(
                f"Channel '{channel_id}' not found. Available: {available}"
            )
        
        # Get configuration
        config = manager.get_channel_config(channel_id)
        if not config:
            self.stderr.write(self.style.WARNING(
                f"No configuration found for {channel_id}. "
                f"Set environment variables with prefix TASKNEXUS_PLUGIN_{channel_id.upper()}_*"
            ))
        
        # Check required AI settings
        if not config.get('project_id') or not config.get('model_group') or not config.get('model_name'):
            self.stderr.write(self.style.WARNING(
                "AI settings (project_id, model_group, model_name) not configured. "
                "Set environment variables:\n"
                f"  TASKNEXUS_PLUGIN_{channel_id.upper()}_PROJECT_ID\n"
                f"  TASKNEXUS_PLUGIN_{channel_id.upper()}_MODEL_GROUP\n"
                f"  TASKNEXUS_PLUGIN_{channel_id.upper()}_MODEL_NAME"
            ))
        
        self.stdout.write(self.style.SUCCESS(
            f'Starting channel bot: {channel.label} ({channel_id})'
        ))
        
        # Create message handler and register callback
        handler = ChannelMessageHandler(channel, config)
        channel.on_message(handler.handle_message)
        
        # Setup signal handlers for graceful shutdown
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run():
            # Setup shutdown handler
            stop_event = asyncio.Event()
            
            def signal_handler():
                logger.info("Shutdown signal received")
                stop_event.set()
            
            if sys.platform != 'win32':
                loop.add_signal_handler(signal.SIGINT, signal_handler)
                loop.add_signal_handler(signal.SIGTERM, signal_handler)
            
            try:
                # Start channel
                await channel.start(config)
                self.stdout.write(self.style.SUCCESS(
                    f'{channel.label} bot is running. Press Ctrl+C to stop.'
                ))
                
                # Wait for stop signal
                await stop_event.wait()
                
            except KeyboardInterrupt:
                pass
            finally:
                self.stdout.write('Stopping channel bot...')
                await channel.stop()
                self.stdout.write(self.style.SUCCESS('Channel bot stopped.'))
        
        try:
            loop.run_until_complete(run())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()

