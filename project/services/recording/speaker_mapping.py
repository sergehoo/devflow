"""
Speaker mapping — associe une voix détectée à un User réel (PR-REC-2).

API publique :
  * map_speaker_to_participant(recording, speaker_label, participant, confirmed_by)
  * confirm_all_mappings(recording, confirmed_by) — valide que tous les
    speakers sont mappés et marque le recording comme prêt pour summary
  * build_final_transcript(recording) — remplace les labels par les noms
    réels et stocke dans recording.final_transcript

Toutes les opérations sont scopées : on vérifie que ``participant`` a
accès au workspace de la réunion (sinon refus).
"""

from __future__ import annotations

import logging
from django.db import transaction
from django.utils import timezone

from project import models as dm
from project.utils.workspaces import get_user_workspace_ids

logger = logging.getLogger(__name__)


@transaction.atomic
def map_speaker_to_participant(
    *,
    recording: dm.MeetingRecording,
    speaker_label: str,
    participant,
    confirmed_by=None,
) -> dm.SpeakerParticipantMapping:
    """
    Crée / met à jour le mapping (recording, speaker_label) → participant.

    Sécurité : le participant doit avoir accès au workspace de la réunion.

    Side-effects :
      * Désactive l'ancien mapping actif pour ce (recording, speaker_label)
      * Crée un nouveau SpeakerParticipantMapping actif
      * Met à jour DetectedSpeaker.mapped_participant + is_confirmed
    """
    if participant is None:
        raise ValueError("participant requis")
    # Vérif accès workspace
    accessible = get_user_workspace_ids(participant)
    if recording.workspace_id not in accessible:
        raise PermissionError(
            f"Le user {participant} n'a pas accès au workspace de cette réunion."
        )

    # Désactive les anciens mappings actifs
    dm.SpeakerParticipantMapping.objects.filter(
        recording=recording, speaker_label=speaker_label, is_active=True,
    ).update(is_active=False)

    mapping = dm.SpeakerParticipantMapping.objects.create(
        recording=recording,
        speaker_label=speaker_label,
        participant=participant,
        confirmed_by=confirmed_by,
        is_active=True,
    )

    # Met à jour le DetectedSpeaker
    dm.DetectedSpeaker.objects.filter(
        recording=recording, speaker_label=speaker_label,
    ).update(
        mapped_participant=participant,
        is_confirmed=True,
        confirmed_by=confirmed_by,
        confirmed_at=timezone.now(),
        display_name=(participant.get_full_name() or participant.get_username()),
    )
    return mapping


def confirm_all_mappings(*, recording, confirmed_by=None) -> None:
    """
    Valide que TOUS les DetectedSpeaker du recording sont mappés.
    Si oui, met le recording en GENERATING_SUMMARY et déclenche le
    transcript final + summary. Sinon, raise ValueError.
    """
    speakers = recording.speakers.all()
    if not speakers.exists():
        raise ValueError("Aucune voix détectée à mapper.")
    unmapped = speakers.filter(mapped_participant__isnull=True)
    if unmapped.exists():
        labels = ", ".join(unmapped.values_list("speaker_label", flat=True))
        raise ValueError(f"Voix non mappées : {labels}")

    recording.status = dm.MeetingRecording.Status.GENERATING_SUMMARY
    recording.save(update_fields=["status", "updated_at"])

    # Génère le transcript final avec noms réels
    build_final_transcript(recording)


def build_final_transcript(recording: dm.MeetingRecording) -> str:
    """
    Remplace les labels SPEAKER_X dans les segments par les noms des
    participants mappés. Stocke dans recording.final_transcript et
    retourne la chaîne.
    """
    speaker_to_name = dict(
        recording.speakers.filter(mapped_participant__isnull=False)
        .values_list("speaker_label", "display_name")
    )
    segments = recording.segments.order_by("start_seconds")
    lines = []
    for seg in segments:
        name = speaker_to_name.get(seg.speaker_label, seg.speaker_label)
        ts = f"[{int(seg.start_seconds // 60):02d}:{int(seg.start_seconds % 60):02d}]"
        lines.append(f"{ts} **{name}** : {seg.text}")
    final = "\n\n".join(lines)
    recording.final_transcript = final
    recording.save(update_fields=["final_transcript", "updated_at"])
    return final
