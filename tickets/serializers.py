from rest_framework import serializers

from config.permissions import check_platform_permission, has_role_level
from users.models import User

from .models import Ticket, TicketStatusLog


def _has_assign_permission(user):
    try:
        check_platform_permission(user, "ticket.assign")
        return True
    except Exception:
        return False


def _has_delete_permission(user):
    try:
        check_platform_permission(user, "ticket.delete")
        return True
    except Exception:
        return False


def _is_maintainer_plus(user):
    return has_role_level(getattr(user, "platform_role", None), "MAINTAINER")


class TicketSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)
    assignee_username = serializers.CharField(source="assignee.username", read_only=True)
    can_assign = serializers.SerializerMethodField()
    can_update_status = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "assignee_username",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
            "closed_at",
            "can_assign",
            "can_update_status",
            "can_edit",
            "can_delete",
        ]
        read_only_fields = [
            "created_by",
            "status",
            "created_at",
            "updated_at",
            "closed_at",
        ]

    def get_can_assign(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return _has_assign_permission(request.user)

    def get_can_update_status(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        return bool(
            _is_maintainer_plus(user)
            or obj.created_by_id == user.id
            or obj.assignee_id == user.id
        )

    def get_can_edit(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        return bool(_is_maintainer_plus(user) or obj.created_by_id == user.id)

    def get_can_delete(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        return bool(obj.created_by_id == user.id or _has_delete_permission(user))


class CreateTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["title", "description", "priority", "assignee"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


class UpdateTicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = ["title", "description", "priority"]


class AssignTicketSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_assignee_id(self, value):
        if value is None:
            return None
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Assignee user not found")
        return value


class UpdateTicketStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.STATUS_CHOICES)


class TicketStatusLogSerializer(serializers.ModelSerializer):
    changed_by_username = serializers.CharField(
        source="changed_by.username", read_only=True
    )

    class Meta:
        model = TicketStatusLog
        fields = [
            "id",
            "ticket",
            "from_status",
            "to_status",
            "changed_by",
            "changed_by_username",
            "changed_at",
        ]
