from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project, ProjectMember
from workflows.models import WorkflowDefinition


User = get_user_model()


def _extract_results(response):
    data = response.data
    if isinstance(data, dict) and 'results' in data:
        return data['results']
    return data


class WorkflowVisibilityTests(APITestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user(
            username='proj_owner', password='pass123', platform_role='REPORTER'
        )
        self.maintainer = User.objects.create_user(
            username='maintainer', password='pass123', platform_role='REPORTER'
        )
        self.developer = User.objects.create_user(
            username='developer', password='pass123', platform_role='REPORTER'
        )
        self.reporter = User.objects.create_user(
            username='reporter', password='pass123', platform_role='REPORTER'
        )
        self.outsider = User.objects.create_user(
            username='outsider', password='pass123', platform_role='REPORTER'
        )

        self.project = Project.objects.create(
            name='Visibility Project',
            description='',
            created_by=self.owner_user,
        )
        ProjectMember.objects.create(project=self.project, user=self.owner_user, role='OWNER')
        ProjectMember.objects.create(project=self.project, user=self.maintainer, role='MAINTAINER')
        ProjectMember.objects.create(project=self.project, user=self.developer, role='DEVELOPER')
        ProjectMember.objects.create(project=self.project, user=self.reporter, role='REPORTER')

    def _create_workflow(self, **kwargs):
        defaults = {
            'name': 'Workflow',
            'key': f"wf_{WorkflowDefinition.objects.count() + 1}",
            'description': '',
            'project': self.project,
            'graph_data': {},
            'pipeline_tree': {},
            'created_by': self.maintainer,
            'tags': [],
        }
        defaults.update(kwargs)
        return WorkflowDefinition.objects.create(**defaults)

    def _list_workflow_ids(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.get('/api/workflows/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {item['id'] for item in _extract_results(response)}

    def test_default_empty_visibility_all_project_members_can_view(self):
        workflow = self._create_workflow()

        for user in [self.owner_user, self.maintainer, self.developer, self.reporter]:
            ids = self._list_workflow_ids(user)
            self.assertIn(workflow.id, ids)

        outsider_ids = self._list_workflow_ids(self.outsider)
        self.assertNotIn(workflow.id, outsider_ids)

    def test_role_visibility(self):
        workflow = self._create_workflow(visible_roles=['MAINTAINER'])

        self.assertIn(workflow.id, self._list_workflow_ids(self.maintainer))
        self.assertNotIn(workflow.id, self._list_workflow_ids(self.reporter))

    def test_user_visibility(self):
        workflow = self._create_workflow(visible_user_ids=[self.developer.id])

        self.assertIn(workflow.id, self._list_workflow_ids(self.developer))
        self.assertNotIn(workflow.id, self._list_workflow_ids(self.reporter))

    def test_union_visibility_role_or_user(self):
        workflow = self._create_workflow(
            created_by=self.developer,
            visible_roles=['DEVELOPER'],
            visible_user_ids=[self.reporter.id],
        )

        self.assertIn(workflow.id, self._list_workflow_ids(self.developer))
        self.assertIn(workflow.id, self._list_workflow_ids(self.reporter))
        self.assertNotIn(workflow.id, self._list_workflow_ids(self.maintainer))

    def test_owner_and_creator_override(self):
        workflow = self._create_workflow(
            created_by=self.reporter,
            visible_roles=['MAINTAINER'],
            visible_user_ids=[],
        )

        self.assertIn(workflow.id, self._list_workflow_ids(self.owner_user))
        self.assertIn(workflow.id, self._list_workflow_ids(self.reporter))

    def test_unauthorized_detail_returns_404(self):
        workflow = self._create_workflow(visible_roles=['MAINTAINER'])

        self.client.force_authenticate(user=self.reporter)
        resp = self.client.get(f'/api/workflows/{workflow.id}/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_rejects_non_member_visible_user(self):
        self.client.force_authenticate(user=self.developer)
        payload = {
            'name': 'Invalid Visibility Workflow',
            'project': self.project.id,
            'graph_data': {},
            'pipeline_tree': {},
            'visible_roles': [],
            'visible_user_ids': [self.outsider.id],
        }
        resp = self.client.post('/api/workflows/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('visible_user_ids', resp.data)
