from django.db import models
from django.contrib.auth import get_user_model
from projects.models import Project

User = get_user_model()

class WorkflowDefinition(models.Model):
    """
    Workflow Definition Model
    Stores the design of a workflow, including visual graph data and executable pipeline tree.
    """
    name = models.CharField(max_length=128, verbose_name="Workflow Name")
    key = models.CharField(max_length=64, unique=True, verbose_name="Unique Key")
    description = models.TextField(blank=True, verbose_name="Description")
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='workflows', null=True, blank=True, verbose_name="Project")
    
    # Store Frontend Graph Data (AntV X6 JSON)
    graph_data = models.JSONField(default=dict, verbose_name="Graph Data")
    
    # Tags for classification (e.g., ["Server", "Client"])
    tags = models.JSONField(default=list, blank=True, verbose_name="Tags")
    
    # Store Backend Pipeline Tree (Bamboo Engine JSON)
    pipeline_tree = models.JSONField(default=dict, blank=True, verbose_name="Pipeline Tree")
    
    # Notification template (uses {{variable}} syntax)
    notify_template = models.TextField(blank=True, default='', verbose_name="通知模板")
    
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workflows', verbose_name="Creator")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Workflow Definition"
        verbose_name_plural = "Workflow Definitions"
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} ({self.key})"
