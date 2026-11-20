from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from django.http import JsonResponse
from django.db import transaction
from .reminders import schedule_todo_reminder

from django.shortcuts import get_object_or_404
from webpush.forms import SubscriptionForm, WebPushForm

from .models import Todo,Nortification
from .serializers import TodoSerializer,NortificationSerializer


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


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_nortifications(request):
    nortifications = Nortification.objects.filter(user=request.user)
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
        serializer = TodoSerializer(todo, data=request.data, partial=request.method == 'PATCH')
        if serializer.is_valid():
            todo = serializer.save(user=request.user)
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
