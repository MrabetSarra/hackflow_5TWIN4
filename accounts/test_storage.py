from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, override_settings

from career_opportunities.models import CareerApplication
from student.models import Resource, Submission
from .models import User
from .storage import PrivateCVStorage


class MediaStorageTests(SimpleTestCase):
    def test_static_files_keep_using_whitenoise(self):
        self.assertEqual(
            settings.STORAGES['staticfiles']['BACKEND'],
            'whitenoise.storage.CompressedStaticFilesStorage',
        )

    def test_profile_photos_are_public_media_and_other_uploads_use_private_storage(self):
        self.assertIs(User._meta.get_field('profile_photo').storage, default_storage)
        self.assertIsInstance(User._meta.get_field('cv').storage, PrivateCVStorage)
        self.assertIsInstance(CareerApplication._meta.get_field('cv').storage, PrivateCVStorage)
        self.assertIsInstance(Submission._meta.get_field('file').storage, PrivateCVStorage)
        self.assertIsInstance(Resource._meta.get_field('document').storage, PrivateCVStorage)

    @override_settings(CLOUDINARY_URL='')
    def test_private_storage_uses_local_filesystem_without_cloudinary(self):
        with TemporaryDirectory() as directory:
            storage = PrivateCVStorage(location=directory, base_url=None)
            name = storage.save('resumes/test.pdf', ContentFile(b'%PDF-test'))
            with storage.open(name, 'rb') as stored:
                self.assertEqual(stored.read(), b'%PDF-test')

    @override_settings(CLOUDINARY_URL='cloudinary://test-key:test-secret@test-cloud')
    def test_private_cloudinary_uploads_are_authenticated_raw_assets(self):
        storage = PrivateCVStorage()
        with patch(
            'cloudinary.uploader.upload',
            return_value={'public_id': 'private/resumes/test.pdf'},
        ) as upload:
            result = storage._save('private/resumes/test.pdf', ContentFile(b'%PDF-test'))

        self.assertEqual(result, 'private/resumes/test.pdf')
        self.assertEqual(upload.call_args.kwargs['resource_type'], 'raw')
        self.assertEqual(upload.call_args.kwargs['type'], 'authenticated')
        self.assertFalse(upload.call_args.kwargs['overwrite'])

    @override_settings(CLOUDINARY_URL='cloudinary://test-key:test-secret@test-cloud')
    def test_private_cloudinary_storage_does_not_expose_public_file_urls(self):
        storage = PrivateCVStorage()
        with self.assertRaisesMessage(ValueError, 'authorized application view'):
            storage.url('resumes/test.pdf')

    def test_cloudinary_upload_failure_propagates_to_the_caller(self):
        cloudinary_settings = {
            'CLOUD_NAME': 'test-cloud', 'API_KEY': 'test-key', 'API_SECRET': 'test-secret',
            'PREFIX': '',
        }
        with override_settings(CLOUDINARY_STORAGE=cloudinary_settings):
            from cloudinary_storage.storage import MediaCloudinaryStorage

            storage = MediaCloudinaryStorage()
            with patch.object(storage, 'exists', return_value=False), patch(
                'cloudinary_storage.storage.cloudinary.uploader.upload',
                side_effect=RuntimeError('upload rejected'),
            ):
                with self.assertRaisesMessage(RuntimeError, 'upload rejected'):
                    storage.save('profile_photos/test.png', ContentFile(b'png data'))

    def test_public_cloudinary_storage_returns_provider_url_after_upload(self):
        cloudinary_settings = {
            'CLOUD_NAME': 'test-cloud', 'API_KEY': 'test-key', 'API_SECRET': 'test-secret',
            'PREFIX': '',
        }
        with override_settings(CLOUDINARY_STORAGE=cloudinary_settings):
            from cloudinary_storage.storage import MediaCloudinaryStorage

            storage = MediaCloudinaryStorage()
            with patch.object(storage, 'exists', return_value=False), patch(
                'cloudinary_storage.storage.cloudinary.uploader.upload',
                return_value={'public_id': 'profile_photos/test'},
            ) as upload, patch(
                'cloudinary_storage.storage.cloudinary.CloudinaryResource',
            ) as resource:
                resource.return_value.url = 'https://res.cloudinary.com/test-cloud/image/upload/profile_photos/test.png'
                name = storage.save('profile_photos/test.png', ContentFile(b'png data'))
                url = storage.url(name)

        self.assertEqual(name, 'profile_photos/test')
        self.assertEqual(url, 'https://res.cloudinary.com/test-cloud/image/upload/profile_photos/test.png')
        self.assertEqual(upload.call_args.kwargs['resource_type'], 'image')
        resource.assert_called_once_with('profile_photos/test', default_resource_type='image')

    def test_local_public_storage_remains_available_without_cloudinary(self):
        self.assertIn(
            settings.STORAGES['default']['BACKEND'],
            ('django.core.files.storage.FileSystemStorage',
             'cloudinary_storage.storage.MediaCloudinaryStorage'),
        )
