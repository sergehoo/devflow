"""
PR1-METHODO : Moteur multi-méthodologies data-driven.

Crée les 6 modèles core :
  * Methodology
  * MethodologyStatus
  * MethodologyRole
  * MethodologyCeremony
  * MethodologyKPI
  * MethodologyArtifact

Migration purement additive — aucun champ existant modifié,
aucune perte de données.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0042_recording_ai_extraction_tasks"),
    ]

    operations = [
        # ─── Methodology ───────────────────────────────────────────────
        migrations.CreateModel(
            name="Methodology",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50, unique=True,
                                          help_text="Identifiant stable (ex : 'scrum', 'kanban', 'waterfall').")),
                ("name", models.CharField(max_length=100)),
                ("family", models.CharField(
                    max_length=20,
                    choices=[
                        ("agile", "Agile / Itératif"),
                        ("sequential", "Séquentiel / Linéaire"),
                        ("hybrid", "Hybride"),
                        ("lean", "Lean / Flow-based"),
                        ("formal", "Formel / Gouvernance"),
                        ("custom", "Personnalisé"),
                    ],
                    default="agile", db_index=True,
                )),
                ("description", models.TextField(blank=True)),
                ("icon", models.CharField(max_length=50, blank=True)),
                ("accent_color", models.CharField(max_length=7, blank=True)),
                ("is_system", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("config", models.JSONField(default=dict, blank=True)),
                ("workspace", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="methodologies", to="project.workspace",
                )),
            ],
            options={
                "ordering": ["family", "name"],
                "verbose_name": "Méthodologie",
                "verbose_name_plural": "Méthodologies",
            },
        ),
        migrations.AddConstraint(
            model_name="methodology",
            constraint=models.UniqueConstraint(
                fields=("workspace", "name"),
                name="uniq_methodology_per_workspace_name",
            ),
        ),
        migrations.AddIndex(
            model_name="methodology",
            index=models.Index(fields=["workspace", "is_active"],
                               name="proj_method_ws_active_idx"),
        ),
        migrations.AddIndex(
            model_name="methodology",
            index=models.Index(fields=["family", "is_active"],
                               name="proj_method_fam_active_idx"),
        ),

        # ─── MethodologyStatus ─────────────────────────────────────────
        migrations.CreateModel(
            name="MethodologyStatus",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50)),
                ("name", models.CharField(max_length=80)),
                ("category", models.CharField(
                    max_length=20, db_index=True,
                    choices=[
                        ("todo", "À faire"),
                        ("wip", "En cours"),
                        ("review", "Revue"),
                        ("done", "Terminé"),
                        ("blocked", "Bloqué"),
                        ("cancelled", "Annulé"),
                    ],
                )),
                ("color", models.CharField(max_length=7, blank=True)),
                ("position", models.PositiveIntegerField(default=0, db_index=True)),
                ("is_initial", models.BooleanField(default=False)),
                ("is_final", models.BooleanField(default=False)),
                ("wip_limit", models.PositiveIntegerField(blank=True, null=True)),
                ("methodology", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="statuses", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["methodology", "position", "name"],
                "verbose_name": "Statut méthodologie",
                "verbose_name_plural": "Statuts méthodologie",
            },
        ),
        migrations.AddConstraint(
            model_name="methodologystatus",
            constraint=models.UniqueConstraint(
                fields=("methodology", "code"),
                name="uniq_status_per_methodology",
            ),
        ),
        migrations.AddIndex(
            model_name="methodologystatus",
            index=models.Index(fields=["methodology", "position"],
                               name="proj_status_meth_pos_idx"),
        ),
        migrations.AddIndex(
            model_name="methodologystatus",
            index=models.Index(fields=["methodology", "category"],
                               name="proj_status_meth_cat_idx"),
        ),

        # ─── MethodologyRole ────────────────────────────────────────────
        migrations.CreateModel(
            name="MethodologyRole",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50)),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True)),
                ("is_required", models.BooleanField(default=False)),
                ("max_holders", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("suggested_rbac_role", models.CharField(max_length=50, blank=True)),
                ("methodology", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="roles", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["methodology", "name"],
                "verbose_name": "Rôle méthodologie",
                "verbose_name_plural": "Rôles méthodologie",
            },
        ),
        migrations.AddConstraint(
            model_name="methodologyrole",
            constraint=models.UniqueConstraint(
                fields=("methodology", "code"),
                name="uniq_role_per_methodology",
            ),
        ),

        # ─── MethodologyCeremony ────────────────────────────────────────
        migrations.CreateModel(
            name="MethodologyCeremony",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50)),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True)),
                ("cadence", models.CharField(
                    max_length=20, default="per_sprint",
                    choices=[
                        ("once", "Unique (au démarrage)"),
                        ("daily", "Quotidienne"),
                        ("weekly", "Hebdomadaire"),
                        ("biweekly", "Bi-hebdo"),
                        ("monthly", "Mensuelle"),
                        ("per_sprint", "Par sprint"),
                        ("per_phase", "Par phase"),
                        ("per_milestone", "Par jalon"),
                        ("on_demand", "À la demande"),
                    ],
                )),
                ("default_duration_min", models.PositiveIntegerField(default=30)),
                ("template_agenda", models.TextField(blank=True)),
                ("required_role_codes", models.JSONField(default=list, blank=True)),
                ("position", models.PositiveIntegerField(default=0, db_index=True)),
                ("methodology", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ceremonies", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["methodology", "position", "name"],
                "verbose_name": "Cérémonie méthodologie",
                "verbose_name_plural": "Cérémonies méthodologie",
            },
        ),
        migrations.AddConstraint(
            model_name="methodologyceremony",
            constraint=models.UniqueConstraint(
                fields=("methodology", "code"),
                name="uniq_ceremony_per_methodology",
            ),
        ),

        # ─── MethodologyKPI ─────────────────────────────────────────────
        migrations.CreateModel(
            name="MethodologyKPI",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50)),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True)),
                ("unit", models.CharField(max_length=20, blank=True)),
                ("chart_type", models.CharField(
                    max_length=20, default="number",
                    choices=[
                        ("number", "Nombre simple"),
                        ("gauge", "Jauge"),
                        ("bar", "Bar chart"),
                        ("line", "Line chart"),
                        ("stacked_bar", "Bar empilé"),
                        ("pie", "Pie chart"),
                        ("burndown", "Burndown"),
                        ("burnup", "Burnup"),
                        ("cumulative_flow", "Cumulative Flow Diagram"),
                        ("gantt", "Gantt"),
                        ("sparkline", "Sparkline"),
                    ],
                )),
                ("compute_strategy", models.CharField(max_length=80)),
                ("target_value", models.FloatField(blank=True, null=True)),
                ("is_pinned", models.BooleanField(default=False)),
                ("position", models.PositiveIntegerField(default=0, db_index=True)),
                ("methodology", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="kpis", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["methodology", "-is_pinned", "position"],
                "verbose_name": "KPI méthodologie",
                "verbose_name_plural": "KPIs méthodologie",
            },
        ),
        migrations.AddConstraint(
            model_name="methodologykpi",
            constraint=models.UniqueConstraint(
                fields=("methodology", "code"),
                name="uniq_kpi_per_methodology",
            ),
        ),

        # ─── MethodologyArtifact ───────────────────────────────────────
        migrations.CreateModel(
            name="MethodologyArtifact",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50)),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True)),
                ("template_kind", models.CharField(
                    max_length=20, default="markdown",
                    choices=[
                        ("markdown", "Markdown"),
                        ("docx", "Word (.docx)"),
                        ("pdf", "PDF"),
                        ("json", "JSON structuré"),
                        ("csv", "CSV"),
                    ],
                )),
                ("ai_prompt_key", models.CharField(max_length=80)),
                ("is_recommended", models.BooleanField(default=False)),
                ("position", models.PositiveIntegerField(default=0, db_index=True)),
                ("methodology", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="artifacts", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["methodology", "-is_recommended", "position"],
                "verbose_name": "Artefact méthodologie",
                "verbose_name_plural": "Artefacts méthodologie",
            },
        ),
        migrations.AddConstraint(
            model_name="methodologyartifact",
            constraint=models.UniqueConstraint(
                fields=("methodology", "code"),
                name="uniq_artifact_per_methodology",
            ),
        ),
    ]
