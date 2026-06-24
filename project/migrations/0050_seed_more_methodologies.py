"""
P+-METHODO : Seed des 7 méthodologies supplémentaires.

Ajoute :
  * Prince2 (formal)
  * PMBOK (formal)
  * SAFe (agile à l'échelle)
  * DevOps (lean + métriques DORA)
  * Lean Project Management (lean)
  * Agile (agile générique)
  * Hybride (Waterfall + Agile)

Chacune avec statuts, rôles, cérémonies, KPIs, artefacts, workflow par
défaut et profil IA spécialisé.

Idempotent (update_or_create) et reversible.
"""

from django.db import migrations


METHODOLOGIES = {
    # ════════════════════════════════════════════════════════════════
    "prince2": {
        "name": "PRINCE2",
        "family": "formal",
        "icon": "fa-shield-halved",
        "accent_color": "#9333ea",
        "description": (
            "PRoject IN Controlled Environments — méthode formelle "
            "britannique structurée en 7 thèmes et 7 processus. "
            "Forte gouvernance, business case justifié."
        ),
        "config": {"has_phases": True, "has_stages": True, "requires_estimation": True},
        "statuses": [
            ("not_started", "Pré-projet", "todo", "#94a3b8", 0, True, False),
            ("initiating", "Initialisation", "wip", "#facc15", 1, False, False),
            ("in_stage", "En étape", "wip", "#fb923c", 2, False, False),
            ("end_stage", "Fin d'étape", "review", "#a855f7", 3, False, False),
            ("closed", "Clôturé", "done", "#22c55e", 4, False, True),
            ("on_hold", "Suspendu", "blocked", "#ef4444", 5, False, False),
        ],
        "roles": [
            ("executive", "Executive", "Sponsor exécutif, autorise le business case.", True, 1, "viewer"),
            ("project_manager", "Project Manager", "Pilote le projet au jour le jour.", True, 1, "project_manager"),
            ("senior_user", "Senior User", "Représente les utilisateurs finaux.", True, None, "member"),
            ("senior_supplier", "Senior Supplier", "Représente les fournisseurs / réalisateurs.", True, None, "member"),
            ("team_manager", "Team Manager", "Encadre une équipe spécialiste.", False, None, "member"),
        ],
        "ceremonies": [
            ("project_board", "Project Board", "monthly", 90,
             "## Project Board\n\n1. Revue avancement\n2. Décisions stratégiques\n3. Validation passage d'étape",
             ["executive", "senior_user", "senior_supplier"], 0),
            ("end_stage_assessment", "End Stage Assessment", "per_phase", 120,
             "## End Stage Assessment\n\n1. Bilan étape\n2. Validation livrables\n3. Plan étape suivante\n4. Go/No-go",
             ["executive", "project_manager"], 1),
            ("daily_log_review", "Daily Log Review", "weekly", 30,
             "## Daily Log Review\n\n1. Issues nouvelles\n2. Risks mis à jour\n3. Quality log",
             ["project_manager"], 2),
        ],
        "kpis": [
            ("business_benefits", "Bénéfices business attendus", "K€", "number", "business_benefits", True, 0),
            ("stage_progress", "Avancement étape courante", "%", "gauge", "advancement_global", True, 1),
            ("risk_register_count", "Risques actifs", "risques", "number", "risk_count_active", True, 2),
            ("quality_metrics", "Conformité qualité", "%", "gauge", "quality_compliance", False, 3),
            ("change_requests", "Change Requests ouverts", "CR", "number", "change_requests_open", False, 4),
        ],
        "artifacts": [
            ("business_case", "Business Case", "docx", "prince2.business_case", True, 0),
            ("project_brief", "Project Brief", "docx", "prince2.project_brief", True, 1),
            ("risk_register", "Risk Register", "docx", "prince2.risk_register", True, 2),
            ("stage_plan", "Stage Plan", "docx", "prince2.stage_plan", True, 3),
            ("lessons_log", "Lessons Log", "markdown", "prince2.lessons_log", False, 4),
            ("quality_register", "Quality Register", "docx", "prince2.quality_register", False, 5),
            ("end_project_report", "End Project Report", "docx", "prince2.end_project_report", False, 6),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow PRINCE2",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("not_started", "initiating", "Démarrer", ["project_manager"], False),
                ("initiating", "in_stage", "Lancer étape", ["project_manager"], False),
                ("in_stage", "end_stage", "Demander validation étape", ["project_manager"], False),
                ("in_stage", "on_hold", "Suspendre", ["executive"], True),
                ("on_hold", "in_stage", "Reprendre", ["executive"], False),
                ("end_stage", "in_stage", "Phase suivante", ["executive", "project_manager"], False),
                ("end_stage", "closed", "Clôturer", ["executive"], True),
            ],
        }],
        "ai_profile": {
            "persona": "Project Manager PRINCE2 certifié — formel, rigoureux, gouvernance",
            "tone": "directive",
            "capabilities": [
                "generate_business_case", "manage_stages", "track_risks",
                "control_quality", "stage_gate_review", "lessons_learned",
            ],
            "system_prompt": (
                "Tu es un Project Manager certifié PRINCE2 (Foundation + "
                "Practitioner). Tu pilotes les projets selon les 7 principes "
                "(continuous business justification, learn from experience, "
                "defined roles, manage by stages, manage by exception, focus "
                "on products, tailored).\n\n"
                "Tu utilises systématiquement les 7 thèmes (Business Case, "
                "Organization, Quality, Plans, Risk, Change, Progress) et "
                "les 7 processus (SU, IP, DP, CS, MP, SB, CP).\n\n"
                "**Format** : Markdown structuré. Tableaux pour les "
                "registres (Risk, Quality, Issue). Référence systématique au "
                "Business Case et aux tolérances (cost, time, scope, risk, "
                "quality, benefits)."
            ),
        },
    },

    # ════════════════════════════════════════════════════════════════
    "pmbok": {
        "name": "PMBOK 7",
        "family": "formal",
        "icon": "fa-book-open",
        "accent_color": "#dc2626",
        "description": (
            "Project Management Body of Knowledge (PMI). 12 principes, "
            "8 domaines de performance. EVM (Earned Value Management) "
            "comme socle métriques."
        ),
        "config": {"has_phases": True, "requires_estimation": True},
        "statuses": [
            ("initiating", "Initiating", "todo", "#94a3b8", 0, True, False),
            ("planning", "Planning", "wip", "#facc15", 1, False, False),
            ("executing", "Executing", "wip", "#fb923c", 2, False, False),
            ("monitoring", "Monitoring & Controlling", "review", "#a855f7", 3, False, False),
            ("closing", "Closing", "done", "#22c55e", 4, False, True),
        ],
        "roles": [
            ("project_manager", "Project Manager", "Responsable global du projet (PMP).", True, 1, "project_manager"),
            ("sponsor", "Sponsor", "Finance et arbitre.", True, 1, "viewer"),
            ("stakeholder", "Stakeholder", "Partie prenante consultée.", False, None, "viewer"),
            ("team_member", "Team Member", "Réalise les livrables.", True, None, "member"),
            ("subject_matter_expert", "SME", "Expert métier consulté.", False, None, "member"),
        ],
        "ceremonies": [
            ("kickoff", "Kickoff meeting", "once", 90,
             "## Kickoff\n\n1. Charter\n2. Scope\n3. Stakeholder analysis\n4. Communication plan",
             ["project_manager", "sponsor", "stakeholder"], 0),
            ("status_meeting", "Status Meeting", "weekly", 45,
             "## Status\n\n1. SPI/CPI\n2. Risks\n3. Issues\n4. Décisions",
             ["project_manager", "team_member"], 1),
            ("change_control_board", "Change Control Board", "biweekly", 60,
             "## CCB\n\n1. Change Requests\n2. Impact analysis\n3. Approval / Reject",
             ["project_manager", "sponsor"], 2),
            ("phase_gate_review", "Phase Gate Review", "per_phase", 90,
             "## Phase Gate\n\n1. Deliverables\n2. Go/No-go",
             ["project_manager", "sponsor", "stakeholder"], 3),
        ],
        "kpis": [
            ("spi", "Schedule Performance Index (SPI)", "ratio", "gauge", "spi", True, 0),
            ("cpi", "Cost Performance Index (CPI)", "ratio", "gauge", "cpi", True, 1),
            ("evm_eac", "Estimate At Completion (EAC)", "K€", "number", "evm_eac", True, 2),
            ("evm_etc", "Estimate To Complete (ETC)", "K€", "number", "evm_etc", False, 3),
            ("ev_pv_ac", "EV / PV / AC", "K€", "line", "ev_pv_ac", False, 4),
            ("risk_exposure", "Risk Exposure", "K€", "number", "risk_exposure", False, 5),
        ],
        "artifacts": [
            ("project_charter", "Project Charter", "docx", "pmbok.project_charter", True, 0),
            ("scope_statement", "Scope Statement", "docx", "pmbok.scope_statement", True, 1),
            ("wbs", "Work Breakdown Structure", "json", "pmbok.wbs", True, 2),
            ("schedule_baseline", "Schedule Baseline", "csv", "pmbok.schedule_baseline", True, 3),
            ("risk_register", "Risk Register", "docx", "pmbok.risk_register", True, 4),
            ("stakeholder_register", "Stakeholder Register", "docx", "pmbok.stakeholder_register", True, 5),
            ("communication_plan", "Communication Management Plan", "docx", "pmbok.communication_plan", False, 6),
            ("change_log", "Change Log", "csv", "pmbok.change_log", False, 7),
            ("lessons_learned", "Lessons Learned Register", "markdown", "pmbok.lessons_learned", False, 8),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow PMBOK",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("initiating", "planning", "Passer en planification", ["project_manager"], False),
                ("planning", "executing", "Démarrer exécution", ["project_manager"], False),
                ("executing", "monitoring", "Soumettre à contrôle", [], False),
                ("monitoring", "executing", "Corriger & continuer", [], False),
                ("monitoring", "closing", "Clôturer", ["project_manager", "sponsor"], False),
            ],
        }],
        "ai_profile": {
            "persona": "Project Manager PMP certifié — analytique, EVM-driven, gouvernance",
            "tone": "analytical",
            "capabilities": [
                "generate_charter", "evm_analysis", "risk_assessment",
                "change_control", "stakeholder_analysis", "earned_value",
            ],
            "system_prompt": (
                "Tu es un Project Manager certifié PMP, expert PMBOK 7. Tu "
                "appliques les 12 principes (stewardship, team, stakeholders, "
                "value, systems thinking, leadership, tailoring, quality, "
                "complexity, risk, adaptability, change). Tu pilotes par les "
                "8 performance domains.\n\n"
                "Tu utilises systématiquement l'Earned Value Management (PV, "
                "EV, AC, CV, SV, CPI, SPI, EAC, ETC, VAC, TCPI). Pour les "
                "risques : qualitative + quantitative analysis avec Expected "
                "Monetary Value.\n\n"
                "**Format** : tableaux EVM exhaustifs, analyses d'écart "
                "chiffrées, recommandations basées sur les seuils de "
                "tolérance définis dans le Charter."
            ),
        },
    },

    # ════════════════════════════════════════════════════════════════
    "safe": {
        "name": "SAFe (Scaled Agile Framework)",
        "family": "agile",
        "icon": "fa-sitemap",
        "accent_color": "#0ea5e9",
        "description": (
            "Framework d'agilité à l'échelle pour grandes organisations. "
            "Équipes Agile groupées en Agile Release Train (ART), "
            "Program Increments (PI) de 8-12 semaines."
        ),
        "config": {"has_sprints": True, "has_pi": True, "requires_estimation": True},
        "statuses": [
            ("backlog", "Program Backlog", "todo", "#94a3b8", 0, True, False),
            ("pi_planned", "PI Planned", "todo", "#60a5fa", 1, False, False),
            ("in_progress", "In Progress", "wip", "#facc15", 2, False, False),
            ("system_demo", "System Demo", "review", "#fb923c", 3, False, False),
            ("done", "Done", "done", "#22c55e", 4, False, True),
            ("dependency_blocked", "Dependency Blocked", "blocked", "#ef4444", 5, False, False),
        ],
        "roles": [
            ("rte", "Release Train Engineer (RTE)", "Facilite l'ART, supprime les blocages inter-équipes.", True, 1, "project_manager"),
            ("product_management", "Product Management", "Gère le program backlog.", True, None, "product_manager"),
            ("system_architect", "System Architect", "Garant de l'architecture transverse.", True, 1, "member"),
            ("scrum_master", "Scrum Master (par équipe)", "Facilite chaque équipe Agile.", True, None, "project_manager"),
            ("product_owner", "Product Owner (par équipe)", "Backlog d'équipe.", True, None, "product_manager"),
            ("business_owner", "Business Owner", "Validation valeur business.", True, None, "viewer"),
        ],
        "ceremonies": [
            ("pi_planning", "PI Planning", "per_phase", 720,
             "## PI Planning (2 jours)\n\n1. Vision & contexte business\n2. Architecture vision\n3. Team breakouts\n4. Draft plan review\n5. Confidence vote",
             ["rte", "product_management", "scrum_master", "product_owner", "business_owner"], 0),
            ("ip_iteration", "IP Iteration (Innovation & Planning)", "per_phase", 90,
             "## IP Iteration\n\n1. Inspect & adapt\n2. PI System demo\n3. Quantitative measurement\n4. Hackathon",
             ["rte", "product_management"], 1),
            ("scrum_of_scrums", "Scrum of Scrums", "weekly", 30,
             "## Scrum of Scrums\n\n1. Avancement par équipe\n2. Dépendances inter-équipes\n3. Blocages",
             ["rte", "scrum_master"], 2),
            ("po_sync", "PO Sync", "weekly", 60,
             "## PO Sync\n\n1. Backlog refinement\n2. Réalignement priorités",
             ["product_management", "product_owner"], 3),
        ],
        "kpis": [
            ("pi_predictability", "PI Predictability", "%", "gauge", "pi_predictability", True, 0),
            ("velocity", "Vélocité ART (moyenne)", "story_points", "line", "velocity", True, 1),
            ("feature_completion", "Features completées (PI)", "features", "number", "feature_completion", True, 2),
            ("dependencies_count", "Dépendances inter-équipes", "deps", "number", "dependencies_count", False, 3),
            ("flow_efficiency", "Flow Efficiency", "%", "gauge", "flow_efficiency", False, 4),
        ],
        "artifacts": [
            ("program_board", "Program Board", "json", "safe.program_board", True, 0),
            ("pi_objectives", "PI Objectives", "markdown", "safe.pi_objectives", True, 1),
            ("feature", "Feature", "markdown", "safe.feature", True, 2),
            ("enabler", "Enabler", "markdown", "safe.enabler", False, 3),
            ("ia_report", "Inspect & Adapt Report", "docx", "safe.ia_report", False, 4),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow SAFe",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("backlog", "pi_planned", "Embarquer dans le PI", ["product_management"], False),
                ("pi_planned", "in_progress", "Démarrer", [], False),
                ("in_progress", "system_demo", "Démo système", [], False),
                ("in_progress", "dependency_blocked", "Bloqué par dépendance", [], True),
                ("dependency_blocked", "in_progress", "Dépendance résolue", ["rte"], False),
                ("system_demo", "done", "Accepté", ["product_management"], False),
            ],
        }],
        "ai_profile": {
            "persona": "SAFe Program Consultant (SPC) — orchestration multi-équipes",
            "tone": "coach",
            "capabilities": [
                "facilitate_pi_planning", "manage_dependencies",
                "compute_pi_predictability", "scrum_of_scrums",
                "feature_breakdown", "release_planning",
            ],
            "system_prompt": (
                "Tu es un SAFe Program Consultant (SPC). Tu accompagnes un "
                "ART (Agile Release Train) selon SAFe 6.0.\n\n"
                "Tu raisonnes en termes de Features, Capabilities, Epics, "
                "Program Increments (PI), Iterations (sprints). Tu maîtrises "
                "les cérémonies SAFe (PI Planning, Scrum of Scrums, PO Sync, "
                "IP Iteration, Inspect & Adapt).\n\n"
                "Tu accordes une attention particulière aux dépendances "
                "inter-équipes, aux risques ROAM (Resolved/Owned/Accepted/"
                "Mitigated) et à la prédictibilité du PI. Tu utilises WSJF "
                "(Weighted Shortest Job First) pour la priorisation."
            ),
        },
    },

    # ════════════════════════════════════════════════════════════════
    "devops": {
        "name": "DevOps",
        "family": "lean",
        "icon": "fa-infinity",
        "accent_color": "#10b981",
        "description": (
            "Culture DevOps : intégration continue, déploiement continu, "
            "infrastructure as code. Métriques DORA (Lead Time, Deployment "
            "Frequency, Change Failure Rate, MTTR)."
        ),
        "config": {"has_sprints": False, "continuous_delivery": True},
        "statuses": [
            ("backlog", "Backlog", "todo", "#94a3b8", 0, True, False),
            ("in_progress", "In Progress", "wip", "#facc15", 1, False, False),
            ("ci_pipeline", "CI Pipeline", "wip", "#fb923c", 2, False, False),
            ("ready_to_deploy", "Ready to Deploy", "review", "#a855f7", 3, False, False),
            ("deployed", "Deployed", "done", "#22c55e", 4, False, True),
            ("rollback", "Rollback", "blocked", "#ef4444", 5, False, False),
        ],
        "roles": [
            ("devops_engineer", "DevOps Engineer", "Pipeline CI/CD + infra.", True, None, "member"),
            ("sre", "SRE (Site Reliability Engineer)", "Garant fiabilité & uptime.", True, None, "member"),
            ("developer", "Developer", "Code + tests + déploiement.", True, None, "member"),
            ("product_owner", "Product Owner", "Définit la valeur livrée.", False, 1, "product_manager"),
            ("security_engineer", "Security Engineer", "DevSecOps.", False, None, "member"),
        ],
        "ceremonies": [
            ("daily_standup", "Daily Standup", "daily", 15,
             "## Daily\n\n- Pipelines en cours\n- Incidents production\n- Blocages",
             ["developer", "devops_engineer", "sre"], 0),
            ("postmortem", "Postmortem (blameless)", "on_demand", 60,
             "## Postmortem\n\n1. Timeline\n2. Root cause analysis\n3. Action items\n4. Lessons learned",
             ["sre", "devops_engineer"], 1),
            ("release_review", "Release Review", "weekly", 30,
             "## Release Review\n\n1. Déploiements de la semaine\n2. Métriques DORA\n3. Incidents",
             ["devops_engineer", "product_owner"], 2),
        ],
        "kpis": [
            ("deployment_frequency", "Deployment Frequency", "deploy/j", "bar", "deployment_frequency", True, 0),
            ("lead_time_changes", "Lead Time for Changes", "heures", "line", "lead_time_changes", True, 1),
            ("mttr", "Mean Time To Recovery", "minutes", "line", "mttr", True, 2),
            ("change_failure_rate", "Change Failure Rate", "%", "gauge", "change_failure_rate", True, 3),
            ("ci_pass_rate", "CI Pass Rate", "%", "gauge", "ci_pass_rate", False, 4),
        ],
        "artifacts": [
            ("runbook", "Runbook opérationnel", "markdown", "devops.runbook", True, 0),
            ("ci_pipeline_config", "Pipeline CI/CD", "json", "devops.ci_pipeline_config", True, 1),
            ("infra_as_code", "Infrastructure as Code", "json", "devops.infra_as_code", True, 2),
            ("postmortem_report", "Postmortem Report", "markdown", "devops.postmortem_report", False, 3),
            ("slo_sla", "SLO / SLA Document", "docx", "devops.slo_sla", False, 4),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow DevOps",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("backlog", "in_progress", "Pull", [], False),
                ("in_progress", "ci_pipeline", "Push pour CI", [], False),
                ("ci_pipeline", "ready_to_deploy", "CI OK", [], False),
                ("ci_pipeline", "in_progress", "CI failed", [], True),
                ("ready_to_deploy", "deployed", "Déployer", ["devops_engineer", "sre"], False),
                ("deployed", "rollback", "Rollback", ["devops_engineer", "sre"], True),
                ("rollback", "in_progress", "Fix & retry", [], False),
            ],
        }],
        "ai_profile": {
            "persona": "DevOps Coach — métriques DORA, automation-first",
            "tone": "analytical",
            "capabilities": [
                "analyze_dora_metrics", "incident_postmortem",
                "pipeline_optimization", "infra_as_code_review",
                "slo_sla_management",
            ],
            "system_prompt": (
                "Tu es un DevOps Coach senior avec une approche SRE. Tu "
                "raisonnes en termes de métriques DORA (Deployment Frequency, "
                "Lead Time for Changes, MTTR, Change Failure Rate) et "
                "d'élite performance (Accelerate book).\n\n"
                "Tu privilégies : automation (CI/CD, IaC), observabilité "
                "(logs/metrics/traces), blameless postmortems, error "
                "budgets, SLO/SLI.\n\n"
                "**Format** : tableaux DORA, runbooks structurés, postmortems "
                "facteurs contributifs (jamais une seule cause)."
            ),
        },
    },

    # ════════════════════════════════════════════════════════════════
    "lean": {
        "name": "Lean Project Management",
        "family": "lean",
        "icon": "fa-leaf",
        "accent_color": "#84cc16",
        "description": (
            "Approche Lean : maximiser la valeur, minimiser le gaspillage "
            "(muda). Value Stream Mapping, Kaizen continu, Just-In-Time."
        ),
        "config": {"continuous_improvement": True},
        "statuses": [
            ("backlog", "Backlog", "todo", "#94a3b8", 0, True, False),
            ("ready", "Ready", "todo", "#60a5fa", 1, False, False),
            ("doing", "Doing", "wip", "#facc15", 2, False, False),
            ("review", "Review", "review", "#fb923c", 3, False, False),
            ("done", "Done", "done", "#22c55e", 4, False, True),
            ("waste", "Waste (muda)", "cancelled", "#ef4444", 5, False, True),
        ],
        "roles": [
            ("lean_coach", "Lean Coach", "Forme l'équipe, anime Kaizen.", True, 1, "project_manager"),
            ("value_stream_owner", "Value Stream Owner", "Optimise le flux de valeur.", True, 1, "product_manager"),
            ("team_member", "Team Member", "Réalise + suggère améliorations.", True, None, "member"),
        ],
        "ceremonies": [
            ("kaizen", "Kaizen Event", "monthly", 240,
             "## Kaizen\n\n1. Identifier gaspillage\n2. Analyser cause racine\n3. Proposer solutions\n4. Plan d'action",
             ["lean_coach", "value_stream_owner", "team_member"], 0),
            ("gemba_walk", "Gemba Walk", "weekly", 60,
             "## Gemba Walk\n\n1. Observation sur le terrain\n2. Questions ouvertes\n3. Pas de solution imposée",
             ["lean_coach", "value_stream_owner"], 1),
            ("daily_huddle", "Daily Huddle", "daily", 10,
             "## Huddle\n\n- Hier / Aujourd'hui / Blocages\n- Métriques visuelles",
             ["team_member"], 2),
        ],
        "kpis": [
            ("value_delivered", "Valeur livrée", "items", "number", "value_delivered", True, 0),
            ("flow_efficiency", "Flow Efficiency", "%", "gauge", "flow_efficiency", True, 1),
            ("waste_count", "Gaspillages identifiés", "muda", "number", "waste_count", True, 2),
            ("cycle_time", "Cycle Time", "jours", "line", "cycle_time", False, 3),
            ("kaizen_count", "Kaizen events réalisés", "events", "number", "kaizen_count", False, 4),
        ],
        "artifacts": [
            ("value_stream_map", "Value Stream Map", "json", "lean.value_stream_map", True, 0),
            ("a3_report", "A3 Report (Problem Solving)", "markdown", "lean.a3_report", True, 1),
            ("waste_log", "Muda Log", "csv", "lean.waste_log", False, 2),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow Lean",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("backlog", "ready", "Ready (préparé)", [], False),
                ("ready", "doing", "Pull", [], False),
                ("doing", "review", "Soumettre", [], False),
                ("review", "done", "Validé", [], False),
                ("review", "doing", "Renvoyer", [], True),
                ("backlog", "waste", "Identifier comme muda", ["lean_coach"], True),
            ],
        }],
        "ai_profile": {
            "persona": "Lean Coach — élimination du gaspillage, amélioration continue",
            "tone": "coach",
            "capabilities": [
                "identify_waste", "value_stream_analysis",
                "a3_problem_solving", "kaizen_facilitation",
            ],
            "system_prompt": (
                "Tu es un Lean Coach formé Toyota Production System. Tu "
                "identifies les 8 gaspillages (DOWNTIME : Defects, "
                "Overproduction, Waiting, Non-utilized talent, Transportation, "
                "Inventory, Motion, Extra-processing).\n\n"
                "Tu utilises systématiquement Value Stream Mapping pour "
                "visualiser les flux. Pour le problem-solving : méthode A3 "
                "(Background, Current Condition, Goal, Root Cause, "
                "Countermeasures, Plan, Follow-up).\n\n"
                "Tu privilégies les améliorations petites et continues (kaizen) "
                "plutôt que les changements radicaux."
            ),
        },
    },

    # ════════════════════════════════════════════════════════════════
    "agile": {
        "name": "Agile (générique)",
        "family": "agile",
        "icon": "fa-bolt",
        "accent_color": "#f59e0b",
        "description": (
            "Approche agile générique sans framework strict. Itérations "
            "courtes, valeur livrée tôt, adaptation continue. "
            "Adapté quand Scrum/Kanban sont trop rigides."
        ),
        "config": {"has_sprints": True, "flexible_ceremonies": True},
        "statuses": [
            ("backlog", "Backlog", "todo", "#94a3b8", 0, True, False),
            ("to_do", "To Do", "todo", "#60a5fa", 1, False, False),
            ("doing", "Doing", "wip", "#facc15", 2, False, False),
            ("done", "Done", "done", "#22c55e", 3, False, True),
        ],
        "roles": [
            ("project_lead", "Project Lead", "Anime l'équipe agile.", True, 1, "project_manager"),
            ("product_owner", "Product Owner", "Priorise la valeur.", True, 1, "product_manager"),
            ("team_member", "Team Member", "Réalise les items.", True, None, "member"),
        ],
        "ceremonies": [
            ("iteration_planning", "Iteration Planning", "biweekly", 90,
             "## Planning\n\n1. Goal de l'itération\n2. Items sélectionnés",
             ["project_lead", "product_owner", "team_member"], 0),
            ("standup", "Standup", "daily", 15,
             "## Standup\n\n- Hier / Aujourd'hui / Blocages",
             ["team_member"], 1),
            ("review_retro", "Review + Retrospective", "biweekly", 90,
             "## Review/Retro\n\n1. Démo\n2. Feedback\n3. What to improve",
             ["project_lead", "product_owner", "team_member"], 2),
        ],
        "kpis": [
            ("velocity", "Vélocité", "points", "line", "velocity", True, 0),
            ("burndown", "Burndown", "points", "burndown", "burndown_sprint", True, 1),
            ("done_per_iteration", "Items / itération", "items", "bar", "story_completion", False, 2),
        ],
        "artifacts": [
            ("iteration_goal", "Iteration Goal", "markdown", "agile.iteration_goal", True, 0),
            ("review_report", "Review Report", "markdown", "agile.review_report", False, 1),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow Agile",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("backlog", "to_do", "Sélectionner", [], False),
                ("to_do", "doing", "Démarrer", [], False),
                ("doing", "done", "Terminer", [], False),
                ("done", "doing", "Rouvrir", [], True),
            ],
        }],
        "ai_profile": {
            "persona": "Agile Coach pragmatique — adaptation > framework",
            "tone": "coach",
            "capabilities": ["estimate_items", "iteration_planning", "retrospective"],
            "system_prompt": (
                "Tu es un Agile Coach pragmatique. Tu privilégies les "
                "principes du Manifeste Agile (individuals & interactions, "
                "working software, customer collaboration, responding to "
                "change) à toute prescription rigide.\n\n"
                "Tu adaptes les pratiques à l'équipe et au contexte. Tu ne "
                "forces pas un framework — tu sors ce qui marche."
            ),
        },
    },

    # ════════════════════════════════════════════════════════════════
    "hybrid": {
        "name": "Hybride (Waterfall + Agile)",
        "family": "hybrid",
        "icon": "fa-shuffle",
        "accent_color": "#6366f1",
        "description": (
            "Combinaison Waterfall (phases stratégiques) + Agile (exécution "
            "par sprints). Idéal pour projets régulés avec exigences fixes "
            "ET besoin d'agilité dans l'implémentation."
        ),
        "config": {"has_phases": True, "has_sprints": True},
        "statuses": [
            ("backlog", "Backlog", "todo", "#94a3b8", 0, True, False),
            ("phase_started", "Phase started", "wip", "#facc15", 1, False, False),
            ("in_sprint", "In Sprint", "wip", "#fb923c", 2, False, False),
            ("phase_review", "Phase Review", "review", "#a855f7", 3, False, False),
            ("approved", "Approved", "done", "#22c55e", 4, False, True),
            ("blocked", "Blocked", "blocked", "#ef4444", 5, False, False),
        ],
        "roles": [
            ("project_manager", "Project Manager", "Pilotage global + phases.", True, 1, "project_manager"),
            ("agile_lead", "Agile Lead", "Animation sprints d'exécution.", True, 1, "project_manager"),
            ("product_owner", "Product Owner", "Priorise par sprint.", True, 1, "product_manager"),
            ("team_member", "Team Member", "Réalisation.", True, None, "member"),
            ("sponsor", "Sponsor", "Valide les phases majeures.", True, 1, "viewer"),
        ],
        "ceremonies": [
            ("phase_gate", "Phase Gate", "per_phase", 90,
             "## Phase Gate\n\n1. Livrables phase\n2. Go/No-go\n3. Plan phase suivante",
             ["project_manager", "sponsor"], 0),
            ("sprint_planning", "Sprint Planning", "per_sprint", 90,
             "## Sprint Planning\n\n1. Goal\n2. Backlog sélectionné",
             ["agile_lead", "product_owner", "team_member"], 1),
            ("daily", "Daily Standup", "daily", 15,
             "## Daily", ["team_member"], 2),
            ("sprint_review", "Sprint Review", "per_sprint", 60,
             "## Review", ["product_owner", "team_member"], 3),
        ],
        "kpis": [
            ("phase_progress", "Avancement phase", "%", "gauge", "advancement_global", True, 0),
            ("velocity", "Vélocité sprint", "points", "line", "velocity", True, 1),
            ("phase_gate_pass_rate", "Phase Gates passés", "%", "gauge", "phase_gate_pass_rate", False, 2),
            ("schedule_adherence", "Respect planning", "%", "gauge", "schedule_adherence", True, 3),
        ],
        "artifacts": [
            ("project_charter", "Project Charter", "docx", "hybrid.project_charter", True, 0),
            ("phase_plan", "Phase Plan", "docx", "hybrid.phase_plan", True, 1),
            ("sprint_plan", "Sprint Plan", "markdown", "hybrid.sprint_plan", True, 2),
            ("risk_register", "Risk Register", "docx", "hybrid.risk_register", False, 3),
        ],
        "workflows": [{
            "code": "task_default", "name": "Workflow Hybride",
            "applies_to": "task", "is_default": True,
            "transitions": [
                ("backlog", "phase_started", "Démarrer phase", ["project_manager"], False),
                ("phase_started", "in_sprint", "Embarquer dans sprint", ["agile_lead", "product_owner"], False),
                ("in_sprint", "phase_review", "Soumettre revue phase", ["agile_lead"], False),
                ("in_sprint", "blocked", "Bloquer", [], True),
                ("blocked", "in_sprint", "Débloquer", [], False),
                ("phase_review", "approved", "Approuver phase", ["sponsor", "project_manager"], False),
                ("phase_review", "phase_started", "Demander corrections", ["sponsor"], True),
            ],
        }],
        "ai_profile": {
            "persona": "PM Hybride — pragmatique, mix Waterfall + Agile",
            "tone": "directive",
            "capabilities": [
                "phase_planning", "sprint_planning",
                "phase_gate_review", "scope_management",
            ],
            "system_prompt": (
                "Tu es un Project Manager senior expert en approche hybride. "
                "Tu sais quand utiliser Waterfall (cadrage stratégique, "
                "phases gates, contraintes réglementaires) et quand utiliser "
                "Agile (réalisation incrémentale, sprints courts).\n\n"
                "Tu privilégies un cadrage rigoureux EN HAUT (objectifs, "
                "phases, jalons) + des sprints agiles DANS chaque phase pour "
                "l'exécution. Les Phase Gates restent stricts."
            ),
        },
    },
}


