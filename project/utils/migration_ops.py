"""
Opérations de migration utilitaires.

Placé hors de ``project/migrations/`` : le loader Django importe chaque module
de ce package et exige une classe ``Migration``.
"""

from django.db import migrations


class SkipIfTableExists(migrations.SeparateDatabaseAndState):
    """
    Applique toujours ``operations`` à l'état des migrations, mais n'exécute
    leur SQL que si ``table`` n'existe pas encore en base.

    Sert aux deux migrations 0027 (``0027_phase3_budget_v2`` et
    ``0027_projectbudgetforecastrun_projectbudgetsnapshot_and_more``), deux
    branches sœurs qui produisent le même schéma : selon l'historique, une
    base a appliqué l'une, l'autre ou les deux. La première à s'exécuter crée
    les objets, la seconde ne fait plus que mettre à jour l'état.
    """

    def __init__(self, table, operations):
        self.table = table
        super().__init__(database_operations=operations, state_operations=operations)

    def deconstruct(self):
        return (
            self.__class__.__qualname__,
            [],
            {"table": self.table, "operations": self.state_operations},
        )

    def _table_exists(self, schema_editor):
        with schema_editor.connection.cursor() as cursor:
            return self.table in schema_editor.connection.introspection.table_names(cursor)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if self._table_exists(schema_editor):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if not self._table_exists(schema_editor):
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)

    def describe(self):
        return f"Opérations conditionnelles (ignorées en base si {self.table} existe)"
