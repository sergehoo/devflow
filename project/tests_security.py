"""
Tests de non-régression — Phase 0 : étanchéité multi-tenant.

Vérifie qu'un utilisateur du workspace W1 NE PEUT PAS atteindre / modifier
les objets du workspace W2 via les endpoints corrigés dans la PR sécurité.

Cibles couvertes :
    * MilestoneListView (override get_queryset qui appelle bien super())
    * sprint_status_update      (FBV avec filtre workspace)
    * task_status_update        (FBV avec filtre workspace)
    * ProjectGenesisAPIView     (workspace_id autoritatif côté serveur)
    * MeetingActionItemCreateView
    * MeetingActionItemConvertToTaskView
    * MeetingAIProcessView
    * TaskQuickAttachmentView
    * TaskKanbanMoveView

Lance avec :
    python manage.py test project.tests_security
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from project import models as dm

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers de setup
# ---------------------------------------------------------------------------
class MultiTenantSetupMixin:
    """
    Crée deux workspaces étanches W1 et W2 avec leurs propres owners.

    user_a est uniquement membre de W1, user_b uniquement membre de W2.
    Les objets créés dans W2 ne doivent jamais être atteignables par user_a.
    """

    @classmethod
    def setUpTestData(cls):
        # --- Workspace 1 ---------------------------------------------------
        cls.user_a = User.objects.create_user(
            username="alice", email="alice@example.com", password="pw-alice-1"
        )
        cls.workspace_a = dm.Workspace.objects.create(
            name="Workspace A",
            owner=cls.user_a,
        )
        dm.UserProfile.objects.create(
            user=cls.user_a,
            workspace=cls.workspace_a,
        )

        # --- Workspace 2 ---------------------------------------------------
        cls.user_b = User.objects.create_user(
            username="bob", email="bob@example.com", password="pw-bob-2"
        )
        cls.workspace_b = dm.Workspace.objects.create(
            name="Workspace B",
            owner=cls.user_b,
        )
        dm.UserProfile.objects.create(
            user=cls.user_b,
            workspace=cls.workspace_b,
        )

        # --- Projets isolés ------------------------------------------------
        cls.project_a = dm.Project.objects.create(
            workspace=cls.workspace_a,
            name="Projet A",
            owner=cls.user_a,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )
        cls.project_b = dm.Project.objects.create(
            workspace=cls.workspace_b,
            name="Projet B",
            owner=cls.user_b,
            start_date=date.today(),
            target_date=date.today() + timedelta(days=30),
        )

    def login_as(self, user, password):
        client = Client()
        logged_in = client.login(username=user.username, password=password)
        self.assertTrue(logged_in, f"Échec du login de {user.username}")
        return client


# ---------------------------------------------------------------------------
# 1) MilestoneListView — fuite via override get_queryset
# ---------------------------------------------------------------------------
class MilestoneListSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_does_not_see_milestones_from_workspace_b(self):
        # Crée un milestone dans W2
        milestone_b = dm.Milestone.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            name="Jalon secret B",
            due_date=date.today() + timedelta(days=15),
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.get(reverse("milestone_list"))

        # La page doit répondre 200 mais ne PAS contenir le jalon de W2
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "Jalon secret B",
            msg_prefix="MilestoneListView fuite : user A voit les jalons de W2",
        )

        # Sanity check : user B doit bien voir son propre jalon
        client_b = self.login_as(self.user_b, "pw-bob-2")
        response_b = client_b.get(reverse("milestone_list"))
        self.assertContains(response_b, "Jalon secret B")


# ---------------------------------------------------------------------------
# 2) sprint_status_update — modification cross-tenant
# ---------------------------------------------------------------------------
class SprintStatusUpdateSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_change_status_of_sprint_in_workspace_b(self):
        sprint_b = dm.Sprint.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            name="Sprint B-1",
            status=dm.Sprint.Status.PLANNED,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=14),
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("sprint_status_update"),
            data=json.dumps({"sprint_id": sprint_b.pk, "status": "CANCELLED"}),
            content_type="application/json",
        )

        # 404 attendu (l'objet n'existe pas dans le scope du user A)
        self.assertEqual(
            response.status_code,
            404,
            msg="sprint_status_update : un cross-tenant doit retourner 404",
        )
        sprint_b.refresh_from_db()
        self.assertEqual(
            sprint_b.status,
            dm.Sprint.Status.PLANNED,
            msg="Le statut du sprint de W2 NE DOIT PAS être modifié par user A",
        )


# ---------------------------------------------------------------------------
# 3) task_status_update — modification cross-tenant
# ---------------------------------------------------------------------------
class TaskStatusUpdateSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_change_status_of_task_in_workspace_b(self):
        task_b = dm.Task.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            title="Tâche B",
            status=dm.Task.Status.TODO,
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("task_status_update"),
            data=json.dumps({"task_id": task_b.pk, "status": "DONE"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)
        task_b.refresh_from_db()
        self.assertEqual(task_b.status, dm.Task.Status.TODO)


# ---------------------------------------------------------------------------
# 4) ProjectGenesisAPIView — création projet dans workspace d'autrui
# ---------------------------------------------------------------------------
class ProjectGenesisAPISecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_create_project_in_workspace_b(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("ai_project_genesis_api"),
            data=json.dumps({
                "name": "Projet pirate",
                "description": "Description pirate",
                "workspace_id": self.workspace_b.pk,
                # use_ai=False : on ne veut pas appeler OpenAI en test
                "use_ai": False,
                "auto_apply": False,
            }),
            content_type="application/json",
        )

        # 403 attendu (workspace existe mais user A n'y a pas accès)
        self.assertEqual(
            response.status_code,
            403,
            msg="ProjectGenesisAPIView : workspace d'autrui doit être bloqué 403",
        )
        # Aucun projet "Projet pirate" ne doit avoir été créé dans W2
        self.assertFalse(
            dm.Project.objects.filter(
                workspace=self.workspace_b, name="Projet pirate"
            ).exists()
        )


# ---------------------------------------------------------------------------
# 5) MeetingActionItemCreateView — ajout d'action sur réunion d'autrui
# ---------------------------------------------------------------------------
class MeetingActionItemCreateSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_add_action_item_to_meeting_in_workspace_b(self):
        meeting_b = dm.ProjectMeeting.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            organizer=self.user_b,
            title="Réunion B",
            scheduled_at=timezone.now(),
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("meeting_action_create", kwargs={"meeting_pk": meeting_b.pk}),
            data={
                "title": "Action injectée",
                "description": "test",
                "priority": "HIGH",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            dm.MeetingActionItem.objects.filter(
                meeting=meeting_b, title="Action injectée"
            ).exists()
        )


# ---------------------------------------------------------------------------
# 6) MeetingActionItemConvertToTaskView — conversion cross-tenant
# ---------------------------------------------------------------------------
class MeetingActionItemConvertSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_convert_action_item_from_workspace_b(self):
        meeting_b = dm.ProjectMeeting.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            organizer=self.user_b,
            title="Réunion B",
            scheduled_at=timezone.now(),
        )
        action_b = dm.MeetingActionItem.objects.create(
            meeting=meeting_b,
            title="Action B",
            priority="MEDIUM",
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("meeting_action_convert_to_task", kwargs={"item_pk": action_b.pk})
        )

        self.assertEqual(response.status_code, 404)
        action_b.refresh_from_db()
        self.assertIsNone(
            action_b.converted_task_id,
            msg="Action item de W2 NE DOIT PAS être convertie en tâche par user A",
        )


# ---------------------------------------------------------------------------
# 7) MeetingAIProcessView — lance pipeline IA sur réunion d'autrui
# ---------------------------------------------------------------------------
class MeetingAIProcessSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_trigger_ai_pipeline_on_meeting_in_workspace_b(self):
        meeting_b = dm.ProjectMeeting.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            organizer=self.user_b,
            title="Réunion B confidentielle",
            scheduled_at=timezone.now(),
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("meeting_ai_process", kwargs={"meeting_pk": meeting_b.pk})
        )

        # 404 attendu, pipeline IA NE DOIT PAS être déclenché
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# 8) TaskQuickAttachmentView — upload pièce jointe sur tâche d'autrui
# ---------------------------------------------------------------------------
class TaskQuickAttachmentSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_attach_file_to_task_in_workspace_b(self):
        task_b = dm.Task.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            title="Tâche B",
            status=dm.Task.Status.TODO,
        )

        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile("evil.txt", b"payload", content_type="text/plain")

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("task_quick_attachment", kwargs={"pk": task_b.pk}),
            data={"file": fake},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            dm.TaskAttachment.objects.filter(task=task_b).count(),
            0,
            msg="Aucune pièce jointe ne doit avoir été uploadée sur la tâche de W2",
        )


# ---------------------------------------------------------------------------
# 9) TaskKanbanMoveView — déplacement kanban cross-tenant
# ---------------------------------------------------------------------------
class TaskKanbanMoveSecurityTests(MultiTenantSetupMixin, TestCase):
    def test_user_a_cannot_move_task_in_workspace_b(self):
        task_b = dm.Task.objects.create(
            workspace=self.workspace_b,
            project=self.project_b,
            title="Tâche B",
            status=dm.Task.Status.TODO,
            position=0,
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(
            reverse("task_kanban_move", kwargs={"pk": task_b.pk}),
            data={"status": "DONE", "position": "5"},
        )

        self.assertEqual(response.status_code, 404)
        task_b.refresh_from_db()
        self.assertEqual(task_b.status, dm.Task.Status.TODO)
        self.assertEqual(task_b.position, 0)


# ===========================================================================
# DRF — IsWorkspaceMember + scoping queryset (Phase 0 PR3)
# ===========================================================================
class DRFCrossTenantTests(MultiTenantSetupMixin, TestCase):
    """
    Vérifie que les ModelViewSet DRF n'exposent JAMAIS les objets de W2 à
    un user authentifié de W1, sur les opérations list / retrieve / patch.

    Cibles : api-workspace, api-project, api-task, api-sprint, api-ai-insight.
    """

    # --- List ------------------------------------------------------------
    def test_list_projects_does_not_leak_workspace_b(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.get("/api/v1/projects/")
        self.assertEqual(response.status_code, 200)

        ids = [item["id"] for item in response.json().get("results", response.json())]
        self.assertIn(self.project_a.pk, ids)
        self.assertNotIn(
            self.project_b.pk,
            ids,
            msg="DRF /projects/ fuite : user A voit le projet de W2",
        )

    def test_list_workspaces_does_not_leak_workspace_b(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.get("/api/v1/workspaces/")
        self.assertEqual(response.status_code, 200)

        ids = [item["id"] for item in response.json().get("results", response.json())]
        self.assertIn(self.workspace_a.pk, ids)
        self.assertNotIn(
            self.workspace_b.pk,
            ids,
            msg="DRF /workspaces/ fuite : user A voit W2",
        )

    def test_list_tasks_does_not_leak_workspace_b(self):
        dm.Task.objects.create(
            workspace=self.workspace_a, project=self.project_a,
            title="Task A", status=dm.Task.Status.TODO,
        )
        task_b = dm.Task.objects.create(
            workspace=self.workspace_b, project=self.project_b,
            title="Task B", status=dm.Task.Status.TODO,
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.get("/api/v1/tasks/")
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.json().get("results", response.json())]
        self.assertNotIn(task_b.pk, ids)

    # --- Retrieve --------------------------------------------------------
    def test_retrieve_project_b_returns_404_for_user_a(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.get(f"/api/v1/projects/{self.project_b.pk}/")
        self.assertIn(
            response.status_code,
            (403, 404),
            msg="DRF retrieve cross-tenant doit retourner 403 ou 404",
        )

    def test_retrieve_workspace_b_returns_404_for_user_a(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.get(f"/api/v1/workspaces/{self.workspace_b.pk}/")
        self.assertIn(response.status_code, (403, 404))

    # --- Update / Action ------------------------------------------------
    def test_patch_project_b_blocked_for_user_a(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.patch(
            f"/api/v1/projects/{self.project_b.pk}/",
            data=json.dumps({"name": "pirate"}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, (403, 404))
        self.project_b.refresh_from_db()
        self.assertEqual(self.project_b.name, "Projet B")

    def test_ai_forecast_on_project_b_blocked_for_user_a(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        response = client.post(f"/api/v1/projects/{self.project_b.pk}/ai/forecast/")
        # 404 attendu : project B exclu du queryset de user A
        self.assertIn(response.status_code, (403, 404))


# ===========================================================================
# Phase 2 — Multi-modes DRF (PR12)
# ===========================================================================
class MultiModeDRFSecurityTests(MultiTenantSetupMixin, TestCase):
    """
    Vérifie l'isolation workspace sur les 5 nouveaux ModelViewSet :
      * /api/v1/project-phases/
      * /api/v1/field-reports/
      * /api/v1/real-estate-lots/
      * /api/v1/admin-cases/
      * /api/v1/project-view-preferences/
    """

    def test_phase_list_isolated_by_workspace(self):
        from datetime import date
        own = dm.ProjectPhase.objects.create(
            workspace=self.workspace_a, project=self.project_a,
            name="Études", position=1,
        )
        other = dm.ProjectPhase.objects.create(
            workspace=self.workspace_b, project=self.project_b,
            name="Études B", position=1,
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get("/api/v1/project-phases/")
        self.assertEqual(resp.status_code, 200)
        ids = [item["id"] for item in resp.json().get("results", resp.json())]
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids,
            msg="Phase de W2 ne doit jamais apparaître dans la liste de user A")

    def test_phase_retrieve_cross_tenant_blocked(self):
        phase_b = dm.ProjectPhase.objects.create(
            workspace=self.workspace_b, project=self.project_b,
            name="Construction", position=2,
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get(f"/api/v1/project-phases/{phase_b.pk}/")
        self.assertIn(resp.status_code, (403, 404))

    def test_field_report_list_isolated(self):
        own = dm.FieldReport.objects.create(
            workspace=self.workspace_a, project=self.project_a,
            location_name="Chantier A",
        )
        other = dm.FieldReport.objects.create(
            workspace=self.workspace_b, project=self.project_b,
            location_name="Chantier B",
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get("/api/v1/field-reports/")
        self.assertEqual(resp.status_code, 200)
        ids = [item["id"] for item in resp.json().get("results", resp.json())]
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids)

    def test_real_estate_lot_isolated(self):
        lot_a = dm.RealEstateLot.objects.create(
            workspace=self.workspace_a, project=self.project_a,
            lot_number="A-101", surface_m2=80,
        )
        lot_b = dm.RealEstateLot.objects.create(
            workspace=self.workspace_b, project=self.project_b,
            lot_number="B-101", surface_m2=80,
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get("/api/v1/real-estate-lots/")
        self.assertEqual(resp.status_code, 200)
        ids = [item["id"] for item in resp.json().get("results", resp.json())]
        self.assertIn(lot_a.pk, ids)
        self.assertNotIn(lot_b.pk, ids)

    def test_admin_case_isolated(self):
        case_a = dm.AdminCase.objects.create(
            workspace=self.workspace_a, project=self.project_a,
            reference="DOSS-A-001", title="Permis A",
        )
        case_b = dm.AdminCase.objects.create(
            workspace=self.workspace_b, project=self.project_b,
            reference="DOSS-B-001", title="Permis B",
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get("/api/v1/admin-cases/")
        self.assertEqual(resp.status_code, 200)
        ids = [item["id"] for item in resp.json().get("results", resp.json())]
        self.assertIn(case_a.pk, ids)
        self.assertNotIn(case_b.pk, ids)

    def test_admin_case_deadline_auto_computed(self):
        from datetime import date, timedelta
        case = dm.AdminCase.objects.create(
            workspace=self.workspace_a, project=self.project_a,
            reference="DOSS-001", title="Permis test",
            requested_at=date(2026, 1, 1),
            sla_days=30,
        )
        # Le save() du modèle doit avoir auto-calculé la deadline.
        self.assertEqual(case.deadline, date(2026, 1, 1) + timedelta(days=30))

    def test_view_preference_only_own(self):
        # Création explicite de prefs pour user A et user B sur leurs projets.
        pref_a = dm.ProjectViewPreference.objects.create(
            user=self.user_a, project=self.project_a, view_mode="GANTT",
        )
        # Pour user B sur W2 (notre infra le scope par workspace ET par user).
        pref_b = dm.ProjectViewPreference.objects.create(
            user=self.user_b, project=self.project_b, view_mode="LIST",
        )
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get("/api/v1/project-view-preferences/")
        self.assertEqual(resp.status_code, 200)
        ids = [item["id"] for item in resp.json().get("results", resp.json())]
        self.assertIn(pref_a.pk, ids)
        self.assertNotIn(pref_b.pk, ids)


# ===========================================================================
# Phase 1 — Quick actions DRF (PR7)
# ===========================================================================
class QuickActionsSecurityTests(MultiTenantSetupMixin, TestCase):
    """
    Vérifie les nouveaux endpoints quick-actions :
      * 200 OK quand user A agit sur sa propre tâche (W1)
      * 404 quand user A tente d'agir sur une tâche de W2
    """

    def _make_task(self, workspace, project, **kwargs):
        defaults = dict(
            workspace=workspace, project=project,
            title="Tâche test", status=dm.Task.Status.TODO, position=0,
        )
        defaults.update(kwargs)
        return dm.Task.objects.create(**defaults)

    # --- toggle-complete -------------------------------------------------
    def test_toggle_complete_owned_task_ok(self):
        task_a = self._make_task(self.workspace_a, self.project_a,
                                  assignee=self.user_a)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(f"/api/v1/tasks/{task_a.pk}/toggle-complete/")
        self.assertEqual(resp.status_code, 200)
        task_a.refresh_from_db()
        self.assertEqual(task_a.status, dm.Task.Status.DONE)

    def test_toggle_complete_cross_tenant_blocked(self):
        task_b = self._make_task(self.workspace_b, self.project_b)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(f"/api/v1/tasks/{task_b.pk}/toggle-complete/")
        self.assertEqual(resp.status_code, 404)
        task_b.refresh_from_db()
        self.assertEqual(task_b.status, dm.Task.Status.TODO)

    # --- update-status ---------------------------------------------------
    def test_update_status_cross_tenant_blocked(self):
        task_b = self._make_task(self.workspace_b, self.project_b)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(
            f"/api/v1/tasks/{task_b.pk}/update-status/",
            data=json.dumps({"status": "DONE"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_update_status_invalid_status_returns_400(self):
        task_a = self._make_task(self.workspace_a, self.project_a)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(
            f"/api/v1/tasks/{task_a.pk}/update-status/",
            data=json.dumps({"status": "NOT_A_STATUS"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    # --- snooze ----------------------------------------------------------
    def test_snooze_sets_snoozed_until(self):
        task_a = self._make_task(self.workspace_a, self.project_a)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(
            f"/api/v1/tasks/{task_a.pk}/snooze/",
            data=json.dumps({"until": "2026-12-31T09:00:00"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        task_a.refresh_from_db()
        self.assertIsNotNone(task_a.snoozed_until)

    def test_snooze_cross_tenant_blocked(self):
        task_b = self._make_task(self.workspace_b, self.project_b)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(
            f"/api/v1/tasks/{task_b.pk}/snooze/",
            data=json.dumps({"until": "2026-12-31T09:00:00"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    # --- move-kanban -----------------------------------------------------
    def test_move_kanban_cross_tenant_blocked(self):
        task_b = self._make_task(self.workspace_b, self.project_b)
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.post(
            f"/api/v1/tasks/{task_b.pk}/move-kanban/",
            data=json.dumps({"status": "DONE", "position": 1}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    # --- me/today --------------------------------------------------------
    def test_me_today_returns_only_own_workspace_tasks(self):
        # Tâche du user A : doit apparaître
        own = self._make_task(
            self.workspace_a, self.project_a,
            assignee=self.user_a,
            due_date=timezone.localdate(),
        )
        # Tâche de user B avec user A comme assignee (cas pathologique
        # impossible en pratique mais on teste le filtre workspace) — ne doit
        # PAS apparaître car workspace inaccessible à user A.
        other = self._make_task(
            self.workspace_b, self.project_b,
            assignee=self.user_a,
            due_date=timezone.localdate(),
        )

        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get("/api/v1/me/today/")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        ids = {t["id"] for t in payload["tasks_today"]}
        self.assertIn(own.pk, ids)
        self.assertNotIn(other.pk, ids)

    # --- vue HTML my-day -------------------------------------------------
    def test_my_day_html_view_renders_200(self):
        client = self.login_as(self.user_a, "pw-alice-1")
        resp = client.get(reverse("my_day"))
        self.assertEqual(resp.status_code, 200)


# ===========================================================================
# Throttle IA — sanity check de configuration (ne brûle pas le quota OpenAI)
# ===========================================================================
class AIThrottleConfigurationTests(TestCase):
    """
    Vérifie juste que AIActionRateThrottle est bien attaché aux actions IA.
    On ne dépasse PAS le rate en test pour ne pas dépendre de cache.
    """

    def test_ai_forecast_action_has_throttle_classes(self):
        from project.api.throttles import AIActionRateThrottle
        from project.api.viewsets import ProjectViewSet, TaskViewSet, WorkspaceViewSet

        for vs_cls, action_name in [
            (ProjectViewSet, "ai_forecast"),
            (ProjectViewSet, "ai_risk_analysis"),
            (TaskViewSet, "ai_effort_estimate"),
            (WorkspaceViewSet, "allocation_advice"),
        ]:
            method = getattr(vs_cls, action_name)
            # DRF expose la liste sur la fonction ; sinon dans method.kwargs
            # selon la version. On supporte les deux pour rester robuste.
            throttles = (
                getattr(method, "throttle_classes", None)
                or getattr(method, "kwargs", {}).get("throttle_classes", [])
            )
            self.assertIn(
                AIActionRateThrottle, throttles or [],
                msg=f"{vs_cls.__name__}.{action_name} doit avoir AIActionRateThrottle",
            )
