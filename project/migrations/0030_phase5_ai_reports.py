"""
Phase 5 — PR22 : Rapports projet IA hebdomadaires.

Migration ADDITIVE :
  * CreateModel ProjectAIReport
  * 2 index (project + period, project + status)
  * 1 UniqueConstraint anti-doublon (project, period, period_start)

ROLLBACK : ``migrate project 0029`` supprime la table. Aucune perte de
donnée existante.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0029_phase5_smart_notifications"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectAIReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("period", models.CharField(
                    choices=[
                        ("WEEKLY", "Hebdomadaire"),
                        ("MONTHLY", "Mensuel"),
                        ("AD_HOC", "À la demande"),
                    ],
                    default="WEEKLY", max_length=10,
                )),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("title", models.CharField(max_length=200)),
                ("status", models.CharField(
                    choices=[
                        ("PENDING", "En attente"),
                        ("GENERATING", "Génération en cours"),
                        ("READY", "Prêt"),
                        ("FAILED", "Échec"),
                    ],
                    db_index=True, default="PENDING", max_length=15,
                )),
                ("content_markdown", models.TextField(
                    blank=True,
                    help_text="Contenu structuré en Markdown.",
                )),
                ("summary", models.TextField(
                    blank=True,
                    help_text="Résumé exécutif (1-2 phrases) extrait du rapport.",
                )),
                ("payload", models.JSONField(
                    blank=True, default=dict,
                    help_text="Données structurées qui ont servi à générer le rapport.",
                )),
                ("used_provider", models.CharField(default="heuristic", max_length=30)),
                ("used_model", models.CharField(blank=True, max_length=80)),
                ("tokens_used", models.PositiveIntegerField(default=0)),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                ("failure_reason", models.TextField(blank=True)),
                ("generated_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="generated_ai_reports",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_reports",
                    to="project.project",
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_reports",
                    to="project.workspace",
                )),
            ],
            options={
                "ordering": ["-period_end", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["project", "period", "period_start"],
                        name="uniq_ai_report_period",
                    ),
                ],
            },
        ),
        migrations.AddIndex(
            model_name="projectaireport",
            index=models.Index(
                fields=["project", "-period_end"],
                name="ai_report_proj_period_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="projectaireport",
            index=models.Index(
                fields=["project", "status"],
                name="ai_report_proj_status_idx",
            ),
        ),
    ]
