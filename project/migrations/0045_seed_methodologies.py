"""
PR3-METHODO : Seed des 3 méthodologies système — Scrum, Kanban, Waterfall.

Crée :
  * 3 objets Methodology (is_system=True)
  * Leurs statuts, rôles, cérémonies, KPIs, artefacts
  * 1 workflow par méthodologie avec transitions complètes

Idempotent : ré-exécutable sans dupliquer (utilise get_or_create).
Reversible : drop des 3 méthodologies (CASCADE supprime tout le reste).
"""

from django.db import migrations


# ════════════════════════════════════════════════════════════════════════════
# Définitions data-driven des méthodologies
# ════════════════════════════════════════════════════════════════════════════
METHODOLOGIES = {
    "scrum": {
        "name": "Scrum",
        "family": "agile",
        "icon": "fa-rotate",
        "accent_color": "#7c6ff7",
        "description": (
            "Méthodologie agile par sprints courts (1-4 semaines). "
            "Cérémonies : Sprint Planning, Daily, Review, Retrospective. "
            "Rôles : Product Owner, Scrum Master, Dev Team."
        ),
        "config": {
            "has_sprints": True,
            "has_phases": False,
            "has_wip_limits": False,
            "requires_estimation": True,
            "estimation_unit": "story_points",
        },
        "statuses": [
            ("backlog", "Backlog", "todo", "#94a3b8", 0, True, False),
            ("to_do", "À faire", "todo", "#60a5fa", 1, False, False),
            ("in_progress", "En cours", "wip", "#facc15", 2, False, False),
            ("review", "Revue", "review", "#fb923c", 3, False, False),
            ("done", "Terminé", "done", "#22c55e", 4, False, True),
            ("cancelled", "Annulé", "cancelled", "#ef4444", 5, False, True),
        ],
        "roles": [
            ("product_owner", "Product Owner",
             "Définit le backlog et les priorités.", True, 1, "product_manager"),
            ("scrum_master", "Scrum Master",
             "Garant du framework, facilite les cérémonies.", True, 1, "project_manager"),
            ("dev_team", "Équipe de développement",
             "Réalise les user stories du sprint.", True, None, "member"),
            ("stakeholder", "Stakeholder",
             "Partie prenante consultée en Sprint Review.", False, None, "viewer"),
        ],
        "ceremonies": [
            ("sprint_planning", "Sprint Planning", "per_sprint", 120,
             "## Sprint Planning\n\n1. Validation des objectifs du sprint\n2. Sélection des user stories\n3. Décomposition en tâches\n4. Engagement de l'équipe",
             ["product_owner", "scrum_master", "dev_team"], 0),
            ("daily_standup", "Daily Standup", "daily", 15,
             "## Daily Standup\n\n- Qu'ai-je fait hier ?\n- Que vais-je faire aujourd'hui ?\n- Ai-je des blocages ?",
             ["scrum_master", "dev_team"], 1),
            ("sprint_review", "Sprint Review", "per_sprint", 60,
             "## Sprint Review\n\n1. Démo des incréments\n2. Feedback stakeholders\n3. Ajustement backlog",
             ["product_owner", "scrum_master", "dev_team", "stakeholder"], 2),
            ("sprint_retro", "Sprint Retrospective", "per_sprint", 60,
             "## Rétrospective\n\n1. What went well ?\n2. What didn't go well ?\n3. Action items",
             ["scrum_master", "dev_team"], 3),
            ("backlog_refinement", "Backlog Refinement", "weekly", 45,
             "## Backlog Refinement\n\n1. Affiner les user stories\n2. Estimer les nouvelles entrées\n3. Prioriser",
             ["product_owner", "scrum_master"], 4),
        ],
        "kpis": [
            ("velocity", "Vélocité", "story_points", "line", "velocity", True, 0),
            ("burndown", "Burndown Sprint", "story_points", "burndown", "burndown_sprint", True, 1),
            ("sprint_success_rate", "Taux de succès Sprint", "%", "gauge", "sprint_success_rate", False, 2),
            ("story_completion", "Stories complétées", "stories", "number", "story_completion", False, 3),
            ("team_capacity", "Capacité équipe", "story_points", "bar", "team_capacity", False, 4),
        ],
        "artifacts": [
            ("user_story", "User Story", "markdown", "scrum.user_story", True, 0),
            ("epic", "Epic", "markdown", "scrum.epic", True, 1),
            ("sprint_goal", "Sprint Goal", "markdown", "scrum.sprint_goal", False, 2),
            ("sprint_plan", "Sprint Plan", "docx", "scrum.sprint_plan", False, 3),
            ("retro_report", "Retrospective Report", "markdown", "scrum.retro_report", False, 4),
        ],
        "workflows": [
            {
                "code": "task_default", "name": "Workflow standard tâches",
                "applies_to": "task", "is_default": True,
                "transitions": [
                    ("backlog", "to_do", "Prendre en charge", [], False),
                    ("to_do", "in_progress", "Démarrer", [], False),
                    ("in_progress", "review", "Soumettre à revue", [], False),
                    ("in_progress", "to_do", "Repousser", [], True),
                    ("review", "done", "Approuver", ["product_owner", "scrum_master"], False),
                    ("review", "in_progress", "Demander modifications", [], True),
                    ("done", "in_progress", "Rouvrir", ["scrum_master"], True),
                    ("backlog", "cancelled", "Annuler", ["product_owner"], True),
                    ("to_do", "cancelled", "Annuler", ["product_owner"], True),
                ],
            },
        ],
    },

    "kanban": {
        "name": "Kanban",
        "family": "lean",
        "icon": "fa-columns",
        "accent_color": "#0ea5c9",
        "description": (
            "Méthode de gestion de flux continu avec WIP limits et "
            "visualisation du travail. Pas de sprints — pull-based. "
            "Métriques : Lead Time, Cycle Time, Throughput."
        ),
        "config": {
            "has_sprints": False,
            "has_phases": False,
            "has_wip_limits": True,
            "requires_estimation": False,
        },
        "statuses": [
            ("backlog", "Backlog", "todo", "#94a3b8", 0, True, False),
            ("to_do", "À faire", "todo", "#60a5fa", 1, False, False),
            ("in_progress", "En cours", "wip", "#facc15", 2, False, False),
            ("review", "Revue", "review", "#fb923c", 3, False, False),
            ("done", "Terminé", "done", "#22c55e", 4, False, True),
            ("blocked", "Bloqué", "blocked", "#ef4444", 5, False, False),
        ],
        "roles": [
            ("flow_manager", "Flow Manager",
             "Optimise le flux et les WIP limits.", True, 1, "project_manager"),
            ("team_member", "Membre d'équipe",
             "Pull les tickets disponibles.", True, None, "member"),
            ("service_owner", "Service Owner",
             "Définit les priorités du backlog.", False, 1, "product_manager"),
        ],
        "ceremonies": [
            ("daily_standup", "Daily Standup", "daily", 15,
             "## Daily Standup\n\n- Revue du board\n- Identification des goulots\n- Blocages",
             ["flow_manager", "team_member"], 0),
            ("replenishment", "Replenishment Meeting", "weekly", 30,
             "## Replenishment\n\n1. Sélection des prochaines tickets prioritaires\n2. Mise à jour du backlog",
             ["service_owner", "flow_manager"], 1),
            ("flow_review", "Flow Review", "monthly", 60,
             "## Flow Review\n\n1. Analyse cycle time / lead time\n2. Ajustement WIP limits\n3. Identification améliorations",
             ["flow_manager", "team_member"], 2),
        ],
        "kpis": [
            ("wip", "Work In Progress", "tickets", "number", "wip_count", True, 0),
            ("cycle_time", "Cycle Time moyen", "days", "line", "cycle_time", True, 1),
            ("lead_time", "Lead Time moyen", "days", "line", "lead_time", True, 2),
            ("throughput", "Throughput hebdo", "tickets", "bar", "throughput_weekly", False, 3),
            ("cumulative_flow", "Cumulative Flow", "tickets", "cumulative_flow", "cumulative_flow", False, 4),
        ],
        "artifacts": [
            ("flow_diagram", "Diagramme de flux", "markdown", "kanban.flow_diagram", True, 0),
            ("bottleneck_report", "Rapport goulots d'étranglement", "markdown", "kanban.bottleneck_report", False, 1),
        ],
        "workflows": [
            {
                "code": "task_default", "name": "Workflow Kanban standard",
                "applies_to": "task", "is_default": True,
                "transitions": [
                    ("backlog", "to_do", "Pull", [], False),
                    ("to_do", "in_progress", "Démarrer", [], False),
                    ("in_progress", "review", "Soumettre à revue", [], False),
                    ("in_progress", "blocked", "Bloquer", [], True),
                    ("blocked", "in_progress", "Débloquer", [], True),
                    ("review", "done", "Approuver", [], False),
                    ("review", "in_progress", "Renvoyer", [], True),
                    ("done", "in_progress", "Rouvrir", ["flow_manager"], True),
                ],
            },
        ],
    },

    "waterfall": {
        "name": "Waterfall (Cycle en V)",
        "family": "sequential",
        "icon": "fa-water",
        "accent_color": "#3b82f6",
        "description": (
            "Approche séquentielle linéaire en phases distinctes "
            "(Étude → Conception → Réalisation → Tests → Déploiement). "
            "Gantt, chemin critique, jalons stricts."
        ),
        "config": {
            "has_sprints": False,
            "has_phases": True,
            "has_wip_limits": False,
            "requires_estimation": True,
            "estimation_unit": "days",
        },
        "statuses": [
            ("not_started", "Non démarré", "todo", "#94a3b8", 0, True, False),
            ("in_progress", "En cours", "wip", "#facc15", 1, False, False),
            ("review", "En revue", "review", "#fb923c", 2, False, False),
            ("approved", "Approuvé", "done", "#22c55e", 3, False, True),
            ("delayed", "En retard", "wip", "#ef4444", 4, False, False),
            ("closed", "Clôturé", "done", "#16a34a", 5, False, True),
        ],
        "roles": [
            ("project_manager", "Chef de projet",
             "Pilote le projet, suit les jalons.", True, 1, "project_manager"),
            ("sponsor", "Sponsor",
             "Valide les phases majeures, finance le projet.", True, 1, "viewer"),
            ("business_analyst", "Business Analyst",
             "Rédige les exigences fonctionnelles.", False, None, "member"),
            ("tech_lead", "Tech Lead",
             "Responsable conception technique.", False, None, "member"),
            ("qa_lead", "QA Lead",
             "Garant qualité, valide la recette.", False, 1, "member"),
        ],
        "ceremonies": [
            ("kickoff", "Réunion de lancement", "once", 90,
             "## Kickoff\n\n1. Présentation projet\n2. Objectifs & périmètre\n3. Équipe & rôles\n4. Planning haut niveau",
             ["project_manager", "sponsor"], 0),
            ("phase_review", "Revue de phase", "per_phase", 60,
             "## Revue de phase\n\n1. Livrables phase\n2. Validation jalon\n3. Go/No-go phase suivante",
             ["project_manager", "sponsor"], 1),
            ("copil", "COPIL (Comité de pilotage)", "monthly", 60,
             "## COPIL\n\n1. Avancement\n2. Risques & alertes\n3. Décisions & arbitrages",
             ["project_manager", "sponsor"], 2),
            ("recette", "Recette / UAT", "per_milestone", 120,
             "## Recette\n\n1. Plan de tests\n2. Exécution scénarios\n3. PV de recette",
             ["qa_lead", "project_manager"], 3),
        ],
        "kpis": [
            ("advancement_pct", "% Avancement global", "%", "gauge", "advancement_global", True, 0),
            ("schedule_adherence", "Respect du planning", "%", "gauge", "schedule_adherence", True, 1),
            ("budget_consumption", "Budget consommé", "%", "gauge", "budget_consumption", True, 2),
            ("critical_path_length", "Chemin critique", "days", "number", "critical_path_length", False, 3),
            ("phase_progress", "Avancement par phase", "%", "stacked_bar", "phase_progress", False, 4),
            ("gantt", "Diagramme de Gantt", "tasks", "gantt", "gantt_data", False, 5),
        ],
        "artifacts": [
            ("project_charter", "Note de cadrage", "docx", "waterfall.project_charter", True, 0),
            ("requirements_doc", "Cahier des charges", "docx", "waterfall.requirements_doc", True, 1),
            ("wbs", "WBS (Work Breakdown Structure)", "json", "waterfall.wbs", True, 2),
            ("gantt_plan", "Planning Gantt", "csv", "waterfall.gantt_plan", True, 3),
            ("quality_plan", "Plan qualité", "docx", "waterfall.quality_plan", False, 4),
            ("risk_register", "Registre des risques", "docx", "waterfall.risk_register", False, 5),
            ("phase_report", "Rapport de phase", "markdown", "waterfall.phase_report", False, 6),
        ],
        "workflows": [
            {
                "code": "task_default", "name": "Workflow tâches Waterfall",
                "applies_to": "task", "is_default": True,
                "transitions": [
                    ("not_started", "in_progress", "Démarrer", [], False),
                    ("in_progress", "review", "Soumettre à revue", [], False),
                    ("in_progress", "delayed", "Marquer en retard", [], True),
                    ("delayed", "in_progress", "Reprendre", [], False),
                    ("review", "approved", "Valider", ["project_manager", "qa_lead"], False),
                    ("review", "in_progress", "Renvoyer", [], True),
                    ("approved", "closed", "Clôturer", ["project_manager"], False),
                ],
            },
            {
                "code": "phase_workflow", "name": "Workflow phases",
                "applies_to": "phase", "is_default": True,
                "transitions": [
                    ("not_started", "in_progress", "Démarrer la phase", ["project_manager"], False),
                    ("in_progress", "review", "Soumettre revue phase", ["project_manager"], False),
                    ("review", "approved", "Approuver phase (jalon)", ["sponsor", "project_manager"], False),
                    ("review", "in_progress", "Demander corrections", ["sponsor"], True),
                    ("approved", "closed", "Clôturer phase", ["project_manager"], False),
                ],
            },
        ],
    },
}


