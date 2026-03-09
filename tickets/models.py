from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone


User = get_user_model()


class Ticket(models.Model):
    STATUS_TODO = "TODO"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_PENDING_RELEASE = "PENDING_RELEASE"
    STATUS_DONE = "DONE"
    STATUS_CHOICES = [
        (STATUS_TODO, "To Do"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_PENDING_RELEASE, "Pending Release"),
        (STATUS_DONE, "Done"),
    ]

    PRIORITY_LOW = "LOW"
    PRIORITY_MEDIUM = "MEDIUM"
    PRIORITY_HIGH = "HIGH"
    PRIORITY_URGENT = "URGENT"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TODO)
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM
    )
    assignee = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="created_tickets"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["assignee"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"#{self.id} {self.title}"

    def set_status(self, new_status, changed_by):
        if new_status == self.status:
            return False

        old_status = self.status
        self.status = new_status
        if new_status == self.STATUS_DONE:
            self.closed_at = timezone.now()
        elif old_status == self.STATUS_DONE:
            self.closed_at = None

        self.save(update_fields=["status", "closed_at", "updated_at"])
        TicketStatusLog.objects.create(
            ticket=self,
            from_status=old_status,
            to_status=new_status,
            changed_by=changed_by,
        )
        return True


class TicketStatusLog(models.Model):
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="status_logs"
    )
    from_status = models.CharField(max_length=20, choices=Ticket.STATUS_CHOICES)
    to_status = models.CharField(max_length=20, choices=Ticket.STATUS_CHOICES)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["ticket", "-changed_at"]),
        ]

    def __str__(self):
        return f"Ticket#{self.ticket_id}: {self.from_status} -> {self.to_status}"
