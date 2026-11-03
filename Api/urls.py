from django.urls import path
from . import views

urlpatterns = [
    path('todos/',views.list_create_todo,name='list_create_todo'),
    path('todos/<int:pk>/',views.detail_update_delete_todo,name='detail_update_delete_todo')
]