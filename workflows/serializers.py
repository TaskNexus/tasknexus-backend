from rest_framework import serializers
from .models import WorkflowDefinition
import uuid
from django.utils.text import slugify
from projects.models import ProjectMember

class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    VALID_ROLES = {role for role, _ in ProjectMember.ROLE_CHOICES}

    class Meta:
        model = WorkflowDefinition
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'key')

    def validate_visible_roles(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('visible_roles must be a list.')

        normalized = []
        seen = set()
        for role in value:
            if not isinstance(role, str):
                raise serializers.ValidationError('visible_roles must contain role strings.')
            upper_role = role.upper().strip()
            if upper_role not in self.VALID_ROLES:
                raise serializers.ValidationError(f'Invalid role: {role}')
            if upper_role not in seen:
                seen.add(upper_role)
                normalized.append(upper_role)
        return normalized

    def validate_visible_user_ids(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('visible_user_ids must be a list.')

        normalized = []
        seen = set()
        for user_id in value:
            try:
                parsed_id = int(user_id)
            except (TypeError, ValueError):
                raise serializers.ValidationError('visible_user_ids must contain integer user IDs.')
            if parsed_id <= 0:
                raise serializers.ValidationError('visible_user_ids must contain positive integers.')
            if parsed_id not in seen:
                seen.add(parsed_id)
                normalized.append(parsed_id)
        return normalized

    def validate(self, attrs):
        project = attrs.get('project', getattr(self.instance, 'project', None))
        visible_roles = attrs.get('visible_roles', getattr(self.instance, 'visible_roles', []))
        visible_user_ids = attrs.get('visible_user_ids', getattr(self.instance, 'visible_user_ids', []))

        if (visible_roles or visible_user_ids) and project is None:
            raise serializers.ValidationError({
                'project': 'Visibility configuration requires a project.'
            })

        if project and visible_user_ids:
            member_ids = set(
                ProjectMember.objects.filter(project=project, user_id__in=visible_user_ids)
                .values_list('user_id', flat=True)
            )
            invalid_user_ids = [uid for uid in visible_user_ids if uid not in member_ids]
            if invalid_user_ids:
                raise serializers.ValidationError({
                    'visible_user_ids': f'Users are not members of the project: {invalid_user_ids}'
                })

        return attrs

    def create(self, validated_data):
        # Automatically assign the current user as creator
        validated_data['created_by'] = self.context['request'].user
        
        # Auto-generate unique key from name
        name = validated_data.get('name', 'workflow')
        base_key = slugify(name).replace('-', '_') or 'workflow'
        unique_suffix = uuid.uuid4().hex[:8]
        validated_data['key'] = f"{base_key}_{unique_suffix}"
        
        return super().create(validated_data)
