from django.urls import path
from . import views

urlpatterns = [
    path('', views.index_prototype, name='index'),
    path('settings', views.settings, name='settings'),
    path('party', views.party_session, name='party_session'),
    path('<str:room_name>/', views.room, name='room')
]