"""
Mémoire vocale workspace (PR-REC-VOICEPRINT).

Permet à DevFlow de reconnaître automatiquement les voix déjà mappées
dans des réunions précédentes. Deux modes selon les libs installées :

  1. ``Resemblyzer`` installé (recommandé) :
       Embedding 256d via modèle d-vector pré-entraîné.
       Matching cosine — précision ~85-95% sur voix bien échantillonnées.

  2. Pas de Resemblyzer (fallback automatique) :
       Suggestion statistique basée sur la fréquence des mappings passés.
       Précision modérée mais marche sans aucune dépendance.

API publique :
  * compute_voice_embedding(audio_path) → list[float] | None
  * update_voiceprint(workspace, user, sample_audio_field) → WorkspaceVoicePrint
  * suggest_user_for_speaker(workspace, audio_field, exclude_user_ids=()) →
        (User, similarity) | None
  * auto_suggest_speakers(recording) → int (nombre de speakers pré-mappés)

Toutes les opérations sont scopées au workspace (jamais cross-tenant).
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from typing import Optional

from django.utils import timezone

from project import models as dm

logger = logging.getLogger(__name__)


# Seuil de similarité au-dessus duquel on suggère automatiquement un user.
# Sur du Resemblyzer, 0.70 = très probable, 0.80+ = quasi-certain.
VOICEPRINT_MATCH_THRESHOLD = 0.70

# Singleton du VoiceEncoder (chargement du modèle pyTorch ~50 Mo, lent au 1er appel)
_encoder = None
_encoder_failed = False


def _get_encoder():
    """Charge l'encoder Resemblyzer une seule fois par worker."""
    global _encoder, _encoder_failed
    if _encoder is not None:
        return _encoder
    if _encoder_failed:
        return None
    try:
        from resemblyzer import VoiceEncoder
        _encoder = VoiceEncoder(device="cpu", verbose=False)
        logger.info("VoiceEncoder loaded (Resemblyzer CPU)")
        return _encoder
    except ImportError:
        _encoder_failed = True
        logger.info(
            "Resemblyzer not installed — voiceprint matching disabled "
            "(fallback to statistical suggestions). "
            "Install with: pip install Resemblyzer"
        )
        return None
    except Exception as exc:
        _encoder_failed = True
        logger.warning("VoiceEncoder load failed: %s", exc)
        return None


def _download_to_tempfile(audio_field) -> Optional[str]:
    """Télécharge un FieldFile audio vers un fichier temporaire local."""
    if not audio_field:
        return None
    try:
        suffix = os.path.splitext(audio_field.name or "")[1] or ".wav"
        fd, path = tempfile.mkstemp(prefix="vp_", suffix=suffix)
        with os.fdopen(fd, "wb") as out:
            audio_field.open("rb")
            try:
                while True:
                    chunk = audio_field.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            finally:
                audio_field.close()
        return path
    except Exception as exc:
        logger.warning("download audio failed: %s", exc)
        return None


def compute_voice_embedding(audio_path: str) -> Optional[list[float]]:
    """
    Calcule un embedding 256d d'un sample audio.

    Retourne None si :
      - Resemblyzer n'est pas installé
      - Le fichier est corrompu / trop court
      - Une exception runtime survient
    """
    encoder = _get_encoder()
    if encoder is None or not audio_path:
        return None
    try:
        from resemblyzer import preprocess_wav
        wav = preprocess_wav(audio_path)
        emb = encoder.embed_utterance(wav)
        return [float(x) for x in emb.tolist()]
    except Exception as exc:
        logger.warning("compute_voice_embedding failed for %s: %s", audio_path, exc)
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity entre deux vecteurs. Retourne 0 si dims différentes."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _running_average(old: list[float], new: list[float], count_before: int) -> list[float]:
    """
    Moyenne mobile pondérée pour fusionner un ancien embedding avec un nouveau.
    Plus l'historique est grand, plus le nouveau a un poids faible.
    """
    if not old:
        return new
    n = max(1, count_before)
    return [(o * n + x) / (n + 1) for o, x in zip(old, new)]


