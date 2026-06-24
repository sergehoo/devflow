"""
DevFlow — Copilote conversationnel projet (PR17-METHODO).

Service qui :
  1. Reçoit un message utilisateur en langage naturel
  2. Décide via l'IA s'il faut appeler un tool ou juste répondre
  3. Exécute le tool si nécessaire (avec audit)
  4. Renvoie une réponse en langage naturel + la liste des actions effectuées

Exemple :
  user: "Crée-moi le Sprint 5 avec pour goal : finaliser RH"
  → tool: create_sprint(name="Sprint 5", goal="finaliser RH")
  → response: "Sprint 5 créé du 03/06 au 17/06. Goal : finaliser RH."
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from project import models as dm
from project.services.ai.base import AIMessage
from project.services.ai.factory import get_ai_provider
from project.services.methodology.tool_registry import (
    TOOL_REGISTRY, execute_tool, list_tools_for_ai,
)
from project.services.methodology.ai_service import MethodologyAIService

logger = logging.getLogger(__name__)


COPILOT_SYSTEM_PROMPT = """\
Tu es le Copilote IA de DevFlow, intégré à un projet spécifique.

Tu as accès à un ensemble de TOOLS qui te permettent d'exécuter des actions
concrètes dans le projet (créer un sprint, générer des user stories, etc.).

**Quand utiliser un tool ?**
- L'utilisateur demande une ACTION concrète (créer, générer, modifier, lister).
- Tu connais le tool exact qui peut le faire.

**Quand répondre directement (sans tool) ?**
- Question informationnelle ("qu'est-ce que...", "explique-moi...")
- Conseil méthodologique
- Demande d'analyse sans action

**Format de tes réponses** :

Si tu veux appeler un tool, renvoie UNIQUEMENT du JSON STRICT (rien d'autre) :
```
{"action": "tool_call", "tool": "create_sprint", "arguments": {"name": "Sprint 5", "duration_weeks": 2}}
```

Si tu réponds en texte, renvoie UNIQUEMENT du JSON STRICT :
```
{"action": "reply", "message": "Ta réponse en Markdown..."}
```

**Règles** :
- Le JSON doit être valide et parsable.
- Ne mets jamais de commentaire ou texte hors du JSON.
- Si tu n'es pas sûr d'un paramètre, choisis "reply" et demande clarification.
- Pour les actions destructives (delete, archive), choisis toujours "reply"
  pour demander confirmation explicite.
"""


def chat(
    project,
    user,
    user_message: str,
    *,
    history: Optional[list] = None,
) -> dict:
    """
    Point d'entrée principal du copilote.

    Retourne ``{ "type": "reply" | "tool_result", "message": str,
                 "actions_executed": [...], "history": [...] }``
    """
    provider = get_ai_provider()
    if not provider or not provider.is_available():
        return {
            "type": "error",
            "message": "L'assistant IA n'est pas disponible. Vérifiez la configuration.",
            "actions_executed": [],
        }

    # 1. Injecte le système prompt copilote + persona méthodologie + tools dispo
    profile = MethodologyAIService.get_profile(project)
    persona_prompt = profile.system_prompt if profile else ""
    tools_desc = json.dumps(list_tools_for_ai(), ensure_ascii=False, indent=2)
    context_block = MethodologyAIService._build_context_block(project)

    full_system = (
        f"{COPILOT_SYSTEM_PROMPT}\n\n"
        f"## Persona méthodologie\n{persona_prompt}\n\n"
        f"## Contexte projet\n{context_block}\n\n"
        f"## Tools disponibles\n{tools_desc}"
    )

    messages = [AIMessage(role="system", content=full_system)]
    for role, content in (history or [])[-10:]:  # garde les 10 derniers tours
        if role in ("user", "assistant") and content:
            messages.append(AIMessage(role=role, content=content))
    messages.append(AIMessage(role="user", content=user_message))

    # 2. Appel IA en JSON mode
    try:
        response = provider.generate(
            messages=messages,
            temperature=0.2,
            max_tokens=1200,
            json_mode=True,
        )
        raw = (response.text or "").strip()
    except Exception as exc:
        logger.warning("Copilot AI call failed: %s", exc)
        return {
            "type": "error",
            "message": f"Erreur IA : {exc}",
            "actions_executed": [],
        }

    # 3. Parse JSON
    try:
        if raw.startswith("```"):
            raw = raw.split("```", 2)[-1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        decision = json.loads(raw.strip())
    except Exception as exc:
        # Fallback : on traite le texte comme une simple reply
        return {
            "type": "reply",
            "message": raw or "Désolé, je n'ai pas compris.",
            "actions_executed": [],
        }

    action = decision.get("action", "reply")

    if action == "tool_call":
        tool_name = decision.get("tool", "")
        args = decision.get("arguments", {}) or {}
        # Exécute avec audit
        result = execute_tool(
            tool_name=tool_name, user=user, project=project,
            user_message=user_message, **args,
        )
        if result["status"] == "SUCCESS":
            r = result.get("result", {}) or {}
            return {
                "type": "tool_result",
                "message": r.get("message", "✓ Action exécutée."),
                "tool_name": tool_name,
                "actions_executed": [{
                    "tool": tool_name, "args": args,
                    "result": r, "log_id": result["log_id"],
                }],
            }
        else:
            return {
                "type": "tool_error",
                "message": (
                    f"L'action a échoué : {result.get('error', 'erreur inconnue')}"
                ),
                "tool_name": tool_name,
                "actions_executed": [{
                    "tool": tool_name, "args": args,
                    "status": result["status"], "log_id": result["log_id"],
                }],
            }
    else:
        # action == "reply"
        return {
            "type": "reply",
            "message": decision.get("message", "—"),
            "actions_executed": [],
        }
