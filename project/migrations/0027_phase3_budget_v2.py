"""
Phase 3 — PR14 : Budget V2.

Migration ENTIÈREMENT ADDITIVE :
  * CreateModel ProjectBudgetSnapshot — snapshots de budget (baseline/forecast)
  * CreateModel ProjectBudgetForecastRun — persistance runs IA pour mesure précision
  * AddField BillingRate.project — TJM négocié projet-spécifique
  * AddField Project.computed_eac — Estimate at Completion stocké
  * AddField Project.computed_cost_variance — Variance baseline/forecast stocké
  * AddField Project.eac_computed_at — horodatage du dernier calcul
  * AddIndex BillingRate (user, project, valid_from)

Aucune RemoveField, aucun renommage, aucun NOT NULL ajouté sur table
existante. Tous les nouveaux champs sont nullable ou ont un default
constant (Decimal("0")) → "fast default" Postgres 11+, pas de réécriture
de table.

ROLLBACK : ``migrate project 0026`` supprime les 2 tables + 4 colonnes
sans toucher aux données existantes.
"""

from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0026_phase2_multimode"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── 1) BillingRate.project ──────────────────────────────────────
        migrations.AddField(
            model_name="billingrate",
            name="project",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="billing_rates",
                to="project.project",
                help_text="Si renseigné, ce tarif ne s'applique qu'à ce projet.",
            ),
        ),
        migrations.AddIndex(
            model_name="billingrate",
            index=models.Index(
                fields=["user", "project", "-valid_from"],
                name="billing_user_proj_idx",
            ),
        ),

        # ─── 2) Project.computed_eac + variance + eac_computed_at ────────
        migrations.AddField(
            model_name="project",
            name="computed_eac",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0"), max_digits=14,
                help_text="Estimate at Completion : coût total prévu à la fin du projet.",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="computed_cost_variance",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0"), max_digits=14,
                help_text="Écart entre baseline et forecast (positif = dépassement).",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="eac_computed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),

        # ─── 3) ProjectBudgetSnapshot ────────────────────────────────────
        migrations.CreateModel(
            name="ProjectBudgetSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(max_length=120)),
                ("kind", models.CharField(
                    choices=[
                        ("BASELINE", "Baseline (référence)"),
                        ("FORECAST", "Forecast (projection)"),
                        ("MANUAL", "Snapshot manuel"),
                        ("AUTO", "Snapshot automatique"),
                    ],
                    db_index=True, default="MANUAL", max_length=20,
                )),
                ("snapshot_date", models.DateField(default=django.utils.timezone.localdate)),
                ("payload", models.JSONField(default=dict)),
                ("notes", models.TextField(blank=True)),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_budget_snapshots",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="budget_snapshots",
                    to="project.project",
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="budget_snapshots",
                    to="project.workspace",
                )),
            ],
            options={"ordering": ["-snapshot_date", "-id"]},
        ),
        migrations.AddIndex(
            model_name="projectbudgetsnapshot",
            index=models.Index(fields=["project", "-snapshot_date"],
                                name="snap_proj_date_idx"),
        ),
        migrations.AddIndex(
            model_name="projectbudgetsnapshot",
            index=models.Index(fields=["project", "kind"],
                                name="snap_proj_kind_idx"),
        ),

        # ─── 4) ProjectBudgetForecastRun ─────────────────────────────────
        migrations.CreateModel(
            name="ProjectBudgetForecastRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("horizon_end", models.DateField()),
                ("base_cost", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
                ("optimistic_cost", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
                ("pessimistic_cost", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
                ("expected_margin", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
                ("expected_margin_percent", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=7)),
                ("overrun_risk_percent", models.PositiveSmallIntegerField(default=0)),
                ("confidence", models.CharField(default="medium", max_length=10,
                                                help_text="low / medium / high")),
                ("used_provider", models.CharField(default="heuristic", max_length=30)),
                ("used_model", models.CharField(blank=True, max_length=80)),
                ("tokens_used", models.PositiveIntegerField(default=0)),
                ("ai_summary", models.TextField(blank=True)),
                ("payload", models.JSONField(default=dict)),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="budget_forecast_runs",
                    to="project.project",
                )),
                ("triggered_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="triggered_forecast_runs",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="budget_forecast_runs",
                    to="project.workspace",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="projectbudgetforecastrun",
            index=models.Index(fields=["project", "-created_at"],
                                name="forecast_proj_date_idx"),
        ),
    ]
