"""
Pipeline complet du traitement d'un enregistrement (PR-REC-2).

Orchestre les étapes appelées par les tâches Celery :
  1. transcribe → SpeakerSegment + full_transcript
  2. aggregate_speakers → DetectedSpeaker
  3. extract_speaker_samples → sample_audio MP3
  4. status = WAITING_SPEAKER_MAPPING + notification

Après mapping utilisateur :
  5. build_final_transcript (déjà appelé par confirm_all_mappings)
  6. generate_summary → summary_markdown
  7. generate_extractions → RecordingAIExtraction
  8. status = COMPLETED + notification
"""

from __future__ import annotations

import logging
from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


def process_recording(recording_id: int) -> None:
    """Étape automatique post-upload : transcribe → diarize → samples."""
    from project.services.recording import transcription, diarization

    recording = dm.MeetingRecording.objects.filter(pk=recording_id).first()
    if recording is None:
        return

    recording.started_at = recording.started_at or timezone.now()
    recording.status = dm.MeetingRecording.Status.TRANSCRIBING
    recording.error_message = ""
    recording.save(update_fields=["status", "started_at", "error_message", "updated_at"])

    try:
        nb_segments = transcription.transcribe(recording)
        if nb_segments == 0 and not recording.error_message:
            recording.error_message = "Aucun segment transcrit."
        if recording.error_message:
            recording.status = dm.MeetingRecording.Status.FAILED
            recording.save(update_fields=["status", "updated_at"])
            return

        recording.status = dm.MeetingRecording.Status.DIARIZING
        recording.save(update_fields=["status", "updated_at"])

        diarization.aggregate_speakers_from_segments(recording)
        diarization.extract_speaker_samples(recording)

        recording.status = dm.MeetingRecording.Status.WAITING_SPEAKER_MAPPING
        recording.save(update_fields=["status", "updated_at"])

        _notify(recording, "speakers_ready")
    except Exception as exc:
        logger.exception("process_recording failed: %s", exc)
        recording.status = dm.MeetingRecording.Status.FAILED
        recording.error_message = f"{type(exc).__name__}: {exc}"
        recording.save(update_fields=["status", "error_message", "updated_at"])


def finalize_recording(recording_id: int) -> None:
    """Étape post-mapping : build final + summary + extractions."""
    from project.services.recording import speaker_mapping, ai_summary

    recording = dm.MeetingRecording.objects.filter(pk=recording_id).first()
    if recording is None:
        return

    recording.status = dm.MeetingRecording.Status.GENERATING_SUMMARY
    recording.save(update_fields=["status", "updated_at"])

    try:
        # Au cas où confirm_all_mappings n'a pas été appelé en amont
        if not recording.final_transcript:
            speaker_mapping.build_final_transcript(recording)
        ai_summary.generate_summary(recording)
        ai_summary.generate_extractions(recording)

        # PR-MEET-6 : détection automatique projets/sprints/milestones
        try:
            from project.services.recording import entity_detection
            entity_detection.detect_and_suggest(recording)
        except Exception as exc:
            logger.warning("entity_detection failed: %s", exc)

        recording.status = dm.MeetingRecording.Status.COMPLETED
        recording.completed_at = timezone.now()
        recording.save(update_fields=["status", "completed_at", "updated_at"])

        _notify(recording, "summary_ready")
    except Exception as exc:
        logger.exception("finalize_recording failed: %s", exc)
        recording.status = dm.MeetingRecording.Status.FAILED
        recording.error_message = f"{type(exc).__name__}: {exc}"
        recording.save(update_fields=["status", "error_message", "updated_at"])


def _notify(recording: dm.MeetingRecording, kind: str) -> None:
    """
    Notification in-app simple (Notification existant).
    Email pourra être ajouté ensuite.
    """
    try:
        meeting = recording.meeting
        url = f"/meetings/{meeting.pk}/recordings/{recording.pk}/"
        title_map = {
            "speakers_ready": "Voix détectées — identifiez-les",
            "summary_ready": "Compte-rendu IA prêt",
        }
        body_map = {
            "speakers_ready": f"L'enregistrement de « {meeting.title} » est prêt à être identifié.",
            "summary_ready": f"Le compte-rendu de « {meeting.title} » est disponible.",
        }
        title = title_map.get(kind, "Mise à jour enregistrement")
        body = body_map.get(kind, "")
        target_url = (
            f"{url}speakers/" if kind == "speakers_ready"
            else f"{url}summary/"
        )

        recipients = list(meeting.internal_participants.all())
        if recording.recorded_by and recording.recorded_by not in recipients:
            recipients.append(recording.recorded_by)
        for u in recipients:
            try:
                dm.Notification.objects.create(
                    recipient=u, workspace=recording.workspace,
                    notification_type=dm.Notification.NotificationType.MESSAGE,
                    title=title, body=body, url=target_url,
                    metadata={"recording_id": recording.pk, "kind": kind},
                )
            except Exception:
                continue

        # Email aux participants ayant un email valide
        _send_recording_email(recording, kind, title, body, target_url, recipients)
    except Exception as exc:
        logger.warning("recording notify failed: %s", exc)


def _send_recording_email(recording, kind, title, body, target_url, recipients):
    """Envoie un email d'information aux participants. Best-effort."""
    try:
        from django.conf import settings as dj_settings
        from django.core.mail import EmailMessage

        # Construit l'URL absolue si possible
        base = getattr(dj_settings, "SITE_URL", None) or getattr(
            dj_settings, "DEVFLOW_BASE_URL", None,
        ) or ""
        absolute_url = f"{base.rstrip('/')}{target_url}" if base else target_url

        from_email = getattr(dj_settings, "DEFAULT_FROM_EMAIL", None) \
            or getattr(dj_settings, "EMAIL_HOST_USER", None) \
            or "noreply@devflow.local"

        emails = [u.email for u in recipients if u and u.email]
        if not emails:
            return

        text_body = (
            f"{body}\n\n"
            f"→ {absolute_url}\n\n"
            f"— DevFlow"
        )
        msg = EmailMessage(
            subject=f"[DevFlow] {title}",
            body=text_body,
            from_email=from_email,
            to=[],
            bcc=emails,
        )
        msg.send(fail_silently=True)
    except Exception as exc:
        logger.warning("recording email send failed: %s", exc)
