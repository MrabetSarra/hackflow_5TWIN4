"""
workshops/admin.py
==================
Interface d'administration Django pour le module Ateliers.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Badge, BadgeAward, Booking, Certificate, Workshop, WorkshopActivity,
    WorkshopFavorite
)


# ---------------------------------------------------------------------------
# Inline : Bookings dans Workshop
# ---------------------------------------------------------------------------

class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    readonly_fields = ('user', 'status', 'seat_number', 'booked_at',
                       'attended_at', 'rating', 'checkin_token')
    fields = ('user', 'status', 'seat_number', 'rating', 'booked_at',
              'attended_at')
    can_delete = False


class CertificateInline(admin.TabularInline):
    model = Certificate
    extra = 0
    readonly_fields = ('user', 'code', 'serial', 'hours', 'issued_at',
                       'is_revoked')
    can_delete = False


# ---------------------------------------------------------------------------
# Workshop
# ---------------------------------------------------------------------------

@admin.register(Workshop)
class WorkshopAdmin(admin.ModelAdmin):
    list_display   = ('title', 'mode', 'level', 'starts_at', 'capacity',
                      'confirmed_count', 'fill_rate_display', 'is_open',
                      'created_by')
    list_filter    = ('mode', 'level', 'is_open', 'starts_at')
    search_fields  = ('title', 'speaker_name', 'speaker_company',
                      'description')
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'starts_at'
    readonly_fields = ('created_at', 'confirmed_count', 'seats_left',
                       'waitlist_count', 'attendee_count', 'average_rating',
                       'fill_rate')
    fieldsets = (
        ('Identité', {
            'fields': ('title', 'slug', 'description', 'speaker_name',
                       'speaker_company', 'cover_image')
        }),
        ('Classification', {
            'fields': ('topic_tags', 'level', 'mode')
        }),
        ('Diffusion', {
            'fields': ('room', 'meeting_url', 'replay_url',
                       'replay_duration', 'available_until')
        }),
        ('Créneau & capacité', {
            'fields': ('starts_at', 'ends_at', 'capacity', 'is_open')
        }),
        ('Statistiques (lecture seule)', {
            'fields': ('confirmed_count', 'seats_left', 'waitlist_count',
                       'attendee_count', 'average_rating', 'fill_rate'),
            'classes': ('collapse',)
        }),
        ('Méta', {
            'fields': ('created_by', 'created_at')
        }),
    )
    inlines        = [BookingInline, CertificateInline]
    actions        = ['close_workshops', 'open_workshops']

    def confirmed_count(self, obj):
        return obj.confirmed_count
    confirmed_count.short_description = 'Confirmés'

    def fill_rate_display(self, obj):
        rate = obj.fill_rate
        if rate is None:
            return '∞'
        color = 'green' if rate < 80 else ('orange' if rate < 100 else 'red')
        return format_html('<span style="color:{}">{} %</span>', color, rate)
    fill_rate_display.short_description = 'Remplissage'

    @admin.action(description='Fermer les inscriptions')
    def close_workshops(self, request, queryset):
        updated = queryset.update(is_open=False)
        self.message_user(request, f'{updated} atelier(s) fermé(s).')

    @admin.action(description='Ouvrir les inscriptions')
    def open_workshops(self, request, queryset):
        updated = queryset.update(is_open=True)
        self.message_user(request, f'{updated} atelier(s) ouvert(s).')


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display   = ('user', 'workshop', 'status', 'seat_number',
                      'rating', 'booked_at', 'attended_at')
    list_filter    = ('status', 'workshop__mode', 'booked_at')
    search_fields  = ('user__username', 'user__first_name', 'user__last_name',
                      'workshop__title')
    readonly_fields = ('checkin_token', 'booked_at', 'cancelled_at',
                       'attended_at')
    raw_id_fields  = ('user', 'workshop')
    date_hierarchy = 'booked_at'


# ---------------------------------------------------------------------------
# WorkshopFavorite
# ---------------------------------------------------------------------------

@admin.register(WorkshopFavorite)
class WorkshopFavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'workshop', 'created_at')
    search_fields = ('user__username', 'user__email', 'workshop__title')
    raw_id_fields = ('user', 'workshop')
    date_hierarchy = 'created_at'


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------

@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display   = ('code', 'serial', 'user', 'workshop', 'hours_display',
                      'issued_at', 'is_revoked')
    list_filter    = ('is_revoked', 'issued_at', 'workshop__mode')
    search_fields  = ('code', 'user__username', 'workshop__title')
    readonly_fields = ('code', 'serial', 'issued_at', 'hours_display')
    raw_id_fields  = ('user', 'workshop')
    actions        = ['revoke_certificates', 'unrevoke_certificates']

    def hours_display(self, obj):
        return obj.hours_display
    hours_display.short_description = 'Durée'

    @admin.action(description='Révoquer les certificats sélectionnés')
    def revoke_certificates(self, request, queryset):
        updated = queryset.update(is_revoked=True)
        self.message_user(request, f'{updated} certificat(s) révoqué(s).')

    @admin.action(description='Restaurer les certificats révoqués')
    def unrevoke_certificates(self, request, queryset):
        updated = queryset.update(is_revoked=False)
        self.message_user(request, f'{updated} certificat(s) restauré(s).')


# ---------------------------------------------------------------------------
# Badge & BadgeAward
# ---------------------------------------------------------------------------

class BadgeAwardInline(admin.TabularInline):
    model = BadgeAward
    extra = 0
    readonly_fields = ('user', 'awarded_at', 'reason', 'workshop')
    can_delete = False


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'icon', 'award_count')
    search_fields = ('name', 'slug', 'description')
    inlines       = [BadgeAwardInline]
    prepopulated_fields = {'slug': ('name',)}

    def award_count(self, obj):
        return obj.awards.count()
    award_count.short_description = 'Décerné à'


@admin.register(BadgeAward)
class BadgeAwardAdmin(admin.ModelAdmin):
    list_display  = ('user', 'badge', 'workshop', 'awarded_at', 'reason')
    list_filter   = ('badge', 'awarded_at')
    search_fields = ('user__username', 'badge__name')
    raw_id_fields = ('user', 'workshop')


# ---------------------------------------------------------------------------
# WorkshopActivity
# ---------------------------------------------------------------------------

@admin.register(WorkshopActivity)
class WorkshopActivityAdmin(admin.ModelAdmin):
    list_display  = ('kind', 'workshop', 'user', 'detail', 'created_at')
    list_filter   = ('kind', 'created_at')
    search_fields = ('workshop__title', 'user__username', 'detail')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
