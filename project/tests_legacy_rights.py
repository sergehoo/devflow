"""
SECURITY (P0 phase 5) — droits sur l'objet réel dans les vues Django
historiques et le pont React (``/api/v1/forms|actions/``) : tâches, sous-objets
de tâches et notifications. IDOR, RBAC, usurpation de champs.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_legacy_rights
"""

from django.conf import settings
from django.test import Client, override_settings

from project import models as dm
from project.tests_api_raw_writes import RawApiFixture


# Rendu des templates historiques sans manifeste collectstatic.
STORAGES = {**settings.STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES)
class LegacyFixture(RawApiFixture):
    def web(self, user):
        client = Client()
        client.force_login(user)
        return client

    def bridge_form(self, user, task, **changes):
        """Relit le formulaire via le pont puis le renvoie modifié (comme React)."""
        api = self.api(user)
        res = api.get(f"/api/v1/forms/task/{task.pk}/")
        if res.status_code != 200:
            return res
        data = {f["name"]: f["value"] for f in res.json()["fields"] if f["value"] not in (None, "") and f["type"] != "file"}
        data.update(changes)
        return api.post(f"/api/v1/forms/task/{task.pk}/", data, format="multipart")

    def action(self, user, name, pk, **data):
        return self.api(user).post(f"/api/v1/actions/{name}/{pk}/", data, format="multipart")


class LegacyTaskRightsTests(LegacyFixture):
    def test_update_view_requires_real_task_rights(self):
        self.assertEqual(self.web(self.peer).get(f"/tasks/{self.task.pk}/update/").status_code, 403)
        self.assertEqual(self.web(self.dev).get(f"/tasks/{self.task.pk}/update/").status_code, 200)
        self.assertEqual(self.web(self.lead).get(f"/tasks/{self.task.pk}/update/").status_code, 200)
        self.assertEqual(self.web(self.bob).get(f"/tasks/{self.task.pk}/update/").status_code, 404)

    def test_bridge_cannot_bypass_update_rights(self):
        self.assertEqual(self.bridge_form(self.peer, self.task, title="pirate").status_code, 403)
        self.assertEqual(self.api(self.bob).post(f"/api/v1/forms/task/{self.task.pk}/", {"title": "x"}).status_code, 404)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "API")
        self.assertEqual(self.bridge_form(self.dev, self.task, title="API v2").status_code, 200)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "API v2")

    def test_reassignment_through_form_requires_can_reassign(self):
        # peer : co-affecté (peut modifier) mais ni assigné principal ni task.assign.
        dm.TaskAssignment.objects.create(task=self.task, user=self.peer, is_active=True)
        res = self.bridge_form(self.peer, self.task, assignee=self.peer.pk)
        self.assertEqual(res.status_code, 400)
        self.assertIn("assignee", res.json())
        self.task.refresh_from_db()
        self.assertEqual(self.task.assignee_id, self.dev.pk)
        self.assertEqual(self.bridge_form(self.lead, self.task, assignee=self.peer.pk).status_code, 200)

    def test_delete_and_archive_require_delete_right(self):
        self.assertEqual(self.web(self.dev).post(f"/tasks/{self.task.pk}/delete/").status_code, 403)
        self.assertEqual(self.action(self.dev, "task-delete", self.task.pk).status_code, 403)
        self.assertEqual(self.action(self.dev, "task-archive", self.task.pk).status_code, 403)
        self.assertEqual(self.action(self.bob, "task-delete", self.task.pk).status_code, 404)
        self.task.refresh_from_db()
        self.assertFalse(self.task.is_archived)
        # Responsable du projet 2 : peut archiver sa tâche ; chef de projet (rôle) : supprimer.
        self.assertEqual(self.action(self.outsider, "task-archive", self.task2.pk).status_code, 200)
        self.task2.refresh_from_db()
        self.assertTrue(self.task2.is_archived)
        self.assertEqual(self.action(self.pm, "task-delete", self.task.pk).status_code, 200)
        self.assertFalse(dm.Task.objects.filter(pk=self.task.pk).exists())

    def test_mark_done_requires_edit_right(self):
        self.assertEqual(self.action(self.peer, "task-done", self.task.pk).status_code, 403)
        self.assertEqual(self.action(self.bob, "task-done", self.task.pk).status_code, 404)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, dm.Task.Status.DONE)
        self.assertEqual(self.action(self.dev, "task-done", self.task.pk).status_code, 200)

    def test_overview_exposes_rights(self):
        data = self.api(self.peer).get(f"/api/v1/tasks/{self.task.pk}/overview/").json()
        self.assertEqual((data["can_edit"], data["can_delete"]), (False, False))
        data = self.api(self.pm).get(f"/api/v1/tasks/{self.task.pk}/overview/").json()
        self.assertEqual((data["can_edit"], data["can_delete"]), (True, True))


