"""
Service d'affectation automatique de tâches selon le rôle / profil.

Utilisé par le module IA de génération de projet : étant donné un projet
et le pool de membres de ses équipes contributrices, on choisit un assignee
pertinent pour chaque tâche en s'appuyant sur :
  - les mots-clés du titre / description (frontend, API, QA, design…),
  - le rôle TeamMembership.role du membre,
  - le profil UserProfile.seniority (Senior / Lead privilégié pour les
    tâches complexes),
  - la charge cumulée déjà attribuée pour équilibrer (round-robin pondéré).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from project import models as dm


# Map mot-clé → rôle TeamMembership prioritaire
_KEYWORD_ROLE_MAP = [
    (re.compile(r"\b(api|backend|django|python|sql|database|db|orm|model)\b", re.I),
     [dm.TeamMembership.Role.DEVELOPER, dm.TeamMembership.Role.TECH_LEAD]),
    (re.compile(r"\b(frontend|front|ui|component|react|vue|tailwind|css|html)\b", re.I),
     [dm.TeamMembership.Role.DEVELOPER, dm.TeamMembership.Role.DESIGNER]),
    (re.compile(r"\b(test|qa|quality|coverage|recette)\b", re.I),
     [dm.TeamMembership.Role.QA]),
    (re.compile(r"\b(deploy|ci|cd|docker|kubernetes|infra|server|monitoring)\b", re.I),
     [dm.TeamMembership.Role.DEVOPS]),
    (re.compile(r"\b(design|ux|ui|wireframe|maquette|figma)\b", re.I),
     [dm.TeamMembership.Role.DESIGNER]),
    (re.compile(r"\b(lead|architecture|review|mentor)\b", re.I),
     [dm.TeamMembership.Role.TECH_LEAD]),
    (re.compile(r"\b(spec|specification|fonctionnel|product|backlog|user story)\b", re.I),
     [dm.TeamMembership.Role.PRODUCT_OWNER, dm.TeamMembership.Role.PM]),
    (re.compile(r"\b(analy|reporting|kpi|dashboard|data)\b", re.I),
     [dm.TeamMembership.Role.ANALYST]),
]

# Pour les tâches complexes (estimate_hours élevé), privilégier la séniorité
_HIGH_COMPLEXITY_THRESHOLD_HOURS = 16
_SENIOR_LEVELS = (
    dm.UserProfile.Seniority.SENIOR,
    dm.UserProfile.Seniority.LEAD,
    dm.UserProfile.Seniority.EXPERT,
)


class TaskAutoAssigner:
    """
    Usage :
        assigner = TaskAutoAssigner.for_project(project)
        user = assigner.pick_for(task)  # retourne un User ou None
    """

    def __init__(self, memberships: list[dm.TeamMembership]):
        self.memberships = list(memberships)
        self._load_counter: Counter = Counter()  # user_id -> nb tâches déjà assignées

    @classmethod
    def for_project(cls, project: dm.Project) -> "TaskAutoAssigner":
        """Construit le pool depuis les équipes contributrices + équipe principale."""
        memberships = list(project.get_assignable_memberships())
        return cls(memberships)

    # ────────────────────────────────────────────────────────────────────
    def _detect_target_roles(self, text: str) -> list[str]:
        roles: list[str] = []
        for pattern, mapped_roles in _KEYWORD_ROLE_MAP:
            if pattern.search(text or ""):
                for r in mapped_roles:
                    if r not in roles:
                        roles.append(r)
        return roles

    def _candidates_for_roles(self, roles: list[str]) -> list[dm.TeamMembership]:
        if not roles:
            return self.memberships
        # On préserve l'ordre de priorité des rôles
        ranked = []
        for role in roles:
            for m in self.memberships:
                if m.role == role and m not in ranked:
                    ranked.append(m)
        # Si aucun match, fallback sur tout le pool
        return ranked or self.memberships

    def _prefer_senior(
        self, candidates: list[dm.TeamMembership]
    ) -> list[dm.TeamMembership]:
        seniors = [
            m for m in candidates
            if getattr(getattr(m.user, "profile", None), "seniority", None) in _SENIOR_LEVELS
        ]
        return seniors or candidates

    def _pick_least_loaded(
        self, candidates: list[dm.TeamMembership]
    ) -> Optional[dm.TeamMembership]:
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda m: (self._load_counter.get(m.user_id, 0), m.user_id),
        )

    # ────────────────────────────────────────────────────────────────────
    def pick_for(self, task) -> Optional[object]:
        """
        Retourne un User candidat pour la tâche, ou None si pool vide.
        Met à jour le compteur de charge interne.
        """
        if not self.memberships:
            return None

        text = " ".join(filter(None, [
            getattr(task, "title", ""),
            getattr(task, "description", ""),
        ]))
        target_roles = self._detect_target_roles(text)
        candidates = self._candidates_for_roles(target_roles)

        # Préférer la séniorité pour les tâches complexes
        try:
            est = float(getattr(task, "estimate_hours", 0) or 0)
        except (TypeError, ValueError):
            est = 0
        if est >= _HIGH_COMPLEXITY_THRESHOLD_HOURS:
            candidates = self._prefer_senior(candidates)

        chosen = self._pick_least_loaded(candidates)
        if chosen:
            self._load_counter[chosen.user_id] += 1
            return chosen.user
        return None

    def pick_for_payload(self, task_data: dict) -> Optional[object]:
        """Variante pour un payload IA brut (dict) au lieu d'une instance Task."""
        # Crée un objet shim
        class _Shim:
            title = (task_data.get("title") or "").strip()
            description = (task_data.get("description") or "").strip()
            estimate_hours = task_data.get("estimate_hours") or 0
        return self.pick_for(_Shim())
