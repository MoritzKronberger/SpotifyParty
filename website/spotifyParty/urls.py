from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('settings', views.settings, name='settings'),
    path('login/', views.login_spotify, name='login_spotify'),
    path('redirect/', views.redirect_page),
    path('<str:room_name>/', views.party_session, name='party_session')
]
