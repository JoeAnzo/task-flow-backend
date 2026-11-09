from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from dj_rest_auth.app_settings import api_settings
from dj_rest_auth.jwt_auth import get_refresh_view, set_jwt_cookies
from dj_rest_auth.registration.views import RegisterView
from dj_rest_auth.views import LoginView


class CSRFProtectedDispatchMixin:
    @method_decorator(csrf_protect)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)


@ensure_csrf_cookie
@api_view(['GET'])
@permission_classes([AllowAny])
def csrf_token(request):
    return Response({'csrfToken': get_token(request)})


class CookieRegisterView(CSRFProtectedDispatchMixin, RegisterView):
    def get_response_data(self, user):
        data = super().get_response_data(user)
        if (
            data
            and api_settings.USE_JWT
            and api_settings.JWT_AUTH_HTTPONLY
            and 'refresh' in data
        ):
            data['refresh'] = ''
        return data

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        if (
            response.status_code == status.HTTP_201_CREATED
            and api_settings.USE_JWT
            and getattr(self, 'access_token', None)
            and getattr(self, 'refresh_token', None)
        ):
            set_jwt_cookies(response, self.access_token, self.refresh_token)
        return response


class CookieLoginView(CSRFProtectedDispatchMixin, LoginView):
    pass


class CookieRefreshView(CSRFProtectedDispatchMixin, get_refresh_view()):
    pass
