"""
Phase 2 — PR10 : modèles multi-modes projet.

Migration ENTIÈREMENT ADDITIVE :
  * AddField Project.methodology (default AGILE → tous les projets existants
    restent en AGILE, comportement strictement identique à avant)
  * CreateModel × 6 : ProjectPhase, ProjectViewPreference, FieldReport,
    FieldReportPhoto, RealEstateLot, AdminCase
  * AlterField BacklogItem.item_type pour étendre les choices avec
    PHASE / DELIVERABLE / LOT (additive — Django n'a pas de check côté DB
    sur les TextChoices)
  * AddField BoardColumn.phase (FK SET_NULL nullable)

Aucun RunPython, aucune perte de donnée possible. Rollback : `migrate
project 0025` supprime les 6 tables + 2 colonnes sans toucher aux données
existantes.

NOTE PROD POSTGRES :
  AddField avec default non-null sur grosse table peut être lent. Project.
  methodology a un default constant CharField — Postgres 11+ utilise un
  "fast default" qui ne réécrit pas la table. Pour les versions plus
  anciennes ou par sécurité, on peut appliquer :
      ALTER TABLE project_project ADD COLUMN methodology varchar(20)
          DEFAULT 'AGILE' NOT NULL;
  puis `migrate --fake project 0026_phase2_multimode`.
"""

