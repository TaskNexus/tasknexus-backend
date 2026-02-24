from rest_framework import viewsets, permissions
from .models import Project, ProjectMember
from .serializers import ProjectSerializer, ProjectMemberSerializer
from config.permissions import check_project_permission, check_platform_permission
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404


class ProjectViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows projects to be viewed or edited.
    """
    serializer_class = ProjectSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.platform_role == 'OWNER':
            return Project.objects.all()
        # Only projects where user is a member
        return Project.objects.filter(members__user=user)

    def perform_create(self, serializer):
        # Permission: controlled by permission matrix 'platform.project_create'
        check_platform_permission(self.request.user, 'platform.project_create')
        project = serializer.save(created_by=self.request.user)
        # Add creator as OWNER
        ProjectMember.objects.create(project=project, user=self.request.user, role='OWNER')

    def perform_update(self, serializer):
        instance = self.get_object()
        check_project_permission(self.request.user, instance, 'project.edit')
        serializer.save()

    def perform_destroy(self, instance):
        check_project_permission(self.request.user, instance, 'project.delete')
        instance.delete()


class ProjectMemberViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectMemberSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = ProjectMember.objects.all()
        project_id = self.request.query_params.get('project_id')
        if project_id:
            queryset = queryset.filter(project_id=project_id)

        user = self.request.user
        if user.platform_role != 'OWNER':
            user_projects = Project.objects.filter(members__user=user)
            queryset = queryset.filter(project__in=user_projects)

        return queryset

    def perform_create(self, serializer):
        project = serializer.validated_data['project']
        check_project_permission(self.request.user, project, 'member.manage')
        serializer.save()

    def perform_update(self, serializer):
        obj = self.get_object()
        check_project_permission(self.request.user, obj.project, 'member.manage')
        serializer.save()

    def perform_destroy(self, instance):
        check_project_permission(self.request.user, instance.project, 'member.manage')
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
        if request.user.platform_role == 'OWNER':
            projects = Project.objects.all().order_by('-created_at')[:4]
            workflows = WorkflowDefinition.objects.all().order_by('-updated_at')[:4]
        else:
             projects = Project.objects.filter(members__user=request.user).order_by('-created_at')[:4]
             workflows = WorkflowDefinition.objects.filter(project__members__user=request.user).order_by('-updated_at')[:4]

        project_data = ProjectSerializer(projects, many=True).data

        # 2. Recent Tasks (Limit 5)
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
