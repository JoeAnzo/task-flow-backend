from django.shortcuts import render
from rest_framework.decorators import api_view,permission_classes
from rest_framework.response import Response
from .serializers import TodoSerializer
from rest_framework.permissions import IsAuthenticated
from .models import Todo
from rest_framework import status

# Create your views here.

    
@api_view(['GET','POST'])
@permission_classes([IsAuthenticated])
def list_create_todo(request):
    if request.method == 'GET':
        if request.user.is_staff:
            todos = Todo.objects.all()
        else:
            todos = Todo.objects.filter(request.user)
        serializer = TodoSerializer(todos,many=True)
        return Response(serializer.data,status=status.HTTP_200_OK)
    elif request.method == 'POST':
        serializer = TodoSerializer(data=request.body if hasattr(request,'body') else request.body)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        else:
            TodoSerializer(serializer.errors,status=status.HTTP_400_BAD_REQUEST)

@api_view(['PUT','PATCH','DELETE','GET'])
@permission_classes([IsAuthenticated])
def detail_update_delete_todo(request,pk):
    try:
        todo = Todo.objects.get(pk=pk)
    except Todo.DoesNotExist:
        return Response({'error':'item doesnot exist'},status=status.HTTP_404_NOT_FOUND)
    if not request.user.is_staff and Todo.user != request.user:
        return Response({'error':'Access denied'},status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        serializer = TodoSerializer(todo)
        return Response(serializer.data,status=status.HTTP_200_OK)
    elif request.method == 'PUT':
        serializer = TodoSerializer(todo,data=request.data,partial=True)
        if serializer.is_valid():
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)
    elif request.method == 'DELETE':
        todo.delete()
        return Response({'message':'item deleted successfully'},status=status.HTTP_204_NO_CONTENT)