from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'Api'

    def ready(self):
        from . import signals  # noqa: F401
