"""
Audio processing helpers — pydub + ffmpeg.

Fonctions exposées :
  * download_to_tempfile(recording) — télécharge l'audio S3/MinIO en /tmp
  * extract_sample(audio_path, start_s, end_s, target_format='mp3') — extrait
    et retourne les bytes du sample
  * sniff_mime(file_path) — détection MIME basique via python-magic

Toutes les fonctions sont best-effort : si pydub/ffmpeg n'est pas dispo,
on retourne None / raise et le caller doit gérer.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def download_to_tempfile(recording) -> str | None:
    """
    Télécharge le fichier audio du recording dans un fichier temporaire
    local. Retourne le path. Le caller est responsable du cleanup.

    Critique pour AssemblyAI : on passe le path local au SDK plutôt qu'une
    URL publique (notamment quand le bucket est privé MinIO interne).
    """
    if not recording.audio_file:
        return None
    try:
        suffix = os.path.splitext(recording.audio_file.name)[1] or ".bin"
        fd, path = tempfile.mkstemp(prefix="devflow-rec-", suffix=suffix)
        try:
            recording.audio_file.open("rb")
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = recording.audio_file.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
        finally:
            try:
                recording.audio_file.close()
            except Exception:
                pass
        return path
    except Exception as exc:
        logger.exception("download_to_tempfile failed: %s", exc)
        return None


def extract_sample(
    audio_path: str,
    *,
    start_s: float,
    end_s: float,
    target_format: str = "mp3",
    bitrate: str = "96k",
) -> bytes | None:
    """
    Extrait un segment audio [start_s, end_s] et l'encode dans le format
    cible (par défaut MP3 96k = ~96 KB pour 8s, écoutable HTML5 partout).

    Retourne les bytes du fichier produit, ou None si erreur (pydub absent,
    ffmpeg non installé, segment hors limites…).
    """
    try:
        from pydub import AudioSegment
    except Exception:
        logger.warning("pydub not installed — cannot extract sample")
        return None
    try:
        audio = AudioSegment.from_file(audio_path)
        total_ms = len(audio)
        start_ms = max(0, int(start_s * 1000))
        end_ms = min(total_ms, int(end_s * 1000))
        if end_ms <= start_ms:
            return None
        segment = audio[start_ms:end_ms]
        buf = io.BytesIO()
        segment.export(buf, format=target_format, bitrate=bitrate)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("extract_sample failed [%s-%s]: %s", start_s, end_s, exc)
        return None


def sniff_mime(file_path: str) -> str:
    """
    Détection MIME via python-magic si dispo, sinon extension.
    """
    try:
        import magic
        return magic.from_file(file_path, mime=True) or ""
    except Exception:
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        ext_map = {
            "webm": "audio/webm",
            "ogg": "audio/ogg",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "m4a": "audio/mp4",
            "mp4": "audio/mp4",
            "flac": "audio/flac",
        }
        return ext_map.get(ext, "application/octet-stream")
