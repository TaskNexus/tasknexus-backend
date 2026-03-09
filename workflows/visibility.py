from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from projects.models import ProjectMember


def get_visible_workflow_queryset(user, queryset=None):
    """
    Return workflows visible to the given user.

    Rules:
    - Platform OWNER can see all workflows.
    - Non-members cannot see project workflows.
    - Project OWNER and workflow creator are always visible (within membership scope).
    - Empty visibility config means all project members can view.
    - Otherwise, role or explicit user id match grants visibility.
    """
    from .models import WorkflowDefinition

    qs = queryset if queryset is not None else WorkflowDefinition.objects.all()

    if getattr(user, "platform_role", None) == "OWNER":
        return qs

    memberships = list(
        ProjectMember.objects.filter(user=user).values_list("project_id", "role")
    )
    if not memberships:
        return qs.filter(created_by=user, project__isnull=True)

    member_project_ids = {project_id for project_id, _ in memberships}
    owner_project_ids = {
        project_id for project_id, role in memberships if role == "OWNER"
    }

    role_project_map = {}
    for project_id, role in memberships:
        role_project_map.setdefault(role, set()).add(project_id)

    access_q = Q(visible_roles=[], visible_user_ids=[]) | Q(
        visible_user_ids__contains=[user.id]
    )
    for role, project_ids in role_project_map.items():
        access_q |= Q(project_id__in=project_ids, visible_roles__contains=[role])

    visible_q = (
        Q(project_id__in=owner_project_ids)
        | Q(created_by=user, project_id__in=member_project_ids)
        | (Q(project_id__in=member_project_ids) & access_q)
    )
    return qs.filter(visible_q).distinct()


def can_user_view_workflow(user, workflow):
    if getattr(user, "platform_role", None) == "OWNER":
        return True

    project = workflow.project
    if project is None:
        return workflow.created_by_id == user.id

    membership = ProjectMember.objects.filter(project=project, user=user).first()
    if membership is None:
        return False

    if membership.role == "OWNER":
        return True
    if workflow.created_by_id == user.id:
        return True

    visible_roles = workflow.visible_roles or []
    visible_user_ids = workflow.visible_user_ids or []

    if not visible_roles and not visible_user_ids:
        return True
    if user.id in visible_user_ids:
        return True
    if membership.role in visible_roles:
        return True
    return False


def assert_user_can_view_workflow(user, workflow):
    if not can_user_view_workflow(user, workflow):
        raise PermissionDenied("You do not have access to this workflow.")
