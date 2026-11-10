"""
Chantier « ai » — API React de structuration automatique des projets :
Genesis, propositions IA (aperçu, édition, validation, application,
régénération, déclenchement + statut), import documentaire, copilote.

Isolation workspace (404), throttle IA, repli heuristique (AI_BACKEND=none),
non-régression du déclenchement asynchrone (proposition « en attente » complétée).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_ai
"""

import shutil
import tempfile
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from project import models as dm
from project.api.throttles import AIActionRateThrottle
from project.api import views_ai
from project.services.ai.services.project_structure import ProjectAIStructureService
from project.tests_legacy_rights import LegacyFixture

Proposal = dm.ProjectAIProposal
Item = dm.ProjectAIProposalItem


MEDIA_ROOT = tempfile.mkdtemp(prefix="devflow-tests-ai-")


def tearDownModule():
    shutil.rmtree(MEDIA_ROOT, ignore_errors=True)


@override_settings(AI_BACKEND="none", MEDIA_ROOT=MEDIA_ROOT)
class AIFixture(LegacyFixture):
    def setUp(self):
        super().setUp()
        cache.clear()  # compteurs de throttle

    def proposal(self, project=None):
        return ProjectAIStructureService.generate_for_project(
            project=project or self.project, triggered_by=self.owner, use_ai=False,
        ).proposal


