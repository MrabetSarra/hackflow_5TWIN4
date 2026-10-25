import calendar
from collections import defaultdict
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from .models import Registration, ScheduleItem


def parse_month(value, today):
    try:
        year, month = (int(part) for part in value.split('-'))
        first = date(year, month, 1)
    except (ValueError, AttributeError):
        return today.replace(day=1)
    return first if 2000 <= first.year <= 2100 else today.replace(day=1)


def shift_month(first, delta):
    index = first.month - 1 + delta
    return date(first.year + index // 12, index % 12 + 1, 1)


def _fmt(moment):
    return date_format(timezone.localtime(moment), 'd/m/Y H:i')


def build_agenda(registrations, first, today):
    """Calendrier mensuel des inscriptions confirmées : hackathons, étapes du programme, conflits et prochain événement."""
    now = timezone.now()
    confirmed = [r for r in registrations if r.status == Registration.Status.CONFIRMED]
    weeks = calendar.Calendar(0).monthdatescalendar(first.year, first.month)
    grid_start, grid_end = weeks[0][0], weeks[-1][-1]
    entries = defaultdict(list)

    for reg in confirmed:
        h = reg.challenge.hackathon
        start = timezone.localtime(h.starts_at).date()
        end = timezone.localtime(h.ends_at).date()
        day = max(start, grid_start)
        while day <= min(end, grid_end):
            entries[day].append({
                'kind': 'hackathon', 'title': h.title, 'challenge': reg.challenge.title, 'color': h.stage_color,
                'when': f'{_fmt(h.starts_at)} → {_fmt(h.ends_at)}', 'place': h.location,
                'url': reverse('hackathons:hackathon_detail', args=[h.slug]),
                'cancel_url': reverse('hackathons:registration_cancel', args=[reg.pk]) if now < h.starts_at else '',
                'first': day == start,
            })
            day += timedelta(days=1)

    by_challenge = {r.challenge_id: r for r in confirmed}
    steps = ScheduleItem.objects.filter(
        challenge_id__in=by_challenge, starts_at__date__gte=grid_start, starts_at__date__lte=grid_end,
    ).select_related('challenge', 'challenge__hackathon')
    for step in steps:
        h = step.challenge.hackathon
        when = _fmt(step.starts_at) + (f' → {_fmt(step.ends_at)}' if step.ends_at else '')
        entries[timezone.localtime(step.starts_at).date()].append({
            'kind': 'schedule', 'title': step.title, 'challenge': step.challenge.title, 'color': 'info',
            'time': timezone.localtime(step.starts_at).strftime('%H:%M'), 'when': when, 'place': step.location,
            'url': reverse('hackathons:hackathon_detail', args=[h.slug]), 'cancel_url': '',
        })
    for items in entries.values():
        items.sort(key=lambda e: (e['kind'] != 'hackathon', e.get('time', '')))

    rows = [
        [{'date': d, 'in_month': d.month == first.month, 'is_today': d == today, 'entries': entries.get(d, [])} for d in week]
        for week in weeks
    ]

    hackathons = [r.challenge.hackathon for r in confirmed]
    conflicts = [
        f'« {a.title} » et « {b.title} » se déroulent en même temps.'
        for i, a in enumerate(hackathons) for b in hackathons[i + 1:]
        if a.starts_at <= b.ends_at and b.starts_at <= a.ends_at
    ]

    upcoming = sorted((h for h in hackathons if h.ends_at >= now), key=lambda h: h.starts_at)
    next_up = None
    if upcoming:
        h = upcoming[0]
        started = h.starts_at <= now
        next_up = {
            'title': h.title, 'url': reverse('hackathons:hackathon_detail', args=[h.slug]),
            'target': (h.ends_at if started else h.starts_at).isoformat(), 'label': 'Fin dans' if started else 'Début dans',
        }

    return {
        'weeks': rows, 'month_label': date_format(first, 'F Y').capitalize(),
        'prev_month': shift_month(first, -1).strftime('%Y-%m'), 'next_month': shift_month(first, 1).strftime('%Y-%m'),
        'is_current_month': first == today.replace(day=1), 'conflicts': conflicts, 'next_up': next_up,
        'has_events': bool(confirmed),
    }
