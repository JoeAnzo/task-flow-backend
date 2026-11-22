from rest_framework import serializers

from .models import Todo,Nortification


class TodoSerializer(serializers.ModelSerializer):
    # Bug: exposing all model fields allowed the client to modify the owner relationship.
    # We keep the user read-only and explicitly list only the fields that a client should edit.
    user = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Todo
        fields = ['id', 'user', 'title', 'completed', 'created_at', 'updated_at', 'due_at']
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']

class NortificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Nortification
        fields = [
            'id',
            'todo',
            'nortification_type',
            'message',
            'is_read',
            'created_at'
        ]
        read_only_fields = fields


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(
        max_length=2000,
        trim_whitespace=True,
        allow_blank=False,
    )
    confirmation_token = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=False
    )