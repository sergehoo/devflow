# Migration : période de tâche (start_date), statut EXPIRED, traçabilité notif PM
# Generated manually on 2026-04-29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0020_workspace_letterhead'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='start_date',
            field=models.DateField(
                blank=True, null=True,
                help_text='Date à partir de laquelle la tâche est planifiée (borne gauche du calendrier).',
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='expired_at',
            field=models.DateField(
                blank=True, null=True,
                help_text='Date à laquelle la tâche a été marquée expirée non traitée.',
            ),
        ),
        migrations.AddField(
            model_name='task',
            name='pm_overdue_notified_at',
            field=models.DateTimeField(
                blank=True, null=True,
                help_text="Dernière fois que le PM a été notifié du dépassement d'échéance.",
            ),
        ),
        migrations.AlterField(
            model_name='task',
            name='status',
            field=models.CharField(
                choices=[
                    ('TODO', 'À faire'), ('IN_PROGRESS', 'En cours'),
                    ('REVIEW', 'Review'), ('DONE', 'Terminé'),
                    ('BLOCKED', 'Bloqué'), ('CANCELLED', 'Annulé'),
                    ('EXPIRED', 'Expirée non traitée'),
                ],
                default='TODO', max_length=20,
            ),
        ),
    ]
