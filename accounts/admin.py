from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class HackFlowUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Profil HackFlow', {'fields': ('role', 'bio', 'school', 'study_level', 'skills', 'specialty', 'preferred_roles', 'preferred_categories', 'availability_windows', 'github_url', 'linkedin_url', 'created_at')}),
    )
    readonly_fields = ('created_at',)
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active', 'is_staff')
