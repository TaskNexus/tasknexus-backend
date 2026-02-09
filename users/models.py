from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    # Feishu integration fields
    feishu_openid = models.CharField(max_length=64, blank=True, null=True, unique=True)
    feishu_union_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
    feishu_name = models.CharField(max_length=128, blank=True, null=True)
    feishu_avatar_url = models.URLField(max_length=512, blank=True, null=True)


    class Meta(AbstractUser.Meta):
        swappable = 'AUTH_USER_MODEL'

class TelegramUser(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='telegram_user')
    telegram_id = models.BigIntegerField(unique=True, help_text="Telegram User ID")
    username = models.CharField(max_length=255, blank=True, null=True, help_text="Telegram Username")
    current_session = models.ForeignKey('chat.ChatSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='telegram_users')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.telegram_id})"
