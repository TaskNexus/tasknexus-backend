from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'date_joined', 'role')
        read_only_fields = ('date_joined',)

    role = serializers.SerializerMethodField()

    def get_role(self, obj):
        if obj.is_superuser:
            return 'OWNER'
        if obj.is_staff:
            return 'ADMIN'
        return 'MEMBER'

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', '')
        )
        return user
