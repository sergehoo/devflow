"""
Données et manipulations des tests E2E Playwright — refusé hors ``ProjectFlow.settings.e2e``.

    manage.py e2e_fixtures seed --out <fichier.json> --webhook-url http://127.0.0.1:8099/hook
    manage.py e2e_fixtures breach --reference TCK-00002   # échéances SLA dans le passé + contrôle SLA

Les mots de passe et secrets sont générés à chaque exécution (valeurs de test locales)
et écrits dans le fichier JSON lu par les tests, jamais affichés.
"""

import json
import secrets
from datetime import timedelta
from pathlib import Path

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from project import models as dm
from project.services import ticketing as svc
from project.services import ticketing_email as mail


class Command(BaseCommand):
    help = "Jeu de données et horloge SLA des tests E2E (settings e2e uniquement)."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        seed = sub.add_parser("seed")
        seed.add_argument("--out", required=True)
        seed.add_argument("--webhook-url", required=True)
        breach = sub.add_parser("breach")
        breach.add_argument("--reference", required=True)

    def handle(self, *args, **options):
        if not getattr(settings, "E2E_MODE", False):
            raise CommandError("Réservé aux tests E2E (DJANGO_SETTINGS_MODULE=ProjectFlow.settings.e2e).")
        if options["action"] == "seed":
            self.seed(Path(options["out"]), options["webhook_url"])
        else:
            self.breach(options["reference"])

    def seed(self, out: Path, webhook_url: str):
        User = get_user_model()
        if User.objects.filter(username__endswith="_e2e").exists():
            raise CommandError("Base E2E déjà initialisée : supprimez frontend/e2e/.state avant de relancer.")
        users, passwords = {}, {}
        for key, first in (("owner", "Olivia"), ("pm", "Paul"), ("agent", "Ana"), ("bob", "Bob")):
            password = secrets.token_urlsafe(18)
            users[key] = User.objects.create_user(f"{key}_e2e", f"{key}@e2e.test", password, first_name=first, last_name="E2E")
            EmailAddress.objects.create(user=users[key], email=users[key].email, verified=True, primary=True)
            passwords[key] = password
        alpha = dm.Workspace.objects.create(name="Alpha E2E", owner=users["owner"])
        beta = dm.Workspace.objects.create(name="Beta E2E", owner=users["bob"])
        support = dm.Team.objects.create(workspace=alpha, name="Support N1", lead=users["pm"])
        for key, ws, team in (("owner", alpha, None), ("pm", alpha, None), ("agent", alpha, support), ("bob", beta, None)):
            dm.UserProfile.objects.update_or_create(user=users[key], defaults={"workspace": ws})
            dm.TeamMembership.objects.create(user=users[key], workspace=ws, team=team)
        dm.WorkspaceRoleAssignment.objects.create(user=users["pm"], workspace=alpha, role="PROJECT_MANAGER")
        project = dm.Project.objects.create(workspace=alpha, name="Portail E2E", owner=users["pm"])
        dm.ProjectMember.objects.get_or_create(project=project, user=users["agent"])
        policy = dm.TicketSLAPolicy.objects.create(
            workspace=alpha, name="SLA E2E", is_default=True, business_hours_only=False, business_days=[0, 1, 2, 3, 4, 5, 6],
            targets={p: {"first_response": 60, "resolution": 480} for p in ("P1", "P2", "P3", "P4")},
        )
        key_id, app_secret = svc.new_credentials()
        app = dm.ExternalApplication(workspace=alpha, name="Portail client E2E", code="portail-e2e", key_id=key_id, project=project,
                                     default_team=support, sla_policy=policy, webhook_url=webhook_url)
        svc.set_secret(app, app_secret)
        app.save()
        app.teams.add(support)
        mail_secret = secrets.token_urlsafe(24)
        box = dm.TicketMailbox(workspace=alpha, application=app, project=project, name="Support E2E", address="support@devflow.test",
                               inbound=dm.TicketMailbox.Inbound.WEBHOOK, inbound_key=mail.new_inbound_key())
        mail.set_secret(box, "webhook_secret", mail_secret)
        box.save()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "users": {k: {"email": u.email, "password": passwords[k], "id": u.pk} for k, u in users.items()},
            "workspaces": {"alpha": alpha.pk, "beta": beta.pk}, "team": support.pk, "project": project.pk,
            "app": {"id": app.pk, "key_id": key_id, "secret": app_secret},
            "mailbox": {"id": box.pk, "inbound_key": box.inbound_key, "secret": mail_secret, "address": box.address},
        }, indent=2))
        out.chmod(0o600)
        self.stdout.write("E2E : données créées.")

    def breach(self, reference: str):
        ticket = dm.Ticket.objects.filter(reference=reference).order_by("-pk").first()
        if ticket is None:
            raise CommandError(f"Ticket {reference} introuvable.")
        past = timezone.now() - timedelta(minutes=5)
        dm.Ticket.objects.filter(pk=ticket.pk).update(first_response_due=past, resolution_due=past)
        stats = svc.check_slas()
        self.stdout.write(json.dumps(stats))
