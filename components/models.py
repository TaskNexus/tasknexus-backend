from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class ComponentCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Category Name")
    icon = models.CharField(max_length=100, default='Component', verbose_name="Icon Name")
    
    class Meta:
        verbose_name = "Component Category"
        verbose_name_plural = "Component Categories"
        
    def __str__(self):
        return self.name


class ComponentNodeTemplate(models.Model):
    name = models.CharField(max_length=128, verbose_name="Template Name")
    node_data = models.JSONField(default=dict, verbose_name="Node Data")
    component_code = models.CharField(max_length=128, verbose_name="Component Code")
    component_version = models.CharField(max_length=64, blank=True, default="", verbose_name="Component Version")
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="component_node_templates",
        verbose_name="Creator",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Component Node Template"
        verbose_name_plural = "Component Node Templates"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.name} ({self.component_code})"
