import django_filters
from django.db.models import Q

from .models import Ticket


class TicketFilter(django_filters.FilterSet):
    assignee_id = django_filters.NumberFilter(field_name="assignee_id")
    created_by_id = django_filters.NumberFilter(field_name="created_by_id")
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = Ticket
        fields = ["status", "priority", "assignee_id", "created_by_id"]

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(title__icontains=value) | Q(description__icontains=value))