def update_voiceprint(workspace, user, sample_audio_field) -> Optional[dm.WorkspaceVoicePrint]:
    """
    Met à jour (ou crée) le WorkspaceVoicePrint pour (workspace, user) à
    partir du sample audio fourni. Calcule l'embedding et le moyenne avec
    le précédent pour stabiliser la signature voix.

    Idempotent : peut être appelé plusieurs fois pour le même user.
    Retourne le voiceprint ou None si la mise à jour a échoué.
    """
    if workspace is None or user is None:
        return None

    tmp_path = _download_to_tempfile(sample_audio_field)
    if not tmp_path:
        return None

    try:
        new_emb = compute_voice_embedding(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not new_emb:
        # Pas d'encoder dispo → on ne fait rien (le compteur mappings_count
        # est déjà mis à jour par speaker_mapping.map_speaker_to_participant).
        return None

    vp, created = dm.WorkspaceVoicePrint.objects.get_or_create(
        workspace=workspace, user=user,
        defaults={
            "embedding": {"vector": new_emb, "dim": len(new_emb)},
            "mappings_count": 1,
            "last_seen_at": timezone.now(),
        },
    )
    if not created:
        # Moyenne mobile pondérée pour stabiliser
        old_vec = (vp.embedding or {}).get("vector") or []
        merged = _running_average(old_vec, new_emb, vp.mappings_count or 0)
        vp.embedding = {"vector": merged, "dim": len(merged)}
        vp.last_seen_at = timezone.now()
        vp.save(update_fields=["embedding", "last_seen_at", "updated_at"])
    return vp


def suggest_user_for_speaker(
    workspace,
    speaker_audio_field,
    *,
    exclude_user_ids: Optional[set[int]] = None,
    threshold: float = VOICEPRINT_MATCH_THRESHOLD,
) -> Optional[tuple[object, float]]:
    """
    Trouve le User dont le voiceprint correspond le mieux à un sample audio.

    Stratégie :
      1. Calcule l'embedding du sample
      2. Pour chaque WorkspaceVoicePrint du workspace, calcule la
         similarité cosine
      3. Retourne (User, similarity) si > threshold, sinon None

    ``exclude_user_ids`` : pour éviter de proposer deux fois le même user
    pour deux speakers différents dans la même réunion.
    """
    exclude_user_ids = exclude_user_ids or set()
    tmp_path = _download_to_tempfile(speaker_audio_field)
    if not tmp_path:
        return None
    try:
        target = compute_voice_embedding(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if not target:
        return None

    voiceprints = (
        dm.WorkspaceVoicePrint.objects
        .filter(workspace=workspace)
        .exclude(user_id__in=exclude_user_ids)
        .select_related("user")
    )

    best_user = None
    best_score = 0.0
    for vp in voiceprints:
        vec = (vp.embedding or {}).get("vector") or []
        score = _cosine_similarity(target, vec)
        if score > best_score:
            best_score = score
            best_user = vp.user

    if best_user is not None and best_score >= threshold:
        return (best_user, best_score)
    return None


def suggest_users_by_frequency(workspace, *, limit: int = 10) -> list[object]:
    """
    Fallback statistique quand Resemblyzer n'est pas dispo : retourne les
    users les plus mappés dans ce workspace, triés par fréquence puis
    récence. Sert d'aide à l'utilisateur dans le selecteur de mapping.
    """
    qs = (
        dm.WorkspaceVoicePrint.objects
        .filter(workspace=workspace)
        .select_related("user")
        .order_by("-mappings_count", "-last_seen_at")[:limit]
    )
    return [vp.user for vp in qs]


def auto_suggest_speakers(recording: dm.MeetingRecording) -> int:
    """
    Pour chaque speaker non encore mappé du recording, propose le meilleur
    User candidat en se basant sur le voiceprint et pré-remplit
    DetectedSpeaker.mapped_participant (mais SANS marquer is_confirmed,
    car l'humain doit toujours valider).

    Retourne le nombre de suggestions appliquées.

    Sécurité : seuls les users ayant déjà un voiceprint dans CE workspace
    peuvent être suggérés (pas de fuite cross-tenant).
    """
    if not recording or not recording.workspace_id:
        return 0
    encoder = _get_encoder()
    if encoder is None:
        logger.info(
            "auto_suggest_speakers: Resemblyzer not available — skipping. "
            "Users will see frequency-based suggestions in UI."
        )
        return 0

    workspace = recording.workspace
    speakers = (
        recording.speakers
        .filter(mapped_participant__isnull=True)
        .exclude(sample_audio="")
    )
    used_user_ids: set[int] = set(
        recording.speakers
        .filter(mapped_participant__isnull=False)
        .values_list("mapped_participant_id", flat=True)
    )

    applied = 0
    for sp in speakers:
        if not sp.sample_audio:
            continue
        match = suggest_user_for_speaker(
            workspace, sp.sample_audio,
            exclude_user_ids=used_user_ids,
        )
        if match is None:
            continue
        user, score = match
        # On set mapped_participant SANS confirmer — l'humain valide ensuite.
        sp.mapped_participant = user
        sp.is_confirmed = False
        sp.display_name = user.get_full_name() or user.get_username()
        sp.save(update_fields=[
            "mapped_participant", "is_confirmed", "display_name", "updated_at",
        ])
        used_user_ids.add(user.pk)
        applied += 1
        logger.info(
            "auto_suggest: recording=%s speaker=%s → %s (similarity=%.3f)",
            recording.pk, sp.speaker_label, user, score,
        )
    return applied
