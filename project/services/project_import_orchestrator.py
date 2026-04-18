from __future__ import annotations

from dataclasses import dataclass

from project import models as dm
from project.services.project_ai_import_service import ProjectAIImportService, ImportContext
from project.services.project_document_ai_service import ProjectDocumentAIService


@dataclass
class ProjectImportResult:
    project: dm.Project
    payload: dict


class ProjectImportOrchestrator:
    @classmethod
    def import_from_file(cls, *, workspace: dm.Workspace, file_field, created_by):
        text = ProjectDocumentAIService.extract_text(file_field)
        prompt = ProjectDocumentAIService.build_prompt(text)
        payload = ProjectDocumentAIService.call_llm_to_structured_json(prompt)

        context = ImportContext(
            workspace=workspace,
            created_by=created_by,
            owner=created_by,
            product_manager=created_by,
        )

        project = ProjectAIImportService.import_from_structured_payload(
            payload=payload,
            context=context,
        )
        return ProjectImportResult(project=project, payload=payload)