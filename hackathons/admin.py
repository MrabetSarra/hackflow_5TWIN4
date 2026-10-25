from django.contrib import admin

from . import models

for model in (
    models.Track, models.HackathonProfile, models.Challenge, models.Registration, models.ScheduleItem,
    models.FlashAnnouncement, models.HackathonResource,
):
    admin.site.register(model)
