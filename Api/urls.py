from django.urls import path,re_path
from . import views

urlpatterns = [
    path('push/public-key/', views.push_public_key, name='push_public_key'),
    path('push/subscriptions/', views.save_push_subscription, name='save_push_subscription'),
    path('todos/',views.list_create_todo,name='list_create_todo'),
    path('todos/<int:pk>/',views.detail_update_delete_todo,name='detail_update_delete_todo'),
    path('nortifications/',views.list_nortifications,name='list_nortification'),
    path('nortifications/<int:pk>/read/',
    views.mark_nortification_read,
    name='mark_nortification_read'
    ),
    re_path(r'^(?P<resource>.*)$', views.catch_all_views, name='catch_all_views'),
]