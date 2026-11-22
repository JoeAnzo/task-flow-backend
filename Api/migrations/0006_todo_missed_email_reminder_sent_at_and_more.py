from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Api', '0005_todo_email_reminder_sent_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='todo',
            field=models.DateTimeField(blank=True, null=True),
            name='missed_email_reminder_sent_at',
        ),
        migrations.AddField(
            model_name='todo',
            field=models.DateTimeField(blank=True, null=True),
            name='missed_push_reminder_sent_at',
        ),
    ]