def forwards_seed(apps, schema_editor):
    Methodology = apps.get_model("project", "Methodology")
    MethodologyStatus = apps.get_model("project", "MethodologyStatus")
    MethodologyRole = apps.get_model("project", "MethodologyRole")
    MethodologyCeremony = apps.get_model("project", "MethodologyCeremony")
    MethodologyKPI = apps.get_model("project", "MethodologyKPI")
    MethodologyArtifact = apps.get_model("project", "MethodologyArtifact")
    MethodologyWorkflow = apps.get_model("project", "MethodologyWorkflow")
    WorkflowTransition = apps.get_model("project", "WorkflowTransition")
    MethodologyAIProfile = apps.get_model("project", "MethodologyAIProfile")

    for code, spec in METHODOLOGIES.items():
        methodology, _ = Methodology.objects.update_or_create(
            code=code,
            defaults={
                "name": spec["name"], "family": spec["family"],
                "description": spec["description"],
                "icon": spec.get("icon", ""),
                "accent_color": spec.get("accent_color", ""),
                "is_system": True, "is_active": True,
                "config": spec.get("config", {}), "workspace": None,
            },
        )
        # Statuts
        status_map = {}
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
                    "name": k_name, "unit": k_unit, "chart_type": k_chart,
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
                    "is_recommended": a_recommended, "position": a_pos,
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
        # Profil IA
        ai_spec = spec.get("ai_profile")
        if ai_spec:
            MethodologyAIProfile.objects.update_or_create(
                methodology=methodology,
                defaults={
                    "persona": ai_spec["persona"],
                    "system_prompt": ai_spec["system_prompt"],
                    "capabilities": ai_spec.get("capabilities", []),
                    "tone": ai_spec.get("tone", ""),
                    "examples": ai_spec.get("examples", []),
                },
            )


def backwards_drop(apps, schema_editor):
    Methodology = apps.get_model("project", "Methodology")
    Methodology.objects.filter(
        code__in=list(METHODOLOGIES.keys()), is_system=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0049_ai_action_log"),
    ]

    operations = [
        migrations.RunPython(forwards_seed, reverse_code=backwards_drop),
    ]
