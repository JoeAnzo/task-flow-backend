import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from webpush import send_user_notification
from django.contrib.auth import get_user_model

from . models import Nortification, Todo

logger = logging.getLogger(__name__)

@shared_task(bind=True)
def send_todo_reminder(self, todo_id, at_due_time=False):
    try:
        todo = Todo.objects.select_related("user").get(pk=todo_id)
    except Todo.DoesNotExist:
        return

    if todo.reminder_task_id != self.request.id or todo.completed:
        return

    if at_due_time:
        if timezone.now() < todo.due_at:
            return
        timing_message = "is due now."
        subject = f"Due now: {todo.title}"
    else:
        if todo.due_at <= timezone.now():
            return
        timing_message = "is due in about 5 minutes."
        subject = f"Reminder: {todo.title} is due soon"

    if not todo.push_reminder_sent_at:
        send_user_notification(
            user=todo.user,
            payload={
                "head": "Todo due now" if at_due_time else "Todo due soon",
                "body": f"'{todo.title}' {timing_message}",
                "url":"/",
            },
            ttl=3600,
        )
        todo.push_reminder_sent_at = timezone.now()
        todo.save(update_fields=["push_reminder_sent_at"])

    if todo.user.email and not todo.email_reminder_sent_at:
        send_mail(
            subject=subject,
            message=f'Your todo "{todo.title}" {timing_message}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[todo.user.email],
            fail_silently=False,
        )
        todo.email_reminder_sent_at = timezone.now()
        todo.save(update_fields=['email_reminder_sent_at'])


@shared_task(bind=True)
def send_missed_todo_reminder(self, todo_id):
    try:
        todo = Todo.objects.select_related("user").get(pk=todo_id)
    except Todo.DoesNotExist:
        return

    if (
        todo.missed_task_id != self.request.id
        or todo.completed
        or timezone.now() < todo.due_at + timedelta(minutes=5)
    ):
        return

    if not Nortification.objects.filter(
        todo=todo,
        nortification_type="MISSED",
    ).exists():
        Nortification.objects.create(
            user=todo.user,
            todo=todo,
            nortification_type="MISSED",
            message=f"Todo '{todo.title}' was missed.",
        )

    if not todo.missed_push_reminder_sent_at:
        try:
            send_user_notification(
                user=todo.user,
                payload={
                    "head": "Todo missed",
                    "body": f"'{todo.title}' is now 5 minutes overdue.",
                    "url": "/",
                },
                ttl=3600,
            )
            todo.missed_push_reminder_sent_at = timezone.now()
            todo.save(update_fields=["missed_push_reminder_sent_at"])
        except Exception:
            logger.exception("Failed to send missed browser reminder for todo %s", todo.pk)

    if todo.user.email and not todo.missed_email_reminder_sent_at:
        try:
            send_mail(
                subject=f"Missed reminder: {todo.title}",
                message=f'Your todo "{todo.title}" was due 5 minutes ago.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[todo.user.email],
                fail_silently=False,
            )
            todo.missed_email_reminder_sent_at = timezone.now()
            todo.save(update_fields=["missed_email_reminder_sent_at"])
        except Exception:
            logger.exception("Failed to send missed email reminder for todo %s", todo.pk)


@shared_task(bind=True,autoretry_for=(Exception,), retry_backoff=60, max_retries=3)
def send_welcome_email(self,user_id):
    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()

    if not user or not user.email:
        return

    send_mail(
        subject="Welcome to Taskflow",
        message=f"Welcome to Taskflow, {user.username}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )