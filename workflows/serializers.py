from rest_framework import serializers
from .models import WorkflowDefinition
import uuid
import re
from django.utils.text import slugify
from projects.models import ProjectMember


IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    VALID_ROLES = {role for role, _ in ProjectMember.ROLE_CHOICES}

    class Meta:
        model = WorkflowDefinition
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'key')

    def _validate_identifier(self, value, field_name):
        if not isinstance(value, str) or not value.strip():
            raise serializers.ValidationError(f'{field_name} must be a non-empty string.')
        key = value.strip()
        if not IDENTIFIER_PATTERN.match(key):
            raise serializers.ValidationError(
                f'{field_name} must match ^[A-Za-z_][A-Za-z0-9_]*$: {value}'
            )
        return key

    def validate_notify_template(self, value):
        if value in (None, ''):
            return ''
        if '{{' in value or '}}' in value:
            raise serializers.ValidationError('notify_template only supports ${...} syntax.')
        return value

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
        graph_data_provided = 'graph_data' in attrs
        graph_data = attrs.get('graph_data', {}) or {}

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

        if graph_data_provided or self.instance is None:
            if graph_data and not isinstance(graph_data, dict):
                raise serializers.ValidationError({'graph_data': 'graph_data must be an object.'})

            workflow_params = graph_data.get('workflow_params', [])
            if workflow_params is not None:
                if not isinstance(workflow_params, list):
                    raise serializers.ValidationError({'graph_data': 'workflow_params must be a list.'})
                for index, param in enumerate(workflow_params):
                    if not isinstance(param, dict):
                        raise serializers.ValidationError({
                            'graph_data': f'workflow_params[{index}] must be an object.'
                        })
                    key = param.get('key', '')
                    self._validate_identifier(key, f'workflow_params[{index}].key')

            global_params_enabled = graph_data.get('global_params_enabled', [])
            if global_params_enabled is not None:
                if not isinstance(global_params_enabled, list):
                    raise serializers.ValidationError({'graph_data': 'global_params_enabled must be a list.'})
                for index, key in enumerate(global_params_enabled):
                    self._validate_identifier(key, f'global_params_enabled[{index}]')

            cells = graph_data.get('cells', [])
            if cells is not None:
                if not isinstance(cells, list):
                    raise serializers.ValidationError({'graph_data': 'cells must be a list.'})
                for c_index, cell in enumerate(cells):
                    if not isinstance(cell, dict):
                        continue
                    data = cell.get('data')
                    if not isinstance(data, dict):
                        continue
                    outputs = data.get('outputs')
                    if not isinstance(outputs, list):
                        continue
                    for o_index, output in enumerate(outputs):
                        if not isinstance(output, dict):
                            continue
                        context_key = output.get('contextKey')
                        if context_key in (None, ''):
                            continue
                        self._validate_identifier(context_key, f'cells[{c_index}].data.outputs[{o_index}].contextKey')

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
