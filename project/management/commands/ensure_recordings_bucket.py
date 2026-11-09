"""
Crée le bucket MinIO/S3 des enregistrements audio s'il n'existe pas (idempotent).

    python manage.py ensure_recordings_bucket

Lancée au démarrage de ``devflowweb`` (docker-compose.yml). Sans
RECORDING_S3_BUCKET / S3_ENDPOINT, les enregistrements utilisent le stockage
local : rien à faire.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

MISSING = {"404", "NoSuchBucket", "NotFound"}


def recordings_s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=settings.MINIO_REGION,
        config=Config(
            signature_version="s3v4", s3={"addressing_style": "path"},  # MinIO
            connect_timeout=5, read_timeout=15, retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


class Command(BaseCommand):
    help = "Crée le bucket des enregistrements audio (MinIO/S3) s'il est absent."

    def handle(self, *args, **options):
        bucket = settings.MINIO_RECORDINGS_BUCKET
        if not (bucket and settings.MINIO_ENDPOINT):
            self.stdout.write("Stockage S3 des enregistrements non configuré (stockage local) : rien à faire.")
            return
        from botocore.exceptions import ClientError

        client = recordings_s3_client()
        try:
            client.head_bucket(Bucket=bucket)
            self.stdout.write(f"Bucket des enregistrements « {bucket} » présent.")
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in MISSING:
                raise CommandError(f"Bucket « {bucket} » inaccessible ({code or exc}) : vérifiez les identifiants S3.")
        client.create_bucket(Bucket=bucket)
        self.stdout.write(self.style.SUCCESS(f"Bucket des enregistrements « {bucket} » créé."))
