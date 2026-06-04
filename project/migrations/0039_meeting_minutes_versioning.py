"""
PR-MEET-7 : versioning des comptes-rendus + nouveaux kinds d'extraction
IA (mentions/suggestions projets/sprints/milestones).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0038_meeting_decision_followup_voiceprint"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Étend les choices de RecordingAIExtraction (PR-MEET-6)
        migrations.AlterField(
            model_name="recordingaiextraction",
            name="kind",
            field=models.CharField(
                choices=[
                    ("decision", "Décision"),
                    ("action", "Action"),
                    ("risk", "Risque"),
                    ("note", "Note"),
                    ("project_suggestion", "Suggestion : nouveau projet"),
                    ("sprint_suggestion", "Suggestion : nouveau sprint"),
                    ("milestone_suggestion", "Suggestion : nouveau jalon"),
                    ("project_mention", "Projet mentionné"),
                    ("sprint_mention", "Sprint mentionné"),
                    ("milestone_mention", "Jalon mentionné"),
                ],
                max_length=25,
            ),
        ),

        # Nouveau modèle MeetingMinutesVersion (PR-MEET-7)
        migrations.CreateModel(
            name="MeetingMinutesVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("version_number", models.PositiveIntegerField(default=1)),
                ("content_markdown", models.TextField(blank=True)),
                ("is_current", models.BooleanField(default=False)),
                ("source", models.CharField(default="manual", max_length=20)),
                ("meeting", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="minutes_versions",
                    to="project.projectmeeting",
                )),
                ("recording", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="minutes_versions",
                    to="project.meetingrecording",
                )),
                ("saved_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="saved_minutes_versions",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="meetingminutesversion",
            index=models.Index(
                fields=["meeting", "-version_number"],
                name="minutes_ver_meet_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="meetingminutesversion",
            constraint=models.UniqueConstraint(
                fields=("meeting", "version_number"),
                name="uniq_meeting_minutes_version",
            ),
        ),
    ]
