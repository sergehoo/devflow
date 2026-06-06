"""
PR-MEET-AGENDA-LIVE : table MeetingAgendaItem (ordre du jour structuré).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0040_meetingparticipation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MeetingAgendaItem",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("duration_minutes", models.PositiveIntegerField(
                    default=5,
                    help_text="Durée estimée allouée à ce point (min).",
                )),
                ("position", models.PositiveIntegerField(default=0, db_index=True)),
                ("status", models.CharField(
                    choices=[
                        ("PENDING", "À traiter"),
                        ("IN_PROGRESS", "En cours"),
                        ("DONE", "Traité"),
                        ("POSTPONED", "Reporté"),
                        ("SKIPPED", "Passé"),
                    ],
                    default="PENDING", db_index=True, max_length=15,
                )),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(
                    blank=True,
                    help_text="Notes prises pendant ce point.",
                )),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_agenda_items",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("meeting", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="agenda_items",
                    to="project.projectmeeting",
                )),
                ("owner", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="owned_agenda_items",
                    to=settings.AUTH_USER_MODEL,
                    help_text="Personne qui présente / défend ce point",
                )),
            ],
            options={
                "ordering": ["position", "id"],
                "verbose_name": "Point d'ordre du jour",
                "verbose_name_plural": "Points d'ordre du jour",
            },
        ),
        migrations.AddIndex(
            model_name="meetingagendaitem",
            index=models.Index(
                fields=["meeting", "position"],
                name="proj_agenda_meet_pos_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="meetingagendaitem",
            index=models.Index(
                fields=["meeting", "status"],
                name="proj_agenda_meet_status_idx",
            ),
        ),
    ]
