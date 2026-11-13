import ast
import json
import os

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from dj_rest_auth.registration.views import SocialLoginView
from Api.auth_views import CSRFProtectedDispatchMixin
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response


def _google_oauth_error_detail(error):
    prefix = 'Error retrieving access token:'
    message = str(error)
    if not message.startswith(prefix):
        return 'Google OAuth token exchange failed.'

    try:
        body = ast.literal_eval(message[len(prefix):])
        payload = json.loads(body)
    except (ValueError, SyntaxError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return 'Google rejected the authorization code. Please try again.'

    if not isinstance(payload, dict):
        return 'Google rejected the authorization code. Please try again.'

    error_code = payload.get('error')
    description = payload.get('error_description')
    if isinstance(description, str) and description:
        if isinstance(error_code, str) and error_code:
            return f'{description} ({error_code})'
        return description
    if isinstance(error_code, str) and error_code:
        return f'Google OAuth error: {error_code}'
    return 'Google rejected the authorization code. Please try again.'


class GoogleLogin(CSRFProtectedDispatchMixin, SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = os.environ.get(
        'GOOGLE_OAUTH_CALLBACK_URL',
        'http://localhost:5173/auth/google/callback',
    )
    client_class = OAuth2Client

    def handle_exception(self, exc):
        if isinstance(exc, ValidationError) and isinstance(exc.__cause__, OAuth2Error):
            return Response(
                {'detail': _google_oauth_error_detail(exc.__cause__)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().handle_exception(exc)