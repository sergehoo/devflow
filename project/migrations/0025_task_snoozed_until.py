"""
Phase 1 — PR7 : ajout du champ Task.snoozed_until.

Migration purement ADDITIVE :
  * nouveau champ DateTimeField nullable + blank
  * default=None (NULL en base)
  * aucun impact sur les tâches existantes (toutes resteront snoozed_until=NULL)

Le champ alimente la nouvelle vue "Mes actions du jour" et les endpoints
quick-action :
    POST /api/v1/tasks/{id}/snooze/   body: {until: ISO datetime}

ROLLBACK : ``migrate project 0024`` supprime juste la colonne — pas de
perte de donnée métier (les éventuelles valeurs renseignées seront
recalculables côté UI).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0024_phase0_perf_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="snoozed_until",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Si défini, la tâche est masquée des dashboards "
                          "rapides jusqu'à cette date.",
            ),
        ),
    ]
