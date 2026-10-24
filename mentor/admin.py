from django.contrib import admin

from .models import (Criterion, EvaluationScore, MentorAssignment, MentorEvaluation, MentoringSession,
                     RequestTriage)


@admin.register(Criterion)
class CriterionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'weight', 'max_score', 'scope', 'order', 'is_active')
    list_editable = ('weight', 'order', 'is_active')
    list_filter = ('scope', 'is_active')
    search_fields = ('name', 'code')

    def has_delete_permission(self, request, obj=None):
        # La grille doit toujours exister : un critère se désactive, il ne se supprime pas.
        return False


@admin.register(MentorAssignment)
class MentorAssignmentAdmin(admin.ModelAdmin):
    list_display = ('mentor', 'team', 'source', 'created_at')
    list_filter = ('source', 'mentor')
    search_fields = ('mentor__username', 'team__name')


@admin.register(MentoringSession)
class MentoringSessionAdmin(admin.ModelAdmin):
    list_display = ('topic', 'team', 'mentor', 'starts_at', 'ends_at', 'status')
    list_filter = ('status', 'mentor')
    search_fields = ('topic', 'team__name')
    date_hierarchy = 'starts_at'


class EvaluationScoreInline(admin.TabularInline):
    model = EvaluationScore
    extra = 0


@admin.register(MentorEvaluation)
class MentorEvaluationAdmin(admin.ModelAdmin):
    list_display = ('submission', 'mentor', 'pitch_readiness', 'is_shared', 'total', 'updated_at')
    list_filter = ('pitch_readiness', 'is_shared', 'mentor')
    search_fields = ('submission__team__name', 'mentor__username')
    inlines = [EvaluationScoreInline]

    @admin.display(description='Total /20')
    def total(self, obj):
        return obj.weighted_total()


@admin.register(RequestTriage)
class RequestTriageAdmin(admin.ModelAdmin):
    list_display = ('help_request', 'status', 'suggested_category', 'suggested_urgency',
                    'corrected_category', 'corrected_urgency', 'latency_ms')
    list_filter = ('status', 'suggested_urgency')
    readonly_fields = ('created_at', 'updated_at')
