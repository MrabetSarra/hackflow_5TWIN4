from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateCVStorage(FileSystemStorage):
    """Store CVs outside the public MEDIA_URL tree."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('location', settings.PRIVATE_MEDIA_ROOT)
        kwargs.setdefault('base_url', None)
        super().__init__(*args, **kwargs)
