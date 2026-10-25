from tempfile import SpooledTemporaryFile

from django.conf import settings
from django.core.files import File
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateCVStorage(FileSystemStorage):
    """Keep sensitive files private, using authenticated Cloudinary assets when configured."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('location', settings.PRIVATE_MEDIA_ROOT)
        kwargs.setdefault('base_url', None)
        super().__init__(*args, **kwargs)

    @staticmethod
    def _cloudinary_enabled():
        return bool(settings.CLOUDINARY_URL)

    @staticmethod
    def _cloudinary_public_id(name):
        return name.replace('\\', '/')

    @staticmethod
    def _cloudinary_resource(name):
        import cloudinary.api

        return cloudinary.api.resource(
            PrivateCVStorage._cloudinary_public_id(name),
            resource_type='raw', type='authenticated',
        )

    def _open(self, name, mode='rb'):
        if self._cloudinary_enabled():
            import cloudinary.utils
            import requests

            public_id = self._cloudinary_public_id(name)
            url, _options = cloudinary.utils.cloudinary_url(
                public_id, resource_type='raw', type='authenticated',
                sign_url=True, secure=True,
            )
            temporary_file = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode='w+b')
            try:
                with requests.get(url, stream=True, timeout=(10, 120)) as response:
                    if response.status_code == 404:
                        raise FileNotFoundError(name)
                    response.raise_for_status()
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            temporary_file.write(chunk)
                temporary_file.seek(0)
                return File(temporary_file, name=name)
            except FileNotFoundError:
                # Supports files already present in the private local directory during rollout.
                temporary_file.close()
            except Exception:
                temporary_file.close()
                raise
        try:
            return super()._open(name, mode)
        except FileNotFoundError:
            # Team documents used to be written under public MEDIA_ROOT. Keep them readable
            # during rollout, but only via the membership-checked download view.
            if name.replace('\\', '/').startswith('team_resources/'):
                legacy_storage = FileSystemStorage(location=settings.MEDIA_ROOT, base_url=None)
                return legacy_storage._open(name, mode)
            raise

    def _save(self, name, content):
        if self._cloudinary_enabled():
            import cloudinary.uploader

            options = {
                'resource_type': 'raw',
                'type': 'authenticated',
                'public_id': self._cloudinary_public_id(name),
                'overwrite': False,
            }
            response = cloudinary.uploader.upload(content, **options)
            return response['public_id']
        return super()._save(name, content)

    def exists(self, name):
        if self._cloudinary_enabled():
            try:
                self._cloudinary_resource(name)
                return True
            except Exception as error:
                if getattr(error, 'http_code', None) != 404:
                    raise
        return super().exists(name)

    def size(self, name):
        if self._cloudinary_enabled():
            try:
                return self._cloudinary_resource(name)['bytes']
            except Exception as error:
                if getattr(error, 'http_code', None) != 404:
                    raise
        return super().size(name)

    def delete(self, name):
        if self._cloudinary_enabled():
            import cloudinary.uploader

            try:
                self._cloudinary_resource(name)
            except Exception as error:
                if getattr(error, 'http_code', None) != 404:
                    raise
            else:
                cloudinary.uploader.destroy(
                    self._cloudinary_public_id(name), invalidate=True,
                    resource_type='raw', type='authenticated',
                )
                return
        return super().delete(name)

    def url(self, name):
        if self._cloudinary_enabled():
            raise ValueError('Private files must be served through an authorized application view.')
        return super().url(name)

    def path(self, name):
        if self._cloudinary_enabled():
            raise NotImplementedError('Cloudinary files do not have a local filesystem path.')
        return super().path(name)
