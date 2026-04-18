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
        À remplacer par ton client OpenAI / Azure / autre.
        Cette fonction doit retourner un dict Python.
        """
        raise NotImplementedError("Brancher ici ton moteur LLM structuré.")