from datetime import timedelta
from uuid import uuid4

from celery import current_app
from django.utils import timezone

from .models import Todo
from .tasks import send_missed_todo_reminder, send_todo_reminder

def schedule_todo_reminder(todo_id):
    todo = Todo.objects.get(pk=todo_id)

    if todo.reminder_task_id:
        current_app.control.revoke(todo.reminder_task_id, terminate=False)

    if todo.missed_task_id:
        current_app.control.revoke(todo.missed_task_id, terminate=False)

    if todo.completed:
        todo.reminder_task_id = ""
        todo.missed_task_id = ""
        todo.save(update_fields=["reminder_task_id", "missed_task_id"])
        return

    reminder_task_id = str(uuid4())
    missed_task_id = str(uuid4())

    todo.reminder_task_id = reminder_task_id
    todo.missed_task_id = missed_task_id
    todo.save(update_fields=["reminder_task_id", "missed_task_id"])

    reminder_time = todo.due_at - timedelta(minutes=5)
    missed_time = todo.due_at + timedelta(minutes=5)

    send_todo_reminder.apply_async(
        args=[todo.pk],
        eta=max(reminder_time, timezone.now()),
        task_id=reminder_task_id,
    )
    send_missed_todo_reminder.apply_async(
        args=[todo.pk],
        eta=max(missed_time, timezone.now()),
        task_id=missed_task_id,
    )
