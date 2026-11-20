import os

from celery import Celery
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "todobackend.settings")

app = Celery("todobackend")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
