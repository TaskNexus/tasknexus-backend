from django.contrib.auth import get_user_model
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from config.pagination import StandardResultsSetPagination
from config.permissions import check_platform_permission, has_role_level

from .filters import TicketFilter
from .models import Ticket
from .serializers import (
    AssignTicketSerializer,
    CreateTicketSerializer,
    TicketSerializer,
    TicketStatusLogSerializer,
    UpdateTicketSerializer,
    UpdateTicketStatusSerializer,
)


User = get_user_model()


def _is_maintainer_plus(user):
    return has_role_level(getattr(user, "platform_role", None), "MAINTAINER")


class TicketViewSet(viewsets.ModelViewSet):
    queryset = Ticket.objects.select_related("created_by", "assignee").all()
    permission_classes = [permissions.IsAuthenticated]
    filterset_class = TicketFilter
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        check_platform_permission(self.request.user, "ticket.view")
        return super().get_queryset()

    def get_serializer_class(self):
        if self.action == "create":
            return CreateTicketSerializer
        if self.action in ["update", "partial_update"]:
            return UpdateTicketSerializer
        return TicketSerializer

    def perform_create(self, serializer):
        check_platform_permission(self.request.user, "ticket.create")
        assignee = serializer.validated_data.get("assignee")
        if assignee is not None:
            check_platform_permission(self.request.user, "ticket.assign")
        serializer.save()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        ticket = serializer.instance
        return Response(
            TicketSerializer(ticket, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def perform_update(self, serializer):
        ticket = self.get_object()
        if not (_is_maintainer_plus(self.request.user) or ticket.created_by_id == self.request.user.id):
            raise PermissionDenied("Only maintainer+ or creator can edit this ticket.")
        serializer.save()

    def update(self, request, *args, **kwargs):
        return self._update_ticket(request, partial=False, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        return self._update_ticket(request, partial=True, **kwargs)

    def _update_ticket(self, request, partial, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(TicketSerializer(instance, context={"request": request}).data)

    def perform_destroy(self, instance):
        if instance.created_by_id == self.request.user.id:
            instance.delete()
            return
        check_platform_permission(self.request.user, "ticket.delete")
        instance.delete()

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        check_platform_permission(request.user, "ticket.assign")

        ticket = self.get_object()
        serializer = AssignTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        assignee_id = serializer.validated_data.get("assignee_id")
        assignee = None
        if assignee_id is not None:
            assignee = User.objects.filter(id=assignee_id).first()
        ticket.assignee = assignee
        ticket.save(update_fields=["assignee", "updated_at"])

        return Response(TicketSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        ticket = self.get_object()
        user = request.user
        if not (
            _is_maintainer_plus(user)
            or ticket.created_by_id == user.id
            or ticket.assignee_id == user.id
        ):
            raise PermissionDenied(
                "Only maintainer+, creator, or assignee can update ticket status."
            )

        serializer = UpdateTicketStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket.set_status(serializer.validated_data["status"], changed_by=user)
        return Response(TicketSerializer(ticket, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        ticket = self.get_object()
        logs = ticket.status_logs.select_related("changed_by").all()
        data = TicketStatusLogSerializer(logs, many=True).data
        return Response(data, status=status.HTTP_200_OK)
