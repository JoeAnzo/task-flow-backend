from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.http import JsonResponse

from .models import Todo
from .serializers import TodoSerializer


# Bug: the original list view used Todo.objects.filter(request.user), which is invalid because
# the filter expects a field lookup like user=request.user. We also need to return the actual
# serializer errors instead of instantiating a serializer and discarding the result.
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
            serializer.save(user=request.user)
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
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'DELETE':
        todo.delete()
        return Response({'message': 'item deleted successfully'}, status=status.HTTP_204_NO_CONTENT)

    return Response({'error': 'Method not allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


def catch_all_views(request,resource=None):
    return JsonResponse({
        'status':404,
        'message':f'The route {request.path} does not exist on this server.'
    })