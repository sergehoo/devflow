# from __future__ import annotations
#
# import json
# from pathlib import Path
#
# from django.core.files.storage import default_storage
#
# from project.schemas.project_import_schema import PROJECT_IMPORT_SCHEMA
# from project.services.openai_client import get_openai_client
#
#
# class AIProjectImportService:
#     @classmethod
#     def upload_file(cls, file_field) -> str:
#         client = get_openai_client()
#
#         # file_field peut être un FileField Django ou un UploadedFile
#         with file_field.open("rb") if hasattr(file_field, "open") else file_field as f:
#             uploaded = client.files.create(
#                 file=f,
#                 purpose="user_data",
#             )
#         return uploaded.id
#
#     @classmethod
#     def analyze_file(cls, file_id: str) -> dict:
#         client = get_openai_client()
#
#         prompt = """
# Tu es un expert PMO, CTO, CFO et analyste métier.
#
# Analyse le document fourni et produis UNE structure projet exploitable dans DevFlow.
#
# Objectifs:
# - identifier le projet
# - construire roadmap, milestones, sprints, features, tâches
# - identifier les équipes impliquées (marketing, dev, sales, etc.)
# - relier les données financières
# - produire les KPI métier
# - calculer si possible:
#   - coût par sprint
#   - coût par feature
#   - ROI par module
#
# Règles:
# - retourne uniquement les informations présentes ou fortement déductibles
# - si une information est absente, renvoie null
# - ne crée pas d'éléments fantaisistes
# - dates au format YYYY-MM-DD si possible
# - montants numériques sans texte
# """
#
#         response = client.responses.create(
#             model="gpt-4.1",
#             input=[
#                 {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "input_text",
#                             "text": prompt,
#                         },
#                         {
#                             "type": "input_file",
#                             "file_id": file_id,
#                         },
#                     ],
#                 }
#             ],
#             text={
#                 "format": {
#                     "type": "json_schema",
#                     "name": PROJECT_IMPORT_SCHEMA["name"],
#                     "schema": PROJECT_IMPORT_SCHEMA["schema"],
#                     "strict": True,
#                 }
#             },
#         )
#
#         # Selon les SDK récents, output_text est le moyen le plus simple
#         raw = response.output_text
#         return json.loads(raw)
#
#     @classmethod
#     def analyze_uploaded_django_file(cls, uploaded_file) -> dict:
#         file_id = cls.upload_file(uploaded_file)
#         return cls.analyze_file(file_id=file_id)