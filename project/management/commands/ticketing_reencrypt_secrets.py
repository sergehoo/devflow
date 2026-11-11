"""
Rechiffre les secrets du ticketing avec la clé principale.

À lancer après avoir introduit ou fait tourner ``TICKETING_ENCRYPTION_KEY`` :
l'ancienne clé doit rester lisible (``TICKETING_ENCRYPTION_KEYS_OLD`` ou
``SECRET_KEY``). Idempotent ; ``--dry-run`` vérifie sans rien modifier. Aucune
valeur de secret n'est affichée.
"""

from django.core.management.base import BaseCommand, CommandError

from project import models as dm
from project.services import ticketing as svc

FIELDS = (
    (dm.ExternalApplication, ("secret_encrypted",)),
    (dm.TicketMailbox, ("imap_password_encrypted", "smtp_password_encrypted", "webhook_secret_encrypted")),
)


class Command(BaseCommand):
    help = "Rechiffre les secrets du ticketing (applications, boîtes e-mail) avec la clé principale."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Vérifie la lisibilité des secrets sans rien modifier.")

    def handle(self, *args, dry_run=False, **options):
        fernet = svc._fernet()
        done = unreadable = 0
        for model, fields in FIELDS:
            for obj in model.objects.only("pk", *fields).iterator():
                changed = {}
                for field in fields:
                    token = getattr(obj, field)
                    if not token:
                        continue
                    try:
                        plain = svc.decrypt_secret(token)
                    except svc.SecretError:
                        unreadable += 1
                        self.stderr.write(f"{model.__name__} #{obj.pk} · {field} : illisible avec les clés configurées")
                        continue
                    changed[field] = fernet.encrypt(plain.encode()).decode()
                if changed and not dry_run:
                    model.objects.filter(pk=obj.pk).update(**changed)
                done += len(changed)
        verb = "lisible(s)" if dry_run else "rechiffré(s)"
        self.stdout.write(f"{done} secret(s) {verb}, {unreadable} illisible(s).")
        if unreadable:
            raise CommandError("Secrets illisibles : restaurez l'ancienne clé dans TICKETING_ENCRYPTION_KEYS_OLD.")
