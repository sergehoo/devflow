"""
Tests PR23 — RBAC : matrice de permissions + résolution de rôle +
escalade de privilèges.

Lance avec :
    python manage.py test project.tests_rbac
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from project import models as dm
from project.services.rbac import (
    CLIENT,
    MEMBER,
    PROJECT_MANAGER,
    ROLE_PERMISSIONS,
    RBACService,
    SUPER_ADMIN,
    TEAM_LEAD,
    WORKSPACE_OWNER,
)

User = get_user_model()


class RBACSetupMixin:
    @classmethod
    def setUpTestData(cls):
        cls.alice_owner = User.objects.create_user(
            username="alice_rbac", email="ar@example.com", password="x",
        )
        cls.bob_pm = User.objects.create_user(
            username="bob_rbac", email="br@example.com", password="x",
        )
        cls.carol_member = User.objects.create_user(
            username="carol_rbac", email="cr@example.com", password="x",
        )
        cls.dave_client = User.objects.create_user(
            username="dave_rbac", email="dr@example.com", password="x",
        )
        cls.admin = User.objects.create_superuser(
            username="superadmin", email="sa@example.com", password="x",
        )
        cls.intruder = User.objects.create_user(
            username="intruder", email="i@example.com", password="x",
        )
        cls.workspace = dm.Workspace.objects.create(
            name="WS RBAC", owner=cls.alice_owner,
        )
        # Profils pour donner accès au workspace (sauf intruder)
        for u in (cls.alice_owner, cls.bob_pm, cls.carol_member, cls.dave_client):
            dm.UserProfile.objects.create(user=u, workspace=cls.workspace)

        # Assignments explicites
        dm.WorkspaceRoleAssignment.objects.create(
            user=cls.bob_pm, workspace=cls.workspace, role=PROJECT_MANAGER,
        )
        dm.WorkspaceRoleAssignment.objects.create(
            user=cls.dave_client, workspace=cls.workspace, role=CLIENT,
        )
        # Carol n'a pas d'assignment → default MEMBER


class RoleResolutionTests(RBACSetupMixin, TestCase):
    def test_superuser_is_super_admin(self):
        self.assertEqual(
            RBACService.get_role_for(self.admin, self.workspace),
            SUPER_ADMIN,
        )

    def test_workspace_owner_implicit(self):
        # Alice est owner du Workspace même sans WorkspaceRoleAssignment
        self.assertEqual(
            RBACService.get_role_for(self.alice_owner, self.workspace),
            WORKSPACE_OWNER,
        )

    def test_explicit_assignment_wins(self):
        self.assertEqual(
            RBACService.get_role_for(self.bob_pm, self.workspace),
            PROJECT_MANAGER,
        )
        self.assertEqual(
            RBACService.get_role_for(self.dave_client, self.workspace),
            CLIENT,
        )

    def test_default_member_for_accessible_user(self):
        """Carol a un profile→workspace mais pas d'assignment → MEMBER."""
        self.assertEqual(
            RBACService.get_role_for(self.carol_member, self.workspace),
            MEMBER,
        )

    def test_no_role_for_outsider(self):
        """Intruder n'est ni owner, ni profile, ni membership → None."""
        self.assertIsNone(
            RBACService.get_role_for(self.intruder, self.workspace),
        )

    def test_anonymous_returns_none(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIsNone(
            RBACService.get_role_for(AnonymousUser(), self.workspace),
        )


class PermissionMatrixTests(RBACSetupMixin, TestCase):
    """
    Vérifie la matrice : pour chaque rôle, certaines permissions doivent
    passer (✓), d'autres doivent être refusées (✗).
    """

    def test_super_admin_can_everything(self):
        for action in ("workspace.delete", "budget.edit", "task.delete",
                       "audit.export", "billing.manage"):
            self.assertTrue(
                RBACService.can(self.admin, action, workspace=self.workspace),
                msg=f"SuperAdmin doit pouvoir {action}",
            )

    def test_workspace_owner_can_manage_all(self):
        for action in ("workspace.manage", "budget.edit", "team.manage",
                       "ai.summarize", "billing.view"):
            self.assertTrue(
                RBACService.can(self.alice_owner, action, workspace=self.workspace),
                msg=f"Owner doit pouvoir {action}",
            )

    def test_project_manager_no_budget_edit(self):
        # PM peut voir le budget mais pas l'éditer (matrix definition)
        self.assertTrue(
            RBACService.can(self.bob_pm, "budget.view", workspace=self.workspace),
        )
        self.assertFalse(
            RBACService.can(self.bob_pm, "budget.edit", workspace=self.workspace),
            msg="PM ne doit PAS pouvoir éditer le budget",
        )
        self.assertFalse(
            RBACService.can(self.bob_pm, "workspace.manage", workspace=self.workspace),
        )

    def test_member_only_own_tasks(self):
        self.assertTrue(
            RBACService.can(self.carol_member, "task.view_assigned",
                             workspace=self.workspace),
        )
        self.assertFalse(
            RBACService.can(self.carol_member, "task.delete", workspace=self.workspace),
            msg="MEMBER ne doit PAS pouvoir supprimer une tâche",
        )
        self.assertFalse(
            RBACService.can(self.carol_member, "budget.view", workspace=self.workspace),
        )
        self.assertFalse(
            RBACService.can(self.carol_member, "team.manage", workspace=self.workspace),
        )

    def test_client_has_no_internal_access(self):
        self.assertTrue(
            RBACService.can(self.dave_client, "project.view_assigned",
                             workspace=self.workspace),
        )
        # Strictement aucun accès finance ni tâche interne
        for action in ("budget.view", "task.view", "team.view",
                       "timesheet.view_team", "billing.view"):
            self.assertFalse(
                RBACService.can(self.dave_client, action, workspace=self.workspace),
                msg=f"CLIENT ne doit PAS pouvoir {action}",
            )

    def test_intruder_denied_all(self):
        for action in ("project.view", "task.view_assigned", "budget.view"):
            self.assertFalse(
                RBACService.can(self.intruder, action, workspace=self.workspace),
                msg=f"Intruder doit être refusé sur {action}",
            )


class PrivilegeEscalationTests(RBACSetupMixin, TestCase):
    """Scénarios d'escalade : on tente de contourner et on vérifie le refus."""

    def test_member_cannot_self_promote(self):
        """
        Un Member ne doit pas pouvoir créer une WorkspaceRoleAssignment
        pour lui-même (vérifié au niveau permission ; côté view, c'est
        protégé par members.manage).
        """
        self.assertFalse(
            RBACService.can(
                self.carol_member, "members.manage", workspace=self.workspace,
            ),
        )

    def test_pm_cannot_delete_workspace(self):
        self.assertFalse(
            RBACService.can(
                self.bob_pm, "workspace.delete", workspace=self.workspace,
            ),
        )

    def test_client_cannot_access_other_users_data(self):
        # Un Client ne peut PAS voir les tâches générales
        self.assertFalse(
            RBACService.can(
                self.dave_client, "task.view", workspace=self.workspace,
            ),
        )

    def test_no_workspace_means_no_permission_unless_superadmin(self):
        """
        Si workspace=None, seul SUPER_ADMIN passe (action globale).
        """
        self.assertTrue(RBACService.can(self.admin, "audit.export"))
        self.assertFalse(RBACService.can(self.alice_owner, "audit.export"))
        self.assertFalse(RBACService.can(self.bob_pm, "audit.export"))


class WildcardMatchTests(TestCase):
    """Vérifie que les wildcards * et domaine.* matchent correctement."""

    def test_global_wildcard(self):
        self.assertTrue(RBACService._matches({"*"}, "n.importe.quoi"))

    def test_domain_wildcard(self):
        self.assertTrue(RBACService._matches({"task.*"}, "task.edit"))
        self.assertTrue(RBACService._matches({"task.*"}, "task.delete"))
        self.assertFalse(RBACService._matches({"task.*"}, "budget.edit"))

    def test_exact_match(self):
        self.assertTrue(RBACService._matches({"task.view"}, "task.view"))
        self.assertFalse(RBACService._matches({"task.view"}, "task.edit"))


class WorkspaceIsolationViaRolesTests(RBACSetupMixin, TestCase):
    """Un user peut avoir des rôles différents dans des workspaces différents."""

    def test_user_can_have_different_role_per_workspace(self):
        ws2 = dm.Workspace.objects.create(name="WS 2", owner=self.bob_pm)
        # Bob est PM dans ws1 (alice's), Owner dans ws2 (sien)
        self.assertEqual(
            RBACService.get_role_for(self.bob_pm, self.workspace),
            PROJECT_MANAGER,
        )
        self.assertEqual(
            RBACService.get_role_for(self.bob_pm, ws2),
            WORKSPACE_OWNER,
        )

    def test_get_all_workspace_roles_returns_dict(self):
        roles = RBACService.get_all_workspace_roles(self.alice_owner)
        self.assertIn(self.workspace.pk, roles)
        self.assertEqual(roles[self.workspace.pk], WORKSPACE_OWNER)
