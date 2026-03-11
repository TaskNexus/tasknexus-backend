from django.db import models
from users.models import User
from workflows.models import WorkflowDefinition
from django.utils import timezone

class TaskInstance(models.Model):
    STATUS_CHOICES = [
        ('CREATED', 'Created'),
        ('RUNNING', 'Running'),
        ('PAUSED', 'Paused'),
        ('FINISHED', 'Finished'),
        ('FAILED', 'Failed'),
        ('REVOKED', 'Revoked'),
    ]

    name = models.CharField(max_length=255)
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name='instances')
    # bamboo-engine pipeline instance id
    pipeline_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='CREATED')
    
    context = models.JSONField(default=dict, blank=True)
    execution_data = models.JSONField(default=dict, blank=True)  # Store execution related data
    workflow_graph_snapshot = models.JSONField(default=dict, blank=True)  # Task workflow graph snapshot

    # Notification settings (platform users)
    notify_enabled = models.BooleanField(default=False)
    notify_user_ids = models.JSONField(default=list, blank=True)  # List of user IDs to notify
    
    # Feishu direct notification (no platform registration needed)
    feishu_notify_enabled = models.BooleanField(default=False)
    feishu_notify_open_ids = models.JSONField(default=list, blank=True)  # List of Feishu open_ids

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.status})"


from django_celery_beat.models import PeriodicTask as CeleryPeriodicTask

class PeriodicTask(models.Model):
    name = models.CharField(max_length=255)
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE)
    
    # Execution Context (Global/Workflow Params)
    context = models.JSONField(default=dict, blank=True)
    
    # Link to actual scheduling model
    celery_task = models.OneToOneField(CeleryPeriodicTask, on_delete=models.CASCADE, null=True, blank=True)
    
    creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    enabled = models.BooleanField(default=True)
    total_run_count = models.IntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    
    # Notification settings
    notify_enabled = models.BooleanField(default=False)
    notify_user_ids = models.JSONField(default=list, blank=True)
    feishu_notify_enabled = models.BooleanField(default=False)
    feishu_notify_open_ids = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

class ScheduledTask(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('EXECUTED', 'Executed'),
        ('FAILED', 'Failed'),
        ('REVOKED', 'Revoked'),
    ]

    name = models.CharField(max_length=255)
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE)
    
    # Execution Context
    context = models.JSONField(default=dict, blank=True)
    
    # Link to celery task
    celery_task = models.OneToOneField(CeleryPeriodicTask, on_delete=models.SET_NULL, null=True, blank=True)
    
    execution_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Notification settings
    notify_enabled = models.BooleanField(default=False)
    notify_user_ids = models.JSONField(default=list, blank=True)
    feishu_notify_enabled = models.BooleanField(default=False)
    feishu_notify_open_ids = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.execution_time}"


import secrets

class WebhookTask(models.Model):
    """Webhook-triggered task configuration"""
    name = models.CharField(max_length=255)
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE)
    
    # Webhook Token (used in URL)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    
    # Optional Secret (for request verification)
    secret = models.CharField(max_length=128, blank=True, null=True)
    
    # Execution Context (Global Params)
    context = models.JSONField(default=dict, blank=True)
    
    # Status
    enabled = models.BooleanField(default=True)
    
    # Statistics
    total_run_count = models.IntegerField(default=0)
    last_run_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Notification settings
    notify_enabled = models.BooleanField(default=False)
    notify_user_ids = models.JSONField(default=list, blank=True)
    feishu_notify_enabled = models.BooleanField(default=False)
    feishu_notify_open_ids = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(16)  # 32 characters
        super().save(*args, **kwargs)
    
    def regenerate_token(self):
        """Regenerate token (invalidates old URL)"""
        self.token = secrets.token_hex(16)
        self.save(update_fields=['token', 'updated_at'])

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} (token: {self.token[:8]}...)"


class NodeExecutionRecord(models.Model):
    """
    Record execution history of a node in a workflow
    Used for calculating average duration and showing history
    """
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name='node_cords')
    # Original Node ID in the workflow template (not the runtime node_id)
    node_id = models.CharField(max_length=64, db_index=True)
    
    # Execution Duration in seconds
    duration = models.IntegerField()
    
    # Specific pipeline instance ID (TaskInstance.pipeline_id)
    pipeline_id = models.CharField(max_length=64, db_index=True)
    
    finished_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-finished_at']
        indexes = [
            models.Index(fields=['workflow', 'node_id']),
        ]

    def __str__(self):
        return f"{self.workflow.name} - {self.node_id} ({self.duration}s)"
