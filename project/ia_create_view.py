from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import FormView
from django import forms

from project import models as dm
from project.services.project_import_orchestrator import ProjectImportOrchestrator


class ProjectImportForm(forms.Form):
    workspace = forms.ModelChoiceField(queryset=dm.Workspace.objects.all())
    file = forms.FileField()

    def __init__(self, *args, **kwargs):
        # Filtrage workspace : on n'expose que les workspaces auxquels
        # l'utilisateur courant a réellement accès (sécurité).
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user is not None and not user.is_superuser:
            self.fields["workspace"].queryset = dm.Workspace.objects.filter(
                memberships__user=user, memberships__status="ACTIVE"
            ).distinct()


class ProjectDocumentImportView(LoginRequiredMixin, FormView):
    """
    Vue legacy d'import IA d'un document projet. Conservée pour compat,
    mais protégée par LoginRequiredMixin et avec un filtrage workspace.
    Le flow recommandé est désormais ``ProjectDocumentImportCreateView``
    (voir project/views.py + templates/project/document_import/).
    """

    template_name = "project/document_import/form.html"
    form_class = ProjectImportForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

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
            return redirect("project_document_import_list")