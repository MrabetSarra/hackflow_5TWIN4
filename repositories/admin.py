from django.contrib import admin

from .models import AIUsageLog, MergeRequest, MergeRequestComment, MergeSession, RepoActivity, Repository, RepositoryFileComment


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'team', 'default_branch', 'created_by', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'slug', 'team__name')
    readonly_fields = ('created_at',)


admin.site.register([MergeRequest, MergeRequestComment, MergeSession, RepoActivity, AIUsageLog, RepositoryFileComment])
