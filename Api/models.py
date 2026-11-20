from django.db import models
from django.conf import settings

# Create your models here.
class Todo(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='todos',
    )
    title = models.CharField(max_length=100)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reminder_task_id = models.CharField(max_length=255,null=True,blank=True)
    missed_task_id = models.CharField(max_length=255,null=True,blank=True)
    due_at = models.DateTimeField()
    email_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    push_reminder_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title

class Nortification(models.Model):
    TYPES = [
        ("CREATED","Task Created"),
        ("PENDING","Task Pending"),
        ("MISSED","Task Missed"),
        ("ACCOMPLISHED","Task Accomplished"),
        ("UPDATED","Task Updated"),
        ("DELETED","Task Deleted")
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="nortifications"
    )
    todo = models.ForeignKey(
        "Todo",
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    nortification_type = models.CharField(max_length=20,choices=TYPES)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
