import django_filters
from .models import TaskInstance

class TaskInstanceFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr='icontains')
    project_id = django_filters.NumberFilter(field_name='workflow__project__id')
    periodic_task_id = django_filters.NumberFilter(method='filter_periodic_task_id')

    class Meta:
        model = TaskInstance
        fields = ['status', 'project_id', 'name']

    def filter_periodic_task_id(self, queryset, name, value):
        try:
            return queryset.filter(execution_data__periodic_task_id=int(value))
        except (ValueError, TypeError):
            return queryset
            
    scheduled_task_id = django_filters.NumberFilter(method='filter_scheduled_task_id')

    def filter_scheduled_task_id(self, queryset, name, value):
        try:
            return queryset.filter(execution_data__scheduled_task_id=int(value))
        except (ValueError, TypeError):
            return queryset
