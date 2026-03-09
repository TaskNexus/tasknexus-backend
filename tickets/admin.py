from django.contrib import admin

from .models import Ticket, TicketStatusLog


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "priority", "assignee", "created_by", "updated_at")
    search_fields = ("title", "description", "created_by__username", "assignee__username")
    list_filter = ("status", "priority")


@admin.register(TicketStatusLog)
class TicketStatusLogAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "from_status", "to_status", "changed_by", "changed_at")
    list_filter = ("from_status", "to_status")
