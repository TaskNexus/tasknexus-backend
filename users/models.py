from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    PLATFORM_ROLE_CHOICES = (
        ('OWNER', 'Owner'),
        ('MAINTAINER', 'Maintainer'),
        ('DEVELOPER', 'Developer'),
        ('REPORTER', 'Reporter'),
    )

    platform_role = models.CharField(
        max_length=20,
        choices=PLATFORM_ROLE_CHOICES,
        default='REPORTER',
        verbose_name='Platform Role',
    )

    # Feishu integration fields
    feishu_openid = models.CharField(max_length=64, blank=True, null=True, unique=True)
    feishu_union_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
    feishu_name = models.CharField(max_length=128, blank=True, null=True)
    feishu_avatar_url = models.URLField(max_length=512, blank=True, null=True)

    class Meta(AbstractUser.Meta):
        swappable = 'AUTH_USER_MODEL'
