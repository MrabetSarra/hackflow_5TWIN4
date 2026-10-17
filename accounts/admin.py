from django.contrib import admin
<<<<<<< HEAD

# Register your models here.
=======
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class HackFlowUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Profil HackFlow', {'fields': ('role', 'bio', 'school', 'study_level', 'skills', 'specialty', 'github_url', 'linkedin_url', 'created_at')}),
    )
    readonly_fields = ('created_at',)
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'is_staff')
    list_filter = ('role', 'is_active', 'is_staff')
>>>>>>> gestion_evenements
