import re

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from celery import current_app
from django.conf import settings
from django.http import JsonResponse
from django.db import transaction
from .reminders import schedule_todo_reminder

from django.shortcuts import get_object_or_404
from webpush.forms import SubscriptionForm, WebPushForm

from .models import Todo,Nortification
from .serializers import TodoSerializer,NortificationSerializer

from django.core.exceptions import ImproperlyConfigured
from django.core import signing
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from google.genai.errors import APIError

from .chat_ai import interpret_message
from .serializers import ChatRequestSerializer

CONFIRMATION_SALT = 'todo-ai-chat-delete'

SMALL_TALK_REPLIES = (
    (
        re.compile(r'^(?:hi|hello|hey)(?: there)?(?: how are you)?$'),
        "Hi! I'm here to help you stay on top of your tasks. What would you like to add, update, or plan?",
    ),
    (
        re.compile(r'^(?:good morning|good afternoon|good evening|good night)$'),
        "Hello! Hope your day is going well. Want to plan your tasks or check what's coming up?",
    ),
    (
        re.compile(r"^(?:how are you|how's it going|how are things|are you doing well)\??$"),
        "I'm doing well, thanks for asking! I'm ready to help you organize your tasks. What would you like to work on?",
    ),
    (
        re.compile(r'^(?:thanks|thank you|thanks a lot|thank you so much)$'),
        "You're welcome! Let me know if you'd like help with another task.",
    ),
    (
        re.compile(r'^(?:who are you|what can you do|how can you help(?: me)?)$'),
        "I'm your task assistant. I can help create, list, update, complete, and delete todos, and help you plan your schedule.",
    ),
)


def _small_talk_reply(message):
    normalized = re.sub(r'\s+', ' ', message.lower().strip())
    normalized = re.sub(r'[.!?]+$', '', normalized)
    for pattern, reply in SMALL_TALK_REPLIES:
        if pattern.fullmatch(normalized):
            return reply
    return None


def _parse_due_at(value):
    if not value:
        return None

    due_at = parse_datetime(value)
    if due_at is None:
        return None
    if timezone.is_naive(due_at):
        due_at = timezone.make_aware(due_at, timezone.get_current_timezone())
    return due_at


def _find_matching_todo(user, task_query):
    if not task_query:
        return None, 'Which task do you mean? Please include its title.'

    matches = list(
        Todo.objects.filter(user=user, title__icontains=task_query.strip())[:6]
    )
    if not matches:
        return None, f'I could not find a task matching "{task_query}".'
    if len(matches) > 1:
        titles = ', '.join(f'"{todo.title}"' for todo in matches)
        return None, f'Multiple tasks match. Please be more specific: {titles}.'
    return matches[0], None


