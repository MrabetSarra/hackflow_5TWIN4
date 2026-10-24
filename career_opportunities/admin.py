from django.contrib import admin
from .models import ApplicationHistory, CareerApplication, Opportunity, OpportunitySkill, SavedOpportunity


class SkillInline(admin.TabularInline):
    model = OpportunitySkill
    extra = 0


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'opportunity_type', 'status', 'deadline')
    list_filter = ('status', 'opportunity_type', 'work_mode')
    search_fields = ('title', 'company', 'description')
    inlines = [SkillInline]


admin.site.register((CareerApplication, ApplicationHistory, SavedOpportunity))
