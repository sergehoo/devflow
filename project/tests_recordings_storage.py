"""
Stockage des enregistrements audio (MinIO/S3) : création idempotente du bucket
(``ensure_recordings_bucket``) et message d'erreur d'upload sans détail interne.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_recordings_storage
"""

import sys
import types
from io import StringIO
from unittest import mock

try:
    from botocore.exceptions import ClientError
    FAKE_BOTOCORE = {}
except ImportError:  # venv local sans django-storages[s3] (présent en production)
    class ClientError(Exception):
        def __init__(self, response, operation):
            super().__init__(operation)
            self.response = response

    _exceptions = types.ModuleType("botocore.exceptions")
    _exceptions.ClientError = ClientError
    FAKE_BOTOCORE = {"botocore": types.ModuleType("botocore"), "botocore.exceptions": _exceptions}
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from project import models as dm
from project.tests_api_meetings import MeetingFixture

S3 = dict(MINIO_RECORDINGS_BUCKET="devflow-recordings", MINIO_ENDPOINT="http://minio:9000",
          MINIO_ACCESS_KEY="k", MINIO_SECRET_KEY="s", MINIO_REGION="eu-west-1")
CLIENT = "project.management.commands.ensure_recordings_bucket.recordings_s3_client"


def client_error(code):
    return ClientError({"Error": {"Code": code}}, "HeadBucket")


class EnsureRecordingsBucketTests(SimpleTestCase):
    def run_command(self):
        out = StringIO()
        with mock.patch.dict(sys.modules, FAKE_BOTOCORE):
            call_command("ensure_recordings_bucket", stdout=out)
        return out.getvalue()

    @override_settings(MINIO_RECORDINGS_BUCKET="", MINIO_ENDPOINT="")
    def test_local_storage_needs_nothing(self):
        with mock.patch(CLIENT) as factory:
            self.assertIn("rien à faire", self.run_command())
        factory.assert_not_called()

    @override_settings(**S3)
    def test_missing_bucket_is_created(self):
        with mock.patch(CLIENT) as factory:
            factory.return_value.head_bucket.side_effect = client_error("404")
            self.assertIn("créé", self.run_command())
        factory.return_value.create_bucket.assert_called_once_with(Bucket="devflow-recordings")

    @override_settings(**S3)
    def test_existing_bucket_is_left_untouched(self):
        with mock.patch(CLIENT) as factory:
            self.assertIn("présent", self.run_command())
        factory.return_value.create_bucket.assert_not_called()

    @override_settings(**S3)
    def test_access_denied_is_reported_not_masked(self):
        with mock.patch(CLIENT) as factory:
            factory.return_value.head_bucket.side_effect = client_error("403")
            with self.assertRaises(CommandError):
                self.run_command()
        factory.return_value.create_bucket.assert_not_called()


class UploadStorageErrorTests(MeetingFixture):
    def test_storage_failure_returns_actionable_message_without_internals(self):
        audio = SimpleUploadedFile("recording.webm", b"\x1aE\xdf\xa3fake", content_type="audio/webm")
        boom = Exception("An error occurred (NoSuchBucket) when calling the PutObject operation: devflow-recordings")
        with mock.patch("django.db.models.fields.files.FieldFile.save", side_effect=boom), \
                mock.patch("project.tasks.process_recording_task.delay") as delay:
            res = self.web(self.dev).post(f"/api/v1/meetings/{self.meeting.pk}/recordings/upload/",
                                          {"audio": audio, "duration_seconds": "3", "consent_acknowledged": "true"})
        self.assertEqual(res.status_code, 502)
        detail = res.json()["detail"]
        self.assertIn("stockage des enregistrements est indisponible", detail)
        self.assertNotIn("NoSuchBucket", detail)
        self.assertNotIn("devflow-recordings", detail)
        delay.assert_not_called()
        self.assertTrue(dm.MeetingRecording.objects.filter(pk=res.json()["recording_id"]).exists())
