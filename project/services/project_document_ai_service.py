from __future__ import annotations

import json
from pathlib import Path

from django.core.files.storage import default_storage

try:
    import docx
except Exception:
    docx = None

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


class ProjectDocumentAIService:
    @staticmethod
    def extract_text_from_docx(file_path: str) -> str:
        if docx is None:
            raise RuntimeError("python-docx n'est pas installé.")
        document = docx.Document(file_path)
        parts = []
        for paragraph in document.paragraphs:
            text = (paragraph.text or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def extract_text_from_pdf(file_path: str) -> str:
        if PdfReader is None:
            raise RuntimeError("pypdf n'est pas installé.")
        reader = PdfReader(file_path)
        parts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
        return "\n\n".join(parts)

    @classmethod
    def extract_text(cls, file_field) -> str:
        file_path = file_field.path if hasattr(file_field, "path") else str(file_field)
        ext = Path(file_path).suffix.lower()

        if ext == ".docx":
            return cls.extract_text_from_docx(file_path)
        if ext == ".pdf":
            return cls.extract_text_from_pdf(file_path)

        raise ValueError(f"Format non supporté: {ext}")

    @staticmethod
    def build_prompt(document_text: str) -> str:
        return f"""
Tu es un analyste senior PMO + architecte logiciel.
Analyse ce document projet et retourne UNIQUEMENT un JSON valide.

Objectif :
- identifier le projet
- détecter roadmap, milestones, sprints, features, tâches
- détecter équipes (marketing, dev, sales, produit...)
- estimer budget, revenus, coûts, KPI
- produire une structure prête pour un import dans DevFlow

Contraintes :
- aucun commentaire
- aucune phrase hors JSON
- dates ISO YYYY-MM-DD si possible
- si une donnée est absente, mets null ou valeur vide
- pour les KPI, inclure au minimum :
  - taux_conversion
  - cout_par_lead
  - temps_traitement

Document :
{document_text}
""".strip()

    @staticmethod
    def call_llm_to_structured_json(prompt: str) -> dict:
        """
        Appelle le provider IA configuré (settings.AI_BACKEND) et retourne
        un dict structuré. Si aucun provider n'est disponible, lève une
        RuntimeError explicite plutôt que NotImplementedError.
        """
        # Imports locaux pour éviter les imports circulaires
        from project.services.ai.base import AIMessage
        from project.services.ai.factory import get_ai_provider
        from project.services.ai.openai_provider import OpenAIProvider

        provider = get_ai_provider()
        if not provider.is_available():
            raise RuntimeError(
                "Aucun provider IA disponible. Configurez OPENAI_API_KEY ou "
                "AI_LOCAL_BASE_URL, ou définissez settings.AI_BACKEND."
            )

        messages = [
            AIMessage(
                role="system",
                content=(
                    "Tu es un analyste senior PMO + architecte logiciel. "
                    "Tu réponds STRICTEMENT en JSON valide, sans aucun texte additionnel."
                ),
            ),
            AIMessage(role="user", content=prompt),
        ]
        response = provider.generate(
            messages=messages,
            temperature=0.1,
            json_mode=provider.supports_json_mode(),
        )

        if isinstance(provider, OpenAIProvider):
            data = OpenAIProvider.parse_json(response)
        else:
            try:
                data = json.loads(response.text)
            except json.JSONDecodeError:
                # Tentative de récupération si entouré de markdown
                text = response.text.strip()
                if text.startswith("```"):
                    text = text.split("```", 2)[-1]
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.rsplit("```", 1)[0]
                data = json.loads(text)

        if not isinstance(data, dict):
            raise RuntimeError("La réponse IA n'est pas un objet JSON exploitable.")
        return data