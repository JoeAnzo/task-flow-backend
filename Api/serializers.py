from rest_framework import serializers

from .models import Todo


class TodoSerializer(serializers.ModelSerializer):
    # Bug: exposing all model fields allowed the client to modify the owner relationship.
    # We keep the user read-only and explicitly list only the fields that a client should edit.
    user = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Todo
        fields = ['id', 'user', 'title', 'completed', 'created_at', 'updated_at', 'due_at']
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']