from django.db import models
from users.models import User

class ChatSession(models.Model):
    SOURCE_CHOICES = [
        ('web', 'Web'),
        ('pipeline', 'Pipeline'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_sessions')
    project_id = models.IntegerField(null=True, blank=True) # Optional link to a project
    model_group = models.CharField(max_length=255, blank=True, null=True)
    model = models.CharField(max_length=255, blank=True, null=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='web')
    title = models.CharField(max_length=255, default="New Chat")
    summary = models.TextField(blank=True, default="")
    last_summarized_message_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_chatsession'
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} - {self.title}"


class ChatMessage(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_chatmessage'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.session.id} - {self.role}: {self.content[:50]}"
