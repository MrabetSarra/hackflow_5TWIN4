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
    path('two-factor/verify/', views.two_factor_verify_view, name='two_factor_verify'),
    path('two-factor/setup/', views.two_factor_setup_view, name='two_factor_setup'),
    path('two-factor/disable/', views.two_factor_disable_view, name='two_factor_disable'),
    path('two-factor/backup-codes/', views.two_factor_backup_codes_view, name='two_factor_backup_codes'),
    path('oauth/login/<str:provider>/', views.oauth_login_view, name='oauth_login'),
    path('oauth/callback/<str:provider>/', views.oauth_callback_view, name='oauth_callback'),
    path('oauth/select-role/', views.oauth_select_role_view, name='oauth_select_role'),
]
