# Migration : multi-équipes contributrices sur Project (M2M en plus du FK team principal)
# Generated manually on 2026-04-29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0021_task_period_and_expired'),
    ]

    operations = [
        migrations.AlterField(
            model_name='project',
            name='team',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='projects',
                to='project.team',
                help_text='Équipe principale (référent). Pour plusieurs équipes, utilisez le champ Équipes contributrices.',
            ),
        ),
        migrations.AddField(
            model_name='project',
            name='teams',
            field=models.ManyToManyField(
                blank=True, related_name='contributing_projects',
                to='project.team',
                help_text='Toutes les équipes qui contribuent au projet (multi-sélection).',
            ),
        ),
    ]
