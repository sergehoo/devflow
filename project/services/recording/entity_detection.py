"""
Détection IA des entités DevFlow mentionnées dans un transcript de réunion
+ suggestions de création de nouveaux objets (PR-MEET-6).

Pipeline :
  1. Récupère la liste des projets/sprints/milestones existants du workspace
  2. Construit un prompt système qui liste ces entités et demande à l'IA :
     a) lesquelles sont mentionnées dans le transcript (avec confiance)
     b) quelles nouvelles entités semblent émerger des échanges
  3. Crée les RecordingAIExtraction correspondantes (kind = *_MENTION ou *_SUGGESTION)

API publique :
  * detect_and_suggest(recording) → int (nombre d'extractions créées)
"""

from __future__ import annotations

import json
import logging

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Tu es l'assistant DevFlow chargé d'analyser le transcript d'une "
    "réunion pour repérer les entités projets/sprints/jalons mentionnées "
    "ou nouvellement émergentes. Tu reçois :\n"
    "  - le transcript final de la réunion (avec noms des participants)\n"
    "  - la liste des projets, sprints et jalons EXISTANTS du workspace\n\n"
    "Tu réponds en JSON STRICT (sans bloc markdown ni commentaire) :\n"
    "{\n"
    '  "mentioned_projects": [{"id": int, "confidence": 0-1, "context": "..."}],\n'
    '  "mentioned_sprints": [{"id": int, "confidence": 0-1, "context": "..."}],\n'
    '  "mentioned_milestones": [{"id": int, "confidence": 0-1, "context": "..."}],\n'
    '  "new_project_suggestions": [{"name": "...", "description": "...", "confidence": 0-1}],\n'
    '  "new_sprint_suggestions": [{"name": "...", "context_project": "...", "confidence": 0-1}],\n'
    '  "new_milestone_suggestions": [{"name": "...", "due_date_hint": "...", "confidence": 0-1}]\n'
    "}\n\n"
    "Règles :\n"
    "  - id = identifiant exact de l'entité existante (utilise ceux fournis).\n"
    "  - confidence = nombre flottant 0-1.\n"
    "  - context = court extrait du transcript qui justifie la mention.\n"
    "  - Pour les suggestions : ne propose que si le besoin est CLAIRE dans "
    "    le transcript (« il faut créer un projet X… », « on devrait lancer "
    "    un sprint pour Y… »). Sinon retourne une liste vide."
)


def detect_and_suggest(recording: dm.MeetingRecording) -> int:
    """
    Analyse le transcript du recording, crée des RecordingAIExtraction
    pour chaque mention détectée + chaque suggestion proposée.

    Retourne le nombre d'extractions créées.
    """
    provider = get_ai_provider()
    if not provider or not provider.is_available():
        return 0

    transcript = recording.final_transcript or recording.full_transcript
    if not transcript.strip():
        return 0

    ws = recording.workspace
    # Catalogues d'entités existantes du workspace (limités à 50 chacun pour ne pas exploser le prompt)
    projects = list(
        dm.Project.objects.filter(workspace=ws, is_archived=False)
        .values("id", "name", "description")[:50]
    )
    sprints = list(
        dm.Sprint.objects.filter(workspace=ws)
        .order_by("-start_date")
        .values("id", "name", "project__name")[:50]
    )
    try:
        milestones = list(
            dm.Milestone.objects.filter(workspace=ws)
            .order_by("-target_date")
            .values("id", "title", "project__name")[:50]
        )
    except Exception:
        milestones = []

    catalog = (
        f"# Projets existants (workspace {ws.name})\n"
        + "\n".join(
            f"  [{p['id']}] {p['name']}"
            + (f" — {p['description'][:80]}" if p.get("description") else "")
            for p in projects
        ) + "\n\n"
        + "# Sprints existants\n"
        + "\n".join(
            f"  [{s['id']}] {s['name']} (projet {s.get('project__name') or '—'})"
            for s in sprints
        ) + "\n\n"
        + "# Jalons existants\n"
        + "\n".join(
            f"  [{m['id']}] {m['title']} (projet {m.get('project__name') or '—'})"
            for m in milestones
        )
    )

    user_content = (
        f"{catalog}\n\n"
        f"## Transcript\n\n{transcript[:25000]}"
    )

    try:
        response = provider.generate(
            messages=[
                AIMessage(role="system", content=SYSTEM_PROMPT),
                AIMessage(role="user", content=user_content),
            ],
            temperature=0.1,
            max_tokens=2500,
            json_mode=True,
        )
        text = (response.text or "").strip()
    except Exception as exc:
        logger.warning("entity_detection: provider call failed: %s", exc)
        return 0

    data = _parse_json_tolerant(text)
    if not data:
        return 0

    created = 0

    # Mentions : entités existantes
    mention_map = [
        ("mentioned_projects", dm.RecordingAIExtraction.Kind.PROJECT_MENTION, projects),
        ("mentioned_sprints", dm.RecordingAIExtraction.Kind.SPRINT_MENTION, sprints),
        ("mentioned_milestones", dm.RecordingAIExtraction.Kind.MILESTONE_MENTION, milestones),
    ]
    for key, kind, catalog_list in mention_map:
        for item in data.get(key, []) or []:
            entity_id = item.get("id")
            if entity_id is None:
                continue
            # Récupère le nom depuis le catalogue
            label = next(
                (c.get("name") or c.get("title") for c in catalog_list
                 if c.get("id") == entity_id),
                str(entity_id),
            )
            dm.RecordingAIExtraction.objects.create(
                recording=recording, kind=kind,
                title=str(label)[:250],
                description=(item.get("context", "") or "")[:5000],
                confidence=float(item.get("confidence", 0) or 0),
            )
            created += 1

    # Suggestions : nouvelles entités
    suggestion_map = [
        ("new_project_suggestions", dm.RecordingAIExtraction.Kind.PROJECT_SUGGESTION),
        ("new_sprint_suggestions", dm.RecordingAIExtraction.Kind.SPRINT_SUGGESTION),
        ("new_milestone_suggestions", dm.RecordingAIExtraction.Kind.MILESTONE_SUGGESTION),
    ]
    for key, kind in suggestion_map:
        for item in data.get(key, []) or []:
            name = item.get("name") or item.get("title")
            if not name:
                continue
            dm.RecordingAIExtraction.objects.create(
                recording=recording, kind=kind,
                title=str(name)[:250],
                description=(
                    item.get("description")
                    or item.get("context_project")
                    or item.get("due_date_hint")
                    or ""
                )[:5000],
                confidence=float(item.get("confidence", 0) or 0),
                due_date_hint=str(item.get("due_date_hint", "") or "")[:80],
            )
            created += 1

    return created


def _parse_json_tolerant(text: str) -> dict:
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
