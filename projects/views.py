from rest_framework import viewsets, permissions
from .models import Project
from .serializers import ProjectSerializer

class ProjectViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows projects to be viewed or edited.
    """
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return Project.objects.all()
        # Only projects where user is a member
        return Project.objects.filter(members__user=user)

    def perform_create(self, serializer):
        project = serializer.save(created_by=self.request.user)
        # Add creator as OWNER
        ProjectMember.objects.create(project=project, user=self.request.user, role='OWNER')

    def perform_update(self, serializer):
        instance = self.get_object()
        user = self.request.user
        if not user.is_superuser:
             membership = ProjectMember.objects.filter(project=instance, user=user).first()
             if not membership or membership.role not in ['OWNER', 'ADMIN']:
                  from rest_framework.exceptions import PermissionDenied
                  raise PermissionDenied("Only Project Owner/Admin can edit project details.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not user.is_superuser:
             membership = ProjectMember.objects.filter(project=instance, user=user).first()
             if not membership or membership.role != 'OWNER':
                  from rest_framework.exceptions import PermissionDenied
                  raise PermissionDenied("Only Project Owner can delete the project.")
        instance.delete()


from .models import ProjectMember
from .serializers import ProjectMemberSerializer
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404

class ProjectMemberViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectMemberSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        # Filter by project_id in query params if provided check permissions
        queryset = ProjectMember.objects.all()
        project_id = self.request.query_params.get('project_id')
        if project_id:
             queryset = queryset.filter(project_id=project_id)
             
        # Security: Can I see members? Only if I am a member of the project?
        # For simplicity, if basic member, can see other members.
        user = self.request.user
        if not user.is_superuser:
             # Only memberships of projects where the user is also a member
             # Use subquery or simple logic
             user_projects = Project.objects.filter(members__user=user)
             queryset = queryset.filter(project__in=user_projects)
             
        return queryset

    def perform_create(self, serializer):
        # Check if request.user is ADMIN or OWNER of the project
        project = serializer.validated_data['project']
        user = self.request.user
        if not user.is_superuser:
             membership = ProjectMember.objects.filter(project=project, user=user).first()
             if not membership or membership.role not in ['OWNER', 'ADMIN']:
                  from rest_framework.exceptions import PermissionDenied
                  raise PermissionDenied("Only Project Admin/Owner can add members.")
        
        serializer.save()

    def perform_update(self, serializer):
        # Check permissions
        obj = self.get_object()
        user = self.request.user
        if not user.is_superuser:
             membership = ProjectMember.objects.filter(project=obj.project, user=user).first()
             if not membership or membership.role not in ['OWNER', 'ADMIN']:
                  from rest_framework.exceptions import PermissionDenied
                  raise PermissionDenied("Only Project Admin/Owner can update members.")
        serializer.save()

    def perform_destroy(self, instance):
        # Check permissions
        user = self.request.user
        if not user.is_superuser:
             membership = ProjectMember.objects.filter(project=instance.project, user=user).first()
             if not membership or membership.role not in ['OWNER', 'ADMIN']:
                  from rest_framework.exceptions import PermissionDenied
                  raise PermissionDenied("Only Project Admin/Owner can remove members.")
        instance.delete()

from rest_framework.views import APIView
from rest_framework.response import Response
from tasks.models import TaskInstance
from workflows.models import WorkflowDefinition
from tasks.serializers import TaskInstanceSerializer
from workflows.serializers import WorkflowDefinitionSerializer

class DashboardStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # 1. Recent Projects (Limit 4)
        if request.user.is_superuser:
            projects = Project.objects.all().order_by('-created_at')[:4]
            workflows = WorkflowDefinition.objects.all().order_by('-updated_at')[:4]
        else:
             projects = Project.objects.filter(members__user=request.user).order_by('-created_at')[:4]
             workflows = WorkflowDefinition.objects.filter(project__members__user=request.user).order_by('-updated_at')[:4]
        
        project_data = ProjectSerializer(projects, many=True).data
        
        # 2. Recent Tasks (Limit 5)
        # Filter by user if needed? Dashboard usually shows global or user's scope.
        # "My Tasks" implies created_by=user.
        tasks = TaskInstance.objects.filter(created_by=request.user).order_by('-created_at')[:5]
        task_data = TaskInstanceSerializer(tasks, many=True).data
        
        # 3. Recent Workflows (Common Flows) (Limit 4)
        workflow_data = WorkflowDefinitionSerializer(workflows, many=True).data
        
        return Response({
            'projects': project_data,
            'tasks': task_data,
            'workflows': workflow_data,
            'stats': {
                'tasks_runnable': 0, # Placeholder
                'tasks_running': TaskInstance.objects.filter(status='RUNNING').count()
            }
        })
