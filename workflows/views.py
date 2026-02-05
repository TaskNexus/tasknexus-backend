from rest_framework import viewsets, permissions
from .models import WorkflowDefinition
from .serializers import WorkflowDefinitionSerializer

class WorkflowViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows workflows to be viewed or edited.
    """
    queryset = WorkflowDefinition.objects.all()
    serializer_class = WorkflowDefinitionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['project', 'key'] 

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by user permissions
        user = self.request.user
        if not user.is_superuser:
            queryset = queryset.filter(project__members__user=user)

        project_id = self.request.query_params.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
