"""
Chantier « projet » — fiche projet complète React (``/api/v1/projects/<id>/detail-tabs/…``).

Isolation workspace (404), droits financiers (``can_view_financials``), IA
(heuristiques, ``AI_BACKEND=none``) et throttle, génération de facture,
non-régression de la fiche historique.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_projet
"""

from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from project import models as dm
from project.api.views_projet import TAB_BUILDERS
from project.tests_legacy_rights import LegacyFixture


class ProjectDetailTabsFixture(LegacyFixture):
    def setUp(self):
        super().setUp()
        cache.clear()  # compteurs du throttle IA
        dm.ProjectMember.objects.get_or_create(project=self.project, user=self.dev, defaults={"allocation_percent": 50})
        self.milestone = dm.Milestone.objects.create(workspace=self.ws, project=self.project, name="Go-live",
                                                     due_date=timezone.localdate() + timedelta(days=30))
        self.expense = dm.ProjectExpense.objects.create(project=self.project, title="Licence", amount=Decimal("1500"))
        self.revenue = dm.ProjectRevenue.objects.create(project=self.project, title="Acompte", amount=Decimal("9000"))
        self.document = dm.ProjectDocumentImport.objects.create(
            workspace=self.ws, project=self.project, uploaded_by=self.owner, file="devflow/project_imports/cahier.pdf")
        self.meeting = dm.ProjectMeeting.objects.create(
            workspace=self.ws, project=self.project, title="Comité de pilotage", scheduled_at=timezone.now())

    def tabs(self, user, project=None, tab=None, **params):
        project = project or self.project
        if tab:
            params["tab"] = tab
        return self.api(user).get(f"/api/v1/projects/{project.pk}/detail-tabs/", params)

    def post(self, user, path, project=None, data=None):
        project = project or self.project
        return self.api(user).post(f"/api/v1/projects/{project.pk}/detail-tabs/{path}/", data or {}, format="multipart")

    def bridge(self, actor, form_name, /, *, pk=None, query=None, **changes):
        """Formulaire via le pont (comme le dialogue React) : relit le schéma puis le renvoie modifié."""
        api = self.api(actor)
        path = f"/api/v1/forms/{form_name}/{pk}/" if pk else f"/api/v1/forms/{form_name}/"
        url = f"{path}?{urlencode(query)}" if query else path
        res = api.get(url)
        if res.status_code != 200:
            return res
        data = {f["name"]: f["value"] for f in res.json()["fields"]
                if f["value"] not in (None, "") and f["type"] not in ("file", "multiselect")}
        data.update(changes)
        return api.post(url, data, format="multipart")

    def delete_member(self, user, member, workspace=None):
        url = f"/api/v1/resources/project-member/{member.pk}/delete/"
        if workspace:
            url += f"?workspace={workspace.pk}"
        return self.api(user).post(url, {"next": "/"}, format="multipart")


class DetailTabsIsolationTests(ProjectDetailTabsFixture):
    def test_other_workspace_cannot_reach_any_endpoint(self):
        """user B (workspace W2) ne peut pas atteindre le projet de W1 → 404 partout."""
        self.assertEqual(self.tabs(self.bob).status_code, 404)
        self.assertEqual(self.tabs(self.dev, project=self.foreign_project).status_code, 404)
        for path in ("ai-forecast", "ai-risk-analysis", "ai-generation", "invoice-generate"):
            self.assertEqual(self.post(self.bob, path).status_code, 404, path)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/projects/{self.project.pk}/detail-tabs/ai-generation/").status_code, 404)
        self.assertEqual(self.api(self.bob).get(f"/api/v1/projects/{self.project.pk}/detail-tabs/invoice-generate/").status_code, 404)
        self.assertFalse(dm.ProjectAIProposal.objects.filter(project=self.project).exists())
        self.assertFalse(dm.Invoice.objects.filter(project=self.project).exists())

    def test_anonymous_is_rejected(self):
        from rest_framework.test import APIClient

        self.assertIn(APIClient().get(f"/api/v1/projects/{self.project.pk}/detail-tabs/").status_code, (401, 403))

    def test_project_of_a_non_current_workspace_is_served(self):
        # Membre de deux workspaces : la fiche ne dépend pas du workspace courant du profil.
        dm.TeamMembership.objects.create(user=self.dev, workspace=self.other)
        res = self.tabs(self.dev, project=self.foreign_project)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["project"]["name"], "Secret")


