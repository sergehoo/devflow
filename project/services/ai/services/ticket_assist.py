"""
Assistance IA au traitement des tickets (infrastructure IA DevFlow existante).

* ``triage``     : suggestion de catégorie, gravité et priorité ;
* ``summary``    : résumé du ticket et de ses échanges ;
* ``reply``      : proposition de réponse au déclarant (fil public uniquement) ;
* ``duplicates`` : doublons potentiels (similarité lexicale, sans IA).

Règles :
* rien n'est appliqué ni envoyé ici : l'agent valide via les actions existantes
  (« qualifier », « commenter ») — aucune réponse automatique au client ;
* sans fournisseur, sans quota ou en cas d'erreur, on renvoie une suggestion
  déterministe (``source = "rules"``) : jamais d'erreur pour l'agent ;
* les adresses e-mail, numéros de téléphone, URL et longues suites de chiffres
  sont masqués avant tout envoi au fournisseur ;
* la proposition de réponse n'utilise jamais les notes internes.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import timedelta

from django.utils import timezone

from project import models as dm
from project.services.ai.base import AIMessage

logger = logging.getLogger(__name__)
T = dm.Ticket
SEVERITY_PRIORITY = {"CRITICAL": "P1", "MAJOR": "P2", "MINOR": "P3", "TRIVIAL": "P4"}
MAX_TEXT = 3000

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://\S+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d .-]{7,}\d(?!\w)")
_LONG_DIGITS = re.compile(r"\d{6,}")


def redact(text: str) -> str:
    """Masque les données personnelles ou secrètes avant envoi à un fournisseur IA."""
    text = _EMAIL.sub("[email]", text or "")
    text = _URL.sub("[url]", text)
    text = _PHONE.sub("[téléphone]", text)
    return _LONG_DIGITS.sub("[nombre]", text)


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


# ---------------------------------------------------------------------------
# Règles déterministes (repli et base de comparaison)
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS = [
    ("ACCESS", ("mot de passe", "connexion", "connecter", "login", "acces", "compte", "authentification", "bloque mon compte")),
    ("FEATURE", ("serait bien", "souhaiterais", "ajouter une", "evolution", "nouvelle fonctionnalite", "amelioration", "pourriez-vous ajouter")),
    ("QUESTION", ("comment ", "est-il possible", "question", "savoir si", "ou trouver", "how to")),
    ("INCIDENT", ("indisponible", "panne", "ne repond plus", "hors service", "down", "inaccessible", "tous les utilisateurs")),
    ("BUG", ("erreur", "bug", "plantage", "crash", "ne fonctionne pas", "echoue", "exception", "500", "affiche mal")),
]
SEVERITY_KEYWORDS = [
    ("CRITICAL", ("tous les utilisateurs", "production", "bloquant", "indisponible", "panne", "perte de donnees", "paiement", "securite", "hors service")),
    ("MAJOR", ("impossible", "ne fonctionne pas", "echoue", "plusieurs utilisateurs", "urgent", "erreur 500")),
    ("TRIVIAL", ("faute", "orthographe", "cosmetique", "alignement", "couleur", "libelle")),
]


def _rules_triage(ticket) -> dict:
    text = _fold(f"{ticket.title}\n{ticket.description}")
    category = next((c for c, words in CATEGORY_KEYWORDS if any(w in text for w in words)), ticket.category)
    severity = next((s for s, words in SEVERITY_KEYWORDS if any(w in text for w in words)), ticket.severity)
    hits = [w for _, words in CATEGORY_KEYWORDS + SEVERITY_KEYWORDS for w in words if w in text][:4]
    rationale = (f"Mots-clés relevés : {', '.join(hits)}." if hits else "Aucun mot-clé déterminant : valeurs actuelles conservées.")
    return {"category": category, "severity": severity, "priority": SEVERITY_PRIORITY.get(severity, ticket.priority),
            "rationale": rationale + " Priorité déduite de la gravité (règle DevFlow)."}


def _public_thread(ticket) -> list:
    return list(ticket.comments.filter(visibility="PUBLIC").select_related("author").order_by("created_at"))


def _rules_summary(ticket, comments) -> str:
    parts = [
        f"{ticket.reference} — {ticket.title} ({ticket.get_category_display()}, gravité {ticket.get_severity_display().lower()}, "
        f"priorité {ticket.get_priority_display()}, statut {ticket.get_status_display().lower()}).",
    ]
    if ticket.description:
        parts.append(f"Demande : {ticket.description.strip()[:300]}{'…' if len(ticket.description.strip()) > 300 else ''}")
    public = sum(c.visibility == "PUBLIC" for c in comments)
    if comments:
        last = comments[-1]
        parts.append(f"{len(comments)} échange(s) dont {public} public(s) ; dernier message le "
                     f"{timezone.localtime(last.created_at):%d/%m/%Y à %H:%M} : {last.body.strip()[:200]}")
    else:
        parts.append("Aucun échange pour l'instant.")
    if ticket.first_response_breached or ticket.resolution_breached:
        parts.append("SLA dépassé.")
    return "\n".join(parts)


def _rules_reply(ticket) -> str:
    who = (ticket.reporter_name or "").split(" ")[0] or "Madame, Monsieur"
    status = {
        T.Status.WAITING: "Pour avancer, pourriez-vous nous préciser les étapes qui mènent au problème et nous joindre une capture d'écran ?",
        T.Status.RESOLVED: "Le correctif est en place : pourriez-vous confirmer que tout fonctionne de votre côté ?",
    }.get(ticket.status, "Notre équipe analyse votre demande et revient vers vous dès que possible.")
    return f"Bonjour {who},\n\nMerci pour votre message concernant « {ticket.title} » ({ticket.reference}).\n{status}\n\nCordialement,\nL'équipe support"


# ---------------------------------------------------------------------------
# Appel au fournisseur IA (quota, masquage, JSON tolérant)
# ---------------------------------------------------------------------------
def _ask(workspace, system: str, payload: dict, *, tokens: int, json_mode: bool):
    from project.services.ai.factory import get_ai_provider
    from project.services.ai.openai_provider import OpenAIProvider
    from project.services.ai.quota import AIQuotaService

    provider = get_ai_provider()
    if not provider.is_available():
        return None, None
    if not AIQuotaService.can_consume(workspace, estimated_tokens=tokens).allowed:
        logger.info("ticket assist: AI quota reached for workspace %s", workspace.pk)
        return None, None
    try:
        response = provider.generate(
            [AIMessage(role="system", content=system), AIMessage(role="user", content=json.dumps(payload, ensure_ascii=False))],
            temperature=0.2, max_tokens=tokens, json_mode=json_mode and provider.supports_json_mode(),
        )
    except Exception as exc:  # réseau, quota fournisseur, clé… → repli sur les règles
        logger.warning("ticket assist: provider %s failed: %s", getattr(provider, "name", "?"), exc.__class__.__name__)
        return None, None
    try:
        AIQuotaService.record_usage(workspace, response.tokens_used or tokens)
    except Exception:  # le suivi de quota ne doit jamais bloquer la suggestion
        logger.warning("ticket assist: quota recording failed", exc_info=True)
    if not json_mode:
        return (response.text or "").strip() or None, provider.name
    data = OpenAIProvider.parse_json(response)
    return (data or None), provider.name


def _ticket_payload(ticket, comments, *, internal: bool) -> dict:
    return {
        "reference": ticket.reference, "application": ticket.application.name if ticket.application_id else "",
        "title": redact(ticket.title), "description": redact(ticket.description)[:MAX_TEXT],
        "category": ticket.category, "severity": ticket.severity, "priority": ticket.priority, "status": ticket.status,
        "messages": [
            {"from": "support" if c.author_id else "client", "visibility": c.visibility if internal else "PUBLIC",
             "date": timezone.localtime(c.created_at).strftime("%d/%m/%Y %H:%M"), "text": redact(c.body)[:800]}
            for c in comments[-12:]
        ],
    }


# ---------------------------------------------------------------------------
# API du service
# ---------------------------------------------------------------------------
def _choice(value, choices, default):
    return value if value in choices.values else default


def triage(ticket, *, use_ai: bool = True) -> dict:
    base = _rules_triage(ticket)
    result, provider = dict(base), None
    if use_ai:
        data, provider = _ask(ticket.workspace, (
            "Tu es responsable support (ITSM). Qualifie le ticket. Réponds STRICTEMENT en JSON : "
            '{"category": "BUG|INCIDENT|QUESTION|FEATURE|ACCESS|OTHER", "severity": "CRITICAL|MAJOR|MINOR|TRIVIAL", '
            '"priority": "P1|P2|P3|P4", "rationale": "une ou deux phrases en français"}. '
            "N'invente aucun fait absent du ticket."
        ), _ticket_payload(ticket, [], internal=False), tokens=400, json_mode=True)
        if isinstance(data, dict):
            result = {
                "category": _choice(data.get("category"), T.Category, base["category"]),
                "severity": _choice(data.get("severity"), T.Severity, base["severity"]),
                "priority": _choice(data.get("priority"), T.Priority, base["priority"]),
                "rationale": str(data.get("rationale") or base["rationale"])[:600],
            }
        else:
            provider = None
    labels = {"category": dict(T.Category.choices), "severity": dict(T.Severity.choices), "priority": dict(T.Priority.choices)}
    return {
        **{f: {"value": result[f], "label": labels[f][result[f]], "current": getattr(ticket, f),
               "changed": result[f] != getattr(ticket, f)} for f in ("category", "severity", "priority")},
        "rationale": result["rationale"], "source": "ai" if provider else "rules", "provider": provider or "",
    }


def summary(ticket, *, internal: bool, use_ai: bool = True) -> dict:
    comments = list(ticket.comments.select_related("author").order_by("created_at"))
    if not internal:
        comments = [c for c in comments if c.visibility == "PUBLIC"]
    text, provider = (None, None)
    if use_ai:
        text, provider = _ask(ticket.workspace, (
            "Tu es agent support. Résume ce ticket et ses échanges en français, en 3 à 6 puces courtes : "
            "problème, impact, ce qui a été fait, ce qui reste à faire ou attendu. Uniquement les faits présents ; "
            "signale clairement les notes internes."
        ), _ticket_payload(ticket, comments, internal=internal), tokens=500, json_mode=False)
    return {"summary": (text or _rules_summary(ticket, comments))[:4000], "source": "ai" if text else "rules", "provider": provider or ""}


def reply(ticket, *, use_ai: bool = True) -> dict:
    comments = _public_thread(ticket)  # jamais de note interne dans une réponse destinée au client
    text, provider = (None, None)
    if use_ai:
        text, provider = _ask(ticket.workspace, (
            "Tu es agent support. Rédige en français une réponse courte, polie et factuelle au déclarant du ticket, "
            "à partir uniquement du fil public fourni. Ne promets aucun délai ni correctif non mentionné. "
            "Si une information manque, demande-la. Pas d'objet, pas de signature nominative ; "
            "les éléments masqués ([email], [url]…) ne doivent pas être recopiés."
        ), _ticket_payload(ticket, comments, internal=False), tokens=500, json_mode=False)
    return {"reply": (text or _rules_reply(ticket))[:4000], "source": "ai" if text else "rules", "provider": provider or ""}


STOP_WORDS = set("""
le la les un une des de du d l et ou a au aux en dans sur pour par avec sans ne pas plus est sont ce cette ces
je j il elle nous vous ils on mon ma mes ton ta tes son sa ses notre votre leur qui que quoi dont the to of and is
bonjour merci svp probleme ticket
""".split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", _fold(text)) if w not in STOP_WORDS}


def duplicates(ticket, visible_qs, *, limit: int = 5, days: int = 90, threshold: float = 0.3) -> list[dict]:
    """
    Tickets proches (mêmes mots dans le titre et le début de la description, même application,
    même déclarant), parmi les tickets **visibles par l'agent** du même workspace.
    """
    title, body = _tokens(ticket.title), _tokens(ticket.description[:600])
    if not (title or body):
        return []
    since = timezone.now() - timedelta(days=days)
    candidates = (visible_qs.filter(workspace_id=ticket.workspace_id, created_at__gte=since)
                  .exclude(pk=ticket.pk).exclude(status=T.Status.CANCELLED)
                  .select_related("application").order_by("-created_at")[:300])
    found = []
    for other in candidates:
        o_title, o_body = _tokens(other.title), _tokens(other.description[:600])
        t_sim = len(title & o_title) / len(title | o_title) if title | o_title else 0
        b_sim = len(body & o_body) / len(body | o_body) if body | o_body else 0
        score = 0.65 * t_sim + 0.35 * b_sim
        reasons = []
        if title & o_title:
            reasons.append("mots du titre : " + ", ".join(sorted(title & o_title)[:5]))
        if other.application_id == ticket.application_id:
            score += 0.1
            reasons.append("même application")
        same_reporter = (ticket.reporter_external_id and other.reporter_external_id == ticket.reporter_external_id) or (
            ticket.reporter_email and other.reporter_email.lower() == ticket.reporter_email.lower())
        if same_reporter:
            score += 0.15
            reasons.append("même déclarant")
        if score >= threshold and (t_sim or b_sim):
            found.append({
                "id": other.pk, "reference": other.reference, "title": other.title, "status": other.status,
                "status_label": other.get_status_display(), "application": other.application.name,
                "created_at": other.created_at, "score": round(min(score, 1.0), 2), "reasons": reasons,
            })
    return sorted(found, key=lambda d: -d["score"])[:limit]
