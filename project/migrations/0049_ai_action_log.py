"""PR16-METHODO : AIActionLog — audit des actions IA."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0048_artifacts_and_templates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIActionLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tool_name", models.CharField(max_length=80, db_index=True)),
                ("arguments", models.JSONField(default=dict, blank=True)),
                ("user_message", models.TextField(blank=True)),
                ("status", models.CharField(
                    max_length=15, default="PENDING", db_index=True,
                    choices=[
                        ("PENDING", "En cours"),
                        ("SUCCESS", "Succès"),
                        ("FAILED", "Échec"),
                        ("DENIED", "Refusé (permissions)"),
                        ("UNDONE", "Annulé par user"),
                    ],
                )),
                ("result", models.JSONField(default=dict, blank=True)),
                ("error_message", models.TextField(blank=True)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("affected_object_type", models.CharField(blank=True, max_length=50)),
                ("affected_object_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("is_reversible", models.BooleanField(default=False)),
                ("undone_at", models.DateTimeField(blank=True, null=True)),
                ("project", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="ai_action_logs", to="project.project",
                )),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="ai_actions", to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_action_logs", to="project.workspace",
                )),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Action IA (audit)",
                "verbose_name_plural": "Actions IA (audit)",
            },
        ),
        migrations.AddIndex(
            model_name="aiactionlog",
            index=models.Index(fields=["workspace", "-created_at"],
                               name="proj_aial_ws_ca_idx"),
        ),
        migrations.AddIndex(
            model_name="aiactionlog",
            index=models.Index(fields=["project", "-created_at"],
                               name="proj_aial_proj_ca_idx"),
        ),
        migrations.AddIndex(
            model_name="aiactionlog",
            index=models.Index(fields=["user", "-created_at"],
                               name="proj_aial_usr_ca_idx"),
        ),
        migrations.AddIndex(
            model_name="aiactionlog",
            index=models.Index(fields=["tool_name", "status"],
                               name="proj_aial_tool_st_idx"),
        ),
    ]
