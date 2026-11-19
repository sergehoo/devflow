"""
Commande ``reset_sequences`` : compteurs d'identifiants PostgreSQL restés en retard
(génération des propositions IA en échec : « duplicate key … projectaiproposallog_pkey »).

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_reset_sequences

Les cas PostgreSQL ne s'exécutent que sur une base PostgreSQL (ignorés sur SQLite).
"""

from io import StringIO
from unittest import skipIf, skipUnless

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from project import models as dm
from project.management.commands.reset_sequences import lagging_sequences

User = get_user_model()
TABLE = dm.ProjectAIProposalLog._meta.db_table


def run(*args) -> str:
    out = StringIO()
    call_command("reset_sequences", *args, stdout=out)
    return out.getvalue()


class ResetSequencesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user("owner", "owner@a.test", "pw")
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=owner)
        project = dm.Project.objects.create(workspace=cls.ws, name="MyKaydan V2")
        cls.proposal = dm.ProjectAIProposal.objects.create(project=project, workspace=cls.ws)

    def restore_logs_with_ids(self, count=12):
        """Restauration avec identifiants : lignes insérées sans faire avancer le compteur."""
        dm.ProjectAIProposalLog.objects.bulk_create([
            dm.ProjectAIProposalLog(id=i, proposal=self.proposal, action="TRIGGERED") for i in range(1, count + 1)])
        if connection.vendor == "postgresql":  # compteur non transactionnel : on le remet au début
            with connection.cursor() as cursor:
                cursor.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), 1, false)", [TABLE])

    def test_production_container_realigns_sequences_before_serving(self):
        from pathlib import Path

        from django.conf import settings

        command = [line.strip() for line in (Path(settings.BASE_DIR) / "docker-compose.yml").read_text().splitlines()
                   if not line.lstrip().startswith("#")]
        start = command.index("python manage.py reset_sequences")
        self.assertTrue(command[start + 1].startswith("||"))  # un échec n'empêche pas le démarrage
        self.assertLess(start, next(i for i, line in enumerate(command) if line.startswith("exec gunicorn")))

    def test_unknown_application_is_rejected(self):
        with self.assertRaises(CommandError):
            run("inconnue")

    @skipIf(connection.vendor == "postgresql", "comportement hors PostgreSQL")
    def test_no_op_outside_postgresql(self):
        self.assertIn("pas de compteur PostgreSQL", run())
        self.assertEqual(lagging_sequences(), [])

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL requis")
    def test_lagging_sequence_is_reported_then_fixed(self):
        self.restore_logs_with_ids()
        with self.assertRaises(IntegrityError), transaction.atomic():
            dm.ProjectAIProposalLog.objects.create(proposal=self.proposal, action="TRIGGERED")
        self.assertEqual([row["table"] for row in lagging_sequences(["project"])], [TABLE])

        report = run("--check")
        self.assertIn(f"{TABLE} : prochain identifiant", report)
        self.assertIn("1 table(s) en retard", report)
        self.assertEqual([row["table"] for row in lagging_sequences()], [TABLE])  # --check n'écrit rien

        self.assertIn("1 compteur(s) recalé(s)", run("project"))
        log = dm.ProjectAIProposalLog.objects.create(proposal=self.proposal, action="TRIGGERED")
        self.assertEqual(log.pk, 13)
        self.assertEqual(lagging_sequences(), [])
        self.assertIn("à jour", run())

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL requis")
    def test_sequence_ahead_is_never_moved_back(self):
        self.restore_logs_with_ids(3)
        with connection.cursor() as cursor:
            cursor.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), 500, true)", [TABLE])
        self.assertEqual(lagging_sequences(), [])
        run()
        self.assertEqual(dm.ProjectAIProposalLog.objects.create(proposal=self.proposal, action="GENERATED").pk, 501)

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL requis")
    def test_only_the_requested_applications_are_fixed(self):
        self.restore_logs_with_ids()
        self.assertIn("à jour", run("auth"))  # la table du projet n'est pas touchée
        self.assertEqual([row["table"] for row in lagging_sequences()], [TABLE])
        self.assertIn("1 compteur(s) recalé(s)", run("project"))
