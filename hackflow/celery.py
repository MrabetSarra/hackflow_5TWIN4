"""Celery application with an eager fallback before the optional dependency is installed."""
from django.conf import settings

try:
    from celery import Celery
except ImportError:
    class _LocalTask:
        def __init__(self, function):
            self.function = function
            self.__name__ = function.__name__

        def __call__(self, *args, **kwargs):
            return self.function(*args, **kwargs)

        def delay(self, *args, **kwargs):
            if not settings.CELERY_TASK_ALWAYS_EAGER:
                raise RuntimeError('Install Celery and start a worker to run background tasks.')
            return self.function(*args, **kwargs)

    class _LocalCelery:
        def task(self, *args, **kwargs):
            def decorate(function):
                return _LocalTask(function)
            return decorate

        def config_from_object(self, *args, **kwargs):
            return None

        def autodiscover_tasks(self, *args, **kwargs):
            return None

    celery_app = _LocalCelery()
else:
    celery_app = Celery('hackflow')
    celery_app.config_from_object('django.conf:settings', namespace='CELERY')
    celery_app.autodiscover_tasks()
