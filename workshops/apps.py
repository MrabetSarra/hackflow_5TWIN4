from django.apps import AppConfig


class WorkshopsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'workshops'
    verbose_name = 'Ateliers & Certificats'

    def ready(self):
        # Connecte les signaux (badges, etc.)
        import workshops.signals  # noqa: F401