def _execute_todo_intent(request, intent):
    if intent.intent == 'unknown':
        return {'reply': 'I can only help with creating, listing, updating, completing, or deleting tasks.'}

    if intent.intent == 'clarify':
        return {'reply': intent.clarification or 'Please provide a little more information.'}

    user = request.user

    if intent.intent == 'create_todo':
        if not intent.title:
            return {'reply': 'What title should I use for the task?'}
        due_at = _parse_due_at(intent.due_at)
        if due_at is None:
            return {'reply': 'When is the task due? Please include a date and time.'}

        todo = Todo.objects.create(
            user=user,
            title=intent.title.strip(),
            due_at=due_at,
        )
        transaction.on_commit(lambda: schedule_todo_reminder(todo.pk))
        Nortification.objects.create(
            user=user,
            todo=todo,
            nortification_type='CREATED',
            message=f"Todo '{todo.title}' was created.",
        )
        return {'reply': f'Created "{todo.title}".'}

    if intent.intent == 'list_todos':
        todos = Todo.objects.filter(user=user)
        if intent.status_filter == 'pending':
            todos = todos.filter(completed=False)
        elif intent.status_filter == 'completed':
            todos = todos.filter(completed=True)

        todos = todos.order_by('-created_at')[:20]
        items = [
            {'id': todo.pk, 'title': todo.title, 'completed': todo.completed, 'due_at': todo.due_at.isoformat()}
            for todo in todos
        ]
        return {'reply': f'Found {len(items)} task(s).', 'todos': items}

    todo, error = _find_matching_todo(user, intent.task_query)
    if error:
        return {'reply': error}

    if intent.intent == 'complete_todo':
        todo.completed = True
        todo.save(update_fields=['completed', 'updated_at'])
        Nortification.objects.create(
            user=user,
            todo=todo,
            nortification_type='ACCOMPLISHED',
            message=f"Todo '{todo.title}' was completed.",
        )
        return {'reply': f'Marked "{todo.title}" as complete.'}

    if intent.intent == 'update_todo':
        changed = False
        if intent.title:
            todo.title = intent.title.strip()
            changed = True
        due_at = _parse_due_at(intent.due_at)
        if intent.due_at and due_at is None:
            return {'reply': 'I could not understand that due date. Please use a complete date and time.'}
        if due_at is not None:
            old_due_at = todo.due_at
            todo.due_at = due_at
            if todo.due_at != old_due_at:
                todo.email_reminder_sent_at = None
                todo.push_reminder_sent_at = None
                todo.missed_email_reminder_sent_at = None
                todo.missed_push_reminder_sent_at = None
            changed = True

        if not changed:
            return {'reply': 'What should I change about the task?'}

        todo.save()
        transaction.on_commit(lambda: schedule_todo_reminder(todo.pk))
        Nortification.objects.create(
            user=user,
            todo=todo,
            nortification_type='UPDATED',
            message=f"Todo '{todo.title}' was updated.",
        )
        return {'reply': f'Updated "{todo.title}".'}

    if intent.intent == 'delete_todo':
        confirmation_token = request.data.get('confirmation_token')
        if confirmation_token:
            try:
                payload = signing.loads(
                    confirmation_token,
                    salt=CONFIRMATION_SALT,
                    max_age=600,
                )
                if payload != {'todo_id': todo.pk, 'user_id': user.pk}:
                    raise signing.BadSignature('Confirmation does not match task.')
            except signing.BadSignature:
                return {
                    'reply': 'That confirmation is invalid or expired. Please confirm the deletion again.',
                    'confirmation_required': True,
                    'confirmation_token': signing.dumps(
                        {'todo_id': todo.pk, 'user_id': user.pk},
                        salt=CONFIRMATION_SALT,
                    ),
                }

            title = todo.title
            if todo.reminder_task_id:
                current_app.control.revoke(todo.reminder_task_id, terminate=False)
            if todo.missed_task_id:
                current_app.control.revoke(todo.missed_task_id, terminate=False)
            Nortification.objects.create(
                user=user,
                todo=None,
                nortification_type='DELETED',
                message=f"Todo '{title}' was deleted",
            )
            todo.delete()
            return {'reply': f'Deleted "{title}".'}

        token = signing.dumps(
            {'todo_id': todo.pk, 'user_id': user.pk},
            salt=CONFIRMATION_SALT,
        )
        return {
            'reply': f'Do you want to delete "{todo.title}"?',
            'confirmation_required': True,
            'confirmation_token': token,
        }

    return {'reply': 'I could not determine which action to take.'}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chat_with_ai(request):
    serializer = ChatRequestSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    message = serializer.validated_data['message']

    if not request.data.get('confirmation_token'):
        small_talk_reply = _small_talk_reply(message)
        if small_talk_reply:
            return Response(
                {
                    'intent': {'intent': 'unknown'},
                    'reply': small_talk_reply,
                },
                status=status.HTTP_200_OK,
            )

    try:
        intent = interpret_message(message)
        result = _execute_todo_intent(request, intent)
    except ImproperlyConfigured as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except APIError as exc:
        return Response({'detail': f'AI provider error: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception as exc:
        return Response({'detail': f'Could not process message: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response(
        {'intent': intent.model_dump(), **result},
        status=status.HTTP_200_OK,
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def push_public_key(request):
    public_key = settings.WEBPUSH_SETTINGS.get('VAPID_PUBLIC_KEY')
    if not public_key:
        return Response(
            {'detail': 'Push notifications are not configured.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({'publicKey': public_key}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_push_subscription(request):
    subscription_data = request.data.get('subscription')
    if not isinstance(subscription_data, dict):
        subscription_data = {}

    keys = subscription_data.get('keys')
    if not isinstance(keys, dict):
        keys = {}

    subscription_form = SubscriptionForm({
        'endpoint': subscription_data.get('endpoint'),
        'auth': keys.get('auth'),
        'p256dh': keys.get('p256dh'),
        'browser': request.data.get('browser', 'unknown'),
        'user_agent': request.data.get('user_agent', ''),
    })
    web_push_form = WebPushForm({'status_type': 'subscribe'})

    if not subscription_form.is_valid() or not web_push_form.is_valid():
        return Response(
            {
                'subscription': dict(subscription_form.errors),
                'request': dict(web_push_form.errors),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    subscription = subscription_form.get_or_save()
    web_push_form.save_or_delete(
        subscription=subscription,
        user=request.user,
        status_type=web_push_form.cleaned_data['status_type'],
        group_name=None,
    )
    return Response(status=status.HTTP_201_CREATED)


# Bug: the original list view used Todo.objects.filter(request.user), which is invalid because
# the filter expects a field lookup like user=request.user. We also need to return the actual
# serializer errors instead of instantiating a serializer and discarding the result.


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def list_nortifications(request):
    nortifications = Nortification.objects.filter(user=request.user)

    if request.method == 'DELETE':
        nortifications.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = NortificationSerializer(nortifications,many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def mark_nortification_read(request,pk):
    nortification = get_object_or_404(
        Nortification,
        pk=pk,
        user=request.user,
    )
    nortification.is_read = True
    nortification.save(update_fields=['is_read','updated_at'])
    return Response(
        NortificationSerializer(nortification).data,
        status=status.HTTP_200_OK
    )


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def list_create_todo(request):
    if request.method == 'GET':
        if request.user.is_staff:
            todos = Todo.objects.all()
        else:
            todos = Todo.objects.filter(user=request.user)
        serializer = TodoSerializer(todos, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    if request.method == 'POST':
        serializer = TodoSerializer(data=request.data)
        if serializer.is_valid():
            todo = serializer.save(user=request.user)
            transaction.on_commit(lambda:schedule_todo_reminder(todo.pk))
            Nortification.objects.create(
                user=request.user,
                todo=todo,
                nortification_type = 'CREATED',
                message = f"Todo '{todo.title}' was created."
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Bug: the original detail view compared Todo.user (a model field reference) against request.user
# instead of checking the actual todo owner. We also now save updates and return the proper
# serializer response when validation fails.
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def detail_update_delete_todo(request, pk):
    try:
        todo = Todo.objects.get(pk=pk)
    except Todo.DoesNotExist:
        return Response({'error': 'item does not exist'}, status=status.HTTP_404_NOT_FOUND)

    if not request.user.is_staff and todo.user != request.user:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        serializer = TodoSerializer(todo)
        return Response(serializer.data, status=status.HTTP_200_OK)

    if request.method in ('PUT', 'PATCH'):
        old_due_at = todo.due_at
        serializer = TodoSerializer(todo, data=request.data, partial=request.method == 'PATCH')
        if serializer.is_valid():
            todo = serializer.save(user=request.user)
            if todo.due_at != old_due_at:
                todo.email_reminder_sent_at = None
                todo.push_reminder_sent_at = None
                todo.missed_email_reminder_sent_at = None
                todo.missed_push_reminder_sent_at = None
                todo.save(update_fields=[
                    'email_reminder_sent_at',
                    'push_reminder_sent_at',
                    'missed_email_reminder_sent_at',
                    'missed_push_reminder_sent_at',
                ])
            transaction.on_commit(lambda: schedule_todo_reminder(todo.pk))
            Nortification.objects.create(
                user=request.user,
                todo = todo,
                nortification_type = 'UPDATED',
                message = f"Todo '{todo.title}' was updated"
            )
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'DELETE':
        if todo.reminder_task_id:
            current_app.control.revoke(todo.reminder_task_id, terminate=False)
        if todo.missed_task_id:
            current_app.control.revoke(todo.missed_task_id, terminate=False)
        Nortification.objects.create(
            user=request.user,
            todo=None,
            nortification_type = 'DELETED',
            message = f"Todo '{todo.title}' was deleted"
        )
        todo.delete()
        return Response({'message': 'item deleted successfully'}, status=status.HTTP_204_NO_CONTENT)

    return Response({'error': 'Method not allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


def catch_all_views(request,resource=None):
    return JsonResponse({
        'status':404,
        'message':f'The route {request.path} does not exist on this server.'
    })

