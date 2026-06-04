"""
Diarisation post-traitement (PR-REC-2).

Étape qui se déroule APRÈS la transcription :
  1. Agrège les SpeakerSegment par speaker_label → DetectedSpeaker
  2. Pour chaque speaker, choisit un extrait représentatif (~8s) en
     préférant un segment au milieu de sa parole (évite les "euh" début)
  3. Extrait l'audio MP3 via pydub et l'attache à sample_audio
  4. Tolère les échecs individuels (1 sample manqué ≠ pipeline cassé)
"""

from __future__ import annotations

import logging
import os
from django.conf import settings
from django.core.files.base import ContentFile

from project import models as dm

logger = logging.getLogger(__name__)


def aggregate_speakers_from_segments(recording: dm.MeetingRecording) -> int:
    """
    Crée un DetectedSpeaker par speaker_label distinct, calcule la durée
    totale et le nombre de segments. Retourne le nombre de speakers créés.

    Idempotent : si un DetectedSpeaker existe déjà pour ce couple
    (recording, label), on met à jour ses compteurs.
    """
    from django.db.models import Count, Sum, F, FloatField, ExpressionWrapper

    durations = (
        dm.SpeakerSegment.objects
        .filter(recording=recording)
        .annotate(dur=ExpressionWrapper(
            F("end_seconds") - F("start_seconds"),
            output_field=FloatField(),
        ))
        .values("speaker_label")
        .annotate(total_dur=Sum("dur"), nb=Count("id"))
        .order_by("-total_dur")
    )

    created = 0
    for row in durations:
        label = row["speaker_label"]
        speaker, was_created = dm.DetectedSpeaker.objects.update_or_create(
            recording=recording, speaker_label=label,
            defaults={
                "total_duration_seconds": row["total_dur"] or 0,
                "total_segments": row["nb"] or 0,
            },
        )
        if was_created:
            created += 1
    return created


def extract_speaker_samples(recording: dm.MeetingRecording) -> int:
    """
    Pour chaque DetectedSpeaker du recording, génère un extrait audio
    MP3 représentatif et l'attache à sample_audio.

    Stratégie de choix de l'extrait :
      * On prend le segment dont la durée est la plus proche de TARGET
        (default 8s) ou plus long.
      * Si tous les segments sont courts, on concatène les premiers
        segments jusqu'à atteindre TARGET (max 12s).

    Tolère les échecs individuels — log et continue.
    Retourne le nombre de samples générés avec succès.
    """
    from project.services.recording.audio_processing import (
        download_to_tempfile, extract_sample,
    )

    audio_path = download_to_tempfile(recording)
    if audio_path is None:
        return 0

    target_dur = float(getattr(settings, "SPEAKER_SAMPLE_DURATION_SEC", 8))
    max_dur = target_dur * 1.5  # tolère un peu plus long
    generated = 0

    try:
        speakers = dm.DetectedSpeaker.objects.filter(recording=recording)
        for speaker in speakers:
            try:
                start, end = _pick_sample_window(
                    recording, speaker.speaker_label,
                    target_dur=target_dur, max_dur=max_dur,
                )
                if start is None or end is None:
                    continue
                mp3_bytes = extract_sample(
                    audio_path, start_s=start, end_s=end,
                    target_format="mp3",
                )
                if not mp3_bytes:
                    continue
                # Reset previous sample
                try:
                    if speaker.sample_audio:
                        speaker.sample_audio.delete(save=False)
                except Exception:
                    pass
                # Save via FileField
                try:
                    filename = f"{speaker.speaker_label}.mp3"
                    speaker.sample_audio.save(
                        filename, ContentFile(mp3_bytes), save=False,
                    )
                except Exception as exc:
                    logger.warning(
                        "Cannot save sample for %s (%s) — reset to None: %s",
                        speaker.speaker_label, recording.pk, exc,
                    )
                    speaker.sample_audio = None
                speaker.sample_start_seconds = start
                speaker.sample_end_seconds = end
                speaker.save(update_fields=[
                    "sample_audio", "sample_start_seconds", "sample_end_seconds",
                    "updated_at",
                ])
                generated += 1
            except Exception as exc:
                logger.warning(
                    "extract_speaker_samples: %s failed: %s",
                    speaker.speaker_label, exc,
                )
                continue
    finally:
        try:
            os.remove(audio_path)
        except Exception:
            pass

    return generated


def _pick_sample_window(
    recording: dm.MeetingRecording,
    speaker_label: str,
    *,
    target_dur: float,
    max_dur: float,
) -> tuple[float | None, float | None]:
    """
    Choisit la meilleure fenêtre temporelle pour cet speaker :
      1. Cherche un segment unique ≥ target_dur — prend les ``target_dur``
         premières secondes
      2. Sinon, concatène plusieurs segments contigus jusqu'à atteindre
         target_dur (sans dépasser max_dur)
    """
    segments = list(
        dm.SpeakerSegment.objects
        .filter(recording=recording, speaker_label=speaker_label)
        .order_by("start_seconds")
        .values("start_seconds", "end_seconds")
    )
    if not segments:
        return None, None

    # 1. Long segment unique ?
    for s in segments:
        dur = s["end_seconds"] - s["start_seconds"]
        if dur >= target_dur:
            return s["start_seconds"], s["start_seconds"] + target_dur

    # 2. Concatène les segments
    first_start = segments[0]["start_seconds"]
    last_end = first_start + target_dur
    for s in segments:
        if s["end_seconds"] >= last_end:
            return first_start, min(last_end, first_start + max_dur)

    # 3. Pas assez de matière → on prend tout ce qu'il y a
    return first_start, min(segments[-1]["end_seconds"], first_start + max_dur)
