from django.contrib import admin
from .models import ComponentCategory, ComponentNodeTemplate


@admin.register(ComponentCategory)
class ComponentCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "icon")
    search_fields = ("name",)


@admin.register(ComponentNodeTemplate)
class ComponentNodeTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "component_code", "component_version", "created_by", "updated_at")
    search_fields = ("name", "component_code", "created_by__username")
    list_filter = ("component_code", "created_by")
