from django.db import models

class ComponentCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Category Name")
    icon = models.CharField(max_length=100, default='Box', verbose_name="Icon Name")
    
    class Meta:
        verbose_name = "Component Category"
        verbose_name_plural = "Component Categories"
        
    def __str__(self):
        return self.name
