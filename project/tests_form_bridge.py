"""
Pont formulaires Django → React (``/api/v1/forms/<nom>/``) : une vue qui
enregistre puis redirige doit être présentée comme un succès.

Régression : l'intégration d'un collaborateur, la création de facture,
d'invitation ou de méthodologie enregistraient l'objet mais le pont
répondait 400 « Enregistrement impossible. » (la vue ne fixait pas
``self.object``) ; un nouvel essai créait alors un doublon.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_form_bridge
"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from project import models as dm

User = get_user_model()


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class FormBridgeSuccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw", first_name="Olive", is_superuser=True)
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Dan", last_name="Dev")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Core", lead=cls.owner)
        owner_p = dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.dev, workspace=cls.ws, manager=owner_p)
        dm.TeamMembership.objects.create(user=cls.owner, workspace=cls.ws, team=cls.team, role="ADMIN")
        dm.TeamMembership.objects.create(user=cls.dev, workspace=cls.ws, team=cls.team)
        cls.client_org = dm.InvoiceClient.objects.create(workspace=cls.ws, name="Kaydan")

    def setUp(self):
        self.client.force_login(self.owner)

    def _payload(self, name, **extra):
        res = self.client.get(f"/api/v1/forms/{name}/")
        self.assertEqual(res.status_code, 200, res.content)
        payload = {
            f["name"]: ("" if f["value"] is None else f["value"])
            for f in res.json()["fields"] if f["type"] not in ("checkbox", "multiselect", "file")
        }
        payload.update(extra)
        return payload

    def test_onboarding_new_employee_returns_created_membership(self):
        with mock.patch("project.services.invitations.send_invitation_email") as send, \
                self.captureOnCommitCallbacks(execute=True):
            res = self.client.post("/api/v1/forms/member/", self._payload(
                "member", mode="new", first_name="Victor", last_name="Kakou", email="Victor.Kakou@A.test",
                team=self.team.pk, role="TECH_LEAD", weekly_capacity="40", arrival_date="2026-07-01",
            ))
        self.assertEqual(res.status_code, 201, res.content)
        membership = dm.TeamMembership.objects.get(pk=res.json()["id"])
        self.assertEqual((membership.user.email, membership.team, membership.user.is_active), ("victor.kakou@a.test", self.team, False))
        self.assertIn("Invitation d'activation envoyée", " ".join(res.json()["messages"]))
        send.assert_called_once()
        again = self.client.post("/api/v1/forms/member/", self._payload(
            "member", mode="new", first_name="Victor", last_name="Kakou", email="victor.kakou@a.test",
        ))
        self.assertEqual(again.status_code, 400)
        self.assertIn("email", again.json())

    def test_invoice_create_returns_created_invoice(self):
        res = self.client.post("/api/v1/forms/invoice/", self._payload("invoice", title="Régie novembre", client=self.client_org.pk))
        self.assertEqual(res.status_code, 201, res.content)
        invoice = dm.Invoice.objects.get(pk=res.json()["id"])
        self.assertEqual((invoice.workspace, invoice.title, invoice.issued_by), (self.ws, "Régie novembre", self.owner))

    def test_workspace_invitation_create_returns_created_invitation(self):
        with mock.patch("project.services.invitations.send_invitation_email") as send:
            res = self.client.post("/api/v1/forms/workspace-invitation/", self._payload(
                "workspace-invitation", email="new@a.test", team=self.team.pk,
            ))
        self.assertEqual(res.status_code, 201, res.content)
        invitation = dm.WorkspaceInvitation.objects.get(pk=res.json()["id"])
        self.assertEqual((invitation.workspace, invitation.email), (self.ws, "new@a.test"))
        send.assert_called_once()

    def test_redirect_without_object_is_success_unless_an_error_was_emitted(self):
        """Vue sans ``self.object`` (méthodologie) : redirection = succès ; ``messages.error`` = 400 explicite."""
        res = self.client.post("/api/v1/forms/methodology/", {"name": "Kanban maison", "family": "custom"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIsNone(res.json()["id"])
        self.assertTrue(dm.Methodology.objects.filter(name="Kanban maison").exists())
        missing = self.client.post("/api/v1/forms/methodology/", {"name": "  "})
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json(), {"detail": "Le nom est obligatoire."})


@override_settings(STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage")
class FormBridgeReviewTests(TestCase):
    """Défauts relevés par la revue du pont : enregistrements présentés en échec, 500, droits."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@a.test", "pw", first_name="Olive", last_name="Owner")
        cls.dev = User.objects.create_user("dev", "dev@a.test", "pw", first_name="Dan", last_name="Dev")
        cls.lead = User.objects.create_user("lead", "lead@a.test", "pw", first_name="Lea", last_name="Lead")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.other_ws = dm.Workspace.objects.create(name="Beta", owner=cls.owner)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Core", lead=cls.owner)
        cls.owner_p = dm.UserProfile.objects.create(user=cls.owner, workspace=cls.ws)
        dm.UserProfile.objects.create(user=cls.lead, workspace=cls.ws)
        cls.dev_p = dm.UserProfile.objects.create(
            user=cls.dev, workspace=cls.ws, manager=cls.owner_p, capacity_hours_per_week=24,
            joined_company_at="2024-01-15",
        )
        cls.owner_m = dm.TeamMembership.objects.create(user=cls.owner, workspace=cls.ws, team=cls.team, role="ADMIN")
        cls.dev_m = dm.TeamMembership.objects.create(user=cls.dev, workspace=cls.ws, team=cls.team)
        dm.TeamMembership.objects.create(user=cls.owner, workspace=cls.other_ws, role="ADMIN")
        dm.WorkspaceRoleAssignment.objects.create(user=cls.lead, workspace=cls.ws, role="TEAM_LEAD")
        dm.TeamMembership.objects.create(user=cls.lead, workspace=cls.ws, team=cls.team, role="TECH_LEAD")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail", team=cls.team)

    def _payload(self, url, **extra):
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200, res.content)
        payload = {
            f["name"]: ("" if f["value"] is None else f["value"])
            for f in res.json()["fields"] if f["type"] not in ("checkbox", "multiselect", "file") and not f["disabled"]
        }
        payload.update(extra)
        return payload

    def test_milestone_and_roadmap_updates_return_success(self):
        """Avant : NoReverseMatch (« project: » non enregistré) → 500 après enregistrement."""
        self.client.force_login(self.owner)
        milestone = dm.Milestone.objects.create(workspace=self.ws, project=self.project, name="Go-live", due_date="2026-12-01")
        res = self.client.post(f"/api/v1/forms/milestone/{milestone.pk}/", self._payload(f"/api/v1/forms/milestone/{milestone.pk}/", name="Go-live v2"))
        self.assertEqual((res.status_code, res.json()["id"]), (200, milestone.pk), res.content)
        roadmap = dm.Roadmap.objects.create(workspace=self.ws, name="R1", start_date="2026-01-01", end_date="2026-12-31")
        res = self.client.post(f"/api/v1/forms/roadmap/{roadmap.pk}/", self._payload(f"/api/v1/forms/roadmap/{roadmap.pk}/", name="R2"))
        self.assertEqual((res.status_code, res.json()["id"]), (200, roadmap.pk), res.content)

    def test_profile_save_keeps_account_fields(self):
        """Le formulaire React du profil n'envoie ni prénom, ni nom, ni e-mail : ils étaient vidés."""
        self.client.force_login(self.owner)
        res = self.client.post("/api/v1/forms/profile/", self._payload("/api/v1/forms/profile/", job_title="Architecte"))
        self.assertEqual(res.status_code, 200, res.content)
        self.owner.refresh_from_db()
        self.assertEqual((self.owner.first_name, self.owner.last_name, self.owner.email), ("Olive", "Owner", "owner@a.test"))

    def test_member_cannot_edit_or_remove_memberships(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(f"/api/v1/forms/member/{self.dev_m.pk}/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/forms/member/{self.dev_m.pk}/", {"role": "ADMIN"}).status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{self.owner_m.pk}/").status_code, 403)
        self.dev_m.refresh_from_db()
        self.assertEqual(self.dev_m.role, "DEVELOPER")
        self.assertTrue(dm.TeamMembership.objects.filter(pk=self.owner_m.pk).exists())
        self.assertFalse(self.client.get("/api/v1/team-members/").json()["permissions"]["can_manage"])
        # Isolation : le rattachement d'un autre tenant reste introuvable (404), même pour un gestionnaire.
        bob = User.objects.create_user("bob", "bob@b.test", "pw")
        gamma = dm.Workspace.objects.create(name="Gamma", owner=bob)
        bob_m = dm.TeamMembership.objects.create(user=bob, workspace=gamma)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(f"/api/v1/forms/member/{bob_m.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{bob_m.pk}/").status_code, 404)

    def test_team_lead_cannot_grant_elevated_roles_or_touch_owner(self):
        self.client.force_login(self.lead)
        url = f"/api/v1/forms/member/{self.dev_m.pk}/"
        res = self.client.post(url, self._payload(url, role="ADMIN"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("role", res.json())
        res = self.client.post(url, self._payload(url, role="QA"))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{self.owner_m.pk}/").status_code, 403)
        self.client.force_login(self.owner)
        res = self.client.post(url, self._payload(url, role="ADMIN"))
        self.assertEqual(res.status_code, 200, res.content)

    def test_onboarding_existing_user_keeps_profile_defaults(self):
        """Rattacher un collaborateur à une autre équipe ne réinitialise ni son N+1, ni sa capacité, ni sa date d'entrée."""
        self.client.force_login(self.owner)
        mobile = dm.Team.objects.create(workspace=self.ws, name="Mobile")
        res = self.client.post("/api/v1/forms/member/", self._payload("/api/v1/forms/member/", mode="existing", user=self.dev.pk, team=mobile.pk))
        self.assertEqual(res.status_code, 201, res.content)
        self.dev_p.refresh_from_db()
        self.assertEqual(
            (self.dev_p.manager_id, float(self.dev_p.capacity_hours_per_week), str(self.dev_p.joined_company_at)),
            (self.owner_p.pk, 24.0, "2024-01-15"),
        )

    def test_financial_forms(self):
        cat = dm.CostCategory.objects.create(name="Infra", category_type=dm.CostCategory.CategoryType.INFRA)
        budget = dm.ProjectBudget.objects.create(project=self.project)
        # Simple membre : plus d'accès au budget par la route d'édition sans ?project=.
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(f"/api/v1/forms/project-budget/{budget.pk}/").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/forms/project-budget/{budget.pk}/", {"status": "DRAFT"}).status_code, 403)
        self.client.force_login(self.owner)
        # Création sans projet : erreur de formulaire au lieu d'un 500.
        res = self.client.post("/api/v1/forms/project-expense/", self._payload("/api/v1/forms/project-expense/", title="Cloud", amount="10", category=cat.pk))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("non_field_errors", res.json())
        # Second budget pour le même projet : refus explicite.
        url = f"/api/v1/forms/project-budget/?project={self.project.pk}"
        res = self.client.post(url, self._payload(url))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("déjà un budget", " ".join(res.json()["non_field_errors"]))
        # Refus par messages.error d'une vue qui expose l'objet → 400, pas un succès.
        expense = dm.ProjectExpense.objects.create(
            project=self.project, category=cat, title="Cloud", amount=10,
            approval_state=dm.ProjectExpense.ApprovalState.LEVEL2_APPROVED,
        )
        res = self.client.post(f"/api/v1/forms/project-expense/{expense.pk}/", {})
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(res.json(), {"detail": "Une dépense validée niveau 2 ne peut plus être modifiée."})

    def test_partial_instances_return_form_errors(self):
        self.client.force_login(self.owner)
        task = dm.Task.objects.create(workspace=self.ws, project=self.project, title="T1")
        res = self.client.post("/api/v1/forms/task-dependency/", self._payload("/api/v1/forms/task-dependency/", from_task=task.pk, to_task=""))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("to_task", res.json())
        res = self.client.post("/api/v1/forms/sprint/", self._payload("/api/v1/forms/sprint/", project=self.project.pk, name="S1", number="1", start_date="2026-11-01", end_date=""))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("end_date", res.json())

    def test_duplicate_with_blank_workspace_returns_form_error(self):
        """Workspace laissé vide (utilisateur multi-espaces) : l'unicité (workspace, nom) n'était plus vérifiée → 500."""
        self.client.force_login(self.owner)
        res = self.client.post("/api/v1/forms/team/", self._payload("/api/v1/forms/team/", name="Core", workspace=""))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(dm.Team.objects.filter(workspace=self.ws, name="Core").count(), 1)

    def test_team_lead_rules_cover_finance_roles_and_management(self):
        """TECH_LEAD / PO ouvrent la finance (lecture, validation des dépenses) : réservés à members.manage."""
        self.client.force_login(self.lead)
        url = f"/api/v1/forms/member/{self.dev_m.pk}/"
        for role in ("TECH_LEAD", "PO"):
            res = self.client.post(url, self._payload(url, role=role))
            self.assertEqual(res.status_code, 400, (role, res.content))
            self.assertIn("role", res.json())
        res = self.client.post("/api/v1/forms/member/", self._payload(
            "/api/v1/forms/member/", mode="new", first_name="Po", last_name="New", email="po@a.test", role="PO",
        ))
        self.assertEqual(res.status_code, 400, res.content)
        # Co-administrateur (rôle RBAC) : ni modifiable, ni retirable, ni rattachable par un team lead.
        coadmin = User.objects.create_user("co", "co@a.test", "pw")
        dm.WorkspaceRoleAssignment.objects.create(user=coadmin, workspace=self.ws, role="WORKSPACE_OWNER")
        co_m = dm.TeamMembership.objects.create(user=coadmin, workspace=self.ws, team=self.team)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{co_m.pk}/").status_code, 403)
        res = self.client.post(f"/api/v1/forms/member/{co_m.pk}/", self._payload(f"/api/v1/forms/member/{co_m.pk}/", role="VIEWER"))
        self.assertEqual(res.status_code, 400, res.content)
        mobile = dm.Team.objects.create(workspace=self.ws, name="Mobile")
        res = self.client.post("/api/v1/forms/member/", self._payload(
            "/api/v1/forms/member/", mode="existing", user=self.owner.pk, team=mobile.pk, manager=self.lead.pk,
        ))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertTrue(dm.TeamMembership.objects.filter(pk=co_m.pk).exists())
        rows = {r["id"]: r["can_manage"] for r in self.client.get("/api/v1/team-members/").json()["results"]}
        self.assertEqual((rows[self.dev_m.pk], rows[co_m.pk], rows[self.owner_m.pk]), (True, False, False))

    def test_invitations_require_rights_and_role_rules(self):
        """Un simple membre ne s'invite plus lui-même en ADMIN ; un team lead n'invite pas en rôle élevé."""
        with mock.patch("project.services.invitations.send_invitation_email"):
            self.client.force_login(self.dev)
            res = self.client.post("/api/v1/forms/workspace-invitation/", {"email": "dev@a.test", "role": "ADMIN", "team": self.team.pk})
            self.assertEqual(res.status_code, 403, res.content)
            self.client.force_login(self.lead)
            url = "/api/v1/forms/workspace-invitation/"
            res = self.client.post(url, self._payload(url, email="x@a.test", role="ADMIN", team=self.team.pk))
            self.assertEqual(res.status_code, 400, res.content)
            res = self.client.post(url, self._payload(url, email="x@a.test", role="DEVELOPER", team=self.team.pk))
            self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(dm.WorkspaceInvitation.objects.filter(email="dev@a.test").exists())

    def test_owner_can_leave_a_secondary_team_but_not_the_workspace(self):
        self.client.force_login(self.owner)
        mobile = dm.Team.objects.create(workspace=self.ws, name="Mobile")
        extra = dm.TeamMembership.objects.create(user=self.owner, workspace=self.ws, team=mobile)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{extra.pk}/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/actions/member-delete/{self.owner_m.pk}/").status_code, 403)

    def test_existing_user_explicit_capacity_is_applied(self):
        self.client.force_login(self.owner)
        mobile = dm.Team.objects.create(workspace=self.ws, name="Mobile")
        res = self.client.post("/api/v1/forms/member/", self._payload(
            "/api/v1/forms/member/", mode="existing", user=self.dev.pk, team=mobile.pk, weekly_capacity="40",
        ))
        self.assertEqual(res.status_code, 201, res.content)
        self.dev_p.refresh_from_db()
        self.assertEqual(float(self.dev_p.capacity_hours_per_week), 40.0)

    def test_anonymous_budget_edit_redirects_to_login(self):
        budget = dm.ProjectBudget.objects.create(project=self.project)
        res = self.client.get(f"/project-budgets/{budget.pk}/update/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("login", res["Location"])

    def _invite(self, email, role="DEVELOPER", team=None, by=None, ws=None):
        return dm.WorkspaceInvitation.objects.create(
            workspace=ws or self.ws, email=email, role=role, team=team, invited_by=by or self.owner,
            token=f"tok-{email}", expires_at="2099-01-01T00:00:00Z",
        )

    def test_invitation_workspace_comes_from_checked_rights(self):
        """Avant : ``?workspace=<espace perso>`` pour les droits + champ workspace=Alpha → auto-invitation ADMIN dans Alpha."""
        own = dm.Workspace.objects.create(name="DevOwn", owner=self.dev)
        with mock.patch("project.services.invitations.send_invitation_email"):
            self.client.force_login(self.dev)
            res = self.client.post(f"/api/v1/forms/workspace-invitation/?workspace={own.pk}", {
                "workspace": self.ws.pk, "email": "dev@a.test", "role": "ADMIN",
            })
        self.assertFalse(dm.WorkspaceInvitation.objects.filter(workspace=self.ws).exists(), res.content)
        if res.status_code == 201:
            self.assertEqual(dm.WorkspaceInvitation.objects.get(pk=res.json()["id"]).workspace, own)

    def test_invitation_lifecycle_requires_rights(self):
        admin_inv = self._invite("cfo@a.test", role="ADMIN")
        plain_inv = self._invite("qa@a.test", role="QA", team=self.team)
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get("/workspace-invitations/").status_code, 403)
        for action in ("resend", "revoke", "accept", "delete"):
            self.assertEqual(self.client.post(f"/workspace-invitations/{plain_inv.pk}/{action}/").status_code, 403, action)
        # Team lead : invitations ordinaires oui, rôle élevé non ; jamais les liens d'acceptation.
        self.client.force_login(self.lead)
        page = self.client.get("/workspace-invitations/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(f"/invitations/{admin_inv.token}/", page.content.decode())
        self.assertEqual(self.client.post(f"/workspace-invitations/{admin_inv.pk}/revoke/").status_code, 403)
        self.assertEqual(self.client.post(f"/workspace-invitations/{plain_inv.pk}/revoke/").status_code, 302)
        # Autre tenant : 404 (et non 500).
        bob = User.objects.create_user("bob", "bob@b.test", "pw")
        gamma = dm.Workspace.objects.create(name="Gamma", owner=bob)
        foreign = self._invite("x@g.test", by=bob, ws=gamma)
        self.client.force_login(self.owner)
        self.assertIn(f"/invitations/{admin_inv.token}/", self.client.get("/workspace-invitations/").content.decode())
        self.assertEqual(self.client.post(f"/workspace-invitations/{foreign.pk}/accept/").status_code, 404)

    def test_accepting_an_old_invitation_keeps_the_current_role(self):
        inv = self._invite("dev@a.test", role="QA", team=self.team)
        self.dev_m.role = "TECH_LEAD"
        self.dev_m.save(update_fields=["role"])
        self.client.force_login(self.dev)
        self.client.post(f"/invitations/{inv.token}/")
        self.dev_m.refresh_from_db()
        self.assertEqual(self.dev_m.role, "TECH_LEAD")

    def test_team_lead_onboarding_cannot_replace_a_pending_elevated_invitation(self):
        self._invite("cfo@a.test", role="ADMIN")
        self.client.force_login(self.lead)
        res = self.client.post("/api/v1/forms/member/", self._payload(
            "/api/v1/forms/member/", mode="new", first_name="C", last_name="Fo", email="cfo@a.test", role="DEVELOPER",
        ))
        self.assertEqual(res.status_code, 400, res.content)
        self.assertEqual(dm.WorkspaceInvitation.objects.get(email="cfo@a.test").role, "ADMIN")

    def test_team_delete_is_reserved_and_member_user_is_frozen(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(f"/api/v1/actions/team-delete/{self.team.pk}/").status_code, 403)
        self.assertTrue(dm.TeamMembership.objects.filter(pk=self.owner_m.pk).exists())
        self.client.force_login(self.owner)
        fields = {f["name"]: f for f in self.client.get(f"/api/v1/forms/member/{self.dev_m.pk}/").json()["fields"]}
        self.assertTrue(fields["user"]["disabled"])

    def test_owner_rows_removable_only_when_not_the_last(self):
        self.client.force_login(self.owner)
        rows = {r["id"]: r for r in self.client.get("/api/v1/team-members/").json()["results"]}
        self.assertFalse(rows[self.owner_m.pk]["can_remove"])
        mobile = dm.Team.objects.create(workspace=self.ws, name="Mobile")
        extra = dm.TeamMembership.objects.create(user=self.owner, workspace=self.ws, team=mobile)
        rows = {r["id"]: r for r in self.client.get("/api/v1/team-members/").json()["results"]}
        self.assertTrue(rows[extra.pk]["can_remove"] and rows[self.owner_m.pk]["can_remove"])
        self.assertIn(f"/team-memberships/{extra.pk}/delete/", self.client.get("/team-memberships/").content.decode())
