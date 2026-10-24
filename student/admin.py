from django.contrib import admin

from .models import (Announcement, DirectMessage, Hackathon, MentorRequest, Milestone, Notification, Resource,
                     Sprint, Submission, Task, Team, TeamInvitation, TeamMembership)


@admin.register(Hackathon)
class HackathonAdmin(admin.ModelAdmin):
    list_display = ('name', 'edition', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('is_active',)


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ('title', 'hackathon', 'due_at', 'status', 'order')
    list_filter = ('status', 'hackathon')


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'hackathon', 'category', 'captain', 'table_number')
    list_filter = ('hackathon', 'category')


for model in (TeamMembership, TeamInvitation, Resource, Task, Submission, MentorRequest, Notification, DirectMessage, Sprint):
    admin.site.register(model)
admin.site.register(Announcement)
