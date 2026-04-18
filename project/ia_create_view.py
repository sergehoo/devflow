from django.contrib import messages
from django.shortcuts import redirect
from django.views.generic import FormView
from django import forms

from project import models as dm
from project.services.project_import_orchestrator import ProjectImportOrchestrator


class ProjectImportForm(forms.Form):
    workspace = forms.ModelChoiceField(queryset=dm.Workspace.objects.all())
    file = forms.FileField()


class ProjectDocumentImportView(FormView):
    template_name = "project/import/form.html"
    form_class = ProjectImportForm

    def form_valid(self, form):
        workspace = form.cleaned_data["workspace"]
        file = form.cleaned_data["file"]

        import_obj = dm.ProjectDocumentImport.objects.create(
            workspace=workspace,
            uploaded_by=self.request.user,
            file=file,
            status=dm.ProjectDocumentImport.ImportStatus.PROCESSING,
        )

        try:
            result = ProjectImportOrchestrator.import_from_file(
                workspace=workspace,
                file_field=import_obj.file,
                created_by=self.request.user,
            )
            import_obj.project = result.project
            import_obj.ai_payload = result.payload
            import_obj.status = dm.ProjectDocumentImport.ImportStatus.COMPLETED
            import_obj.save(update_fields=["project", "ai_payload", "status", "updated_at"])

            messages.success(self.request, "Projet importé automatiquement avec succès.")
            return redirect("project_detail", pk=result.project.pk)

        except Exception as exc:
            import_obj.status = dm.ProjectDocumentImport.ImportStatus.FAILED
            import_obj.error_message = str(exc)
            import_obj.save(update_fields=["status", "error_message", "updated_at"])
            messages.error(self.request, f"Échec de l'import : {exc}")
            return redirect("project_import")