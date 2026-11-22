import ast
import json
import logging
import os

from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client, OAuth2Error
from dj_rest_auth.registration.views import SocialLoginView
from Api.auth_views import CSRFProtectedDispatchMixin
from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from redis import Redis

from .celery import app as celery_app


logger = logging.getLogger(__name__)


@require_GET
def health_check(request):
    checks = {
        'database': 'ok',
        'redis': 'ok',
        'workers': 'ok',
    }

    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        logger.exception('Health check could not connect to the database.')
        checks['database'] = 'unavailable'

    redis_available = False
    try:
        with Redis.from_url(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        ) as redis_client:
            redis_available = bool(redis_client.ping())
        if not redis_available:
            checks['redis'] = 'unavailable'
    except Exception:
        logger.exception('Health check could not connect to Redis.')
        checks['redis'] = 'unavailable'

    worker_count = 0
    if redis_available:
        try:
            worker_responses = celery_app.control.inspect(timeout=2).ping() or {}
            worker_count = len(worker_responses)
            if worker_count == 0:
                checks['workers'] = 'unavailable'
        except Exception:
            logger.exception('Health check could not inspect Celery workers.')
            checks['workers'] = 'unavailable'
    else:
        checks['workers'] = 'unavailable'

    healthy = all(value == 'ok' for value in checks.values())
    return JsonResponse(
        {
            'status': 'ok' if healthy else 'degraded',
            'checks': checks,
            'workers': {'online': worker_count},
        },
        status=200 if healthy else 503,
    )


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