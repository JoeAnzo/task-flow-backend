from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from webpush import send_user_notification

from . models import Todo

@shared_task(bind=True)
def send_todo_reminder(self,todo_id):
    try:
        todo = Todo.objects.select_related("user").get(pk=todo_id)
    except Todo.DoesNotExist:
        return

    if (todo.reminder_task_id != self.request.id or todo.completed or todo.due_at <= timezone.now()):
        return

    if todo.user.email and not todo.email_reminder_sent_at:
        send_mail(
            subject=f"Reminder: {todo.title} is due soon",
            message=f'Your todo "{todo.title}" is due in about 5 minutes.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[todo.user.email],
            fail_silently=False,
        )
        todo.email_reminder_sent_at = timezone.now()
        todo.save(update_fields=['email_reminder_sent_at'])

    if not todo.push_reminder_sent_at:
        send_user_notification(
            user=todo.user,
            payload={
                "head":"Todo due soon",
                "body":f"'{todo.title}' is due in about 5 minutes.",
                "url":"/",
            },
            ttl=3600,
        )
        todo.push_reminder_sent_at = timezone.now()
        todo.save(update_fields=["push_reminder_sent_at"])