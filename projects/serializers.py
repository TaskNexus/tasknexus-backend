from rest_framework import serializers
from .models import Project
import re


IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

class ProjectSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Project
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at')

    def validate_extra_config(self, value):
        if value in (None, ''):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError('extra_config must be an object.')

        global_params = value.get('global_params')
        if global_params is None:
            return value
        if not isinstance(global_params, list):
            raise serializers.ValidationError('extra_config.global_params must be a list.')

        for index, item in enumerate(global_params):
            if not isinstance(item, dict):
                raise serializers.ValidationError(f'global_params[{index}] must be an object.')
            key = item.get('key')
            if not isinstance(key, str) or not key.strip():
                raise serializers.ValidationError(f'global_params[{index}].key must be a non-empty string.')
            normalized_key = key.strip()
            if not IDENTIFIER_PATTERN.match(normalized_key):
                raise serializers.ValidationError(
                    f'global_params[{index}].key must match ^[A-Za-z_][A-Za-z0-9_]*$: {key}'
                )

        return value

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)

from .models import ProjectMember

class ProjectMemberSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    
    class Meta:
        model = ProjectMember
        fields = ['id', 'project', 'user', 'username', 'email', 'role', 'created_at']
        read_only_fields = ['created_at']
