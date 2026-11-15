"""
Méthodologie des projets : codes historiques en minuscules (« agile ») ramenés au
choix valide (« AGILE »). Sans cela, le formulaire projet refusait tout
enregistrement (« Sélectionnez un choix valide. agile n'en fait pas partie »).
Seules les valeurs correspondant à un choix (casse ignorée) sont modifiées.
"""
from django.db import migrations

CHOICES = ("SCRUM", "KANBAN", "AGILE", "WATERFALL", "MILESTONE", "FIELD", "REAL_ESTATE", "ADMINISTRATIVE")


def normalize(apps, schema_editor):
    Project = apps.get_model("project", "Project")
    for code in CHOICES:
        Project.objects.filter(methodology__iexact=code).exclude(methodology=code).update(methodology=code)


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0058_sync_task_spent_hours"),
    ]

    operations = [
        migrations.RunPython(normalize, migrations.RunPython.noop),
    ]