class DetailTabsContentTests(ProjectDetailTabsFixture):
    def test_header_kpis_and_tabs_for_financial_user(self):
        data = self.tabs(self.owner).json()
        self.assertTrue(data["can_view_financials"])
        self.assertEqual(data["project"]["name"], "Portail")
        self.assertEqual(data["active_tab"], "planification")
        keys = [t["key"] for t in data["tabs"]]
        self.assertEqual(keys, ["planification", "budget_estimatif", "budget_previsionnel", "facturation_client",
                                "depenses", "equipes", "evolution", "taches", "kpi_roi", "documents", "meetings"])
        self.assertEqual(data["kpis"]["tasks_total"], 1)
        self.assertIsNotNone(data["kpis"]["actual_cost"])
        self.assertEqual(data["tab"]["milestones"][0]["name"], "Go-live")
        self.assertIn("todo", data["band"])

    def test_every_tab_answers(self):
        for key in TAB_BUILDERS:
            res = self.tabs(self.owner, tab=key)
            self.assertEqual(res.status_code, 200, key)
            self.assertEqual(res.json()["tab"]["key"], key)
        expenses = self.tabs(self.owner, tab="depenses").json()["tab"]["expenses"]
        self.assertEqual([e["title"] for e in expenses], ["Licence"])
        docs = self.tabs(self.owner, tab="documents").json()["tab"]["documents"]
        self.assertEqual((docs[0]["name"], docs[0]["type_label"]), ("cahier.pdf", "PDF"))
        meetings = self.tabs(self.owner, tab="meetings").json()["tab"]
        self.assertEqual((meetings["count"], meetings["meetings"][0]["title"]), (1, "Comité de pilotage"))
        tasks = self.tabs(self.owner, tab="taches").json()["tab"]["tasks"]
        self.assertEqual(tasks[0]["assignee_id"], self.dev.pk)

    def test_financial_data_never_reaches_non_financial_member(self):
        data = self.tabs(self.dev, tab="depenses").json()
        self.assertFalse(data["can_view_financials"])
        self.assertEqual(data["active_tab"], "planification")  # onglet financier refusé côté Django
        keys = {t["key"] for t in data["tabs"]}
        self.assertFalse(keys & {"budget_estimatif", "budget_previsionnel", "facturation_client", "depenses"})
        self.assertIsNone(data["kpis"]["actual_cost"])
        self.assertIsNone(data["band"]["approved_budget"])
        self.assertEqual(data["project"]["budget_status_label"], "")
        equipes = self.tabs(self.dev, tab="equipes").json()["tab"]
        self.assertIsNone(equipes["member_costs"])
        self.assertEqual(equipes["members"][0]["name"], "dev")
        dm.ProjectModuleROI.objects.create(project=self.project, module_name="Paiement",
                                           estimated_cost=Decimal("100"), estimated_revenue=Decimal("300"))
        kpi = self.tabs(self.dev, tab="kpi_roi").json()["tab"]
        self.assertIsNone(kpi["module_rois"][0]["estimated_cost"])
        self.assertIsNone(kpi["roi_summary"]["total_cost"])
        self.assertIsNone(kpi["sprint_finance"])
        kpi_owner = self.tabs(self.owner, tab="kpi_roi").json()["tab"]
        self.assertEqual(kpi_owner["module_rois"][0]["estimated_cost"], "100.00")

    def test_tjm_costs_exposed_to_financial_user(self):
        equipes = self.tabs(self.owner, tab="equipes").json()["tab"]
        self.assertIsNotNone(equipes["member_costs"])
        self.assertEqual(equipes["member_costs"]["rows"][0]["name"], "dev")
        self.assertEqual(equipes["allocation_average"], 50)

    def test_unknown_tab_falls_back(self):
        self.assertEqual(self.tabs(self.owner, tab="inconnu").json()["active_tab"], "planification")

    def test_description_is_sanitized(self):
        self.project.description = '<p>Objectif</p><script>alert(1)</script><img src=x onerror="alert(2)">'
        self.project.save(update_fields=["description"])
        html = self.tabs(self.dev).json()["project"]["description_html"]
        self.assertIn("<p>Objectif</p>", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)

    def test_methodology_mode_payload(self):
        self.project.methodology = dm.Project.Methodology.WATERFALL
        self.project.save(update_fields=["methodology"])
        dm.ProjectPhase.objects.create(workspace=self.ws, project=self.project, name="Conception")
        mode = self.tabs(self.dev).json()["mode"]
        self.assertEqual(mode["kind"], "waterfall")
        self.assertEqual(mode["phases"][0]["name"], "Conception")

    def test_legacy_detail_page_is_unchanged(self):
        res = self.web(self.owner).get(f"/projects/{self.project.pk}/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Portail")
        self.assertEqual(self.web(self.bob).get(f"/projects/{self.project.pk}/").status_code, 404)


