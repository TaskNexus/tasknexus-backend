from rest_framework import viewsets, permissions
from .models import WorkflowDefinition
from .serializers import WorkflowDefinitionSerializer
from config.permissions import check_project_permission
from config.pagination import StandardResultsSetPagination

class WorkflowViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows workflows to be viewed or edited.
    """
    queryset = WorkflowDefinition.objects.all()
    serializer_class = WorkflowDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['project', 'key'] 
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by user permissions
        user = self.request.user
        if user.platform_role != 'OWNER':
            queryset = queryset.filter(project__members__user=user)

        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        tag = self.request.query_params.get('tag')
        if tag:
            queryset = queryset.filter(tags__contains=[tag])

        return queryset

    def perform_create(self, serializer):
        # Check: Developer+ can create workflows
        project = serializer.validated_data.get('project')
        if project:
            check_project_permission(self.request.user, project, 'workflow.create')
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        if instance.project:
            # Maintainer+ can edit all; Developer can edit own
            check_project_permission(
                self.request.user, instance.project, 'workflow.edit', instance
            )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.project:
            # Maintainer+ can delete all; Developer can delete own
            check_project_permission(
                self.request.user, instance.project, 'workflow.delete', instance
            )
        instance.delete()
