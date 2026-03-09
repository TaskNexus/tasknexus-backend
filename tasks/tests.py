from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project, ProjectMember
from tasks.models import PeriodicTask, ScheduledTask, TaskInstance, WebhookTask
from workflows.models import WorkflowDefinition


User = get_user_model()


def _extract_results(response):
    data = response.data
    if isinstance(data, dict) and 'results' in data:
        return data['results']
    return data


class TaskVisibilityTests(APITestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user(
            username='task_owner', password='pass123', platform_role='REPORTER'
        )
        self.maintainer = User.objects.create_user(
            username='task_maintainer', password='pass123', platform_role='REPORTER'
        )
        self.reporter = User.objects.create_user(
            username='task_reporter', password='pass123', platform_role='REPORTER'
        )

        self.project = Project.objects.create(
            name='Task Visibility Project',
            description='',
            created_by=self.owner_user,
        )
        ProjectMember.objects.create(project=self.project, user=self.owner_user, role='OWNER')
        ProjectMember.objects.create(project=self.project, user=self.maintainer, role='MAINTAINER')
        ProjectMember.objects.create(project=self.project, user=self.reporter, role='REPORTER')

        self.open_workflow = WorkflowDefinition.objects.create(
            name='Open Workflow',
            key='task_open_wf',
            project=self.project,
            graph_data={},
            pipeline_tree={},
            created_by=self.maintainer,
            visible_roles=[],
            visible_user_ids=[],
        )
        self.hidden_workflow = WorkflowDefinition.objects.create(
            name='Hidden Workflow',
            key='task_hidden_wf',
            project=self.project,
            graph_data={},
            pipeline_tree={},
            created_by=self.maintainer,
            visible_roles=['MAINTAINER'],
            visible_user_ids=[],
        )

        self.open_task = TaskInstance.objects.create(
            name='Open Task',
            workflow=self.open_workflow,
            created_by=self.maintainer,
            status='CREATED',
        )
        self.hidden_task = TaskInstance.objects.create(
            name='Hidden Task',
            workflow=self.hidden_workflow,
            created_by=self.maintainer,
            status='CREATED',
        )

        self.open_periodic = PeriodicTask.objects.create(
            name='Open Periodic',
            workflow=self.open_workflow,
            creator=self.maintainer,
        )
        self.hidden_periodic = PeriodicTask.objects.create(
            name='Hidden Periodic',
            workflow=self.hidden_workflow,
            creator=self.maintainer,
        )

        future = timezone.now() + timedelta(hours=1)
        self.open_scheduled = ScheduledTask.objects.create(
            name='Open Scheduled',
            workflow=self.open_workflow,
            creator=self.maintainer,
            execution_time=future,
        )
        self.hidden_scheduled = ScheduledTask.objects.create(
            name='Hidden Scheduled',
            workflow=self.hidden_workflow,
            creator=self.maintainer,
            execution_time=future + timedelta(hours=1),
        )

        self.open_webhook = WebhookTask.objects.create(
            name='Open Webhook',
            workflow=self.open_workflow,
            creator=self.maintainer,
        )
        self.hidden_webhook = WebhookTask.objects.create(
            name='Hidden Webhook',
            workflow=self.hidden_workflow,
            creator=self.maintainer,
        )

    def test_task_list_and_detail_are_filtered_by_workflow_visibility(self):
        self.client.force_authenticate(user=self.reporter)

        list_resp = self.client.get('/api/tasks/')
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        task_ids = {item['id'] for item in _extract_results(list_resp)}
        self.assertIn(self.open_task.id, task_ids)
        self.assertNotIn(self.hidden_task.id, task_ids)

        detail_resp = self.client.get(f'/api/tasks/{self.hidden_task.id}/')
        self.assertEqual(detail_resp.status_code, status.HTTP_404_NOT_FOUND)

        node_history_resp = self.client.get(
            f'/api/tasks/{self.hidden_task.id}/node_history/',
            {'node_id': 'n1'},
        )
        self.assertEqual(node_history_resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_reporter_cannot_create_task_for_hidden_workflow(self):
        self.client.force_authenticate(user=self.reporter)

        payload = {
            'name': 'Blocked Task',
            'workflow': self.hidden_workflow.id,
            'context': {},
        }
        resp = self.client.post('/api/tasks/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_periodic_scheduled_webhook_lists_are_filtered(self):
        self.client.force_authenticate(user=self.reporter)

        periodic_resp = self.client.get('/api/tasks/periodic/')
        self.assertEqual(periodic_resp.status_code, status.HTTP_200_OK)
        periodic_ids = {item['id'] for item in _extract_results(periodic_resp)}
        self.assertIn(self.open_periodic.id, periodic_ids)
        self.assertNotIn(self.hidden_periodic.id, periodic_ids)

        scheduled_resp = self.client.get('/api/tasks/scheduled/')
        self.assertEqual(scheduled_resp.status_code, status.HTTP_200_OK)
        scheduled_ids = {item['id'] for item in _extract_results(scheduled_resp)}
        self.assertIn(self.open_scheduled.id, scheduled_ids)
        self.assertNotIn(self.hidden_scheduled.id, scheduled_ids)

        webhook_resp = self.client.get('/api/tasks/webhook/')
        self.assertEqual(webhook_resp.status_code, status.HTTP_200_OK)
        webhook_ids = {item['id'] for item in _extract_results(webhook_resp)}
        self.assertIn(self.open_webhook.id, webhook_ids)
        self.assertNotIn(self.hidden_webhook.id, webhook_ids)

    def test_reporter_cannot_create_periodic_scheduled_webhook_for_hidden_workflow(self):
        self.client.force_authenticate(user=self.reporter)
        execution_time = (timezone.now() + timedelta(hours=2)).isoformat()

        periodic_resp = self.client.post(
            '/api/tasks/periodic/',
            {
                'name': 'Blocked Periodic',
                'workflow': self.hidden_workflow.id,
                'minute': '*',
                'hour': '*',
                'day_of_week': '*',
                'day_of_month': '*',
                'month_of_year': '*',
            },
            format='json',
        )
        self.assertEqual(periodic_resp.status_code, status.HTTP_403_FORBIDDEN)

        scheduled_resp = self.client.post(
            '/api/tasks/scheduled/',
            {
                'name': 'Blocked Scheduled',
                'workflow': self.hidden_workflow.id,
                'execution_time': execution_time,
            },
            format='json',
        )
        self.assertEqual(scheduled_resp.status_code, status.HTTP_403_FORBIDDEN)

        webhook_resp = self.client.post(
            '/api/tasks/webhook/',
            {
                'name': 'Blocked Webhook',
                'workflow': self.hidden_workflow.id,
            },
            format='json',
        )
        self.assertEqual(webhook_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_history_endpoints_hide_hidden_periodic_scheduled_webhook(self):
        self.client.force_authenticate(user=self.reporter)

        periodic_history_resp = self.client.get(
            f'/api/tasks/periodic/{self.hidden_periodic.id}/history/'
        )
        self.assertEqual(periodic_history_resp.status_code, status.HTTP_404_NOT_FOUND)

        scheduled_history_resp = self.client.get(
            f'/api/tasks/scheduled/{self.hidden_scheduled.id}/history/'
        )
        self.assertEqual(scheduled_history_resp.status_code, status.HTTP_404_NOT_FOUND)

        webhook_history_resp = self.client.get(
            f'/api/tasks/webhook/{self.hidden_webhook.id}/history/'
        )
        self.assertEqual(webhook_history_resp.status_code, status.HTTP_404_NOT_FOUND)
