"""
Génération du compte-rendu IA à partir du transcript final (PR-REC-2).

Utilise le ``FallbackChainProvider`` existant : DeepSeek (1) → Anthropic
Claude (2) → Ollama (3). Bascule silencieusement en cas d'erreur.

API publique :
  * generate_summary(recording) → str (Markdown), stocke dans
    recording.summary_markdown
  * generate_extractions(recording) → list[RecordingAIExtraction] créés
"""

from __future__ import annotations

import json
import logging

from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider

logger = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = (
    "Tu es l'assistant DevFlow. À partir du transcript brut d'une "
    "réunion (avec timestamps et noms des speakers), produis un compte-"
    "rendu professionnel en Markdown, en français, structuré comme suit :\n\n"
    "## Résumé exécutif\n"
    "(3-5 lignes maximum, dense et factuel)\n\n"
    "## Décisions prises\n"
    "(liste à puces : décision + qui l'a prise si identifiable)\n\n"
    "## Actions à mener\n"
    "(format : - [@responsable] action — pour quand)\n\n"
    "## Points de vigilance / risques\n\n"
    "## Prochaines étapes\n\n"
    "Conserve les chiffres et noms exacts du transcript. Ne fabrique rien. "
    "Si une section est vide, écris '— Néant —'."
)

EXTRACTIONS_SYSTEM_PROMPT = (
    "Tu extrais d'un transcript de réunion des éléments structurés sous "
    "forme JSON STRICT (pas de markdown ni commentaire). Format :\n\n"
    "{\n"
    '  "decisions": [{"title": "...", "description": "..."}],\n'
    '  "actions": [{"title": "...", "description": "...", '
    '"assignee_hint": "...", "due_date_hint": "...", "priority_hint": "..."}],\n'
    '  "risks": [{"title": "...", "description": "..."}]\n'
    "}\n\n"
    "Règles :\n"
    "- Pas de décision/action/risque sans preuve textuelle dans le transcript.\n"
    "- assignee_hint = nom mentionné s'il est identifiable.\n"
    "- due_date_hint = texte tel quel ('semaine prochaine', '15/06/2026'…).\n"
    "- priority_hint = 'critical|high|medium|low' si l'urgence est explicite, "
    "sinon ''.\n"
    "- Si rien à extraire pour une catégorie, retourne une liste vide.\n"
    "- Réponds UNIQUEMENT par le JSON, sans bloc markdown ni commentaire."
)


def generate_summary(recording: dm.MeetingRecording) -> str:
    """
    Génère le compte-rendu Markdown et le stocke dans
    recording.summary_markdown. Retourne le texte (vide si tout fail).
    """
    provider = get_ai_provider()
    if not provider or not provider.is_available():
        return ""

    transcript = recording.final_transcript or recording.full_transcript
    if not transcript.strip():
        return ""

    context = (
        f"Réunion : {recording.meeting.title}\n"
        f"Date : {recording.meeting.scheduled_at.strftime('%d/%m/%Y') if recording.meeting.scheduled_at else '—'}\n\n"
        f"Transcript complet :\n\n{transcript[:30000]}"
    )

    try:
        response = provider.generate(
            messages=[
                AIMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
                AIMessage(role="user", content=context),
            ],
            temperature=0.3,
            max_tokens=2500,
        )
        text = (response.text or "").strip()
    except Exception as exc:
        logger.warning("generate_summary failed: %s", exc)
        return ""

    if text:
        recording.summary_markdown = text[:30000]
        recording.summary_provider = response.provider
        recording.tokens_used = (recording.tokens_used or 0) + (response.tokens_used or 0)
        recording.save(update_fields=[
            "summary_markdown", "summary_provider", "tokens_used", "updated_at",
        ])
    return text


def generate_extractions(recording: dm.MeetingRecording) -> int:
    """
    Extrait décisions, actions, risques en JSON via le provider, et crée
    les ``RecordingAIExtraction`` correspondants (state is_accepted=False).

    Retourne le nombre d'extractions créées (toutes catégories confondues).
    """
    provider = get_ai_provider()
    if not provider or not provider.is_available():
        return 0

    transcript = recording.final_transcript or recording.full_transcript
    if not transcript.strip():
        return 0

    try:
        response = provider.generate(
            messages=[
                AIMessage(role="system", content=EXTRACTIONS_SYSTEM_PROMPT),
                AIMessage(role="user", content=transcript[:30000]),
            ],
            temperature=0.1,
            max_tokens=2000,
            json_mode=True,
        )
        text = (response.text or "").strip()
    except Exception as exc:
        logger.warning("generate_extractions failed: %s", exc)
        return 0

    data = _parse_json_tolerant(text)
    if not data:
        return 0

    created = 0
    for item in data.get("decisions", []) or []:
        if not item.get("title"):
            continue
        dm.RecordingAIExtraction.objects.create(
            recording=recording,
            kind=dm.RecordingAIExtraction.Kind.DECISION,
            title=item.get("title", "")[:250],
            description=item.get("description", "")[:5000],
        )
        created += 1
    for item in data.get("actions", []) or []:
        if not item.get("title"):
            continue
        dm.RecordingAIExtraction.objects.create(
            recording=recording,
            kind=dm.RecordingAIExtraction.Kind.ACTION,
            title=item.get("title", "")[:250],
            description=item.get("description", "")[:5000],
            assignee_hint=item.get("assignee_hint", "")[:120],
            due_date_hint=item.get("due_date_hint", "")[:80],
            priority_hint=item.get("priority_hint", "")[:15],
        )
        created += 1
    for item in data.get("risks", []) or []:
        if not item.get("title"):
            continue
        dm.RecordingAIExtraction.objects.create(
            recording=recording,
            kind=dm.RecordingAIExtraction.Kind.RISK,
            title=item.get("title", "")[:250],
            description=item.get("description", "")[:5000],
        )
        created += 1
    return created


def _parse_json_tolerant(text: str) -> dict:
    """Retire ```json ... ``` et tente le parse."""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[-1]
        if t.startswith("json"):
            t = t[4:]
        t = t.rsplit("```", 1)[0]
    try:
        return json.loads(t.strip())
    except Exception:
        return {}
