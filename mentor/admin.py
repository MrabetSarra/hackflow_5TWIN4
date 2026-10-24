from django.contrib import admin

from .models import Criterion


@admin.register(Criterion)
class CriterionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'weight', 'max_score', 'scope', 'order', 'is_active')
    list_editable = ('weight', 'order', 'is_active')
    list_filter = ('scope', 'is_active')
    search_fields = ('name', 'code')

    def has_delete_permission(self, request, obj=None):
        # La grille doit toujours exister : un critère se désactive, il ne se supprime pas.
        return False
