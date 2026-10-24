from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from career_opportunities.models import Opportunity, SavedOpportunity
from student.models import Notification


class Command(BaseCommand):
    help = 'Notify students who saved an opportunity closing within seven days.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        offers = Opportunity.objects.filter(status='published', deadline__gte=today, deadline__lte=today + timedelta(days=7))
        created = 0
        for offer in offers:
            for saved in SavedOpportunity.objects.filter(opportunity=offer).select_related('user'):
                title = 'Opportunity deadline approaching'
                message = f'{offer.title} at {offer.company} closes on {offer.deadline}.'
                url = f'/careers/{offer.pk}/'
                if not saved.user.student_notifications.filter(title=title, message=message, url=url).exists():
                    Notification.objects.create(user=saved.user, title=title, message=message, icon='bi-briefcase-fill', url=url)
                    created += 1
        self.stdout.write(f'{created} deadline notification(s) created.')
