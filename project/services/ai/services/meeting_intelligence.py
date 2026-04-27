"""
IA appliquée aux réunions DevFlow.

Capacités :
- summarize_notes(meeting)        → compte-rendu structuré
- extract_decisions(meeting)      → liste des décisions prises
- extract_action_items(meeting)   → MeetingActionItem créés (convertibles en Tasks)
- detect_risks(meeting)           → AInsight de type RISK
- full_process(meeting)           → pipeline complet en 1 appel

Tous les services suivent le pattern DevFlow :
- IA si dispo (Llama3.2 / OpenAI via factory pluggable)
- Heuristique de fallback (regex / patterns) toujours opérationnelle
- Persistance complète : ai_summary sur ProjectMeeting, MeetingActionItem,
  AInsight pour les risques.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.ai.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)
User = get_user_model()


@dataclass
class MeetingProcessResult:
    summary: str = ""
    decisions: list[str] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    risks: list[dict] = field(default_factory=list)
    used_provider: str = "heuristic"
    created_action_items: int = 0
    created_risk_insights: int = 0


class MeetingIntelligenceService:

    SYSTEM_PROMPT = (
        "Tu es un PMO senior qui analyse des comptes-rendus de réunion projet. "
        "Réponds STRICTEMENT en JSON valide, en français, avec la structure :\n"
        "{\n"
        '  "summary": "compte-rendu synthétique 4-8 phrases, structuré",\n'
        '  "decisions": ["décision 1", "décision 2", ...],\n'
        '  "action_items": [\n'
        '    {"title": "...", "description": "...", "owner_hint": "Nom ou rôle", '
        '"due_date_hint": "YYYY-MM-DD ou null", "priority": "LOW|MEDIUM|HIGH|CRITICAL"}\n'
        "  ],\n"
        '  "risks": [\n'
        '    {"title": "...", "severity": "INFO|LOW|MEDIUM|HIGH|CRITICAL", "description": "..."}\n'
        "  ]\n"
        "}\n"
        "Sans aucun texte hors JSON, sans markdown."
    )

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    @classmethod
    def full_process(cls, meeting: dm.ProjectMeeting, actor=None) -> MeetingProcessResult:
        """Pipeline complet : résumé + décisions + actions + risques."""
        payload, used_provider = cls._call_ai_or_heuristic(meeting)

        # Met à jour le ProjectMeeting
        meeting.ai_summary = payload.get("summary", "")[:8000]
        meeting.ai_used_provider = used_provider
        meeting.ai_extracted_at = timezone.now()
        if not meeting.decisions and payload.get("decisions"):
            meeting.decisions = "\n".join(f"• {d}" for d in payload["decisions"])
        meeting.save(update_fields=[
            "ai_summary", "ai_used_provider", "ai_extracted_at",
            "decisions", "updated_at",
        ])

        # Crée les MeetingActionItem
        action_items_payload = payload.get("action_items", []) or []
        created_actions = cls._persist_action_items(meeting, action_items_payload, actor)

        # Crée les AInsight pour les risques
        risks_payload = payload.get("risks", []) or []
        created_risks = cls._persist_risks(meeting, risks_payload)

        return MeetingProcessResult(
            summary=payload.get("summary", ""),
            decisions=payload.get("decisions", []) or [],
            action_items=action_items_payload,
            risks=risks_payload,
            used_provider=used_provider,
            created_action_items=created_actions,
            created_risk_insights=created_risks,
        )

    # ---------------------------------------------------------------------
    # AI / heuristique
    # ---------------------------------------------------------------------
    @classmethod
    def _call_ai_or_heuristic(cls, meeting: dm.ProjectMeeting) -> tuple[dict, str]:
        provider = get_ai_provider()
        if provider.is_available():
            try:
                return cls._call_ai(provider, meeting), provider.name
            except Exception as exc:
                logger.warning("Meeting AI failed: %s", exc)
        return cls._heuristic(meeting), "heuristic"

    @classmethod
    def _call_ai(cls, provider, meeting: dm.ProjectMeeting) -> dict:
        meeting_payload = {
            "project": meeting.project.name,
            "title": meeting.title,
            "type": meeting.meeting_type,
            "date": meeting.scheduled_at.isoformat() if meeting.scheduled_at else None,
            "agenda": meeting.agenda,
            "notes": meeting.notes,
            "decisions": meeting.decisions,
            "blockers": meeting.blockers,
            "next_steps": meeting.next_steps,
            "participants": [str(u) for u in meeting.internal_participants.all()],
        }

        messages = [
            AIMessage(role="system", content=cls.SYSTEM_PROMPT),
            AIMessage(role="user", content=json.dumps(meeting_payload, ensure_ascii=False)),
        ]
        resp = provider.generate(
            messages=messages,
            temperature=0.2,
            json_mode=provider.supports_json_mode(),
        )
        if isinstance(provider, OpenAIProvider):
            data = OpenAIProvider.parse_json(resp)
        else:
            text = (resp.text or "").strip()
            if text.startswith("```"):
                text = text.split("```", 2)[-1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0]
            try:
                data = json.loads(text)
            except Exception:
                data = {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _heuristic(meeting: dm.ProjectMeeting) -> dict:
        """
        Fallback déterministe : extrait actions/décisions depuis les notes
        en cherchant des marqueurs simples (TODO:, ACTION:, → ...).
        """
        notes = meeting.notes or ""
        decisions_field = meeting.decisions or ""

        decisions: list[str] = []
        for line in (decisions_field or "").splitlines():
            line = line.strip(" •-*")
            if line:
                decisions.append(line)

        action_pattern = re.compile(
            r"(?im)^\s*(?:[-*•]?\s*)?(?:action|todo|à faire|task)\s*[:\-]\s*(.+)$"
        )
        actions: list[dict] = []
        for m in action_pattern.finditer(notes):
            title = m.group(1).strip()
            if title and len(actions) < 20:
                actions.append({
                    "title": title[:200],
                    "description": "",
                    "owner_hint": "",
                    "due_date_hint": None,
                    "priority": "MEDIUM",
                })

        # Risques détectés depuis blockers + mots-clés dans notes
        risks: list[dict] = []
        if meeting.blockers and meeting.blockers.strip():
            for line in meeting.blockers.splitlines():
                line = line.strip(" •-*")
                if line:
                    risks.append({
                        "title": line[:180],
                        "severity": "HIGH",
                        "description": "Point bloquant remonté en réunion",
                    })

        # Résumé heuristique : 1ères phrases de notes
        summary = ""
        if notes:
            sentences = re.split(r"(?<=[.!?])\s+", notes.strip())
            summary = " ".join(sentences[:5])[:1500]

        return {
            "summary": summary or f"Réunion « {meeting.title} » du {meeting.scheduled_at:%d/%m/%Y}.",
            "decisions": decisions,
            "action_items": actions,
            "risks": risks,
        }

    # ---------------------------------------------------------------------
    # Persistance
    # ---------------------------------------------------------------------
    @classmethod
    def _persist_action_items(cls, meeting, items_payload, actor) -> int:
        created = 0
        team_users = list(meeting.internal_participants.all())
        for item in items_payload:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            owner = cls._guess_owner(item.get("owner_hint"), team_users)
            due = cls._parse_date(item.get("due_date_hint"))
            priority = (item.get("priority") or "MEDIUM").upper()
            if priority not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                priority = "MEDIUM"

            dm.MeetingActionItem.objects.create(
                meeting=meeting,
                title=title[:300],
                description=(item.get("description") or "")[:2000],
                owner=owner,
                due_date=due,
                priority=priority,
            )
            created += 1
        return created

    @classmethod
    def _persist_risks(cls, meeting, risks_payload) -> int:
        created = 0
        for r in risks_payload:
            title = (r.get("title") or "").strip()
            if not title:
                continue
            severity = (r.get("severity") or "MEDIUM").upper()
            if severity not in {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                severity = "MEDIUM"
            try:
                dm.AInsight.objects.create(
                    workspace=meeting.workspace,
                    project=meeting.project,
                    insight_type=dm.AInsight.InsightType.RISK,
                    severity=severity,
                    title=title[:200],
                    summary=(r.get("description") or "Risque détecté en réunion")[:1000],
                    score={"INFO": 10, "LOW": 30, "MEDIUM": 50, "HIGH": 75, "CRITICAL": 95}.get(severity, 50),
                )
                created += 1
            except Exception as exc:
                logger.warning("Could not create AInsight from meeting risk: %s", exc)
        return created

    @staticmethod
    def _guess_owner(hint: str | None, team_users: list) -> User | None:
        if not hint or not team_users:
            return None
        h = hint.lower()
        for u in team_users:
            if h in (u.username or "").lower() or h in (u.email or "").lower():
                return u
            if h in (u.get_full_name() or "").lower():
                return u
        return None

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        try:
            return timezone.datetime.fromisoformat(str(value)).date()
        except Exception:
            return None