class GenesisTests(AIFixture):
    url = "/api/v1/ai/genesis/"

    def test_schema_lists_only_user_workspaces_and_ai_status(self):
        data = self.api(self.pm).get(self.url).json()
        fields = {f["name"]: f for f in data["fields"]}
        ws_values = {c["value"] for c in fields["workspace"]["choices"]}
        self.assertIn(str(self.ws.pk), ws_values)
        self.assertNotIn(str(self.other.pk), ws_values)
        self.assertEqual(fields["workspace"]["value"], self.ws.pk)
        self.assertEqual(data["ai"], {"available": False, "provider": ""})
        self.assertTrue(data["can_create"])

    def test_member_without_project_create_right_is_refused(self):
        data = self.api(self.dev).get(self.url).json()
        fields = {f["name"]: f for f in data["fields"]}
        self.assertFalse(data["can_create"])
        self.assertNotIn(str(self.ws.pk), {c["value"] for c in fields["workspace"]["choices"]})
        res = self.api(self.dev).post(self.url, {
            "name": "Interdit", "description": "x", "workspace": self.ws.pk, "priority": "MEDIUM",
        }, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(dm.Project.objects.filter(name="Interdit").exists())

    def test_foreign_workspace_is_refused(self):
        res = self.api(self.pm).post(self.url, {
            "name": "Pirate", "description": "x", "workspace": self.other.pk, "priority": "MEDIUM",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("workspace", res.json())
        self.assertFalse(dm.Project.objects.filter(name="Pirate").exists())

    def test_create_and_apply_with_heuristic_fallback(self):
        res = self.api(self.pm).post(self.url, {
            "name": "Boutique", "description": "Refonte du site marchand", "workspace": self.ws.pk,
            "priority": "HIGH", "methodology": "SCRUM", "auto_apply": True,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertTrue(body["applied"])
        self.assertEqual(body["used_provider"], "heuristic")
        project = dm.Project.objects.get(pk=body["project"]["id"])
        self.assertEqual((project.workspace_id, project.owner_id), (self.ws.pk, self.pm.pk))
        self.assertGreater(project.tasks.count(), 0)
        self.assertEqual(Proposal.objects.get(pk=body["proposal"]["id"]).status, Proposal.Status.APPLIED)

    def test_preview_mode_keeps_proposal_for_review(self):
        res = self.api(self.pm).post(self.url, {
            "name": "Revue", "description": "Projet à relire", "workspace": self.ws.pk,
            "priority": "MEDIUM", "auto_apply": False,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(res.json()["applied"])
        proposal = Proposal.objects.get(pk=res.json()["proposal"]["id"])
        self.assertEqual(proposal.status, Proposal.Status.READY)
        self.assertEqual(proposal.project.tasks.count(), 0)

    def test_auto_apply_leaves_a_single_proposal(self):
        """Non-régression : le signal post_save ne relance plus une génération IA en double."""
        from project.tasks import generate_project_ai_proposal_task

        def run_now(**kwargs):  # Celery synchrone
            generate_project_ai_proposal_task.apply(kwargs={**kwargs, "use_ai": False})

        with mock.patch.object(generate_project_ai_proposal_task, "delay", side_effect=run_now) as delay, \
                self.captureOnCommitCallbacks(execute=True):
            res = self.api(self.pm).post(self.url, {
                "name": "Unique", "description": "Refonte", "workspace": self.ws.pk,
                "priority": "MEDIUM", "auto_apply": True,
            }, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        delay.assert_not_called()
        statuses = list(Proposal.objects.filter(project_id=res.json()["project"]["id"]).values_list("status", flat=True))
        self.assertEqual(statuses, [Proposal.Status.APPLIED])

    def test_post_is_ai_throttled(self):
        view = views_ai.GenesisView()
        view.request = mock.Mock(method="POST")
        self.assertTrue(any(isinstance(t, AIActionRateThrottle) for t in view.get_throttles()))


class ProposalTests(AIFixture):
    def setUp(self):
        super().setUp()
        self.p = self.proposal()
        self.task_item = self.p.items.filter(kind=Item.Kind.TASK).first()

    def detail(self, user):
        return self.api(user).get(f"/api/v1/ai-proposals/{self.p.pk}/")

    def test_detail_exposes_tree_coherence_and_logs(self):
        res = self.detail(self.pm)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "READY")
        self.assertTrue(all(data[k] for k in ("can_edit", "editable", "can_apply", "can_reject", "can_regenerate")))
        self.assertEqual(len(data["items"]), self.p.items.count())
        self.assertIn("TASK", data["counts"]["by_kind"])
        self.assertIn("unassigned_tasks", data["coherence"])
        self.assertTrue(any(log["action"] == "GENERATED" for log in data["logs"]))

    def test_cross_tenant_access_is_404(self):
        base = f"/api/v1/ai-proposals/{self.p.pk}"
        bob = self.api(self.bob)
        self.assertEqual(self.detail(self.bob).status_code, 404)
        self.assertEqual(bob.post(f"{base}/apply/").status_code, 404)
        self.assertEqual(bob.post(f"{base}/reject/").status_code, 404)
        self.assertEqual(bob.post(f"{base}/validate-all/").status_code, 404)
        self.assertEqual(bob.post(f"{base}/regenerate/").status_code, 404)
        self.assertEqual(bob.post(f"{base}/items/{self.task_item.pk}/validate/").status_code, 404)
        self.assertEqual(bob.get(f"{base}/items/{self.task_item.pk}/form/").status_code, 404)
        self.assertEqual(bob.get(f"/api/v1/projects/{self.project.pk}/ai-proposals/").status_code, 404)
        self.assertEqual(bob.post(f"/api/v1/projects/{self.project.pk}/ai-proposals/trigger/").status_code, 404)
        self.assertEqual(bob.get(f"/api/v1/projects/{self.project.pk}/ai-proposals/status/").status_code, 404)
        ids = [r["id"] for r in bob.get("/api/v1/ai-proposals/").json()["results"]]
        self.assertNotIn(self.p.pk, ids)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, Proposal.Status.READY)

    def test_item_of_another_proposal_is_404(self):
        other = self.proposal(self.project2)
        foreign_item = other.items.first()
        res = self.api(self.dev).post(f"/api/v1/ai-proposals/{self.p.pk}/items/{foreign_item.pk}/validate/")
        self.assertEqual(res.status_code, 404)

    def test_item_validate_reject_and_edit(self):
        api = self.api(self.pm)
        base = f"/api/v1/ai-proposals/{self.p.pk}/items/{self.task_item.pk}"
        res = api.post(f"{base}/validate/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["item"]["item_status"], "VALIDATED")
        self.assertEqual(res.json()["proposal_status"], "PARTIALLY_VALIDATED")
        res = api.post(f"{base}/reject/")
        self.assertEqual(res.status_code, 200)  # message « warning » côté Django : succès quand même
        self.assertEqual(res.json()["item"]["item_status"], "REJECTED")
        schema = api.get(f"{base}/form/").json()
        labels = {f["name"]: f["label"] for f in schema["fields"]}
        self.assertEqual(labels["recommended_profile"], "Profil recommandé")
        data = {f["name"]: f["value"] for f in schema["fields"] if f["value"] not in (None, "")}
        data.update({"title": "Tâche revue", "estimate_hours": "12"})
        res = api.post(f"{base}/form/", data, format="multipart")
        self.assertEqual(res.status_code, 200, res.content)
        self.task_item.refresh_from_db()
        self.assertEqual((self.task_item.title, self.task_item.item_status), ("Tâche revue", "EDITED"))
        self.assertTrue(self.p.logs.filter(action="ITEM_EDITED").exists())

    def test_validate_all_apply_and_links(self):
        api = self.api(self.pm)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/validate-all/").status_code, 200)
        res = api.post(f"/api/v1/ai-proposals/{self.p.pk}/apply/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["project_id"], self.project.pk)
        self.assertGreater(res.json()["applied_by_kind"]["TASK"], 0)
        data = self.detail(self.pm).json()
        self.assertEqual(data["status"], "APPLIED")
        task = next(i for i in data["items"] if i["kind"] == "TASK")
        self.assertRegex(task["applied"]["link"], r"^/tasks/\d+$")
        self.assertTrue(dm.Task.objects.filter(pk=task["applied"]["id"], project=self.project).exists())
        # Une fois appliquée : plus d'action qui recréerait des doublons.
        item = self.p.items.filter(item_status=Item.ItemStatus.APPLIED).first()
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/items/{item.pk}/validate/").status_code, 409)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/reject/").status_code, 409)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/validate-all/").status_code, 409)
        res = api.post(f"/api/v1/ai-proposals/{self.p.pk}/apply/")
        self.assertEqual(res.status_code, 400)  # ProposalApplyService refuse (message d'erreur Django)

    def test_reject_and_regenerate(self):
        api = self.api(self.pm)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/reject/").status_code, 200)
        self.p.refresh_from_db()
        self.assertEqual(self.p.status, Proposal.Status.REJECTED)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/reject/").status_code, 409)  # déjà rejetée
        res = api.post(f"/api/v1/ai-proposals/{self.p.pk}/regenerate/", {"use_ai": "on"}, format="multipart")
        self.assertEqual(res.status_code, 201, res.content)
        new = Proposal.objects.get(pk=res.json()["id"])
        self.assertNotEqual(new.pk, self.p.pk)
        self.assertEqual((new.project_id, new.status), (self.project.pk, Proposal.Status.READY))
        self.assertTrue(self._ai_throttled(action="regenerate"))
        self.assertFalse(self._ai_throttled(action="apply"))

    def test_member_without_rights_cannot_act(self):
        """RBAC : un MEMBER lit la proposition mais n'agit pas dessus (403), même en appelant l'API directement."""
        api = self.api(self.dev)
        base = f"/api/v1/ai-proposals/{self.p.pk}"
        data = self.detail(self.dev).json()
        self.assertEqual(data["status"], "READY")
        self.assertFalse(any(data[k] for k in ("can_edit", "editable", "can_apply", "can_validate_all", "can_reject", "can_regenerate")))
        for action in ("validate-all", "apply", "reject", "regenerate"):
            self.assertEqual(api.post(f"{base}/{action}/").status_code, 403, action)
        self.assertEqual(api.post(f"{base}/items/{self.task_item.pk}/validate/").status_code, 403)
        self.assertEqual(api.post(f"{base}/items/{self.task_item.pk}/reject/").status_code, 403)
        self.assertEqual(api.post(f"{base}/items/{self.task_item.pk}/form/", {"title": "x"}, format="multipart").status_code, 403)
        self.assertEqual(api.post(f"/api/v1/projects/{self.project.pk}/ai-proposals/trigger/").status_code, 403)
        self.assertFalse(api.get(f"/api/v1/projects/{self.project.pk}/ai-proposals/").json()["can_trigger"])
        self.p.refresh_from_db()
        self.assertEqual((self.p.status, Proposal.objects.filter(project=self.project).count()), (Proposal.Status.READY, 1))
        self.assertFalse(self.p.items.exclude(item_status=Item.ItemStatus.PROPOSED).exists())

    def test_project_lead_keeps_rights_on_own_project(self):
        # outsider : MEMBER du workspace mais product manager du projet 2.
        other = self.proposal(self.project2)
        item = other.items.filter(kind=Item.Kind.TASK).first()
        api = self.api(self.outsider)
        self.assertTrue(api.get(f"/api/v1/ai-proposals/{other.pk}/").json()["can_apply"])
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{other.pk}/items/{item.pk}/validate/").status_code, 200)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{self.p.pk}/validate-all/").status_code, 403)

    def test_reject_is_refused_while_generating(self):
        running = Proposal.objects.create(project=self.project, workspace=self.ws, status=Proposal.Status.GENERATING)
        api = self.api(self.pm)
        self.assertFalse(api.get(f"/api/v1/ai-proposals/{running.pk}/").json()["can_reject"])
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{running.pk}/reject/").status_code, 409)
        running.refresh_from_db()
        self.assertEqual(running.status, Proposal.Status.GENERATING)
        # Génération bloquée (au-delà du délai de suivi) : la proposition reste rejetable.
        Proposal.objects.filter(pk=running.pk).update(created_at=timezone.now() - views_ai.GENERATION_TIMEOUT * 2)
        self.assertEqual(api.post(f"/api/v1/ai-proposals/{running.pk}/reject/").status_code, 200)

    @staticmethod
    def _ai_throttled(**kwargs):
        view = views_ai.AIProposalActionView()
        view.kwargs = kwargs
        return any(isinstance(t, AIActionRateThrottle) for t in view.get_throttles())

    def test_project_history_and_global_list(self):
        data = self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/ai-proposals/").json()
        self.assertEqual(data["project"]["id"], self.project.pk)
        self.assertEqual([p["id"] for p in data["proposals"]], [self.p.pk])
        self.assertGreater(data["proposals"][0]["items_count"], 0)
        rows = self.api(self.dev).get("/api/v1/ai-proposals/", {"status": "READY"}).json()["results"]
        self.assertIn(self.p.pk, [r["id"] for r in rows])


class TriggerTests(AIFixture):
    def test_trigger_creates_placeholder_completed_by_task(self):
        from project.tasks import generate_project_ai_proposal_task

        with mock.patch.object(generate_project_ai_proposal_task, "delay") as delay, \
                self.captureOnCommitCallbacks(execute=True):
            res = self.api(self.pm).post(f"/api/v1/projects/{self.project.pk}/ai-proposals/trigger/")
        self.assertEqual(res.status_code, 202, res.content)
        proposal_id = res.json()["proposal_id"]
        delay.assert_called_once_with(project_id=self.project.pk, triggered_by_id=self.pm.pk, proposal_id=proposal_id)
        self.assertEqual(Proposal.objects.get(pk=proposal_id).status, Proposal.Status.PENDING)
        status = self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/ai-proposals/status/").json()
        self.assertEqual((status["proposal_id"], status["is_terminal"]), (proposal_id, False))

        # Le worker complète la proposition attendue (plus d'orpheline « En attente »),
        # même si une proposition prête existait déjà (déclenchement explicite).
        ProjectAIStructureService.generate_for_project(project=self.project, use_ai=False)
        before = Proposal.objects.filter(project=self.project).count()
        generate_project_ai_proposal_task.apply(kwargs={
            "project_id": self.project.pk, "triggered_by_id": self.pm.pk, "use_ai": False, "proposal_id": proposal_id,
        })
        self.assertEqual(Proposal.objects.filter(project=self.project).count(), before)
        proposal = Proposal.objects.get(pk=proposal_id)
        self.assertEqual(proposal.status, Proposal.Status.READY)
        self.assertGreater(proposal.items.count(), 0)
        status = self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/ai-proposals/status/").json()
        self.assertTrue(status["is_terminal"])

    def test_trigger_is_rate_limited(self):
        with override_settings(DEVFLOW_AI_RATE_LIMIT="1/min"), \
                mock.patch("project.tasks.generate_project_ai_proposal_task.delay"):
            api = self.api(self.pm)
            self.assertEqual(api.post(f"/api/v1/projects/{self.project.pk}/ai-proposals/trigger/").status_code, 202)
            self.assertEqual(api.post(f"/api/v1/projects/{self.project.pk}/ai-proposals/trigger/").status_code, 429)


    def test_rejected_placeholder_is_never_generated(self):
        """Proposition attendue rejetée avant le passage du worker : ni génération ni appel IA."""
        from project.tasks import generate_project_ai_proposal_task

        placeholder = Proposal.objects.create(project=self.project, workspace=self.ws, status=Proposal.Status.REJECTED)
        result = generate_project_ai_proposal_task.apply(kwargs={
            "project_id": self.project.pk, "use_ai": False, "proposal_id": placeholder.pk,
        }).get()
        self.assertTrue(result["skipped"])
        self.assertEqual(Proposal.objects.filter(project=self.project).count(), 1)
        # Instance chargée par le worker avant le rejet : la prise en charge échoue, rien n'est créé.
        in_worker = Proposal.objects.create(project=self.project, workspace=self.ws, status=Proposal.Status.PENDING)
        Proposal.objects.filter(pk=in_worker.pk).update(status=Proposal.Status.REJECTED)
        res = ProjectAIStructureService.generate_for_project(project=self.project, use_ai=False, proposal=in_worker)
        self.assertEqual((res.proposal.status, res.items_created), (Proposal.Status.REJECTED, 0))
        self.assertFalse(in_worker.items.exists())

    def test_rejection_during_generation_is_not_overwritten(self):
        placeholder = Proposal.objects.create(project=self.project, workspace=self.ws, status=Proposal.Status.PENDING)
        heuristic = ProjectAIStructureService._heuristic_payload

        def reject_meanwhile(project):  # rejet concurrent pendant la génération
            Proposal.objects.filter(pk=placeholder.pk).update(status=Proposal.Status.REJECTED, rejected_at=timezone.now())
            return heuristic(project)

        with mock.patch.object(ProjectAIStructureService, "_heuristic_payload", side_effect=reject_meanwhile):
            ProjectAIStructureService.generate_for_project(project=self.project, use_ai=False, proposal=placeholder)
        placeholder.refresh_from_db()
        self.assertEqual(placeholder.status, Proposal.Status.REJECTED)
        self.assertIsNotNone(placeholder.rejected_at)
        self.assertGreater(placeholder.items.count(), 0)
        self.assertFalse(placeholder.items.exclude(item_status=Item.ItemStatus.REJECTED).exists())


class CopilotTests(AIFixture):
    def test_chat_falls_back_without_ai_and_is_scoped(self):
        url = f"/api/v1/projects/{self.project.pk}/copilot/"
        res = self.api(self.dev).post(url, {"message": "Quels sont les risques ?", "history": []}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["type"], "error")
        self.assertEqual(self.api(self.dev).post(url, {"message": "  "}, format="json").status_code, 400)
        self.assertEqual(self.api(self.bob).post(url, {"message": "x"}, format="json").status_code, 404)

    def test_chat_executes_tool_with_link(self):
        from project.services.ai.base import AIResponse

        provider = mock.Mock()
        provider.is_available.return_value = True
        provider.generate.return_value = AIResponse(
            text='{"action": "tool_call", "tool": "create_milestone", "arguments": {"name": "Recette", "due_date": "2026-12-15"}}',
            model="m", tokens_used=1,
        )
        with mock.patch("project.services.methodology.copilot.get_ai_provider", return_value=provider):
            res = self.api(self.owner).post(f"/api/v1/projects/{self.project.pk}/copilot/",
                                            {"message": "Crée le jalon Recette"}, format="json")
        data = res.json()
        self.assertEqual(data["type"], "tool_result", data)
        self.assertRegex(data["actions_executed"][0]["link"], r"^/m/milestone/\d+$")
        logs = self.api(self.owner).get(f"/api/v1/projects/{self.project.pk}/copilot/logs/").json()["logs"]
        self.assertEqual(logs[0]["tool_name"], "create_milestone")
        self.assertEqual(logs[0]["status"], "SUCCESS")

    def test_logs_are_scoped(self):
        dm.AIActionLog.objects.create(workspace=self.ws, project=self.project, user=self.dev, tool_name="create_sprint")
        data = self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/copilot/logs/").json()
        self.assertEqual([log["tool_name"] for log in data["logs"]], ["create_sprint"])
        self.assertEqual(self.api(self.bob).get(f"/api/v1/projects/{self.project.pk}/copilot/logs/").status_code, 404)

    def test_chat_is_rate_limited(self):
        with override_settings(DEVFLOW_AI_RATE_LIMIT="1/min"):
            api = self.api(self.dev)
            url = f"/api/v1/projects/{self.project.pk}/copilot/"
            self.assertEqual(api.post(url, {"message": "a"}, format="json").status_code, 200)
            self.assertEqual(api.post(url, {"message": "b"}, format="json").status_code, 429)


class DocumentImportTests(AIFixture):
    def make_import(self, workspace=None, project=None, name="cahier_des_charges.pdf"):
        return dm.ProjectDocumentImport.objects.create(
            workspace=workspace or self.ws, project=project, uploaded_by=self.owner,
            file=SimpleUploadedFile(name, b"%PDF-1.4 test"),
        )

    def test_list_and_detail_are_scoped(self):
        mine = self.make_import(project=self.project)
        foreign = self.make_import(workspace=self.other, project=self.foreign_project, name="secret.pdf")
        data = self.api(self.dev).get("/api/v1/imports/").json()
        ids = [r["id"] for r in data["results"]]
        self.assertIn(mine.pk, ids)
        self.assertNotIn(foreign.pk, ids)
        self.assertNotIn(self.foreign_project.pk, [p["id"] for p in data["projects"]])
        self.assertEqual(data["stats"]["total"], 1)
        self.assertEqual(self.api(self.dev).get(f"/api/v1/imports/{foreign.pk}/").status_code, 404)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/imports/{mine.pk}/").status_code, 404)
        self.assertEqual(self.api(self.bob).post(f"/api/v1/imports/{mine.pk}/analyze/").status_code, 404)
        detail = self.api(self.dev).get(f"/api/v1/imports/{mine.pk}/").json()
        self.assertRegex(detail["file_name"], r"^cahier_des_charges.*\.pdf$")
        self.assertEqual(detail["file_ext"], "pdf")
        # Filtre workspace (parité list.html) limité aux workspaces de l'utilisateur.
        self.assertEqual(data["workspaces"], [{"id": self.ws.pk, "name": self.ws.name}])
        self.assertEqual(self.api(self.dev).get("/api/v1/imports/", {"workspace": self.ws.pk}).status_code, 200)
        self.assertEqual(self.api(self.dev).get("/api/v1/imports/", {"workspace": self.other.pk}).status_code, 404)
        # Paramètre invalide ignoré (la vue historique levait une ValueError → 500).
        self.assertEqual(self.api(self.dev).get("/api/v1/imports/", {"project": "abc"}).status_code, 200)

    def test_rows_show_error_or_text_excerpt(self):
        failed = self.make_import()
        dm.ProjectDocumentImport.objects.filter(pk=failed.pk).update(error_message="Format non supporté : " + "x" * 200)
        done = self.make_import(name="lot2.pdf")
        dm.ProjectDocumentImport.objects.filter(pk=done.pk).update(extracted_text="<p>Lot 2</p> " + "facturation " * 20)
        rows = {r["id"]: r for r in self.api(self.dev).get("/api/v1/imports/").json()["results"]}
        self.assertTrue(rows[failed.pk]["excerpt"].startswith("Format non supporté"))
        self.assertLessEqual(len(rows[failed.pk]["excerpt"]), 90)
        self.assertTrue(rows[done.pk]["excerpt"].startswith("Lot 2 facturation"))
        self.assertLessEqual(len(rows[done.pk]["excerpt"]), 100)

    def test_upload_form_never_lists_foreign_projects(self):
        fields = {f["name"]: f for f in self.api(self.dev).get("/api/v1/forms/project-import/").json()["fields"]}
        values = {c["value"] for c in fields["project"]["choices"]}
        self.assertIn(str(self.project.pk), values)
        self.assertNotIn(str(self.foreign_project.pk), values)

    @mock.patch("project.services.project_document_ai_service.ProjectDocumentAIService.extract_text",
                return_value="Plateforme de réservation : paiement, back-office, application mobile.")
    def test_analyze_unlinked_document_creates_project_for_review(self, _extract):
        imp = self.make_import()
        res = self.api(self.pm).post(f"/api/v1/imports/{imp.pk}/analyze/", {"name": "Réservations"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        imp.refresh_from_db()
        self.assertEqual(imp.status, dm.ProjectDocumentImport.ImportStatus.COMPLETED)
        self.assertEqual(imp.project.name, "Réservations")
        self.assertEqual(imp.project.workspace_id, self.ws.pk)
        self.assertIn("réservation", imp.extracted_text)
        self.assertEqual(imp.ai_payload["proposal_id"], body["proposal"]["id"])
        self.assertEqual(body["proposal"]["status"], "READY")
        detail = self.api(self.dev).get(f"/api/v1/imports/{imp.pk}/").json()
        self.assertEqual(detail["proposal"]["id"], body["proposal"]["id"])

    @mock.patch("project.services.project_document_ai_service.ProjectDocumentAIService.extract_text",
                return_value="Plateforme de réservation : paiement, back-office.")
    def test_member_cannot_analyze(self, _extract):
        imp = self.make_import()
        linked = self.make_import(project=self.project, name="lot.pdf")
        self.assertFalse(self.api(self.dev).get(f"/api/v1/imports/{imp.pk}/").json()["can_analyze"])
        self.assertTrue(self.api(self.pm).get(f"/api/v1/imports/{imp.pk}/").json()["can_analyze"])
        for target in (imp, linked):
            res = self.api(self.dev).post(f"/api/v1/imports/{target.pk}/analyze/", {"name": "x"}, format="json")
            self.assertEqual(res.status_code, 403)
            target.refresh_from_db()
            self.assertEqual(target.status, dm.ProjectDocumentImport.ImportStatus.UPLOADED)
        self.assertFalse(dm.Project.objects.filter(name="x").exists())
        _extract.assert_not_called()

    @mock.patch("project.services.project_document_ai_service.ProjectDocumentAIService.extract_text",
                return_value="Cahier des charges : module de réservation en ligne.")
    def test_regenerate_keeps_source_document_context(self, _extract):
        imp = self.make_import(project=self.project)
        first = self.api(self.pm).post(f"/api/v1/imports/{imp.pk}/analyze/", {}, format="json").json()["proposal"]["id"]
        with mock.patch.object(ProjectAIStructureService, "generate_for_project",
                               wraps=ProjectAIStructureService.generate_for_project) as gen:
            res = self.api(self.pm).post(f"/api/v1/ai-proposals/{first}/regenerate/", {"use_ai": "on"}, format="multipart")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIn("module de réservation", gen.call_args.kwargs["document_text"])
        new = res.json()["id"]
        self.assertNotEqual(new, first)
        imp.refresh_from_db()
        self.assertEqual(imp.ai_payload["proposal_id"], new)
        self.assertEqual(self.api(self.dev).get(f"/api/v1/imports/{imp.pk}/").json()["proposal"]["id"], new)

    def test_upload_only_accepts_analyzable_formats(self):
        url = f"/api/v1/forms/project-import/?workspace={self.ws.pk}"
        res = self.api(self.dev).post(url, {"file": SimpleUploadedFile("page.html", b"<script>alert(1)</script>")},
                                      format="multipart")
        self.assertEqual(res.status_code, 400)
        self.assertIn("file", res.json())
        self.assertFalse(dm.ProjectDocumentImport.objects.filter(file__endswith=".html").exists())
        res = self.api(self.dev).post(url, {"file": SimpleUploadedFile("cdc.pdf", b"%PDF-1.4 test")}, format="multipart")
        self.assertEqual(res.status_code, 201, res.content)

    def test_media_never_renders_active_content_inline(self):
        html = self.make_import(name="page.html")
        pdf = self.make_import(name="cdc.pdf")
        client = self.web(self.dev)
        res = client.get(f"/media/{html.file.name}")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res["Content-Disposition"].startswith("attachment"))
        self.assertEqual(res["Content-Security-Policy"], "sandbox")
        res.close()
        res = client.get(f"/media/{pdf.file.name}")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.get("Content-Disposition", "").startswith("attachment"))
        res.close()

    @mock.patch("project.services.project_document_ai_service.ProjectDocumentAIService.extract_text",
                return_value="Lot 2 : module de facturation")
    def test_analyze_linked_document_proposes_structure_for_project(self, _extract):
        imp = self.make_import(project=self.project)
        res = self.api(self.pm).post(f"/api/v1/imports/{imp.pk}/analyze/", {}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["project"]["id"], self.project.pk)
        self.assertEqual(Proposal.objects.get(pk=res.json()["proposal"]["id"]).project_id, self.project.pk)

    @mock.patch("project.services.project_document_ai_service.ProjectDocumentAIService.extract_text",
                side_effect=ValueError("Format non supporté: .png"))
    def test_extraction_failure_marks_import_failed(self, _extract):
        imp = self.make_import(name="photo.png")
        res = self.api(self.pm).post(f"/api/v1/imports/{imp.pk}/analyze/", {}, format="json")
        self.assertEqual(res.status_code, 400)
        imp.refresh_from_db()
        self.assertEqual(imp.status, dm.ProjectDocumentImport.ImportStatus.FAILED)
        self.assertIn("Format non supporté", imp.error_message)
        self.assertIsNone(imp.project_id)
