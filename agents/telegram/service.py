import os
import logging
import asyncio

logger = logging.getLogger('django')


class TelegramService:
    def __init__(self, token: str = None):
        self.token = token or os.environ.get('TELEGRAM_BOT_TOKEN')
    
    def send_message(self, chat_id: int, text: str) -> bool:
        if not self.token:
            logger.error('TELEGRAM_BOT_TOKEN not configured')
            return False
        
        try:
            from telegram import Bot
            
            bot = Bot(token=self.token)
            
            # Telegram max message length is 4096 characters
            MAX_LENGTH = 4096
            chunks = [text[i:i+MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]
            
            async def _send():
                for chunk in chunks:
                    await bot.send_message(chat_id=chat_id, text=chunk)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_send())
            finally:
                loop.close()
            
            logger.info(f'Sent Telegram message to chat {chat_id} ({len(chunks)} chunk(s))')
            return True
            
        except Exception as e:
            logger.exception(f'Error sending Telegram message to {chat_id}: {e}')
            return False
    
    def send_message_to_user(self, user_id: int, text: str) -> dict:
        from django.contrib.auth import get_user_model
        from users.models import TelegramUser
        
        User = get_user_model()
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return {'success': False, 'error': f'User {user_id} not found'}
        
        try:
            tg_user = TelegramUser.objects.get(user=user)
        except TelegramUser.DoesNotExist:
            return {'success': False, 'error': f'User {user.username} has no Telegram binding'}
        if self.send_message(tg_user.telegram_id, text):
            return {'success': True, 'error': None}
        else:
            return {'success': False, 'error': 'Failed to send message'}
    
    def send_message_to_users(self, content: str, user_ids: list) -> dict:
        if not self.token:
            return {
                'success_count': 0,
                'failed_recipients': user_ids,
                'errors': ['TELEGRAM_BOT_TOKEN not configured']
            }
        
        success_count = 0
        failed_recipients = []
        errors = []
        
        for user_id in user_ids:
            result = self.send_message_to_user(user_id, content)
            if result['success']:
                success_count += 1
            else:
                failed_recipients.append(user_id)
                errors.append(result['error'])
        
        return {
            'success_count': success_count,
            'failed_recipients': failed_recipients,
            'errors': errors
        }
