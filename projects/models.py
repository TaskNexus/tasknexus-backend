from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Project(models.Model):
    """
    Project Model
    Groups workflows and resources.
    """
    name = models.CharField(max_length=128, verbose_name="Project Name")
    description = models.TextField(blank=True, verbose_name="Description")
    
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects', verbose_name="Creator")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    
    extra_config = models.JSONField(default=dict, blank=True, verbose_name="Extra Configuration")

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

class ProjectMember(models.Model):
    ROLE_CHOICES = (
        ('OWNER', 'Owner'),
        ('MAINTAINER', 'Maintainer'),
        ('DEVELOPER', 'Developer'),
        ('REPORTER', 'Reporter'),
    )

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='REPORTER')
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('project', 'user')
        verbose_name = "Project Member"
        verbose_name_plural = "Project Members"

    def __str__(self):
        return f"{self.user.username} - {self.project.name} ({self.role})"

from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Project)
def assign_admin_owner(sender, instance, created, **kwargs):
    if created:
        try:
            admin_user = User.objects.get(username='admin')
            # If admin is not the creator, add them as owner
            if instance.created_by != admin_user:
                ProjectMember.objects.get_or_create(
                    project=instance,
                    user=admin_user,
                    defaults={'role': 'OWNER'}
                )
        except User.DoesNotExist:
            pass
