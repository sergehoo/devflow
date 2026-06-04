"""
PR-REC-1 : module Enregistrement audio + transcription IA des réunions.

Migration ENTIÈREMENT ADDITIVE :
  * 5 nouvelles tables : MeetingRecording, SpeakerSegment,
    DetectedSpeaker, SpeakerParticipantMapping, RecordingAIExtraction
  * Aucune modification d'une table existante
  * Aucune destruction de données
  * Réversible sans perte

NOTE STORAGE : les FileField ``audio_file`` et ``sample_audio`` utilisent
un storage 'recordings' dédié (cf. settings.STORAGES). En dev local sans
MinIO configuré, le fallback est ``default_storage`` (FileField local).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import project.models as project_models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0036_meeting_series_and_reviews"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── MeetingRecording ─────────────────────────────────────────
        migrations.CreateModel(
            name="MeetingRecording",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("audio_file", models.FileField(
                    blank=True, max_length=600, null=True,
                    storage=project_models._recording_storage,
                    upload_to=project_models._audio_upload_path,
                )),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("mime_type", models.CharField(blank=True, max_length=80)),
                ("duration_seconds", models.FloatField(default=0)),
                ("file_size_bytes", models.BigIntegerField(default=0)),
                ("status", models.CharField(
                    choices=[
                        ("draft", "Brouillon"),
                        ("uploading", "Upload en cours"),
                        ("uploaded", "Audio uploadé"),
                        ("transcribing", "Transcription en cours"),
                        ("diarizing", "Détection des voix"),
                        ("waiting_speaker_mapping", "Identification voix"),
                        ("generating_summary", "Génération du compte-rendu"),
                        ("completed", "Terminé"),
                        ("failed", "Échec"),
                        ("cancelled", "Annulé"),
                    ],
                    db_index=True, default="draft", max_length=30,
                )),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("consent_acknowledged", models.BooleanField(default=False)),
                ("consent_acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("full_transcript", models.TextField(blank=True)),
                ("final_transcript", models.TextField(blank=True)),
                ("summary_markdown", models.TextField(blank=True)),
                ("transcription_provider", models.CharField(blank=True, max_length=40)),
                ("summary_provider", models.CharField(blank=True, max_length=40)),
                ("tokens_used", models.PositiveIntegerField(default=0)),
                ("meeting", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="recordings",
                    to="project.projectmeeting",
                )),
                ("recorded_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="recordings_made",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="meeting_recordings",
                    to="project.workspace",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="meetingrecording",
            index=models.Index(fields=["workspace", "status"], name="recording_ws_status_idx"),
        ),
        migrations.AddIndex(
            model_name="meetingrecording",
            index=models.Index(fields=["meeting", "-created_at"], name="recording_meet_date_idx"),
        ),

        # ─── SpeakerSegment ───────────────────────────────────────────
        migrations.CreateModel(
            name="SpeakerSegment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("speaker_label", models.CharField(max_length=40)),
                ("start_seconds", models.FloatField(default=0)),
                ("end_seconds", models.FloatField(default=0)),
                ("text", models.TextField()),
                ("confidence", models.FloatField(default=0)),
                ("recording", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="segments",
                    to="project.meetingrecording",
                )),
            ],
            options={"ordering": ["recording", "start_seconds", "id"]},
        ),
        migrations.AddIndex(
            model_name="speakersegment",
            index=models.Index(fields=["recording", "speaker_label"], name="segment_rec_label_idx"),
        ),
        migrations.AddIndex(
            model_name="speakersegment",
            index=models.Index(fields=["recording", "start_seconds"], name="segment_rec_start_idx"),
        ),

        # ─── DetectedSpeaker ──────────────────────────────────────────
        migrations.CreateModel(
            name="DetectedSpeaker",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("speaker_label", models.CharField(db_index=True, max_length=40)),
                ("display_name", models.CharField(blank=True, max_length=200)),
                ("total_duration_seconds", models.FloatField(default=0)),
                ("total_segments", models.PositiveIntegerField(default=0)),
                ("sample_audio", models.FileField(
                    blank=True, max_length=600, null=True,
                    storage=project_models._recording_storage,
                    upload_to=project_models._speaker_sample_upload_path,
                )),
                ("sample_start_seconds", models.FloatField(default=0)),
                ("sample_end_seconds", models.FloatField(default=0)),
                ("is_confirmed", models.BooleanField(default=False)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("confirmed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="confirmed_speaker_mappings",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("mapped_participant", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="speaker_mappings",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("recording", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="speakers",
                    to="project.meetingrecording",
                )),
            ],
            options={"ordering": ["recording", "speaker_label"]},
        ),
        migrations.AddConstraint(
            model_name="detectedspeaker",
            constraint=models.UniqueConstraint(
                fields=("recording", "speaker_label"),
                name="uniq_detected_speaker_per_recording",
            ),
        ),
        migrations.AddIndex(
            model_name="detectedspeaker",
            index=models.Index(
                fields=["recording", "is_confirmed"],
                name="detected_spk_confirmed_idx",
            ),
        ),

        # ─── SpeakerParticipantMapping ────────────────────────────────
        migrations.CreateModel(
            name="SpeakerParticipantMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("speaker_label", models.CharField(max_length=40)),
                ("is_active", models.BooleanField(default=True)),
                ("note", models.TextField(blank=True)),
                ("confirmed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="speaker_mappings_made",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("participant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="received_speaker_mappings",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("recording", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="speaker_mappings",
                    to="project.meetingrecording",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="speakerparticipantmapping",
            index=models.Index(
                fields=["recording", "speaker_label", "is_active"],
                name="spk_map_rec_active_idx",
            ),
        ),

        # ─── RecordingAIExtraction ────────────────────────────────────
        migrations.CreateModel(
            name="RecordingAIExtraction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(
                    choices=[
                        ("decision", "Décision"),
                        ("action", "Action"),
                        ("risk", "Risque"),
                        ("note", "Note"),
                    ],
                    max_length=15,
                )),
                ("title", models.CharField(max_length=250)),
                ("description", models.TextField(blank=True)),
                ("assignee_hint", models.CharField(blank=True, max_length=120)),
                ("due_date_hint", models.CharField(blank=True, max_length=80)),
                ("priority_hint", models.CharField(blank=True, max_length=15)),
                ("confidence", models.FloatField(default=0)),
                ("is_accepted", models.BooleanField(default=False)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("created_action_item", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="source_extraction",
                    to="project.meetingactionitem",
                )),
                ("recording", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_extractions",
                    to="project.meetingrecording",
                )),
            ],
            options={"ordering": ["recording", "kind", "id"]},
        ),
        migrations.AddIndex(
            model_name="recordingaiextraction",
            index=models.Index(
                fields=["recording", "kind", "is_accepted"],
                name="ai_extract_rec_kind_idx",
            ),
        ),
    ]