class LegacyTaskSubObjectTests(LegacyFixture):
    def test_checklist_requires_edit_right_on_task(self):
        self.web(self.peer).post("/task-checklists/create/", {"task": self.task.pk, "title": "pirate", "position": 0})
        self.assertFalse(dm.TaskChecklist.objects.filter(title="pirate").exists())
        self.web(self.dev).post("/task-checklists/create/", {"task": self.task.pk, "title": "Recette", "position": 0})
        checklist = dm.TaskChecklist.objects.get(title="Recette")
        self.assertEqual(self.web(self.peer).post(f"/task-checklists/{checklist.pk}/delete/").status_code, 403)
        self.assertTrue(dm.TaskChecklist.objects.filter(pk=checklist.pk).exists())

    def test_assignment_requires_reassign_right_and_forces_actor(self):
        dm.ProjectMember.objects.create(project=self.project, user=self.peer)  # règle métier existante
        self.web(self.peer).post("/task-assignments/create/", {
            "task": self.task.pk, "user": self.peer.pk, "allocation_percent": 100, "is_active": "on"})
        self.assertFalse(dm.TaskAssignment.objects.filter(task=self.task, user=self.peer).exists())
        self.web(self.lead).post("/task-assignments/create/", {
            "task": self.task.pk, "user": self.peer.pk, "assigned_by": self.owner.pk,
            "allocation_percent": 50, "is_active": "on"})
        assignment = dm.TaskAssignment.objects.get(task=self.task, user=self.peer)
        self.assertEqual(assignment.assigned_by_id, self.lead.pk)

    def test_comment_author_is_forced_and_protected(self):
        self.web(self.peer).post("/task-comments/create/", {"task": self.task.pk, "author": self.owner.pk, "body": "Bonjour"})
        comment = dm.TaskComment.objects.get(body="Bonjour")
        self.assertEqual(comment.author_id, self.peer.pk)
        self.assertEqual(self.web(self.dev).get(f"/task-comments/{comment.pk}/update/").status_code, 403)
        self.assertEqual(self.web(self.dev).post(f"/task-comments/{comment.pk}/delete/").status_code, 403)
        self.assertEqual(self.web(self.bob).get(f"/task-comments/{comment.pk}/update/").status_code, 404)
        self.assertEqual(self.web(self.peer).get(f"/task-comments/{comment.pk}/update/").status_code, 200)
        # Modération : chef de projet.
        self.web(self.pm).post(f"/task-comments/{comment.pk}/delete/")
        self.assertFalse(dm.TaskComment.objects.filter(pk=comment.pk).exists())


class LegacyNotificationTests(LegacyFixture):
    def setUp(self):
        super().setUp()
        mk = lambda user, title: dm.Notification.objects.create(  # noqa: E731
            recipient=user, workspace=self.ws, notification_type="SYSTEM", title=title)
        self.mine = mk(self.dev, "Pour dev")
        self.theirs = mk(self.peer, "Pour peer")

    def form(self, notification, **changes):
        data = {"recipient": notification.recipient_id, "workspace": notification.workspace_id,
                "notification_type": "SYSTEM", "title": notification.title, "body": "", "url": "", "metadata": "{}"}
        data.update(changes)
        return data

    def test_other_users_notifications_are_unreachable(self):
        dev = self.web(self.dev)
        self.assertEqual(dev.get(f"/notifications/{self.theirs.pk}/update/").status_code, 404)
        self.assertEqual(dev.post(f"/notifications/{self.theirs.pk}/update/", self.form(self.theirs, title="x")).status_code, 404)
        self.assertEqual(dev.post(f"/notifications/{self.theirs.pk}/delete/").status_code, 404)
        self.assertEqual(dev.post(f"/notifications/{self.theirs.pk}/mark-read/").status_code, 404)
        self.assertEqual(self.web(self.bob).post(f"/notifications/{self.mine.pk}/delete/").status_code, 404)
        self.theirs.refresh_from_db()
        self.assertEqual((self.theirs.title, self.theirs.is_read), ("Pour peer", False))

    def test_recipient_cannot_reassign_own_notification(self):
        self.web(self.dev).post(f"/notifications/{self.mine.pk}/update/",
                                self.form(self.mine, recipient=self.peer.pk, title="Lu", is_read="on"))
        self.mine.refresh_from_db()
        self.assertEqual((self.mine.recipient_id, self.mine.title), (self.dev.pk, "Lu"))
        self.web(self.dev).post(f"/notifications/{self.mine.pk}/delete/")
        self.assertFalse(dm.Notification.objects.filter(pk=self.mine.pk).exists())

    def test_manual_creation_reserved_to_workspace_admins(self):
        payload = self.form(self.mine, recipient=self.peer.pk, title="Faux message système")
        self.assertEqual(self.web(self.dev).post("/notifications/create/", payload).status_code, 403)
        self.assertFalse(dm.Notification.objects.filter(title="Faux message système").exists())
        self.web(self.owner).post("/notifications/create/", dict(payload, url="javascript:alert(1)"))
        self.assertFalse(dm.Notification.objects.filter(title="Faux message système").exists())
        self.web(self.owner).post("/notifications/create/", dict(payload, url="/tasks/"))
        self.assertTrue(dm.Notification.objects.filter(title="Faux message système", recipient=self.peer).exists())
