"""
Django Management Command to run the Telegram Bot.

Uses long polling to receive messages and integrates with ChatService.
"""
import os
import logging
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.conf import settings
from asgiref.sync import sync_to_async

logger = logging.getLogger('django')


class Command(BaseCommand):
    help = 'Runs the Telegram Bot using long polling.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--token',
            type=str,
            help='Telegram Bot Token (or set TELEGRAM_BOT_TOKEN env var)',
        )

    def handle(self, *args, **options):
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            MessageHandler,
            filters,
            ContextTypes,
        )

        token = options.get('token') or os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:
            self.stderr.write(self.style.ERROR(
                'Telegram Bot Token is required. Use --token or set TELEGRAM_BOT_TOKEN env var.'
            ))
            return

        self.stdout.write(self.style.SUCCESS(f'Starting Telegram Bot...'))

        # --- Async-safe database operations ---
        @sync_to_async
        def get_user_by_id(user_id):
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                return User.objects.get(id=user_id)
            except User.DoesNotExist:
                return None

        @sync_to_async
        def get_telegram_user(telegram_id):
            from users.models import TelegramUser
            try:
                return TelegramUser.objects.select_related('user').get(telegram_id=telegram_id)
            except TelegramUser.DoesNotExist:
                return None

        @sync_to_async
        def check_user_has_telegram(user):
            return hasattr(user, 'telegram_user')

        @sync_to_async
        def create_telegram_user(user, telegram_id, username):
            from users.models import TelegramUser
            return TelegramUser.objects.create(
                user=user,
                telegram_id=telegram_id,
                username=username
            )

        @sync_to_async
        def delete_telegram_user(tg_user):
            username = tg_user.user.username
            tg_user.delete()
            return username

        @sync_to_async
        def clear_session(tg_user):
            tg_user.current_session = None
            tg_user.save()

        @sync_to_async
        def update_session(tg_user, session_id):
            tg_user.current_session_id = session_id
            tg_user.save()

        @sync_to_async
        def process_chat_message(tg_user, user_text, project_id, model_group, model_name):
            from agents.services import ChatService
            service = ChatService(
                user=tg_user.user,
                session_id=tg_user.current_session_id,
                project_id=project_id,
                model_group=model_group,
                model_name=model_name
            )
            return service.process_message(user_content=user_text)

        @sync_to_async
        def get_cache(key):
            return cache.get(key)

        @sync_to_async
        def delete_cache(key):
            cache.delete(key)

        # --- Command Handlers ---
        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /start command."""
            await update.message.reply_text(
                "👋 欢迎使用 TaskNexus AI 助手!\n\n"
                "请先完成账号绑定:\n"
                "1. 在 TaskNexus 网页端的 Platform Members 页面点击 'Bind Telegram'\n"
                "2. 获取验证码后发送: /bind <验证码>\n\n"
                "使用 /help 查看所有命令。"
            )

        async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /help command."""
            await update.message.reply_text(
                "📖 可用命令:\n\n"
                "/start - 显示欢迎信息\n"
                "/bind <code> - 绑定 TaskNexus 账号\n"
                "/unbind - 解除账号绑定\n"
                "/new - 开始新对话\n"
                "/help - 显示此帮助\n\n"
                "绑定成功后，直接发送消息即可与 AI 对话。"
            )

        async def bind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /bind <code> command."""
            args = context.args
            if not args or len(args) < 1:
                await update.message.reply_text("❌ 用法: /bind <验证码>")
                return

            code = args[0]
            cache_key = f"tg_bind:{code}"
            user_id = await get_cache(cache_key)

            if not user_id:
                await update.message.reply_text("❌ 验证码无效或已过期，请重新获取。")
                return

            user = await get_user_by_id(user_id)
            if not user:
                await update.message.reply_text("❌ 用户不存在。")
                return

            # Check if already bound
            tg_id = update.effective_user.id
            tg_username = update.effective_user.username or update.effective_user.first_name

            existing = await get_telegram_user(tg_id)
            if existing:
                if existing.user_id == user_id:
                    await update.message.reply_text(f"✅ 已绑定到 {user.username}。")
                else:
                    await update.message.reply_text(
                        f"❌ 此 Telegram 账号已绑定到其他用户 ({existing.user.username})。\n"
                        "请先使用 /unbind 解绑。"
                    )
                return

            # Check if user already has a different telegram bound
            if await check_user_has_telegram(user):
                await update.message.reply_text(
                    f"❌ 用户 {user.username} 已绑定其他 Telegram 账号。\n"
                    "请先在网页端解绑。"
                )
                return

            # Create binding
            await create_telegram_user(user, tg_id, tg_username)

            # Delete the code from cache
            await delete_cache(cache_key)

            await update.message.reply_text(
                f"✅ 绑定成功! 欢迎 {user.username}!\n\n"
                "现在你可以直接发送消息与 AI 对话了。\n"
                "使用 /new 开始新对话。"
            )

        async def unbind_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /unbind command."""
            tg_id = update.effective_user.id
            tg_user = await get_telegram_user(tg_id)
            
            if tg_user:
                username = await delete_telegram_user(tg_user)
                await update.message.reply_text(f"✅ 已解除与 {username} 的绑定。")
            else:
                await update.message.reply_text("❌ 您的 Telegram 未绑定任何账号。")

        async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /new command - start a new conversation."""
            tg_id = update.effective_user.id
            tg_user = await get_telegram_user(tg_id)
            
            if tg_user:
                await clear_session(tg_user)
                await update.message.reply_text("✨ 已开始新对话。请发送您的问题。")
            else:
                await update.message.reply_text("❌ 请先绑定账号。使用 /start 查看说明。")

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle regular text messages."""
            tg_id = update.effective_user.id
            user_text = update.message.text

            # Check binding
            tg_user = await get_telegram_user(tg_id)
            if not tg_user:
                await update.message.reply_text(
                    f"❌ 未授权用户。请先绑定账号。\n"
                    f"您的 Telegram ID: {tg_id}\n\n"
                    "使用 /start 查看绑定说明。"
                )
                return

            # Show typing indicator
            await update.message.chat.send_action('typing')

            try:
                # Process message
                result = await process_chat_message(
                    tg_user, user_text, 
                    5, "Nvidia", "minimaxai/minimax-m2.1"
                )

                # Update session reference
                if result.get('session_id'):
                    await update_session(tg_user, result['session_id'])

                # Send response
                ai_response = result.get('result', '抱歉，我无法生成回复。')
                
                # Telegram has 4096 char limit, split if needed
                if len(ai_response) > 4000:
                    chunks = [ai_response[i:i+4000] for i in range(0, len(ai_response), 4000)]
                    for chunk in chunks:
                        await update.message.reply_text(chunk)
                else:
                    await update.message.reply_text(ai_response)

            except Exception as e:
                logger.exception("Error processing message in Telegram bot")
                await update.message.reply_text(f"❌ 处理消息时发生错误: {str(e)}")

        # --- Build Application ---
        application = Application.builder().token(token).build()

        # Register handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("bind", bind_command))
        application.add_handler(CommandHandler("unbind", unbind_command))
        application.add_handler(CommandHandler("new", new_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # Start polling
        self.stdout.write(self.style.SUCCESS('Bot is running. Press Ctrl+C to stop.'))
        application.run_polling(allowed_updates=Update.ALL_TYPES)
