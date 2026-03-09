from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from tickets.models import Ticket, TicketStatusLog


User = get_user_model()


def _extract_results(response):
    data = response.data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


class TicketApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="ticket_owner", password="pass123", platform_role="OWNER"
        )
        self.maintainer = User.objects.create_user(
            username="ticket_maintainer", password="pass123", platform_role="MAINTAINER"
        )
        self.creator = User.objects.create_user(
            username="ticket_creator", password="pass123", platform_role="REPORTER"
        )
        self.assignee = User.objects.create_user(
            username="ticket_assignee", password="pass123", platform_role="REPORTER"
        )
        self.reporter = User.objects.create_user(
            username="ticket_reporter", password="pass123", platform_role="REPORTER"
        )
        self.other_reporter = User.objects.create_user(
            username="ticket_other", password="pass123", platform_role="REPORTER"
        )

    def test_reporter_can_create_and_view_ticket(self):
        self.client.force_authenticate(user=self.reporter)
        create_resp = self.client.post(
            "/api/tickets/",
            {"title": "Ticket A", "description": "desc", "priority": "HIGH"},
            format="json",
        )
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        ticket_id = create_resp.data["id"]

        list_resp = self.client.get("/api/tickets/")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in _extract_results(list_resp)}
        self.assertIn(ticket_id, ids)

        detail_resp = self.client.get(f"/api/tickets/{ticket_id}/")
        self.assertEqual(detail_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_resp.data["created_by"], self.reporter.id)

    def test_reporter_cannot_assign_ticket(self):
        ticket = Ticket.objects.create(title="Assign Denied", created_by=self.creator)
        self.client.force_authenticate(user=self.reporter)
        resp = self.client.post(
            f"/api/tickets/{ticket.id}/assign/",
            {"assignee_id": self.assignee.id},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_maintainer_can_assign_any_ticket(self):
        ticket = Ticket.objects.create(title="Need Assign", created_by=self.creator)
        self.client.force_authenticate(user=self.maintainer)
        resp = self.client.post(
            f"/api/tickets/{ticket.id}/assign/",
            {"assignee_id": self.assignee.id},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee_id, self.assignee.id)

    def test_status_update_permissions(self):
        ticket = Ticket.objects.create(title="Status Ticket", created_by=self.creator)

        # creator can update
        self.client.force_authenticate(user=self.creator)
        creator_resp = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"status": "IN_PROGRESS"},
            format="json",
        )
        self.assertEqual(creator_resp.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "IN_PROGRESS")

        # maintainer assigns assignee
        self.client.force_authenticate(user=self.maintainer)
        self.client.post(
            f"/api/tickets/{ticket.id}/assign/",
            {"assignee_id": self.assignee.id},
            format="json",
        )

        # assignee can update
        self.client.force_authenticate(user=self.assignee)
        assignee_resp = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"status": "DONE"},
            format="json",
        )
        self.assertEqual(assignee_resp.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "DONE")

        # unrelated reporter cannot update
        self.client.force_authenticate(user=self.other_reporter)
        denied_resp = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"status": "TODO"},
            format="json",
        )
        self.assertEqual(denied_resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_permissions(self):
        ticket_by_creator = Ticket.objects.create(title="Creator Delete", created_by=self.creator)
        ticket_by_reporter = Ticket.objects.create(title="Maint Delete", created_by=self.reporter)

        self.client.force_authenticate(user=self.creator)
        creator_delete = self.client.delete(f"/api/tickets/{ticket_by_creator.id}/")
        self.assertEqual(creator_delete.status_code, status.HTTP_204_NO_CONTENT)

        self.client.force_authenticate(user=self.maintainer)
        maint_delete = self.client.delete(f"/api/tickets/{ticket_by_reporter.id}/")
        self.assertEqual(maint_delete.status_code, status.HTTP_204_NO_CONTENT)

        ticket_denied = Ticket.objects.create(title="Denied", created_by=self.creator)
        self.client.force_authenticate(user=self.other_reporter)
        denied_delete = self.client.delete(f"/api/tickets/{ticket_denied.id}/")
        self.assertEqual(denied_delete.status_code, status.HTTP_403_FORBIDDEN)

    def test_status_change_creates_log_and_updates_closed_at(self):
        ticket = Ticket.objects.create(title="Log Ticket", created_by=self.creator)
        self.client.force_authenticate(user=self.creator)

        done_resp = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"status": "DONE"},
            format="json",
        )
        self.assertEqual(done_resp.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.closed_at)
        self.assertEqual(TicketStatusLog.objects.filter(ticket=ticket).count(), 1)

        reopen_resp = self.client.post(
            f"/api/tickets/{ticket.id}/status/",
            {"status": "IN_PROGRESS"},
            format="json",
        )
        self.assertEqual(reopen_resp.status_code, status.HTTP_200_OK)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.closed_at)
        self.assertEqual(TicketStatusLog.objects.filter(ticket=ticket).count(), 2)

    def test_filtering_by_status_priority_assignee_and_search(self):
        t1 = Ticket.objects.create(
            title="UI Bug",
            description="Button style issue",
            created_by=self.creator,
            assignee=self.assignee,
            status="TODO",
            priority="HIGH",
        )
        t2 = Ticket.objects.create(
            title="API Refactor",
            description="Refactor ticket endpoint",
            created_by=self.creator,
            status="IN_PROGRESS",
            priority="MEDIUM",
        )
        t3 = Ticket.objects.create(
            title="Ops Task",
            description="Server maintenance",
            created_by=self.reporter,
            status="PENDING_RELEASE",
            priority="LOW",
        )

        self.client.force_authenticate(user=self.reporter)

        status_resp = self.client.get("/api/tickets/?status=IN_PROGRESS")
        status_ids = {item["id"] for item in _extract_results(status_resp)}
        self.assertEqual(status_ids, {t2.id})

        priority_resp = self.client.get("/api/tickets/?priority=HIGH")
        priority_ids = {item["id"] for item in _extract_results(priority_resp)}
        self.assertEqual(priority_ids, {t1.id})

        assignee_resp = self.client.get(f"/api/tickets/?assignee_id={self.assignee.id}")
        assignee_ids = {item["id"] for item in _extract_results(assignee_resp)}
        self.assertEqual(assignee_ids, {t1.id})

        search_resp = self.client.get("/api/tickets/?search=refactor")
        search_ids = {item["id"] for item in _extract_results(search_resp)}
        self.assertEqual(search_ids, {t2.id})

        pending_release_resp = self.client.get("/api/tickets/?status=PENDING_RELEASE")
        pending_release_ids = {item["id"] for item in _extract_results(pending_release_resp)}
        self.assertEqual(pending_release_ids, {t3.id})

        created_by_resp = self.client.get(f"/api/tickets/?created_by_id={self.reporter.id}")
        created_by_ids = {item["id"] for item in _extract_results(created_by_resp)}
        self.assertEqual(created_by_ids, {t3.id})