def forwards_seed_methodologies(apps, schema_editor):
    """Crée les 3 méthodologies système + leurs sous-objets."""
    Methodology = apps.get_model("project", "Methodology")
    MethodologyStatus = apps.get_model("project", "MethodologyStatus")
    MethodologyRole = apps.get_model("project", "MethodologyRole")
    MethodologyCeremony = apps.get_model("project", "MethodologyCeremony")
    MethodologyKPI = apps.get_model("project", "MethodologyKPI")
    MethodologyArtifact = apps.get_model("project", "MethodologyArtifact")
    MethodologyWorkflow = apps.get_model("project", "MethodologyWorkflow")
    WorkflowTransition = apps.get_model("project", "WorkflowTransition")

    for code, spec in METHODOLOGIES.items():
        methodology, _ = Methodology.objects.update_or_create(
            code=code,
            defaults={
                "name": spec["name"],
                "family": spec["family"],
                "description": spec["description"],
                "icon": spec.get("icon", ""),
                "accent_color": spec.get("accent_color", ""),
                "is_system": True,
                "is_active": True,
                "config": spec.get("config", {}),
                "workspace": None,
            },
        )

        # Statuts
        status_map = {}  # code → instance, pour les workflows
        for s_code, s_name, s_cat, s_color, s_pos, s_initial, s_final in spec["statuses"]:
            obj, _ = MethodologyStatus.objects.update_or_create(
                methodology=methodology, code=s_code,
                defaults={
                    "name": s_name, "category": s_cat, "color": s_color,
                    "position": s_pos, "is_initial": s_initial,
                    "is_final": s_final,
                },
            )
            status_map[s_code] = obj

        # Rôles
        for r_code, r_name, r_desc, r_req, r_max, r_rbac in spec["roles"]:
            MethodologyRole.objects.update_or_create(
                methodology=methodology, code=r_code,
                defaults={
                    "name": r_name, "description": r_desc,
                    "is_required": r_req, "max_holders": r_max,
                    "suggested_rbac_role": r_rbac or "",
                },
            )

        # Cérémonies
        for c_code, c_name, c_cadence, c_dur, c_agenda, c_roles, c_pos in spec["ceremonies"]:
            MethodologyCeremony.objects.update_or_create(
                methodology=methodology, code=c_code,
                defaults={
                    "name": c_name, "cadence": c_cadence,
                    "default_duration_min": c_dur,
                    "template_agenda": c_agenda,
                    "required_role_codes": c_roles, "position": c_pos,
                },
            )

        # KPIs
        for k_code, k_name, k_unit, k_chart, k_strategy, k_pinned, k_pos in spec["kpis"]:
            MethodologyKPI.objects.update_or_create(
                methodology=methodology, code=k_code,
                defaults={
                    "name": k_name, "unit": k_unit,
                    "chart_type": k_chart,
                    "compute_strategy": k_strategy,
                    "is_pinned": k_pinned, "position": k_pos,
                },
            )

        # Artefacts
        for a_code, a_name, a_kind, a_prompt, a_recommended, a_pos in spec["artifacts"]:
            MethodologyArtifact.objects.update_or_create(
                methodology=methodology, code=a_code,
                defaults={
                    "name": a_name, "template_kind": a_kind,
                    "ai_prompt_key": a_prompt,
                    "is_recommended": a_recommended,
                    "position": a_pos,
                },
            )

        # Workflows + transitions
        for wf_spec in spec.get("workflows", []):
            workflow, _ = MethodologyWorkflow.objects.update_or_create(
                methodology=methodology, code=wf_spec["code"],
                defaults={
                    "name": wf_spec["name"],
                    "applies_to": wf_spec["applies_to"],
                    "is_default": wf_spec.get("is_default", False),
                },
            )
            for from_code, to_code, label, roles, req_comment in wf_spec["transitions"]:
                from_obj = status_map.get(from_code)
                to_obj = status_map.get(to_code)
                if not from_obj or not to_obj:
                    continue
                WorkflowTransition.objects.update_or_create(
                    workflow=workflow,
                    from_status=from_obj, to_status=to_obj,
                    defaults={
                        "label": label,
                        "required_role_codes": roles,
                        "requires_comment": req_comment,
                    },
                )


def backwards_drop_methodologies(apps, schema_editor):
    """Supprime les 3 méthodologies système (CASCADE supprime le reste)."""
    Methodology = apps.get_model("project", "Methodology")
    Methodology.objects.filter(
        code__in=["scrum", "kanban", "waterfall"], is_system=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0044_methodology_workflow"),
    ]

    operations = [
        migrations.RunPython(
            forwards_seed_methodologies,
            reverse_code=backwards_drop_methodologies,
        ),
    ]
