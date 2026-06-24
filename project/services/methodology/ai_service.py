"""
DevFlow — MethodologyAIService (PR9-PR12).

Injecte automatiquement le bon system prompt selon ``project.methodology``
quand un user discute avec le copilote du projet.

API publique :
  * MethodologyAIService.get_profile(project) → MethodologyAIProfile | None
  * MethodologyAIService.chat(project, user_message, history=None) → str
        appelle le provider IA avec le bon persona
  * MethodologyAIService.generate_artifact(project, artifact_code, context)
        génère un artefact en utilisant le prompt dédié de l'artefact

Toutes les opérations sont workspace-safe (le project est validé en amont).
"""

from __future__ import annotations

import logging
from typing import Optional

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider

logger = logging.getLogger(__name__)


class MethodologyAIService:
    """Couche IA spécialisée par méthodologie."""

    @staticmethod
    def get_profile(project) -> Optional[dm.MethodologyAIProfile]:
        """Retourne le profil IA de la méthodologie du projet, ou None."""
        if not project:
            return None
        code = (getattr(project, "methodology", None) or "").lower()
        if not code:
            return None
        methodology = dm.Methodology.objects.filter(code=code).first()
        if not methodology:
            return None
        return getattr(methodology, "ai_profile", None)

    @staticmethod
    def _build_context_block(project) -> str:
        """Contexte structuré injecté à chaque appel IA."""
        lines = [
            f"# Projet : {project.name}",
            f"Méthodologie : {project.get_methodology_display() if hasattr(project, 'get_methodology_display') else project.methodology}",
        ]
        if project.description:
            lines.append(f"Description : {project.description[:500]}")
        if hasattr(project, "status"):
            lines.append(f"Statut : {project.status}")
        if hasattr(project, "progress_percent"):
            lines.append(f"Avancement : {project.progress_percent or 0}%")
        if hasattr(project, "sprints"):
            active = project.sprints.filter(status="ACTIVE").first()
            if active:
                lines.append(
                    f"Sprint actif : {active.name} ({active.completed_story_points or 0}/{active.total_story_points or 0} SP)"
                )
        if hasattr(project, "phases"):
            phases = project.phases.all()
            if phases.exists():
                lines.append(
                    f"Phases : {phases.count()} ({phases.filter(status='DONE').count()} terminées)"
                )
        return "\n".join(lines)

    @classmethod
    def chat(
        cls,
        project,
        user_message: str,
        *,
        history: Optional[list] = None,
        max_tokens: int = 1500,
        temperature: float = 0.4,
    ) -> str:
        """
        Envoie un message à l'IA avec le persona méthodologie + contexte projet.

        ``history`` : liste de tuples (role, content) pour multi-tour.
        Retourne la réponse texte (Markdown) ou un message d'erreur poli.
        """
        provider = get_ai_provider()
        if not provider or not provider.is_available():
            return (
                "L'assistant IA n'est pas disponible pour le moment. "
                "Vérifiez la configuration DeepSeek/Anthropic dans les paramètres."
            )

        profile = cls.get_profile(project)
        if not profile:
            # Fallback générique
            system = (
                "Tu es un assistant projet polyvalent. Aide l'utilisateur de "
                "manière concise et factuelle, en français."
            )
        else:
            system = profile.system_prompt

        context = cls._build_context_block(project)
        full_system = f"{system}\n\n## Contexte projet courant\n{context}"

        messages = [AIMessage(role="system", content=full_system)]

        # Few-shot examples si dispo
        if profile and profile.examples:
            for ex in profile.examples[:3]:
                if ex.get("user"):
                    messages.append(AIMessage(role="user", content=ex["user"]))
                if ex.get("assistant"):
                    messages.append(AIMessage(role="assistant", content=ex["assistant"]))

        # Historique conversationnel
        for role, content in (history or []):
            if role in ("user", "assistant") and content:
                messages.append(AIMessage(role=role, content=content))

        messages.append(AIMessage(role="user", content=user_message))

        try:
            response = provider.generate(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (response.text or "").strip()
        except Exception as exc:
            logger.warning("MethodologyAIService.chat failed: %s", exc)
            return f"Erreur lors de la génération : {exc}"

    @classmethod
    def generate_artifact(
        cls,
        project,
        artifact_code: str,
        context_input: str = "",
    ) -> dict:
        """
        Génère un artefact (User Story, WBS, Risk Register, ...) en utilisant
        le prompt dédié de ``MethodologyArtifact.ai_prompt_key``.

        Retourne : ``{ "content": str, "kind": str, "title": str }`` ou
        ``{ "error": str }`` en cas d'échec.
        """
        code = (getattr(project, "methodology", None) or "").lower()
        if not code:
            return {"error": "Le projet n'a pas de méthodologie typée."}
        methodology = dm.Methodology.objects.filter(code=code).first()
        if not methodology:
            return {"error": "Méthodologie introuvable."}

        artifact = methodology.artifacts.filter(code=artifact_code).first()
        if not artifact:
            return {"error": f"Artefact '{artifact_code}' inconnu pour {code}."}

        provider = get_ai_provider()
        if not provider or not provider.is_available():
            return {"error": "Provider IA non disponible."}

        # Prompt système dérivé du persona + spécifique à l'artefact
        profile = cls.get_profile(project)
        persona_prompt = profile.system_prompt if profile else ""
        artifact_instruction = _ARTIFACT_PROMPTS.get(
            artifact.ai_prompt_key,
            f"Génère un document {artifact.name} structuré et professionnel.",
        )
        context_block = cls._build_context_block(project)

        messages = [
            AIMessage(role="system", content=f"{persona_prompt}\n\n{artifact_instruction}"),
            AIMessage(
                role="user",
                content=(
                    f"## Contexte\n{context_block}\n\n"
                    f"## Demande spécifique\n{context_input or 'Génère un premier brouillon basé sur le contexte.'}"
                ),
            ),
        ]

        try:
            response = provider.generate(
                messages=messages, temperature=0.3, max_tokens=3000,
            )
            return {
                "content": (response.text or "").strip(),
                "kind": artifact.template_kind,
                "title": artifact.name,
                "provider": response.provider,
            }
        except Exception as exc:
            logger.warning("Artifact generation failed: %s", exc)
            return {"error": str(exc)}


# ════════════════════════════════════════════════════════════════════════════
# Bibliothèque de prompts par artefact (clé = ai_prompt_key dans le seed)
# ════════════════════════════════════════════════════════════════════════════
_ARTIFACT_PROMPTS = {
    # Scrum
    "scrum.user_story": (
        "Génère UNE user story complète au format INVEST :\n"
        "- Titre court\n"
        "- 'As a [persona], I want [action], so that [valeur]'\n"
        "- Critères d'acceptation (Given/When/Then, 3-5 critères)\n"
        "- Story points estimés (Fibonacci 1, 2, 3, 5, 8)\n"
        "- Définition of Done\n"
        "Format Markdown."
    ),
    "scrum.epic": (
        "Génère un epic au format :\n"
        "- Titre\n"
        "- Objectif business\n"
        "- 3-8 user stories enfants (titre + 1 ligne)\n"
        "- Critères de succès (KPIs)\n"
        "- Risques identifiés"
    ),
    "scrum.sprint_goal": (
        "Génère un Sprint Goal clair, mesurable, focalisé. 1 phrase "
        "maximum + 3 sous-objectifs supportant le goal principal."
    ),
    "scrum.sprint_plan": (
        "Génère un plan de sprint structuré :\n"
        "- Sprint Goal\n"
        "- Capacité équipe\n"
        "- User stories sélectionnées (avec story points)\n"
        "- Risques identifiés\n"
        "- Dépendances externes"
    ),
    "scrum.retro_report": (
        "Génère un rapport de rétrospective :\n"
        "- 3 sections : What went well / What didn't / Action items\n"
        "- Tendances comparées au sprint précédent\n"
        "- Recommandations concrètes"
    ),

    # Kanban
    "kanban.flow_diagram": (
        "Génère un rapport de flux Kanban :\n"
        "- État du board (par colonne)\n"
        "- Identification des goulots d'étranglement\n"
        "- Recommandations WIP\n"
        "- Prévisions de débit"
    ),
    "kanban.bottleneck_report": (
        "Identifie et analyse les goulots d'étranglement du flux Kanban "
        "(tickets aging, WIP trop élevé, retards récurrents) et propose "
        "des actions correctives priorisées."
    ),

    # Waterfall
    "waterfall.project_charter": (
        "Génère une note de cadrage (Project Charter) :\n"
        "- Contexte & enjeux\n- Objectifs SMART\n- Périmètre (in/out)\n"
        "- Livrables\n- Parties prenantes & rôles\n- Planning haut niveau\n"
        "- Budget global\n- Risques majeurs initiaux"
    ),
    "waterfall.requirements_doc": (
        "Génère un cahier des charges fonctionnel :\n"
        "- Présentation du projet\n- Exigences fonctionnelles (numérotées)\n"
        "- Exigences non-fonctionnelles\n- Contraintes techniques\n"
        "- Critères d'acceptation"
    ),
    "waterfall.wbs": (
        "Génère un WBS (Work Breakdown Structure) à 3 niveaux :\n"
        "1. Phases (Études, Conception, Réalisation, Tests, Déploiement)\n"
        "2. Lots de travail par phase\n"
        "3. Tâches détaillées par lot\n"
        "Format JSON structuré (clé 'wbs' avec tree)."
    ),
    "waterfall.gantt_plan": (
        "Génère un planning Gantt :\n"
        "- Une ligne par tâche : Nom, début, fin, durée (jours), "
        "dépendances (IDs prédécesseurs), responsable\n"
        "Format CSV avec entête."
    ),
    "waterfall.quality_plan": (
        "Génère un plan qualité :\n"
        "- Standards applicables\n- Critères de validation par livrable\n"
        "- Plan de tests\n- Indicateurs qualité (DOR/DOD)\n- Revue des risques"
    ),
    "waterfall.risk_register": (
        "Génère un registre des risques :\n"
        "- Tableau : ID | Risque | Probabilité (1-5) | Impact (1-5) | "
        "Criticité (PxI) | Mitigation | Owner\n"
        "Identifie 8-15 risques pertinents au contexte."
    ),
    "waterfall.phase_report": (
        "Génère un rapport de phase :\n"
        "- Livrables produits\n- Avancement vs plan\n- Anomalies & corrections\n"
        "- Décisions prises\n- Risques actualisés\n- Go/No-go phase suivante"
    ),
}