from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0025_task_snoozed_until"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── 1) Champ methodology sur Project ─────────────────────────────
        migrations.AddField(
            model_name="project",
            name="methodology",
            field=models.CharField(
                choices=[
                    ("SCRUM", "Scrum"),
                    ("KANBAN", "Kanban"),
                    ("AGILE", "Agile (mixte)"),
                    ("WATERFALL", "Waterfall / Cycle V"),
                    ("MILESTONE", "Pilotage par jalons"),
                    ("FIELD", "Terrain / Chantier"),
                    ("REAL_ESTATE", "Immobilier"),
                    ("ADMINISTRATIVE", "Administratif"),
                ],
                db_index=True,
                default="AGILE",
                help_text="Détermine les vues et générations IA disponibles pour ce projet.",
                max_length=20,
            ),
        ),

        # ─── 2) BacklogItem.item_type : étendre les choix ────────────────
        migrations.AlterField(
            model_name="backlogitem",
            name="item_type",
            field=models.CharField(
                choices=[
                    ("EPIC", "Epic"),
                    ("STORY", "User Story"),
                    ("TASK", "Task"),
                    ("BUG", "Bug"),
                    ("IMPROVEMENT", "Improvement"),
                    ("SPIKE", "Spike"),
                    ("PHASE", "Phase"),
                    ("DELIVERABLE", "Livrable"),
                    ("LOT", "Lot"),
                ],
                default="TASK",
                max_length=20,
            ),
        ),

        # ─── 3) ProjectPhase (Waterfall) ─────────────────────────────────
        migrations.CreateModel(
            name="ProjectPhase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(
                    choices=[
                        ("PLANNED", "Planifiée"),
                        ("IN_PROGRESS", "En cours"),
                        ("REVIEW", "Revue de gate"),
                        ("DONE", "Terminée"),
                        ("BLOCKED", "Bloquée"),
                    ],
                    db_index=True, default="PLANNED", max_length=20,
                )),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("gate_required", models.BooleanField(
                    default=False,
                    help_text="Si vrai, la phase suivante ne peut démarrer qu'après validation de cette phase.",
                )),
                ("progress_percent", models.PositiveSmallIntegerField(default=0)),
                ("owner", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="owned_phases",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="phases", to="project.project",
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="phases", to="project.workspace",
                )),
            ],
            options={
                "ordering": ["project", "position", "id"],
                "unique_together": {("project", "name")},
            },
        ),
        migrations.AddIndex(
            model_name="projectphase",
            index=models.Index(fields=["project", "position"], name="phase_project_pos_idx"),
        ),

        # ─── 4) BoardColumn.phase (FK vers ProjectPhase, nullable) ───────
        migrations.AddField(
            model_name="boardcolumn",
            name="phase",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="board_columns",
                to="project.projectphase",
                help_text="Optionnel : rattache la colonne à une phase Waterfall.",
            ),
        ),

        # ─── 5) ProjectViewPreference ────────────────────────────────────
        migrations.CreateModel(
            name="ProjectViewPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("view_mode", models.CharField(
                    choices=[
                        ("KANBAN", "Kanban"),
                        ("LIST", "Liste"),
                        ("GANTT", "Gantt"),
                        ("CALENDAR", "Calendrier"),
                        ("PHASES", "Phases"),
                        ("MAP", "Carte"),
                    ],
                    default="KANBAN", max_length=20,
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="view_preferences",
                    to="project.project",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="project_view_preferences",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-updated_at"],
                "unique_together": {("user", "project")},
            },
        ),

        # ─── 6) FieldReport (Terrain / Chantier) ─────────────────────────
        migrations.CreateModel(
            name="FieldReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("report_date", models.DateField(default=django.utils.timezone.localdate)),
                ("location_name", models.CharField(blank=True, max_length=200)),
                ("location_lat", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("location_lng", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("weather", models.CharField(
                    blank=True, default="OTHER", max_length=12,
                    choices=[
                        ("SUNNY", "Ensoleillé"),
                        ("CLOUDY", "Nuageux"),
                        ("RAINY", "Pluvieux"),
                        ("STORMY", "Orageux"),
                        ("WINDY", "Venteux"),
                        ("OTHER", "Autre"),
                    ],
                )),
                ("workforce_count", models.PositiveIntegerField(default=0)),
                ("incidents", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="field_reports", to="project.project",
                )),
                ("reporter", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="field_reports", to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="field_reports", to="project.workspace",
                )),
            ],
            options={"ordering": ["-report_date", "-id"]},
        ),
        migrations.AddIndex(
            model_name="fieldreport",
            index=models.Index(fields=["project", "-report_date"], name="field_report_proj_date_idx"),
        ),

        # ─── 7) FieldReportPhoto ─────────────────────────────────────────
        migrations.CreateModel(
            name="FieldReportPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("image", models.ImageField(upload_to="devflow/field_reports/")),
                ("caption", models.CharField(blank=True, max_length=200)),
                ("report", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="photos", to="project.fieldreport",
                )),
                ("uploaded_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="uploaded_field_photos",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),

        # ─── 8) RealEstateLot ────────────────────────────────────────────
        migrations.CreateModel(
            name="RealEstateLot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("lot_number", models.CharField(max_length=40)),
                ("floor", models.CharField(blank=True, max_length=40)),
                ("surface_m2", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=8)),
                ("bedrooms", models.PositiveSmallIntegerField(default=0)),
                ("price", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
                ("currency", models.CharField(default="XOF", max_length=3)),
                ("status", models.CharField(
                    choices=[
                        ("AVAILABLE", "Disponible"),
                        ("RESERVED", "Réservé"),
                        ("OPTION", "Sous option"),
                        ("SOLD", "Vendu"),
                        ("DELIVERED", "Livré"),
                        ("WITHDRAWN", "Retiré"),
                    ],
                    db_index=True, default="AVAILABLE", max_length=12,
                )),
                ("buyer_name", models.CharField(blank=True, max_length=200)),
                ("buyer_email", models.EmailField(blank=True, max_length=254)),
                ("buyer_phone", models.CharField(blank=True, max_length=40)),
                ("reserved_at", models.DateField(blank=True, null=True)),
                ("sold_at", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="real_estate_lots", to="project.project",
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="real_estate_lots", to="project.workspace",
                )),
            ],
            options={
                "ordering": ["project", "lot_number"],
                "unique_together": {("project", "lot_number")},
            },
        ),
        migrations.AddIndex(
            model_name="realestatelot",
            index=models.Index(fields=["project", "status"], name="lot_proj_status_idx"),
        ),

        # ─── 9) AdminCase ────────────────────────────────────────────────
        migrations.CreateModel(
            name="AdminCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_archived", models.BooleanField(default=False)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                ("reference", models.CharField(max_length=80)),
                ("title", models.CharField(max_length=200)),
                ("applicant", models.CharField(blank=True, max_length=200)),
                ("document_type", models.CharField(
                    blank=True, max_length=120,
                    help_text="Ex: permis de construire, licence d'exploitation, …",
                )),
                ("status", models.CharField(
                    choices=[
                        ("DRAFT", "Brouillon"),
                        ("SUBMITTED", "Déposé"),
                        ("UNDER_REVIEW", "Instruction"),
                        ("AWAITING_INFO", "Informations attendues"),
                        ("APPROVED", "Validé"),
                        ("REJECTED", "Rejeté"),
                        ("CLOSED", "Clôturé"),
                    ],
                    db_index=True, default="DRAFT", max_length=20,
                )),
                ("requested_at", models.DateField(blank=True, null=True)),
                ("sla_days", models.PositiveIntegerField(
                    default=0,
                    help_text="Délai de traitement réglementaire en jours (0 = pas de SLA).",
                )),
                ("deadline", models.DateField(blank=True, null=True)),
                ("decided_at", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("assignee", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="assigned_admin_cases",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="admin_cases", to="project.project",
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="admin_cases", to="project.workspace",
                )),
            ],
            options={
                "ordering": ["-requested_at", "-id"],
                "unique_together": {("project", "reference")},
            },
        ),
        migrations.AddIndex(
            model_name="admincase",
            index=models.Index(fields=["project", "status"], name="case_proj_status_idx"),
        ),
        migrations.AddIndex(
            model_name="admincase",
            index=models.Index(fields=["deadline"], name="case_deadline_idx"),
        ),
    ]
