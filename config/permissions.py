# -*- coding: utf-8 -*-
"""
Project-level Role-Based Permission System

Core permission checking module that implements:
- Default permission matrix (Jenkins-style)
- "Own resource" logic: non-Maintainer roles can only operate on their own creations
- DRF Permission class for ViewSet integration
"""

from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied

# Role hierarchy (higher index = more privileges)
ROLE_HIERARCHY = {
    'REPORTER': 0,
    'DEVELOPER': 1,
    'MAINTAINER': 2,
    'OWNER': 3,
}

# Default permission matrix
# Format: action -> minimum role required
# Actions suffixed with '_own' mean the user can do it on their own resources
# Actions suffixed with '_all' mean the user can do it on all resources
DEFAULT_PERMISSION_MATRIX = {
    # Project
    'project.view':          'REPORTER',
    'project.create':        'OWNER',       # Platform-level; only Owner can create projects
    'project.edit':          'MAINTAINER',
    'project.delete':        'OWNER',

    # Members
    'member.view':           'REPORTER',
    'member.manage':         'MAINTAINER',

    # Workflow
    'workflow.view':         'REPORTER',
    'workflow.create':       'DEVELOPER',
    'workflow.edit_own':     'DEVELOPER',
    'workflow.edit_all':     'MAINTAINER',
    'workflow.delete_own':   'DEVELOPER',
    'workflow.delete_all':   'MAINTAINER',

    # Task
    'task.view':             'REPORTER',
    'task.create':           'REPORTER',
    'task.operate_own':      'REPORTER',    # pause/resume/revoke own tasks
    'task.operate_all':      'MAINTAINER',  # pause/resume/revoke any task
    'task.delete_own':       'REPORTER',
    'task.delete_all':       'MAINTAINER',

    # Component
    'component.view':        'REPORTER',
    'component.edit':        'MAINTAINER',

    # AI Agent
    'agent.chat':            'OWNER',

    # Platform-level (checked against user.platform_role)
    'platform.project_create':   'OWNER',
    'platform.user_manage':      'MAINTAINER',
    'platform.user_delete':      'MAINTAINER',
    'platform.config_edit':      'OWNER',
}


def get_project_role(user, project):
    """
    Get a user's role in a project.
    Returns the role string or None if the user is not a member.
    Superusers are treated as OWNER.
    """
    if getattr(user, 'platform_role', None) == 'OWNER':
        return 'OWNER'

    from projects.models import ProjectMember
    membership = ProjectMember.objects.filter(
        project=project, user=user
    ).first()

    if membership:
        return membership.role
    return None


def get_permission_matrix():
    """
    Get the permission matrix.
    Priority: PlatformConfig custom > DEFAULT_PERMISSION_MATRIX
    """
    merged = dict(DEFAULT_PERMISSION_MATRIX)

    # Platform-level custom matrix
    try:
        from config.models import PlatformConfig
        config = PlatformConfig.get_config()
        platform_matrix = config.get('permission_matrix')
        if platform_matrix and isinstance(platform_matrix, dict):
            merged.update(platform_matrix)
    except Exception:
        pass

    return merged


def has_role_level(user_role, required_role):
    """Check if user_role meets or exceeds required_role in the hierarchy."""
    if user_role is None:
        return False
    return ROLE_HIERARCHY.get(user_role, -1) >= ROLE_HIERARCHY.get(required_role, 999)


def check_project_permission(user, project, action, obj=None):
    """
    Core permission check function.

    Args:
        user: The requesting user
        project: The Project instance
        action: Permission action string (e.g., 'workflow.edit')
        obj: Optional object being operated on (for own-resource checks)

    Returns:
        True if permitted

    Raises:
        PermissionDenied if not permitted
    """
    role = get_project_role(user, project)
    if role is None:
        raise PermissionDenied("You are not a member of this project.")

    matrix = get_permission_matrix()

    # Check for '_all' action first (can operate on everything)
    all_action = action + '_all' if not action.endswith(('_own', '_all')) else action
    own_action = action + '_own' if not action.endswith(('_own', '_all')) else action

    # If the action has _all/_own variants
    if all_action in matrix and own_action in matrix:
        # Check if user has '_all' permission
        if has_role_level(role, matrix[all_action]):
            return True

        # Check if user has '_own' permission and the object belongs to them
        if has_role_level(role, matrix[own_action]):
            if obj is not None:
                created_by = getattr(obj, 'created_by', None) or getattr(obj, 'creator', None)
                if created_by and created_by == user:
                    return True
                # If creator is accessible via _id
                created_by_id = getattr(obj, 'created_by_id', None) or getattr(obj, 'creator_id', None)
                if created_by_id and created_by_id == user.id:
                    return True

            raise PermissionDenied(
                f"You can only {action.replace('_own', '').replace('_all', '')} "
                f"resources you created. Maintainer+ role required for all resources."
            )

        raise PermissionDenied(
            f"Insufficient permissions. Required role: {matrix.get(own_action, 'UNKNOWN')}+"
        )

    # Simple action (no _own/_all variants)
    if action in matrix:
        if has_role_level(role, matrix[action]):
            return True
        raise PermissionDenied(
            f"Insufficient permissions. Required role: {matrix[action]}+"
        )

    # Action not in matrix — deny by default
    raise PermissionDenied(f"Unknown action: {action}")


def get_platform_permission_matrix():
    """
    Get the effective permission matrix from PlatformConfig.
    Custom values override defaults.
    """
    try:
        from config.models import PlatformConfig
        config = PlatformConfig.get_config()
        custom_matrix = config.get('permission_matrix')
        if custom_matrix and isinstance(custom_matrix, dict):
            merged = dict(DEFAULT_PERMISSION_MATRIX)
            merged.update(custom_matrix)
            return merged
    except Exception:
        pass
    return DEFAULT_PERMISSION_MATRIX


def check_platform_permission(user, action):
    """
    Platform-level permission check (not tied to a project).
    Uses user.platform_role against the permission matrix.

    Args:
        user: The requesting user
        action: Permission action string (e.g., 'platform.user_manage')

    Returns:
        True if permitted

    Raises:
        PermissionDenied if not permitted
    """
    role = getattr(user, 'platform_role', None)
    if role is None:
        raise PermissionDenied("User has no platform role.")

    matrix = get_platform_permission_matrix()
    if action in matrix:
        if has_role_level(role, matrix[action]):
            return True
        raise PermissionDenied(
            f"Insufficient permissions. Required platform role: {matrix[action]}+"
        )
    raise PermissionDenied(f"Unknown action: {action}")


class ProjectRolePermission(BasePermission):
    """
    DRF Permission class for project-level role checks.

    Usage in ViewSet:
        permission_classes = [IsAuthenticated, ProjectRolePermission]

    The ViewSet should define `get_project()` method or the object
    should have a `project` attribute.
    """

    # Map HTTP methods to action prefixes — override in subclass or ViewSet
    action_map = {}

    def has_permission(self, request, view):
        # For list/create actions, we need the project from query params
        return True  # Defer to has_object_permission or manual checks

    def has_object_permission(self, request, view, obj):
        project = getattr(obj, 'project', None)
        if project is None:
            project = obj  # The object itself is the project

        action = self.action_map.get(view.action)
        if action is None:
            return True  # No action mapping, allow

        try:
            check_project_permission(request.user, project, action, obj)
            return True
        except PermissionDenied:
            return False
