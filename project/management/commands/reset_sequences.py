"""
Recale les compteurs d'identifiants PostgreSQL sur les données existantes.

Après une restauration ou une copie de données avec leurs identifiants, un compteur
resté en arrière fait échouer toute création dans la table concernée :
« duplicate key value violates unique constraint "…_pkey" — Key (id)=(10) already exists ».
La commande repère les tables touchées et ne recale que celles-ci, sur leur plus grand
identifiant (un compteur déjà en avance n'est jamais modifié). Sans effet hors PostgreSQL.

    python manage.py reset_sequences --check       # diagnostic seul, aucune écriture
    python manage.py reset_sequences               # toutes les applications
    python manage.py reset_sequences project auth  # applications choisies
"""

from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, router, transaction

AUTO_FIELDS = {"AutoField", "BigAutoField", "SmallAutoField"}


def _tables(app_labels, using):
    """(table, colonne clé) des modèles à clé auto-incrémentée, tables M2M comprises."""
    seen = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if app_labels and meta.app_label not in app_labels:
            continue
        if not meta.managed or meta.proxy or meta.pk is None or meta.pk.get_internal_type() not in AUTO_FIELDS:
            continue
        if not router.allow_migrate_model(using, model):
            continue
        key = (meta.db_table, meta.pk.column)
        if key not in seen:
            seen.add(key)
            yield key


def lagging_sequences(app_labels=(), using="default") -> list[dict]:
    """Tables dont le prochain identifiant attribué existe déjà (compteur en retard)."""
    connection = connections[using]
    if connection.vendor != "postgresql":
        return []
    quote = connection.ops.quote_name
    existing = set(connection.introspection.table_names())
    found = []
    with connection.cursor() as cursor:
        for table, column in _tables(app_labels, using):
            if table not in existing:
                continue
            cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", [quote(table), column])
            sequence = cursor.fetchone()[0]
            if not sequence:
                continue
            cursor.execute(f"SELECT last_value, is_called FROM {sequence}")
            last_value, is_called = cursor.fetchone()
            cursor.execute(f"SELECT MAX({quote(column)}) FROM {quote(table)}")
            highest = cursor.fetchone()[0]
            next_value = last_value + 1 if is_called else last_value
            if highest is not None and next_value <= highest:
                found.append({"table": table, "sequence": sequence, "next": next_value, "max": highest})
    return found


class Command(BaseCommand):
    help = "Recale les compteurs d'identifiants PostgreSQL restés en retard (erreurs « duplicate key … _pkey »)."

    def add_arguments(self, parser):
        parser.add_argument("app_labels", nargs="*", help="Applications à traiter (défaut : toutes).")
        parser.add_argument("--check", action="store_true", help="Diagnostic seul, aucune écriture.")
        parser.add_argument("--database", default="default", help="Base de données (défaut : default).")

    def handle(self, *args, app_labels=(), check=False, database="default", **options):
        app_labels = tuple(app_labels or ())
        for label in app_labels:
            try:
                apps.get_app_config(label)
            except LookupError as exc:
                raise CommandError(f"Application inconnue : {label}") from exc
        connection = connections[database]
        if connection.vendor != "postgresql":
            self.stdout.write(f"Base {connection.vendor} : pas de compteur PostgreSQL à recaler.")
            return
        with transaction.atomic(using=database):
            lagging = lagging_sequences(app_labels, database)
            if not lagging:
                self.stdout.write(self.style.SUCCESS("Tous les compteurs d'identifiants sont à jour."))
                return
            for item in lagging:
                self.stdout.write(f"- {item['table']} : prochain identifiant {item['next']}, "
                                  f"identifiant le plus élevé {item['max']}")
            if check:
                self.stdout.write(self.style.WARNING(
                    f"{len(lagging)} table(s) en retard. Relancez sans --check pour les recaler."))
                return
            with connection.cursor() as cursor:
                for item in lagging:
                    # GREATEST : une création concurrente ayant déjà avancé le compteur n'est pas annulée.
                    cursor.execute(
                        f"SELECT setval(%s, GREATEST(%s, (SELECT last_value FROM {item['sequence']})), true)",
                        [item["sequence"], item["max"]],
                    )
        self.stdout.write(self.style.SUCCESS(f"{len(lagging)} compteur(s) recalé(s)."))
