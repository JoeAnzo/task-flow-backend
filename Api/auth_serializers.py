from allauth.socialaccount.models import SocialAccount
from dj_rest_auth.serializers import UserDetailsSerializer as BaseUserDetailsSerializer
from rest_framework import serializers


class UserDetailsSerializer(BaseUserDetailsSerializer):
    google_display_name = serializers.SerializerMethodField()

    class Meta(BaseUserDetailsSerializer.Meta):
        fields = (*BaseUserDetailsSerializer.Meta.fields, 'google_display_name')

    def get_google_display_name(self, user):
        extra_data = SocialAccount.objects.filter(
            user=user,
            provider='google',
        ).values_list('extra_data', flat=True).first()
        if not isinstance(extra_data, dict):
            return None

        name = extra_data.get('name')
        return name.strip() if isinstance(name, str) and name.strip() else None
