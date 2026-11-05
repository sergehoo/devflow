"""
Phase 5 — pont générique ``/api/v1/resources/`` (vues Django CRUD), transfert
de propriété du workspace, budget projet et espace méthodologie.
Isolation workspace, droits réels, non-régression.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_resources
"""

from project import models as dm
from project.api.resources import RESOURCES, _views
from project.tests_legacy_rights import LegacyFixture


class ResourceBridgeTests(LegacyFixture):
    def test_registry_and_every_list_and_form_answer(self):
        api = self.api(self.owner)
        names = {r["name"] for r in api.get("/api/v1/resources/").json()["resources"]}
        self.assertIn("sprint", names)
        for name in RESOURCES:
            views = _views(name)
            if views["list"]:
                self.assertEqual(api.get(f"/api/v1/resources/{name}/").status_code, 200, name)
            if views["create"] and name != "methodology":  # méthodologies : superuser uniquement
                self.assertEqual(api.get(f"/api/v1/forms/{name}/").status_code, 200, name)
        self.assertEqual(api.get("/api/v1/resources/inconnu/").status_code, 404)

    def test_list_and_detail_are_workspace_scoped(self):
        risk = dm.Risk.objects.create(workspace=self.ws, project=self.project, title="Fuite")
        foreign = dm.Risk.objects.create(workspace=self.other, project=self.foreign_project, title="Secret")
        labels = [r["label"] for r in self.api(self.dev).get("/api/v1/resources/risk/").json()["results"]]
        self.assertIn("Fuite", labels)
        self.assertNotIn("Secret", labels)
        self.assertEqual(self.api(self.dev).get(f"/api/v1/resources/risk/{foreign.pk}/").status_code, 404)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/resources/risk/{risk.pk}/").status_code, 404)
        self.assertEqual(self.api(self.bob).post(f"/api/v1/resources/risk/{risk.pk}/delete/").status_code, 404)
        self.assertEqual(self.api(self.bob).post(f"/api/v1/resources/risk/{risk.pk}/actions/archive/").status_code, 404)
        self.assertTrue(dm.Risk.objects.filter(pk=risk.pk, is_archived=False).exists())
        detail = self.api(self.dev).get(f"/api/v1/resources/risk/{risk.pk}/").json()
        self.assertEqual(detail["actions"], [{"code": "archive", "label": "Archiver"}])

    def test_checklist_through_bridge_follows_task_rights(self):
        # Préremplissage ?task= puis création par l'assigné ; refus pour un collègue.
        schema = self.api(self.dev).get("/api/v1/forms/task-checklist/", {"task": self.task.pk}).json()
        self.assertEqual(next(f for f in schema["fields"] if f["name"] == "task")["value"], str(self.task.pk))
        post = {"task": self.task.pk, "title": "Recette", "position": 0}
        self.assertEqual(self.api(self.peer).post("/api/v1/forms/task-checklist/", post, format="multipart").status_code, 400)
        res = self.api(self.dev).post("/api/v1/forms/task-checklist/", post, format="multipart")
        self.assertEqual(res.status_code, 201)
        checklist_id = res.json()["id"]
        self.assertEqual(self.api(self.peer).post(f"/api/v1/resources/task-checklist/{checklist_id}/delete/").status_code, 403)
        self.assertEqual(self.api(self.dev).post(f"/api/v1/resources/task-checklist/{checklist_id}/delete/").status_code, 200)
        self.assertFalse(dm.TaskChecklist.objects.filter(pk=checklist_id).exists())

    def test_actor_fields_are_locked_in_schema(self):
        fields = {f["name"]: f for f in self.api(self.dev).get("/api/v1/forms/task-label/").json()["fields"]}
        self.assertTrue(fields["added_by"]["disabled"])

    def test_overview_lists_dependencies_both_ways_and_labels(self):
        dm.TaskDependency.objects.create(from_task=self.task, to_task=self.task2)
        label = dm.Label.objects.create(workspace=self.ws, name="Urgent")
        dm.TaskLabel.objects.create(task=self.task, label=label)
        data = self.api(self.dev).get(f"/api/v1/tasks/{self.task.pk}/overview/").json()
        self.assertEqual([(d["direction"], d["task_id"]) for d in data["dependencies"]], [("out", self.task2.pk)])
        self.assertEqual([lbl["name"] for lbl in data["labels"]], ["Urgent"])


