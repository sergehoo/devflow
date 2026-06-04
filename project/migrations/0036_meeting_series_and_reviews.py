"""
PR-MEET-1 : module Réunions cycliques + revue projet par projet.

Migration ENTIÈREMENT ADDITIVE :
  * AlterField ProjectMeeting.project → null=True, blank=True
    (les réunions de comité ne sont pas liées à 1 projet spécifique
    mais passent en revue plusieurs projets)
  * AddField ProjectMeeting.projects (M2M Project, blank)
  * AddField ProjectMeeting.series (FK MeetingSeries, SET_NULL, null)
  * CreateModel MeetingSeries (récurrence + valeurs par défaut)
  * CreateModel MeetingProjectReview (1 par couple meeting × project)

ROLLBACK : ``migrate project 0035`` supprime les nouvelles tables et
re-passe ProjectMeeting.project à NOT NULL. Si des réunions sans projet
ont été créées entretemps, le rollback va échouer — il faudra d'abord
leur assigner un project ou les supprimer.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0035_invoice_project_nullable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1) ProjectMeeting.project → nullable
        migrations.AlterField(
            model_name="projectmeeting",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="meetings",
                to="project.project",
                help_text=(
                    "Projet principal (optionnel). Pour une revue "
                    "multi-projets, utilisez plutôt 'projects'."
                ),
            ),
        ),

        # 2) MeetingSeries
        migrations.CreateModel(
            name="MeetingSeries",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("meeting_type", models.CharField(
                    choices=[
                        ("FRAMING", "Cadrage"),
                        ("FOLLOW_UP", "Suivi"),
                        ("SPRINT_REVIEW", "Sprint review"),
                        ("PROJECT_COMMITTEE", "Comité projet"),
                        ("STEERING_COMMITTEE", "Comité de pilotage"),
                        ("RETROSPECTIVE", "Rétrospective"),
                        ("OTHER", "Autre"),
                    ],
                    default="FOLLOW_UP",
                    max_length=25,
                )),
                ("recurrence", models.CharField(
                    choices=[
                        ("NONE", "Aucune (réunion unique)"),
                        ("DAILY", "Quotidienne (jours ouvrés)"),
                        ("WEEKLY", "Hebdomadaire"),
                        ("BIWEEKLY", "Bi-hebdomadaire"),
                        ("MONTHLY", "Mensuelle (jour du mois)"),
                    ],
                    default="WEEKLY",
                    max_length=15,
                )),
                ("weekday", models.PositiveSmallIntegerField(
                    blank=True, null=True,
                    help_text="Pour les récurrences hebdo/bi-hebdo : 0=lundi…6=dimanche.",
                )),
                ("month_day", models.PositiveSmallIntegerField(
                    blank=True, null=True,
                    help_text="Pour la récurrence mensuelle : 1-31, ou 0 = dernier jour.",
                )),
                ("time_local", models.TimeField(
                    help_text="Heure locale de l'occurrence (ex: 09:30).",
                )),
                ("duration_minutes", models.PositiveIntegerField(default=60)),
                ("location", models.CharField(blank=True, max_length=200)),
                ("meeting_link", models.URLField(blank=True)),
                ("start_date", models.DateField(
                    help_text="Date de la 1ère occurrence (ex: lundi prochain).",
                )),
                ("end_date", models.DateField(
                    blank=True, null=True,
                    help_text="Si renseignée, plus aucune occurrence après cette date.",
                )),
                ("is_active", models.BooleanField(default=True)),
                ("default_agenda", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_meeting_series",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("default_participants", models.ManyToManyField(
                    blank=True,
                    related_name="default_meeting_series",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("default_projects", models.ManyToManyField(
                    blank=True,
                    related_name="default_meeting_series",
                    to="project.project",
                )),
                ("organizer", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="organized_meeting_series",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="meeting_series",
                    to="project.workspace",
                )),
            ],
            options={
                "ordering": ["-is_active", "name"],
                "verbose_name": "Série de réunions",
                "verbose_name_plural": "Séries de réunions",
            },
        ),
        migrations.AddIndex(
            model_name="meetingseries",
            index=models.Index(
                fields=["workspace", "is_active"],
                name="meeting_ser_ws_active_idx",
            ),
        ),

        # 3) ProjectMeeting.projects (M2M) + .series (FK)
        migrations.AddField(
            model_name="projectmeeting",
            name="projects",
            field=models.ManyToManyField(
                blank=True,
                related_name="committee_meetings",
                to="project.project",
                help_text="Projets passés en revue dans cette réunion.",
            ),
        ),
        migrations.AddField(
            model_name="projectmeeting",
            name="series",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="occurrences",
                to="project.meetingseries",
            ),
        ),

        # 4) MeetingProjectReview
        migrations.CreateModel(
            name="MeetingProjectReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("status_snapshot", models.CharField(
                    choices=[
                        ("ON_TRACK", "Sur les rails"),
                        ("AT_RISK", "À risque"),
                        ("BLOCKED", "Bloqué"),
                        ("AHEAD", "En avance"),
                        ("COMPLETED", "Terminé"),
                        ("ON_HOLD", "En attente"),
                    ],
                    default="ON_TRACK",
                    max_length=15,
                )),
                ("progress_pct", models.PositiveSmallIntegerField(default=0)),
                ("achievements", models.TextField(blank=True)),
                ("blockers", models.TextField(blank=True)),
                ("decisions", models.TextField(blank=True)),
                ("actions_to_take", models.TextField(blank=True)),
                ("next_milestone", models.CharField(blank=True, max_length=200)),
                ("next_milestone_date", models.DateField(blank=True, null=True)),
                ("meeting", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="project_reviews",
                    to="project.projectmeeting",
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="meeting_reviews",
                    to="project.project",
                )),
                ("presented_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="presented_meeting_reviews",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["meeting", "position", "id"],
                "verbose_name": "Revue projet",
                "verbose_name_plural": "Revues projet",
            },
        ),
        migrations.AddConstraint(
            model_name="meetingprojectreview",
            constraint=models.UniqueConstraint(
                fields=("meeting", "project"),
                name="uniq_meeting_project_review",
            ),
        ),
        migrations.AddIndex(
            model_name="meetingprojectreview",
            index=models.Index(
                fields=["meeting", "position"],
                name="meet_review_pos_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="meetingprojectreview",
            index=models.Index(
                fields=["project", "-created_at"],
                name="meet_review_proj_idx",
            ),
        ),
    ]