class DetailTabsAITests(ProjectDetailTabsFixture):
    def test_forecast_requires_financial_rights(self):
        self.assertEqual(self.post(self.dev, "ai-forecast").status_code, 403)
        res = self.post(self.owner, "ai-forecast")
        self.assertEqual(res.status_code, 200)
        self.assertIn("base_cost", res.json())
        self.assertEqual(res.json()["used_provider"], "heuristic")

    def test_risk_analysis_requires_financial_rights(self):
        self.assertEqual(self.post(self.dev, "ai-risk-analysis").status_code, 403)
        res = self.post(self.owner, "ai-risk-analysis")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["project_id"], self.project.pk)
        self.assertIn("signals", res.json())

    def test_raw_api_ai_actions_require_financial_rights(self):
        """API brute ``projects/<id>/ai/forecast|risk-analysis`` alignée sur les vues Django (coûts / marges)."""
        for path in ("ai/forecast", "ai/risk-analysis"):
            url = f"/api/v1/projects/{self.project.pk}/{path}/"
            self.assertEqual(self.api(self.dev).post(url).status_code, 403, path)
            self.assertEqual(self.api(self.bob).post(url).status_code, 404, path)
            self.assertEqual(self.api(self.owner).post(url).status_code, 200, path)

    @override_settings(DEVFLOW_AI_RATE_LIMIT="2/min")
    def test_ai_actions_are_throttled(self):
        codes = [self.post(self.owner, "ai-forecast").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_generation_trigger_and_status(self):
        api = self.api(self.dev)
        url = f"/api/v1/projects/{self.project.pk}/detail-tabs/ai-generation/"
        self.assertIsNone(api.get(url).json()["status"])
        with self.captureOnCommitCallbacks(execute=False):
            res = api.post(url, {}, format="multipart")
        self.assertEqual(res.status_code, 200)
        proposal = dm.ProjectAIProposal.objects.get(project=self.project)
        self.assertEqual((res.json()["proposal_id"], proposal.status), (proposal.pk, dm.ProjectAIProposal.Status.PENDING))
        status = api.get(url).json()
        self.assertEqual(status["proposal_id"], proposal.pk)
        self.assertFalse(status["is_terminal"])

    @override_settings(DEVFLOW_AI_RATE_LIMIT="1/min")
    def test_generation_polling_is_not_throttled_but_trigger_is(self):
        url = f"/api/v1/projects/{self.project.pk}/detail-tabs/ai-generation/"
        codes = [self.api(self.dev).get(url).status_code for _ in range(4)]
        self.assertEqual(codes, [200] * 4)
        with self.captureOnCommitCallbacks(execute=False):
            codes = [self.api(self.dev).post(url, {}, format="multipart").status_code for _ in range(2)]
        self.assertEqual(codes, [200, 429])
        self.assertEqual(dm.ProjectAIProposal.objects.filter(project=self.project).count(), 1)


class InvoiceGenerationTests(ProjectDetailTabsFixture):
    def test_requires_financial_rights(self):
        self.assertEqual(self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/detail-tabs/invoice-generate/").status_code, 403)
        self.assertEqual(self.post(self.dev, "invoice-generate", data={"mode": "FIXED", "tax_rate": "18", "currency": "XOF"}).status_code, 403)
        self.assertFalse(dm.Invoice.objects.exists())

    def test_schema_validation_and_generation(self):
        fields = {f["name"]: f for f in self.api(self.owner).get(
            f"/api/v1/projects/{self.project.pk}/detail-tabs/invoice-generate/").json()["fields"]}
        self.assertEqual((fields["mode"]["type"], fields["mode"]["label"]), ("select", "Mode de facturation"))
        bad = self.post(self.owner, "invoice-generate", data={"mode": "FIXED", "tax_rate": "500", "currency": "XOF"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("tax_rate", bad.json())
        res = self.post(self.owner, "invoice-generate", data={"mode": "FIXED", "tax_rate": "18", "currency": "XOF"})
        self.assertEqual(res.status_code, 201, res.content)
        invoice = dm.Invoice.objects.get(pk=res.json()["id"])
        self.assertEqual(invoice.project_id, self.project.pk)
        self.assertEqual(res.json()["link"], f"/m/invoice/{invoice.pk}")


class TeamRightsTests(ProjectDetailTabsFixture):
    """Coûts TJM (``billing.view``) et gestion des affectations (``can_manage_project_members``)."""

    def test_tjm_rows_require_billing_view(self):
        # lead : RBAC TEAM_LEAD (pas de billing.view) mais rôle historique TECH_LEAD → can_view_financials.
        dm.TeamMembership.objects.filter(user=self.lead, workspace=self.ws).update(role=dm.TeamMembership.Role.TECH_LEAD)
        res = self.tabs(self.lead, tab="equipes")
        self.assertTrue(res.json()["can_view_financials"])
        team = res.json()["tab"]
        self.assertIsNone(team["member_costs"])
        self.assertTrue(team["member_costs_restricted"])
        for key in (b"daily_cost", b"daily_sale", b"allocated_project_cost", b"daily_cost_total"):
            self.assertNotIn(key, res.content)
        self.assertEqual(self.api(self.lead).get("/api/v1/billing-rates/").status_code, 403)  # même règle que l'API TJM
        # Chef de projet (billing.view) : coûts servis.
        pm_team = self.tabs(self.pm, tab="equipes").json()["tab"]
        self.assertEqual(pm_team["member_costs"]["rows"][0]["name"], "dev")
        self.assertFalse(pm_team["member_costs_restricted"])
        # Sans droit financier : rien, et aucun bandeau « restreint ».
        dev_team = self.tabs(self.dev, tab="equipes").json()["tab"]
        self.assertIsNone(dev_team["member_costs"])
        self.assertFalse(dev_team["member_costs_restricted"])

    def test_member_cannot_manage_assignments(self):
        member = dm.ProjectMember.objects.get(project=self.project, user=self.dev)
        self.assertFalse(self.tabs(self.peer, tab="equipes").json()["tab"]["can_manage_members"])
        self.assertFalse(self.tabs(self.dev, tab="equipes").json()["tab"]["can_manage_members"])
        # peer : RBAC MEMBER, ni responsable du projet → 403 partout, affectation conservée.
        self.assertEqual(self.delete_member(self.peer, member).status_code, 403)
        self.assertEqual(self.bridge(self.peer, "project-member", pk=member.pk, allocation_percent=90).status_code, 403)
        self.assertEqual(self.bridge(self.peer, "project-member", query={"project": self.project.pk},
                                     user=self.peer.pk, allocation_percent=10).status_code, 403)
        self.assertEqual(self.web(self.peer).get(f"/project-members/{member.pk}/update/").status_code, 403)
        self.assertEqual(self.web(self.peer).post(f"/project-members/{member.pk}/delete/").status_code, 403)
        # Autre tenant → 404 (avant tout 403).
        self.assertEqual(self.delete_member(self.bob, member).status_code, 404)
        member.refresh_from_db()
        self.assertEqual(member.allocation_percent, 50)
        self.assertFalse(dm.ProjectMember.objects.filter(project=self.project, user=self.peer).exists())

    def test_managers_and_project_leads_manage_assignments(self):
        member = dm.ProjectMember.objects.get(project=self.project, user=self.dev)
        self.assertTrue(self.tabs(self.owner, tab="equipes").json()["tab"]["can_manage_members"])
        # Team lead (team.manage_members) : modification ; chef de projet (project.edit) : ajout.
        self.assertEqual(self.bridge(self.lead, "project-member", pk=member.pk, allocation_percent=60).status_code, 200)
        member.refresh_from_db()
        self.assertEqual(member.allocation_percent, 60)
        res = self.bridge(self.pm, "project-member", query={"project": self.project.pk}, user=self.peer.pk, allocation_percent=20)
        self.assertEqual(res.status_code, 201, res.content)
        # Responsable du projet 2 (product manager, RBAC MEMBER) : gère les membres de SON projet uniquement.
        self.assertTrue(self.tabs(self.outsider, project=self.project2, tab="equipes").json()["tab"]["can_manage_members"])
        self.assertFalse(self.tabs(self.outsider, tab="equipes").json()["tab"]["can_manage_members"])
        self.assertEqual(self.delete_member(self.outsider, member).status_code, 403)
        # Propriétaire du workspace : retrait.
        self.assertEqual(self.delete_member(self.owner, member).status_code, 200)
        self.assertFalse(dm.ProjectMember.objects.filter(pk=member.pk).exists())

    def test_project_lead_cannot_move_assignment_to_another_project(self):
        lead_member = dm.ProjectMember.objects.create(project=self.project2, user=self.peer, allocation_percent=30)
        res = self.bridge(self.outsider, "project-member", pk=lead_member.pk, project=self.project.pk)
        self.assertEqual(res.status_code, 403)
        lead_member.refresh_from_db()
        self.assertEqual(lead_member.project_id, self.project2.pk)


class InvoiceRightsTests(ProjectDetailTabsFixture):
    def test_project_manager_cannot_generate_invoice(self):
        """PROJECT_MANAGER : budget / invoice en lecture seule (pas d'invoice.create) → 403, aucune facture."""
        url = f"/api/v1/projects/{self.project.pk}/detail-tabs/invoice-generate/"
        self.assertEqual(self.api(self.pm).get(url).status_code, 403)
        res = self.post(self.pm, "invoice-generate", data={"mode": "FIXED", "tax_rate": "18", "currency": "XOF"})
        self.assertEqual(res.status_code, 403)
        self.assertFalse(dm.Invoice.objects.exists())
        billing = self.tabs(self.pm, tab="facturation_client").json()
        self.assertEqual(billing["active_tab"], "facturation_client")  # l'onglet reste consultable
        self.assertFalse(billing["tab"]["can_generate_invoice"])
        self.assertTrue(self.tabs(self.owner, tab="facturation_client").json()["tab"]["can_generate_invoice"])


class NonCurrentWorkspaceTests(ProjectDetailTabsFixture):
    """Fiche d'un projet hors workspace courant : actions envoyées avec ``?workspace=`` (validé par Django)."""

    def setUp(self):
        super().setUp()
        dm.TeamMembership.objects.create(user=self.pm, workspace=self.other)
        dm.WorkspaceRoleAssignment.objects.create(user=self.pm, workspace=self.other, role="PROJECT_MANAGER")
        self.q = {"project": self.foreign_project.pk, "workspace": self.other.pk}

    def test_dialog_forms_create_in_the_project_workspace(self):
        due = (timezone.localdate() + timedelta(days=10)).isoformat()
        # Sans ?workspace= : workspace du profil → projet rejeté (bogue corrigé côté React).
        self.assertEqual(self.bridge(self.pm, "milestone", query={"project": self.foreign_project.pk},
                                     name="Recette", due_date=due).status_code, 400)
        res = self.bridge(self.pm, "milestone", query=self.q, name="Recette", due_date=due)
        self.assertEqual(res.status_code, 201, res.content)
        milestone = dm.Milestone.objects.get(pk=res.json()["id"])
        self.assertEqual((milestone.project_id, milestone.workspace_id), (self.foreign_project.pk, self.other.pk))
        res = self.bridge(self.pm, "risk", query=self.q, title="Retard fournisseur")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(dm.Risk.objects.get(pk=res.json()["id"]).project_id, self.foreign_project.pk)

    def test_workspace_param_is_validated(self):
        """?workspace= d'un tenant étranger : 404 (jamais de création dans un autre workspace)."""
        foreign_ws = dm.Workspace.objects.create(name="Gamma", owner=self.bob)
        res = self.api(self.pm).get(f"/api/v1/forms/milestone/?project={self.foreign_project.pk}&workspace={foreign_ws.pk}")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.bridge(self.dev, "milestone", query=self.q, name="X").status_code, 404)  # dev hors de Beta

    def test_member_removal_and_project_edit_with_workspace(self):
        member = dm.ProjectMember.objects.create(project=self.foreign_project, user=self.bob, allocation_percent=40)
        self.assertEqual(self.delete_member(self.pm, member).status_code, 404)  # workspace du profil
        self.assertEqual(self.delete_member(self.pm, member, workspace=self.other).status_code, 200)
        self.assertFalse(dm.ProjectMember.objects.filter(pk=member.pk).exists())
        edit = f"/api/v1/forms/project/{self.foreign_project.pk}/"
        self.assertEqual(self.api(self.pm).get(edit).status_code, 404)
        self.assertEqual(self.api(self.pm).get(f"{edit}?workspace={self.other.pk}").status_code, 200)


class DetailTabsParityTests(ProjectDetailTabsFixture):
    def test_header_team_and_stack(self):
        self.project.tech_stack = "Django / React"
        self.project.save(update_fields=["tech_stack"])
        header = self.tabs(self.dev).json()["project"]
        self.assertEqual((header["team"], header["team_id"], header["tech_stack"]), ("Core", self.team.pk, "Django / React"))

    def test_project_board_columns(self):
        dm.BoardColumn.objects.create(project=self.project, name="À faire", mapped_status=self.task.status, position=1, wip_limit=0)
        dm.BoardColumn.objects.create(project=self.project, name="Libre", position=2, wip_limit=1)
        tab = self.tabs(self.dev, tab="taches").json()["tab"]
        self.assertTrue(tab["has_board"])
        first, second = tab["board"]
        self.assertEqual((first["name"], first["task_ids"], first["wip_limit"], first["over_wip"]), ("À faire", [self.task.pk], None, False))
        self.assertEqual((second["task_ids"], second["wip_limit"]), ([], 1))

    def test_methodology_space_sprint_history(self):
        self.project.methodology = dm.Project.Methodology.SCRUM
        self.project.save(update_fields=["methodology"])
        today = timezone.localdate()
        dm.Sprint.objects.create(workspace=self.ws, project=self.project, name="S1", start_date=today,
                                 end_date=today + timedelta(days=13), total_story_points=21, completed_story_points=13)
        dm.BacklogItem.objects.create(workspace=self.ws, project=self.project, title="Connexion", story_points=5, rank=1)
        space = self.api(self.dev).get(f"/api/v1/projects/{self.project.pk}/space/").json()
        self.assertEqual(space["kind"], "scrum")
        self.assertEqual((space["sprints"][0]["total_story_points"], space["sprints"][0]["completed_story_points"]), (21, 13))
        self.assertEqual((space["backlog"][0]["story_points"], space["backlog"][0]["rank"]), (5, 1))
