from rest_framework import serializers
from .models import WorkflowDefinition
import uuid
from django.utils.text import slugify

class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowDefinition
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at', 'key')

    def create(self, validated_data):
        # Automatically assign the current user as creator
        validated_data['created_by'] = self.context['request'].user
        
        # Auto-generate unique key from name
        name = validated_data.get('name', 'workflow')
        base_key = slugify(name).replace('-', '_') or 'workflow'
        unique_suffix = uuid.uuid4().hex[:8]
        validated_data['key'] = f"{base_key}_{unique_suffix}"
        
        return super().create(validated_data)
