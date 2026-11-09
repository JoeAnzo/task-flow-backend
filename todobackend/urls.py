"""
URL configuration for todobackend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from Api.auth_views import CookieLoginView, CookieRefreshView, CookieRegisterView, csrf_token

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/csrf/', csrf_token, name='auth_csrf'),
    path('api/v1/auth/login/', CookieLoginView.as_view(), name='rest_login'),
    path(
        'api/v1/auth/registration/',
        CookieRegisterView.as_view(),
        name='rest_register',
    ),
    path(
        'api/v1/auth/token/refresh/',
        CookieRefreshView.as_view(),
        name='token_refresh',
    ),
    path('api/v1/auth/', include('dj_rest_auth.urls')),
    path('api/v1/auth/registration/', include('dj_rest_auth.registration.urls')),
    path('api/v1/', include('Api.urls')),
]
