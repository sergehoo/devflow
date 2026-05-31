"""
Phase 4 — PR18-19-20 : IA V2.

Migration ENTIÈREMENT ADDITIVE :
  * CreateModel AIUsageQuota — quota mensuel par workspace (1-1)
  * CreateModel AIPromptTemplate — bibliothèque de prompts par workspace
  * Indexes pour le lookup rapide (workspace, intent, is_default)

Pas de RunPython initial : les quotas sont créés à la demande via le signal
``post_save Workspace`` branché dans ``project/signals.py`` (PR19) ou via
``AIQuotaService.get_or_create_quota(workspace)``.

ROLLBACK : ``migrate project 0027`` supprime les 2 tables. Aucune perte de
donnée existante.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0027_phase3_budget_v2"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AIUsageQuota",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("monthly_token_limit", models.PositiveIntegerField(
                    default=1000000,
                    help_text="Quota mensuel de tokens (0 = illimité).",
                )),
                ("monthly_tokens_used", models.PositiveIntegerField(default=0)),
                ("period_start", models.DateField(
                    default=django.utils.timezone.localdate,
                    help_text="Début du cycle mensuel courant.",
                )),
                ("last_call_at", models.DateTimeField(blank=True, null=True)),
                ("over_limit_notified_at", models.DateTimeField(blank=True, null=True)),
                ("workspace", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_quota",
                    to="project.workspace",
                )),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="AIPromptTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=120)),
                ("intent", models.CharField(
                    max_length=60,
                    help_text="Clé d'usage : project_summary, project_recommendations, "
                              "budget_forecast, risk_analysis, project_genesis…",
                )),
                ("template", models.TextField(
                    help_text="Prompt complet. Variables Jinja-like : {project_name}, "
                              "{description}, {team}, etc. — interpolées côté service.",
                )),
                ("is_default", models.BooleanField(
                    default=False,
                    help_text="Si vrai, ce template est utilisé en premier pour cet intent.",
                )),
                ("notes", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_ai_prompts",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_prompts",
                    to="project.workspace",
                )),
            ],
            options={
                "ordering": ["workspace", "intent", "name"],
                "unique_together": {("workspace", "intent", "name")},
            },
        ),
        migrations.AddIndex(
            model_name="aiprompttemplate",
            index=models.Index(
                fields=["workspace", "intent", "is_default"],
                name="prompt_ws_intent_idx",
            ),
        ),
    ]