class WorkspaceOwnershipTests(LegacyFixture):
    def transfer(self, user, target):
        return self.api(user).post(f"/api/v1/workspaces/{self.ws.pk}/transfer-ownership/", {"user_id": target.pk}, format="json")

    def test_transfer_requires_manage_right_and_member_target(self):
        self.assertEqual(self.transfer(self.dev, self.dev).status_code, 403)
        self.assertEqual(self.transfer(self.bob, self.bob).status_code, 404)
        self.assertEqual(self.transfer(self.owner, self.bob).status_code, 400)  # pas membre
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.owner_id, self.owner.pk)
        self.assertEqual(self.transfer(self.owner, self.pm).status_code, 200)
        self.ws.refresh_from_db()
        self.assertEqual(self.ws.owner_id, self.pm.pk)
        self.assertTrue(dm.SecurityAuditLog.objects.filter(action="workspace.transfer_ownership").exists())

    def test_patch_owner_cannot_target_outsider(self):
        res = self.api(self.owner).patch(f"/api/v1/workspaces/{self.ws.pk}/", {"owner": self.bob.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.api(self.dev).post("/api/v1/workspaces/", {"name": "Usurpé", "owner": self.owner.pk}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_members_endpoint_is_scoped(self):
        ids = {m["id"] for m in self.api(self.owner).get(f"/api/v1/workspaces/{self.ws.pk}/members/").json()}
        self.assertIn(self.dev.pk, ids)
        self.assertNotIn(self.bob.pk, ids)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/workspaces/{self.ws.pk}/members/").status_code, 404)


class ProjectFinanceAndSpaceTests(LegacyFixture):
    def test_budget_endpoints_require_financial_rights(self):
        self.assertEqual(self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/budget-panel/").status_code, 403)
        self.assertEqual(self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/budget-overview/").status_code, 403)
        self.assertEqual(self.api(self.dev).post(f"/api/v1/projects/{self.project.pk}/refresh-financials/").status_code, 403)
        res = self.api(self.owner).get(f"/api/v1/projects/{self.project.pk}/budget-panel/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("approved_budget", res.json()["overview"])

    def test_budget_actions_are_workspace_scoped(self):
        self.assertEqual(self.action(self.bob, "project-recalculate-budget", self.project.pk).status_code, 404)
        self.assertEqual(self.action(self.owner, "project-generate-estimates", self.project.pk).status_code, 200)
        # Création de budget sur le projet d'un autre tenant via ?project= → 404.
        res = self.api(self.owner).get("/api/v1/forms/project-budget/", {"project": self.foreign_project.pk})
        self.assertEqual(res.status_code, 404)

    def test_space_endpoint(self):
        self.project.methodology = "scrum"
        self.project.save(update_fields=["methodology"])
        data = self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/space/").json()
        self.assertEqual(data["kind"], "scrum")
        self.assertIn("velocity", data["kpis"])
        self.assertEqual(self.api(self.bob).get(f"/api/v1/projects/{self.project.pk}/space/").status_code, 404)
        dm.ProjectPhase.objects.create(workspace=self.ws, project=self.project2, name="Conception")
        for kind in ("kanban", "waterfall"):
            self.project2.methodology = kind
            self.project2.save(update_fields=["methodology"])
            res = self.api(self.owner).get(f"/api/v1/projects/{self.project2.pk}/space/")
            self.assertEqual((res.status_code, res.json()["kind"]), (200, kind))
        self.assertEqual(res.json()["phases"][0]["name"], "Conception")
