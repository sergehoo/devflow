"""
PR-MEET-5 : Registre transversal des décisions, suivi post-réunion,
mémoire vocale par workspace.

Migration ADDITIVE. 3 nouvelles tables, aucune modification existante.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0037_meeting_recordings"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── MeetingDecision ─────────────────────────────────────────
        migrations.CreateModel(
            name="MeetingDecision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("title", models.CharField(max_length=250)),
                ("description", models.TextField(blank=True)),
                ("category", models.CharField(
                    choices=[
                        ("STRATEGIC", "Stratégique"),
                        ("BUDGETARY", "Budgétaire"),
                        ("OPERATIONAL", "Opérationnelle"),
                        ("TECHNICAL", "Technique"),
                        ("HR", "RH"),
                        ("OTHER", "Autre"),
                    ],
                    db_index=True, default="OPERATIONAL", max_length=15,
                )),
                ("status", models.CharField(
                    choices=[
                        ("VALIDATED", "Validée"),
                        ("PENDING", "En attente"),
                        ("EXECUTED", "Exécutée"),
                        ("REVERSED", "Annulée"),
                    ],
                    db_index=True, default="VALIDATED", max_length=15,
                )),
                ("decided_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("executed_at", models.DateTimeField(blank=True, null=True)),
                ("impact_summary", models.TextField(blank=True)),
                ("cost_impact", models.DecimalField(
                    blank=True, decimal_places=2, max_digits=14, null=True,
                )),
                ("decided_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="decisions_made", to=settings.AUTH_USER_MODEL,
                )),
                ("executed_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="decisions_executed", to=settings.AUTH_USER_MODEL,
                )),
                ("meeting", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="structured_decisions",
                    to="project.projectmeeting",
                )),
                ("projects", models.ManyToManyField(
                    blank=True, related_name="meeting_decisions",
                    to="project.project",
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="meeting_decisions", to="project.workspace",
                )),
            ],
            options={"ordering": ["-decided_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="meetingdecision",
            index=models.Index(fields=["workspace", "status"], name="decision_ws_status_idx"),
        ),
        migrations.AddIndex(
            model_name="meetingdecision",
            index=models.Index(fields=["workspace", "-decided_at"], name="decision_ws_date_idx"),
        ),

        # ─── MeetingFollowUp ─────────────────────────────────────────
        migrations.CreateModel(
            name="MeetingFollowUp",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("kind", models.CharField(
                    choices=[
                        ("reminder_before", "Rappel avant"),
                        ("reminder_after", "Relance après"),
                        ("minutes_sent", "Compte-rendu envoyé"),
                        ("ack", "Accusé de réception"),
                        ("note", "Note libre"),
                    ],
                    db_index=True, max_length=20,
                )),
                ("sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("target_email", models.EmailField(blank=True, max_length=254)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("note", models.TextField(blank=True)),
                ("meeting", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="follow_ups", to="project.projectmeeting",
                )),
                ("sent_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="sent_follow_ups", to=settings.AUTH_USER_MODEL,
                )),
                ("target_user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="received_follow_ups", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-sent_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="meetingfollowup",
            index=models.Index(fields=["meeting", "kind"], name="meet_followup_kind_idx"),
        ),

        # ─── WorkspaceVoicePrint ─────────────────────────────────────
        migrations.CreateModel(
            name="WorkspaceVoicePrint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("mappings_count", models.PositiveIntegerField(default=0)),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("embedding", models.JSONField(blank=True, default=dict)),
                ("last_detected_speaker", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="voice_prints_anchored",
                    to="project.detectedspeaker",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="voice_prints", to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="voice_prints", to="project.workspace",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="workspacevoiceprint",
            constraint=models.UniqueConstraint(
                fields=("workspace", "user"),
                name="uniq_voiceprint_per_user_workspace",
            ),
        ),
        migrations.AddIndex(
            model_name="workspacevoiceprint",
            index=models.Index(
                fields=["workspace", "-last_seen_at"],
                name="voiceprint_ws_seen_idx",
            ),
        ),
    ]
