# backend/agents/telegram/__init__.py
"""
Telegram integration module.

Provides services for sending messages via Telegram Bot.
"""
from .service import TelegramService

__all__ = ['TelegramService']
