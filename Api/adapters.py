from urllib.parse import urlencode

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings


class AccountAdapter(DefaultAccountAdapter):
    def get_email_confirmation_url(self, request, emailconfirmation):
        base_url = settings.FRONTEND_BASE_URL.rstrip("/")
        query = urlencode({"key": emailconfirmation.key})
        return f"{base_url}/verify-email?{query}"
