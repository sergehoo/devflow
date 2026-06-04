"""
Transcription audio via AssemblyAI (PR-REC-2).

API publique :
  * transcribe(recording) → list[SpeakerSegment] créés en DB + texte
    complet stocké dans recording.full_transcript

Détails techniques importants :
  * On télécharge l'audio en /tmp puis on passe le PATH LOCAL à AAI
    (pas une URL publique — le bucket MinIO peut être privé).
  * On NE spécifie PAS speech_model (défaut serveur universal-2).
  * Diarisation activée seulement si audio ≥ 30s (sinon AAI peut ne pas
    diariser et on aura 0 utterances → fallback SPEAKER_00).
  * Langue : settings.ASSEMBLYAI_LANGUAGE (default "fr").
  * Toutes les erreurs sont capturées et stockées dans recording.error_message.
"""

from __future__ import annotations

import logging
import os

from django.conf import settings
from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


def _ensure_aai_configured():
    try:
        import assemblyai as aai
    except ImportError:
        raise RuntimeError("assemblyai SDK not installed")
    api_key = getattr(settings, "ASSEMBLYAI_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not configured")
    aai.settings.api_key = api_key
    return aai


def transcribe(recording: dm.MeetingRecording) -> int:
    """
    Lance la transcription complète de l'enregistrement.

    Side-effects :
      * recording.full_transcript = texte concaténé
      * recording.transcription_provider = "assemblyai"
      * Crée N SpeakerSegment liés au recording

    Retourne le nombre de segments créés. 0 si transcription vide ou échec.
    """
    from project.services.recording.audio_processing import download_to_tempfile

    aai = _ensure_aai_configured()

    local_path = download_to_tempfile(recording)
    if local_path is None:
        recording.error_message = "Impossible de télécharger l'audio."
        recording.save(update_fields=["error_message", "updated_at"])
        return 0

    try:
        # Diarisation activée si durée >= 30s (sinon AAI peut ne rien diariser
        # sur de l'audio mono court → on évite un faux résultat vide).
        speaker_labels = (recording.duration_seconds or 0) >= 30

        config = aai.TranscriptionConfig(
            language_code=getattr(settings, "ASSEMBLYAI_LANGUAGE", "fr"),
            speaker_labels=speaker_labels,
            punctuate=True,
            format_text=True,
        )
        transcriber = aai.Transcriber()

        # Le SDK accepte un path local — il upload en interne.
        transcript = transcriber.transcribe(local_path, config)

        if transcript.status == aai.TranscriptStatus.error:
            err = getattr(transcript, "error", "Unknown AssemblyAI error")
            recording.error_message = f"AssemblyAI: {err}"
            recording.save(update_fields=["error_message", "updated_at"])
            return 0

        # Texte complet
        recording.full_transcript = (transcript.text or "").strip()
        recording.transcription_provider = "assemblyai"
        recording.save(update_fields=[
            "full_transcript", "transcription_provider", "updated_at",
        ])

        # Création des segments
        return _save_segments(recording, transcript)

    except Exception as exc:
        logger.exception("AssemblyAI transcription failed: %s", exc)
        recording.error_message = f"Transcription échouée: {exc}"
        recording.save(update_fields=["error_message", "updated_at"])
        return 0
    finally:
        try:
            os.remove(local_path)
        except Exception:
            pass


def _save_segments(recording: dm.MeetingRecording, transcript) -> int:
    """
    Crée les SpeakerSegment à partir du transcript.utterances. Si pas
    d'utterances (audio mono ou trop court), on crée un seul segment
    SPEAKER_00 avec le texte complet.
    """
    utterances = getattr(transcript, "utterances", None) or []
    segments = []

    if not utterances:
        # Fallback : 1 seul speaker
        text = (transcript.text or "").strip()
        if not text:
            return 0
        segments.append(dm.SpeakerSegment(
            recording=recording,
            speaker_label="SPEAKER_00",
            start_seconds=0,
            end_seconds=recording.duration_seconds or 0,
            text=text,
            confidence=getattr(transcript, "confidence", 0) or 0,
        ))
    else:
        for utt in utterances:
            # AssemblyAI labels sont 'A', 'B', etc. — on normalise en SPEAKER_X
            raw_label = getattr(utt, "speaker", "") or "?"
            label = _normalize_label(raw_label)
            start = (getattr(utt, "start", 0) or 0) / 1000.0
            end = (getattr(utt, "end", 0) or 0) / 1000.0
            text = (getattr(utt, "text", "") or "").strip()
            if not text:
                continue
            segments.append(dm.SpeakerSegment(
                recording=recording,
                speaker_label=label,
                start_seconds=start,
                end_seconds=end,
                text=text,
                confidence=getattr(utt, "confidence", 0) or 0,
            ))

    if segments:
        dm.SpeakerSegment.objects.bulk_create(segments)
    return len(segments)


def _normalize_label(raw: str) -> str:
    """'A' → 'SPEAKER_A', 'SPEAKER_00' → 'SPEAKER_00'."""
    raw = str(raw).strip()
    if not raw:
        return "SPEAKER_UNKNOWN"
    if raw.upper().startswith("SPEAKER"):
        return raw.upper()
    return f"SPEAKER_{raw.upper()}"
