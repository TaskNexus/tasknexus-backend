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
