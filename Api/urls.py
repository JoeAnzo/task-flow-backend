from django.urls import path,re_path
from . import views

urlpatterns = [
    path('todos/',views.list_create_todo,name='list_create_todo'),
    path('todos/<int:pk>/',views.detail_update_delete_todo,name='detail_update_delete_todo'),
    re_path(r'^(?P<resource>.*)$', views.catch_all_views, name='catch_all_views'),
]