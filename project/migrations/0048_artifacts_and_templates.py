"""
PR13-15 METHODO : ProjectArtifact + ProjectTemplate + seed templates.

Crée :
  * ProjectArtifact (stockage versioned des artefacts générés)
  * ProjectTemplate (templates sectoriels)
  * Seed de 12 templates (IT, Construction, Industrie, Santé, Finance, Admin)
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


# ════════════════════════════════════════════════════════════════════════════
# Seed des templates sectoriels
# ════════════════════════════════════════════════════════════════════════════
TEMPLATES = [
    # ─── IT ────────────────────────────────────────────────────────
    {
        "name": "Développement logiciel sur-mesure",
        "sector": "it", "sub_sector": "Custom Software",
        "icon": "fa-code", "methodology_code": "scrum",
        "estimated_duration_days": 120,
        "description": "Développement d'une application métier from scratch.",
        "default_phases": [
            {"name": "Cadrage & Spécifications", "duration_days": 15},
            {"name": "Conception technique", "duration_days": 15},
            {"name": "Développement", "duration_days": 60},
            {"name": "Tests & Recette", "duration_days": 20},
            {"name": "Déploiement", "duration_days": 10},
        ],
        "default_milestones": [
            {"name": "Validation cahier des charges", "offset_days": 15},
            {"name": "Démo MVP", "offset_days": 60},
            {"name": "Mise en production", "offset_days": 120},
        ],
        "default_risks": [
            {"title": "Évolution du périmètre", "category": "scope", "probability": 4, "impact": 4},
            {"title": "Dette technique non gérée", "category": "technical", "probability": 3, "impact": 4},
        ],
    },
    {
        "name": "ERP / Implémentation",
        "sector": "it", "sub_sector": "ERP",
        "icon": "fa-building", "methodology_code": "waterfall",
        "estimated_duration_days": 240,
        "description": "Déploiement d'un ERP (SAP, Odoo, NetSuite, ...).",
        "default_phases": [
            {"name": "Cadrage & Choix solution", "duration_days": 30},
            {"name": "Paramétrage", "duration_days": 60},
            {"name": "Reprise de données", "duration_days": 45},
            {"name": "Tests d'intégration", "duration_days": 30},
            {"name": "Formation utilisateurs", "duration_days": 30},
            {"name": "Mise en production progressive", "duration_days": 45},
        ],
        "default_risks": [
            {"title": "Données legacy corrompues", "category": "data", "probability": 4, "impact": 5},
            {"title": "Résistance utilisateurs", "category": "change", "probability": 4, "impact": 4},
            {"title": "Customisation excessive", "category": "scope", "probability": 5, "impact": 4},
        ],
    },
    {
        "name": "CRM Implementation",
        "sector": "it", "sub_sector": "CRM",
        "icon": "fa-users-rectangle", "methodology_code": "scrum",
        "estimated_duration_days": 90,
        "description": "Mise en place d'un CRM (Salesforce, HubSpot, Pipedrive).",
        "default_phases": [
            {"name": "Audit processus commercial", "duration_days": 15},
            {"name": "Configuration & intégrations", "duration_days": 30},
            {"name": "Migration données clients", "duration_days": 20},
            {"name": "Formation équipes", "duration_days": 15},
            {"name": "Pilote & rollout", "duration_days": 10},
        ],
    },
    {
        "name": "Application Mobile",
        "sector": "it", "sub_sector": "Mobile App",
        "icon": "fa-mobile-screen", "methodology_code": "scrum",
        "estimated_duration_days": 150,
        "description": "Développement app mobile native ou hybride.",
        "default_phases": [
            {"name": "UX/UI Design", "duration_days": 20},
            {"name": "Architecture", "duration_days": 15},
            {"name": "Développement iOS/Android", "duration_days": 70},
            {"name": "Backend & APIs", "duration_days": 30},
            {"name": "QA & Publication stores", "duration_days": 15},
        ],
    },
    {
        "name": "SaaS Multi-tenant",
        "sector": "it", "sub_sector": "SaaS",
        "icon": "fa-cloud", "methodology_code": "kanban",
        "estimated_duration_days": 180,
        "description": "Plateforme SaaS B2B avec architecture multi-tenant.",
    },

    # ─── Construction / BTP ────────────────────────────────────────
    {
        "name": "Construction bâtiment résidentiel",
        "sector": "construction", "sub_sector": "Bâtiment",
        "icon": "fa-building", "methodology_code": "waterfall",
        "estimated_duration_days": 540,
        "description": "Construction d'un immeuble résidentiel R+5.",
        "default_phases": [
            {"name": "Études & permis", "duration_days": 90},
            {"name": "Terrassement & fondations", "duration_days": 60},
            {"name": "Gros œuvre", "duration_days": 180},
            {"name": "Second œuvre", "duration_days": 120},
            {"name": "Finitions", "duration_days": 60},
            {"name": "Réception & livraison", "duration_days": 30},
        ],
        "default_risks": [
            {"title": "Aléas climatiques", "category": "external", "probability": 5, "impact": 3},
            {"title": "Pénurie de matériaux", "category": "supply", "probability": 4, "impact": 4},
            {"title": "Recours des riverains", "category": "legal", "probability": 3, "impact": 5},
        ],
    },
    {
        "name": "Aménagement VRD",
        "sector": "construction", "sub_sector": "VRD",
        "icon": "fa-road", "methodology_code": "waterfall",
        "estimated_duration_days": 240,
        "description": "Voirie, Réseaux Divers (eau, électricité, télécom).",
    },
    {
        "name": "Promotion immobilière",
        "sector": "construction", "sub_sector": "Immobilier",
        "icon": "fa-house-chimney", "methodology_code": "waterfall",
        "estimated_duration_days": 720,
        "description": "Opération de promotion immobilière (étude → livraison).",
    },

    # ─── Industrie ────────────────────────────────────────────────
    {
        "name": "Mise en service ligne de production",
        "sector": "industry", "sub_sector": "Production",
        "icon": "fa-industry", "methodology_code": "waterfall",
        "estimated_duration_days": 180,
        "description": "Implantation d'une nouvelle ligne industrielle.",
    },
    {
        "name": "Plan de maintenance préventive",
        "sector": "industry", "sub_sector": "Maintenance",
        "icon": "fa-gears", "methodology_code": "kanban",
        "estimated_duration_days": 60,
        "description": "Mise en place d'un plan de maintenance préventive.",
    },

    # ─── Santé ────────────────────────────────────────────────────
    {
        "name": "Étude clinique multicentrique",
        "sector": "health", "sub_sector": "Recherche clinique",
        "icon": "fa-microscope", "methodology_code": "waterfall",
        "estimated_duration_days": 720,
        "description": "Essai clinique phase 2/3 avec recrutement patients.",
        "default_risks": [
            {"title": "Difficulté recrutement patients", "category": "execution", "probability": 4, "impact": 5},
            {"title": "Réglementation évolutive", "category": "legal", "probability": 3, "impact": 5},
        ],
    },
    {
        "name": "Surveillance épidémiologique",
        "sector": "health", "sub_sector": "Surveillance sanitaire",
        "icon": "fa-virus", "methodology_code": "kanban",
        "estimated_duration_days": 365,
        "description": "Plateforme de surveillance épidémiologique continue.",
    },

    # ─── Finance ──────────────────────────────────────────────────
    {
        "name": "Audit interne",
        "sector": "finance", "sub_sector": "Audit",
        "icon": "fa-magnifying-glass-chart", "methodology_code": "waterfall",
        "estimated_duration_days": 90,
        "description": "Mission d'audit interne (financier, opérationnel, IT).",
        "default_phases": [
            {"name": "Cadrage de mission", "duration_days": 10},
            {"name": "Planification & risques", "duration_days": 15},
            {"name": "Travaux d'audit", "duration_days": 45},
            {"name": "Rédaction rapport", "duration_days": 15},
            {"name": "Restitution & suivi recommandations", "duration_days": 5},
        ],
    },
    {
        "name": "Transformation digitale banque",
        "sector": "finance", "sub_sector": "Transformation digitale",
        "icon": "fa-bank", "methodology_code": "scrum",
        "estimated_duration_days": 540,
        "description": "Refonte digitale d'une banque (core banking + apps).",
    },

    # ─── Administration ──────────────────────────────────────────
    {
        "name": "Projet gouvernemental",
        "sector": "administration", "sub_sector": "Gouvernemental",
        "icon": "fa-landmark", "methodology_code": "waterfall",
        "estimated_duration_days": 365,
        "description": "Programme gouvernemental avec parties prenantes multiples.",
    },
    {
        "name": "Modernisation institution publique",
        "sector": "administration", "sub_sector": "Institutionnel",
        "icon": "fa-university", "methodology_code": "waterfall",
        "estimated_duration_days": 540,
        "description": "Refonte processus administratifs avec digitalisation.",
    },
]


def forwards_seed_templates(apps, schema_editor):
    Methodology = apps.get_model("project", "Methodology")
    ProjectTemplate = apps.get_model("project", "ProjectTemplate")
    for spec in TEMPLATES:
        methodology = None
        if spec.get("methodology_code"):
            methodology = Methodology.objects.filter(code=spec["methodology_code"]).first()
        ProjectTemplate.objects.update_or_create(
            name=spec["name"],
            defaults={
                "sector": spec["sector"],
                "sub_sector": spec.get("sub_sector", ""),
                "description": spec.get("description", ""),
                "icon": spec.get("icon", ""),
                "methodology": methodology,
                "estimated_duration_days": spec.get("estimated_duration_days", 90),
                "default_phases": spec.get("default_phases", []),
                "default_milestones": spec.get("default_milestones", []),
                "default_risks": spec.get("default_risks", []),
                "default_tasks": spec.get("default_tasks", []),
                "is_system": True,
                "is_active": True,
            },
        )


def backwards_drop_templates(apps, schema_editor):
    ProjectTemplate = apps.get_model("project", "ProjectTemplate")
    ProjectTemplate.objects.filter(is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0047_seed_ai_profiles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── ProjectArtifact ───────────────────────────────────────
        migrations.CreateModel(
            name="ProjectArtifact",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("artifact_code", models.SlugField(max_length=50, db_index=True)),
                ("title", models.CharField(max_length=120)),
                ("content", models.TextField(blank=True)),
                ("template_kind", models.CharField(default="markdown", max_length=20)),
                ("version", models.PositiveIntegerField(default=1)),
                ("ai_provider", models.CharField(blank=True, max_length=40)),
                ("ai_prompt_used", models.TextField(blank=True)),
                ("is_current", models.BooleanField(default=True)),
                ("file", models.FileField(blank=True, null=True,
                                          upload_to="devflow/artifacts/")),
                ("generated_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="artifacts_generated", to=settings.AUTH_USER_MODEL,
                )),
                ("methodology_artifact", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="instances", to="project.methodologyartifact",
                )),
                ("project", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="artifacts", to="project.project",
                )),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "Artefact projet",
                "verbose_name_plural": "Artefacts projet",
            },
        ),
        migrations.AddIndex(
            model_name="projectartifact",
            index=models.Index(fields=["project", "artifact_code"],
                               name="proj_art_proj_code_idx"),
        ),
        migrations.AddIndex(
            model_name="projectartifact",
            index=models.Index(fields=["project", "is_current"],
                               name="proj_art_proj_cur_idx"),
        ),

        # ─── ProjectTemplate ──────────────────────────────────────
        migrations.CreateModel(
            name="ProjectTemplate",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)),
                ("sector", models.CharField(
                    max_length=20, db_index=True,
                    choices=[
                        ("it", "Informatique / Tech"),
                        ("construction", "Construction / BTP"),
                        ("industry", "Industrie / Production"),
                        ("health", "Santé / Recherche"),
                        ("finance", "Finance / Banque"),
                        ("administration", "Administration / Public"),
                        ("education", "Éducation / Formation"),
                        ("marketing", "Marketing / Communication"),
                        ("other", "Autre"),
                    ],
                )),
                ("sub_sector", models.CharField(blank=True, max_length=80)),
                ("description", models.TextField(blank=True)),
                ("icon", models.CharField(blank=True, max_length=50)),
                ("estimated_duration_days", models.PositiveIntegerField(default=90)),
                ("estimated_budget", models.DecimalField(
                    blank=True, null=True, decimal_places=2, max_digits=14,
                )),
                ("default_phases", models.JSONField(default=list, blank=True)),
                ("default_milestones", models.JSONField(default=list, blank=True)),
                ("default_risks", models.JSONField(default=list, blank=True)),
                ("default_tasks", models.JSONField(default=list, blank=True)),
                ("is_system", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("usage_count", models.PositiveIntegerField(default=0)),
                ("methodology", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="templates", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["sector", "name"],
                "verbose_name": "Template projet",
                "verbose_name_plural": "Templates projet",
            },
        ),
        migrations.AddIndex(
            model_name="projecttemplate",
            index=models.Index(fields=["sector", "is_active"],
                               name="proj_tmpl_sec_act_idx"),
        ),
        migrations.AddIndex(
            model_name="projecttemplate",
            index=models.Index(fields=["methodology", "is_active"],
                               name="proj_tmpl_meth_act_idx"),
        ),

        # Seed des 17 templates système
        migrations.RunPython(forwards_seed_templates, reverse_code=backwards_drop_templates),
    ]
