from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class PlatformUserManager(UserManager):
    def create_user(self, username, email=None, password=None, **extra_fields):
        if not extra_fields.get('platform_role'):
            if extra_fields.get('is_superuser'):
                extra_fields['platform_role'] = 'OWNER'
            elif extra_fields.get('is_staff'):
                extra_fields['platform_role'] = 'MAINTAINER'
        return super().create_user(username, email=email, password=password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('platform_role', 'OWNER')
        return super().create_superuser(username, email=email, password=password, **extra_fields)


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

    objects = PlatformUserManager()

    class Meta(AbstractUser.Meta):
        swappable = 'AUTH_USER_MODEL'
