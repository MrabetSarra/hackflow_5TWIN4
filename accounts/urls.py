from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password-reset/', views.password_reset_request_view, name='password_reset_request'),
    path('password-reset/verify/', views.password_reset_verify_view, name='password_reset_verify'),
    path('register/', views.register_view, name='register'),
    path('register/<str:role>/', views.register_role_view, name='register_role'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/cv/', views.download_cv_view, name='download_cv'),
]
