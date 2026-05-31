# Audit & Plan d'évolution — DevFlow

**Mission** : évolution progressive de DevFlow en production
**Logique** : production-first — améliorer sans casser
**Périmètre audité** : modèles, vues, services, API, IA, budget/TJM, UX, sécurité prod
**Date** : 28 mai 2026
**Audité par** : Cowork (Anthropic)

---

## Table des matières

1. [Synthèse exécutive](#1-synthese-executive)
2. [Audit de production](#2-audit-de-production)
3. [Plan d'évolution par phases](#3-plan-devolution-par-phases)
4. [Backlog features prioritaires](#4-backlog-features-prioritaires)
5. [Modèles & migrations à prévoir](#5-modeles-migrations-a-prevoir)
6. [Vues & API à ajouter ou modifier](#6-vues-api-a-ajouter-ou-modifier)
7. [Templates Tailwind/Alpine prêts à intégrer](#7-templates-tailwindalpine-prets-a-integrer)
8. [Services métier à factoriser](#8-services-metier-a-factoriser)
9. [Checklist de déploiement production](#9-checklist-de-deploiement-production)
10. [Recommandations anti-régression](#10-recommandations-anti-regression)

---

## 1. Synthèse exécutive

DevFlow est une plateforme Django/Tailwind/Alpine déjà conséquente : environ 70 modèles, 222 vues CBV, 13 viewsets DRF, 21 modules de services, intégration IA multi-providers (OpenAI / Ollama / fallback heuristique), workflow d'approbation budgétaire, génération automatique de structure projet par IA, chat IA contextuel et système de réunions enrichies par IA.

L'architecture de base est saine : mixins maison cohérents (`WorkspaceSecurityMixin`, `DevflowBaseMixin`, `ProjectFinancialPermissionMixin`, `_WorkspaceAccessMixin`), abstraction propre du provider IA (`AIProvider`, `factory.get_ai_provider`), service budgétaire mature (`ProjectBudgetService`), couverture de tests budgétaires correcte (13 tests sur les calculs TJM/marges/forecast).

L'audit révèle néanmoins **trois familles de risques production qui doivent être traitées avant toute évolution majeure** :

1. **Sécurité / multi-tenant** : au moins sept points d'accès ne filtrent pas par workspace (vues FBV `sprint_status_update`, `task_status_update`, `MilestoneListView.get_queryset` qui shunt complètement le filtre parent, `ProjectGenesisAPIView`, plusieurs `MeetingActionItem*View`, et l'ensemble des `ModelViewSet` DRF sans permission object-level). Risque de fuite de données entre tenants et de modifications cross-workspace.
2. **Performance** : pagination court-circuitée dans `ProjectListView` (boucle Python sur tout le queryset), 13 `count()` consécutifs dans `AInsightDashboardView`, 8 `count()` de debug dans `DashboardView`, N+1 sur les imports IA, envois d'e-mails synchrones bloquant la requête HTTP (`notify_task_assignment`, `send_invitation_email`, `notify_pm_task_overdue`) alors que Celery est déjà configuré.
3. **Dette UX & code mort** : 49 templates orphelins, ~30 routes URL probablement non liées depuis l'UI, `task/board.html` réduit à un stub HTML vide, `task/list.html` minimaliste là où le backend expose une dizaine de quick-actions inutilisées côté template.

L'évolution est proposée en **six phases sécurisées** sur environ **10-14 semaines**, chacune isolée par un feature flag et déployable indépendamment. Phase 0 (stabilisation) doit précéder toute introduction de nouveauté. Les phases 1 à 5 introduisent la valeur métier demandée : actions rapides, multi-modes projet, budget renforcé, IA pragmatique enrichie, notifications & rapports IA.

**Aucune migration destructrice** n'est nécessaire pour atteindre la cible : toutes les évolutions schéma sont additives (ajout de champs nullable avec défaut, création de tables, ajout d'index `CONCURRENTLY` sur PostgreSQL). Les transformations sensibles (renommer un modèle, refondre TJM, supprimer un champ) sont écartées du plan.

---

## 2. Audit de production

### 2.1 Architecture générale

Le projet suit une organisation Django classique avec une app principale `project/` qui concentre la quasi-totalité du domaine métier (~14 600 lignes pour `models.py + views.py + forms.py` réunis). La séparation des préoccupations est correcte au niveau des services (`project/services/` contient 21 fichiers métier) et de l'IA (`project/services/ai/` avec son abstraction provider, neuf services métier, un module factory). L'API REST est isolée dans `project/api/` (DRF `ModelViewSet` + drf-spectacular). Le templating utilise Tailwind via CDN (non compilé), Alpine.js (CDN), Chart.js, Flatpickr, SweetAlert2, Tippy, Sortable, TinyMCE et Select2, tous chargés depuis des CDN — l'absence de bundler local rend la version Tailwind dépendante du runtime de la page.

Le projet utilise PostgreSQL en production (à confirmer par `DATABASES`), Redis pour Celery (broker + backend), et un fichier `docker-compose.yml` indique une stack complète. Le `Dockerfile` et le dossier `deploy/` témoignent d'une mise en production réelle. 26 migrations Django composent l'historique entre avril et fin avril 2026, dont deux merges (`0022_merge_*`, `0023_merge_*`) qui signalent des branches Git fusionnées en désordre — c'est un signal faible à confirmer en prod (`SELECT * FROM django_migrations`).

### 2.2 Modèles (`project/models.py`, 3 558 lignes, ~70 modèles)

**Domaines couverts** : Workspace/UserProfile (multi-tenant), Project/ProjectCategory/ProjectMember, Sprint/BacklogItem/BoardColumn, Task/TaskAssignment/TaskComment/TaskAttachment/TaskChecklist/ChecklistItem/TaskDependency/TaskReminder, Team/TeamMembership, Roadmap/RoadmapItem/Milestone/MilestoneTask/Release, Objective/KeyResult, Risk, BillingRate/CostCategory/TimesheetEntry/TimesheetCostSnapshot, ProjectBudget/ProjectEstimateLine/ProjectExpense/ProjectRevenue, Invoice/InvoiceLine/InvoicePayment/InvoiceClient, SprintMetric/SprintReview/SprintRetrospective/SprintFinancialSnapshot, FeatureFinancialSnapshot/ProjectModuleROI/ProjectKPI, AInsight/ProjectAIProposal/ProjectAIProposalItem/ProjectAIProposalLog/AIChatSession/AIChatMessage/ProjectDocumentImport, ProjectMeeting/MeetingAttachment/MeetingActionItem, Notification/ActivityLog/Webhook/Integration/APIKey, DirectChannel/ChannelMembership/Message/MessageAttachment/Reaction, Label/TaskLabel/ProjectLabel, DashboardSnapshot/UserPreference/WorkspaceSettings/WorkspaceInvitation, Workspace.letterhead (13 champs papier en-tête).

**Points forts** :
- Multi-tenant cohérent par `Workspace` foreign key sur la quasi-totalité des modèles.
- Méthodes `clean()` solides sur `Sprint`, `Milestone`, `Risk`, `AInsight`, `BillingRate` (vérification XOR user/team, sale ≥ cost).
- `TextChoices` utilisé presque partout pour les enums.
- Stack budget mature : `BillingRate` versionné, `TimesheetCostSnapshot` figé via signal pour préserver l'historique.

**Points faibles** :
- **Pas de vérification de cohérence workspace au niveau modèle** : un `Task` n'oblige pas à ce que `task.project.workspace == task.workspace`. La protection est entièrement applicative, ce qui crée un risque de fuite si un formulaire est mal protégé.
- **Doublon de `@property`** dans `CostCategory` (lignes 524 et 546) : `is_direct_cost_category` et `is_labor_category` sont définis deux fois ; la seconde version écrase la première (Python). La sémantique de `is_direct_cost_category` se retrouve donc différente de ce qu'on lit en premier — bug potentiel.
- **Coquille `AInsight`** : devrait être `AIInsight`, propagée dans `related_name="ai_insights"`. À conserver pour éviter une migration coûteuse, mais documenter.
- **Double source de vérité TJM** : `BillingRate` (nouveau, propre, versionné) et `UserProfile.cost_per_day` / `billable_rate_per_day` (marqués « legacy » dans le code mais toujours utilisés en fallback).
- **`Project.team` (FK) + `Project.teams` (M2M)** introduits dans deux migrations distinctes coexistent. Le helper `get_assignable_memberships()` (l. 451) les fusionne, mais d'autres parties du code peuvent ne lire qu'un seul côté.
- **`Sprint.total_story_points` / `completed_story_points` / `remaining_story_points`** : trois compteurs persistés, non recalculés par signal — source de désynchronisation silencieuse.
- **Pas de champ `methodology` sur `Project`** : impossible aujourd'hui de discriminer un projet Scrum, Kanban, Waterfall, jalons, terrain, immobilier ou administratif. Tous les projets ont accès à toutes les vues (sprints, kanban, roadmap, milestones simultanément), à la discrétion de l'utilisateur.
- **Aucun modèle pour les modes « terrain », « immobilier », « administratif »** : pas de `FieldReport`, `RealEstateLot`, `AdminCase`, ni de `ProjectPhase` pour le Waterfall séquentiel.
- **Index manquants probables** sur `Task.due_date`, `Task(workspace, status)`, `Project(workspace, status, priority)`, `Notification(recipient, is_read, -created_at)`, `TimesheetEntry(user, entry_date)` — à valider via `EXPLAIN` sur la prod.

**Migrations sensibles** :
- `0006` supprime `ProjectRevenue.is_received` puis `0009` le recrée — hésitation produit.
- `0019_invoicing_and_team_constraints` remplace un `unique_together` par un `UniqueConstraint` conditionnel sur `TeamMembership` — si la production contient des doublons, la migration bloque.
- Double numérotation `0021` puis `0022` résolue par des merges — vérifier que `django_migrations` est aligné en prod.
- Aucune `RunPython` détectée ; l'évolution est purement schéma.

### 2.3 Vues, services, API (`views.py` 8 762 lignes + `views_*.py`)

**Cartographie** :
- ~222 vues CBV organisées en familles `Devflow{List,Detail,Create,Update,Delete,Archive}View`.
- ~10 FBV historiques (`sprint_status_update`, `task_status_update`, `roadmap_item_shift_dates`, `channel_*`).
- 13 `ModelViewSet` DRF (Workspace, Team, Project, ProjectMember, BillingRate, ProjectBudget, ProjectEstimateLine, ProjectRevenue, ProjectExpense, Sprint, Task, Timesheet, AInsight) + actions custom IA (`ai/forecast`, `ai/risk-analysis`, `ai/effort-estimate`, `allocation-advice`, `portfolio`, `budget-overview`).
- Endpoints HTML quick-action déjà présents (`TaskQuickStatusView`, `TaskQuickAssignView`, `TaskKanbanMoveView`, `TaskMarkDoneView`, `TaskExtendView`, `TaskMarkExpiredView`, `TaskToggleFlagView`, `TaskQuickCommentView`, `TaskQuickAttachmentView`) mais pas exposés en JSON DRF.

**Risques critiques de fuite cross-tenant** (à corriger en Phase 0) :

| Endroit | Sévérité | Problème |
|---|---|---|
| `MilestoneListView.get_queryset` (views.py:6701) | **CRITIQUE** | Override total sans appel `super().get_queryset()` — le filtre workspace du parent est court-circuité. Un utilisateur voit tous les jalons de tous les workspaces. |
| `sprint_status_update` (views.py:3850) | **CRITIQUE** | Pas de `@login_required` ni `@require_POST`, `get_object_or_404(dm.Sprint, pk=...)` sans filtre workspace. |
| `task_status_update` (views.py:3889) | **CRITIQUE** | Décorateurs OK mais pas de filtre workspace sur le `get_object_or_404`. |
| `ProjectGenesisAPIView` (views_ai_genesis.py:172) | **CRITIQUE** | `Workspace.objects.filter(pk=workspace_id).first()` sans appel à `_user_can_access_workspace`. |
| DRF `ModelViewSet` (api/viewsets.py) | **HAUTE** | `queryset = dm.Project.objects.filter(is_archived=False)` — aucun filtrage utilisateur. `permission_classes = [IsAuthenticated]` seul. |
| `MeetingActionItem*View` (views_meeting.py:154, 173, 219) | **HAUTE** | `get_object_or_404(dm.ProjectMeeting, pk=...)` sans contrôle workspace. |
| `TaskQuickAttachmentView` / `TaskKanbanMoveView` (views.py:4313, 4336) | **HAUTE** | Incohérence avec les autres `TaskQuick*View` qui filtrent bien. |

**Performances ORM** (à corriger en Phase 0 ou Phase 1) :
- `AInsightDashboardView` (views.py:5350-5366) : 13 `count()` consécutifs dans une boucle sur `InsightType` puis `Severity`. À remplacer par un seul `aggregate(...)` avec `Count('id', filter=Q(...))`.
- `DashboardView.debug_info` (views.py:1227-1234) : 8 `count()` permanents en prod. À gating sur `settings.DEBUG`.
- `ProjectListView.stats` (views.py:1963-2001) : cinq `count()` séparés au lieu d'un seul aggregate.
- `ProjectListView._build_category_sections` (1879-1907) : itère TOUT le queryset (200+ projets) après `get_queryset()`, court-circuitant la pagination de `paginate_by=12`.
- `ProjectBudgetService.regenerate_estimate_lines_from_tasks` (services/budget.py:465-495) : boucle `save()` unitaire, à passer en `bulk_create`.
- `ProjectBudgetService.build_portfolio_overview` (services/budget.py:765-788) : appelle `build_budget_overview` par projet — N×15 requêtes. À remplacer par un agrégat GROUP BY.

**Synchrone bloquant la requête HTTP** :
- `services/notifications.py::notify_task_assignment` envoie l'e-mail synchrone (alors que `send_task_assignment_email_task` Celery existe — utilisée nulle part).
- `services/invitations.py::send_invitation_email` : SMTP sync, `fail_silently=False` → expose les erreurs SMTP dans la vue.
- `services/task_overdue.py::notify_pm_task_overdue` : SMTP sync.

**API DRF — trous de sécurité et d'usage** :
- Pas de throttling (`throttle_classes` absent) sur les actions IA payantes (`ai/forecast`, `ai/risk-analysis`, `ai/effort-estimate`) — un utilisateur peut générer du coût OpenAI illimité.
- Pas de filtrage `get_queryset` par workspace de l'utilisateur sur les `ModelViewSet`.
- Aucun `@extend_schema` custom : la doc Swagger générée par drf-spectacular est pauvre.
- Aucun `IsWorkspaceMember` (à créer).

**Celery** :
- 4 tâches : `send_task_assignment_email_task`, `generate_project_ai_proposal_task`, `run_task_reminder_sweep`, `refresh_project_budget_task`.
- Beat schedule limité : 2 sweeps de rappel/jour (9h et 16h Africa/Abidjan). Pas de `scan_overdue_tasks` automatique, pas de nettoyage notifications, pas de recalibration de budget hebdomadaire.
- Aucun `task_acks_late=True` ni `task_reject_on_worker_lost=True` — risque de tâches perdues si worker SIGKILL.
- Pas de monitoring (Flower / Sentry).

**Code mort** :
- 49 templates orphelins listés dans `outputs_audit/orphan_templates.json` (dont des doublons : `dashboard/analytics.html`, `dashboard/project_detail.html`, `sprint/board.html`, `task/board.html` qui est réduit à un stub HTML vide, `team/*`, `settings/*`).
- ~30 URL names réellement non liés depuis l'UI (le reste est faux positif venant d'allauth, DRF schemas, debug toolbar).
- Doublon `ia_create_view.ProjectDocumentImportView` (FormView legacy) ↔ `ProjectDocumentImportCreateView` (CBV moderne).
- Double système de messaging (`channel_chat_views.py` FBV ↔ `DirectChannel*View` CBV).

### 2.4 Budget & TJM (`services/budget.py` 811 lignes + `views_budget.py` + `tests_budget.py`)

**Architecture en quatre couches** :
```
BillingRate (TJM par user/team, versionné via valid_from/valid_to)
   ↓
TimesheetEntry → TimesheetCostSnapshot (coût figé par signal post_save)
   ↓
ProjectEstimateLine (5 stages × 4 budget_stages : ESTIMATED/BASELINE/FORECAST/RAF)
   ↓
ProjectBudget (1-1 projet : labor/software/infra/subcontract/other + contingency
              + management_reserve + markup_percent + target_margin_percent
              + approved_budget + alert_threshold_percent + overhead + tax)
```

**Workflow** :
- `ProjectExpense` a un workflow d'approbation à deux niveaux (`PENDING → LEVEL1_APPROVED → LEVEL2_APPROVED`, ou `REJECTED`) avec persistance des approbateurs et timestamps. Bonne implémentation, déjà en place.
- `ProjectFinancialPermissionMixin` (views_budget.py:24) borne les vues sensibles aux rôles ADMIN/CTO/PM/PO/TECH_LEAD via `TeamMembership`.

**Tests couverts** (`tests_budget.py`, 13 méthodes) :
- TJM (`test_user_daily_cost_uses_billing_rate`, `test_user_daily_sale_uses_billing_rate`).
- Allocation membre/période (`test_member_period_cost_respects_allocation`).
- Working days (`test_working_days_between`).
- Estimate tasks (`test_estimate_task_costs`, `test_estimate_task_remaining`).
- Summarize revenues/expenses (`test_summarize_revenues_uses_actual_amounts`, `test_summarize_expenses_uses_real_statuses`).
- Build budget overview (`test_build_budget_overview_keys_present`).
- IA budget forecast heuristique (`test_budget_forecast_heuristic_runs`).
- IA risk analysis heuristique (`test_risk_analysis_heuristic_runs`).
- IA effort estimation heuristique (`test_effort_estimation_heuristic`).

**Gaps majeurs** :
- **Pas de modèle `BaselineSnapshot`** : impossible de figer un budget de référence à un instant T pour le comparer au forecast ultérieur.
- **Pas de courbe de consommation temporelle** : aucun stockage de l'historique du `total_estimated_cost` au fil du temps.
- **Pas de TJM spécifique projet** : `BillingRate` est rattaché à `(user, team)` mais pas à `(user, project)`. Impossible d'avoir un tarif négocié différent par projet.
- **Pas de gestion multi-devise** : tout est en `currency` configurable par modèle, mais aucune conversion automatique. Un workspace multi-pays paie au comptant.
- **Pas d'écart EAC** (Estimate at Completion) ni de `Cost Variance` stocké, alors que toutes les briques existent pour le calculer.
- **`ProjectBudget.status` (DRAFT/ESTIMATED/BASELINE/APPROVED/REVISED/CLOSED) n'est pas synchronisé** avec `ProjectEstimateLine.budget_stage` (ESTIMATED/BASELINE/FORECAST/RAF). Deux machines à états parallèles, aucune transition automatique.
- **Alerte de dépassement** : `ProjectBudget.alert_threshold_percent` existe (champ non borné 0-100, à valider), mais aucune tâche Celery ne le déclenche périodiquement. Les notifications sont émises uniquement lors de l'enregistrement d'une dépense — pas de scan global.
- **Pas de prévisions financières IA stockées** : `BudgetForecast` (services/ai/services/budget_forecast.py) retourne un objet `dataclass` éphémère ; rien n'est persisté pour comparer la précision des prévisions IA dans le temps.

### 2.5 IA (`project/services/ai/`)

**Architecture provider** :
- `AIProvider` ABC (`base.py`, 62 lignes) — interface minimale : `generate(messages, temperature, max_tokens, json_mode)` retournant `AIResponse(text, raw, tokens_used, provider, model, metadata)`.
- `OpenAIProvider` : supporte `response_format={"type":"json_object"}`, parse JSON robuste (gère les ` ```json ` markdown).
- `LocalProvider` : compatible OpenAI Chat (Ollama, vLLM, LocalAI), pas de support natif json_mode.
- `_NullProvider` : déclenché par `settings.AI_BACKEND="none"`, force le fallback heuristique.
- `factory.get_ai_provider()` : mode `auto` choisit OpenAI si clé API présente, sinon Local si endpoint configuré, sinon NullProvider.

**Use cases couverts** (`project/services/ai/services/`, 9 modules, ~4 000 lignes) :

| Use case | Fichier | Statut | Pattern |
|---|---|---|---|
| Génération roadmap/sprint/milestone/tâches depuis brief texte | `project_genesis.py` (187 l.) + `project_structure.py` (790 l.) + `proposal_apply.py` (222 l.) | **Présent et mature** | Heuristique 13 phases par défaut + enrichissement LLM |
| Génération depuis document (PDF/DOCX) | `services/project_document_ai_service.py` + `project_import_orchestrator.py` | **Présent** | Extract → prompt → JSON structuré → import atomique |
| Forecast budgétaire | `budget_forecast.py` (234 l.) | **Présent** | Heuristique TJM × allocation × durée + enrichissement qualitatif IA |
| Analyse de risques | `risk_analysis.py` (261 l.) | **Présent** | Signaux quantitatifs (retards, dépassement, vélocité) + analyse qualitative LLM, persistance en `AInsight` type RISK |
| Recommandations d'allocation | `allocation_advice.py` (206 l.) | **Présent** | Heuristique de charge équipe + suggestion IA |
| Estimation des délais (effort) | `effort_estimation.py` (155 l.) | **Présent** | Heuristique points/complexité + ajustement IA |
| Chat assistant contextuel | `chat.py` (1 556 l.) | **Présent** | `DevFlowContextBuilder` injecte sprint actif, vélocité, projets à risque, charge équipe ; intents pré-câblés (analyse sprint, projets à risque, rapport, charge) qui répondent factuellement même IA HS |
| Intelligence des réunions | `meeting_intelligence.py` (285 l.) | **Présent** | Synthèse + extraction d'action items |
| Résumé projet ad-hoc | À ajouter | **Absent en endpoint dédié** | Existe partiellement via le chat (intent) |
| Streaming SSE/WebSocket | À ajouter | **Absent** | Tous les services renvoient en full-buffer, donc requêtes HTTP de 20-40s |

**Fiabilité** :
- Tous les services suivent le même pattern : heuristique déterministe garantie + enrichissement IA optionnel en `try/except`. Bon découplage, robuste si l'IA tombe.
- Pas de retries automatiques au niveau provider (juste Celery `max_retries=2` sur `generate_project_ai_proposal_task`).
- `parse_json` côté OpenAIProvider tolère les artefacts markdown — propre.

**Coûts & quotas** :
- `AIResponse.tokens_used` est tracé partout. Persisté dans `ProjectAIProposal.tokens_used` et `AIChatMessage.tokens_used`.
- **Aucun quota au niveau workspace** : pas de `AIUsageQuota` ni de garde-fou en amont. Un utilisateur peut spammer les endpoints IA sans limite.
- **Pas de throttling DRF** sur les actions IA.

**Prompts** :
- `project/services/ai/prompts/` ne contient que `__init__.py` — **les prompts sont hardcodés inline dans les services**. Pas de versioning, pas de bibliothèque, pas d'i18n explicite. Tous en français.
- Pas de modèle `AIPromptTemplate` pour personnalisation workspace.
- Contexte injecté limité aux données nécessaires (pas de fuite massive de données privées), mais aucune anonymisation explicite des e-mails utilisateurs ni des noms — à valider pour RGPD si on l'envoie à un provider tiers.

**Gaps** :
- Pas de streaming (réponses longues retournées en full-buffer).
- Pas d'endpoint `/api/v1/projects/<id>/ai/summary/` ni `/recommendations/` ni `/generate-roadmap/?stream=true`.
- `LocalProvider.is_available` ne pingue jamais l'endpoint Ollama — l'échec n'est détecté qu'à l'appel `generate`. À améliorer par un cache TTL court.
- Le `chat.py` (1 556 lignes) commence à concentrer trop de responsabilités ; à refactorer en sous-modules quand on ajoutera le streaming.

### 2.6 UX & templates

**Stack** : Tailwind via CDN (`https://cdn.tailwindcss.com`), Alpine.js, Chart.js, Flatpickr, SweetAlert2, Tippy, Sortable, TinyMCE, Select2. Pas de bundler local (Vite/Webpack absent), pas de compilation Tailwind locale — la couleur du thème est définie via CSS variables (`--bg`, `--accent`, etc.) consommées par les classes Tailwind custom (`devbg`, `devaccent`). Theme switcher light/dark fonctionnel (`data-theme` + `localStorage`).

**Layout principal** (`templates/layout/base.html`) :
- Stable, cohérent.
- Topbar avec barre de recherche déclenchant un command palette (`openPalette()`), panel notifications (`toggleNotif()`), panel IA (`openAI()`).
- Sidebar (`_sidebar.html`) avec une navigation très exhaustive : exposition CRUD séparée pour `task_comment_list`, `task_attachment_list`, `task_dependency_list`, `task_checklist_list`, `checklist_item_list`, `board_column_list`, `task_assignment_list`. **Trop granulaire** — ces vues sont des sous-objets de Task et ne devraient pas être des items de navigation principale. Charge cognitive élevée.

**Dashboard** (`templates/dashboard/index.html`) :
- Riche : bannière IA cliquable, cards d'analyse colorées par sévérité, sprint banner avec progress story points, kanban du sprint actif, table des projets, graphique de vélocité, distribution des tâches.
- Aucune vue « Mes actions du jour » dédiée n'existe — c'est l'un des gros manques produit identifiés par la mission.

**Vues task** :
- `templates/task/list.html` : **table très minimaliste** (6 colonnes : titre, projet, assigné, statut, priorité, échéance, badge statique). Aucun filtre, aucun quick-action, aucun mode kanban. Alors que `TaskListView` côté backend gère déjà un mode kanban (avec `BoardColumn`) et expose 9 quick-actions.
- `templates/task/board.html` : **stub HTML vide** (`<!DOCTYPE html><html><head>...</head><body></body></html>`). Aucun rendu kanban.
- `templates/task/detail.html` : riche, composant Alpine.js dédié pour la visualisation de documents, onglets, actions.
- `templates/task/backlog.html`, `form.html` : présents, fonctionnels.

**Vues projet** :
- `templates/project/detail.html` : très riche (onglets `tab='planification'`, lecteur de documents multi-format Alpine.js, actions menu). 8 sous-dossiers (`activity_log/`, `ai_genesis/`, `ai_import/`, `ai_insight/`, `ai_proposal/`, `api_key/`, `backlog_item/`, etc.) — granularité par modèle, ce qui aboutit à plus de 30 sous-dossiers de templates dans `project/`.

**Composants** :
- `templates/components/` ne contient que `list_search_bar.html` + un dossier `forms/`. **Bibliothèque de composants quasi inexistante**.
- `templates/partials/` contient une dizaine de partials (kanban_board, stats_cards, projects_table, ai_banner, sprint_banner, velocity_chart, team_workload…). Réutilisés depuis le dashboard.
- Pas de système de design tokens documenté ni de Storybook.

**Feedbacks visuels** :
- SweetAlert2 chargé mais utilisation non systématique.
- `templates/layout/_toast_container.html` existe (placeholder probable) — à vérifier l'usage.
- Pas de loader global ni de skeleton sur les listes longues.
- États vides présents (`{% empty %}Aucune tâche disponible.{% endfor %}`) mais textes secs sans illustration ni call-to-action.

**Accessibilité** :
- Labels sur la plupart des formulaires (via `BaseStyledModelForm`).
- Pas d'attribut `aria-*` détecté dans le topbar (recherche, notifications, AI panel).
- Couleurs : `var(--accent)`, `var(--text1/2/3)` — contraste à valider en mode light.

**Mobile** :
- `grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3` utilisé sur les cards — responsive partiel.
- Pas de menu burger explicite repéré sur le sidebar — à valider <768px.

**Templates orphelins** (49 listés) : la plupart sont des templates concurrents non utilisés (`dashboard/analytics.html`, `dashboard/project_detail.html`, `dashboard/sprint_detail.html`, `dashboard/team_detail.html`, `sprint/board.html`, `sprint/burndown.html`, `task/board.html` = stub vide, `team/*`, `settings/*`, `objective/*` sans préfixe `project/`). À isoler dans `templates/_legacy/` puis purger après une release sans incident.

### 2.7 Score de maturité par axe

| Axe | Score /10 | Commentaire |
|---|---|---|
| Architecture domaine | 7 | Modèles riches, cohérents, mais quelques doublons et incohérences (TJM legacy, story points, properties dupliquées). |
| Sécurité multi-tenant | 4 | Mixins maison solides MAIS plusieurs trous critiques en FBV, DRF et certains override `get_queryset`. À durcir d'urgence. |
| Performance | 5 | Bons réflexes (`select_related`, `prefetch_related` partout), mais quelques vues lourdes (Dashboard, AInsightDashboard, ProjectList pagination court-circuitée). |
| Tests | 4 | `tests_budget.py` correct (13 méthodes), `tests.py` quasi vide. Pas de tests de vues, ni DRF, ni IA. |
| IA | 7 | Architecture provider mature, 9 services, fallback heuristique systématique. Manque streaming, quotas, bibliothèque de prompts. |
| Budget/TJM | 7 | Cycle complet implémenté, workflow approbation présent. Manque baseline snapshot, EAC, multi-devise. |
| UX/UI | 5 | Layout cohérent, dashboard riche, MAIS `task/list.html` minimaliste, `task/board.html` stub vide, pas de vue « ma journée », pas de bibliothèque de composants. |
| Code mort | 5 | ~30 vrais templates orphelins, doublons (ia_create_view, channel_chat_views, dashboard concurrents). |
| Observabilité prod | 3 | Pas de monitoring Celery, pas de Sentry visible, pas de feature flags, pas d'audit log des actions sensibles. |

---

## 3. Plan d'évolution par phases

Six phases progressives, chacune isolée par un feature flag, déployable indépendamment. Aucune phase ne casse la précédente. Durée totale estimée 10-14 semaines.

### Phase 0 — Stabilisation production (durée 1-2 semaines)

**Objectif** : éliminer les risques de fuite cross-tenant et les coûts de performance évidents avant toute évolution. Aucun changement fonctionnel visible utilisateur.

**Tâches** :
1. Corriger `MilestoneListView.get_queryset` (réintégrer `super().get_queryset()`).
2. Ajouter `@login_required` + `@require_POST` + filtre workspace sur `sprint_status_update` et `task_status_update`.
3. Durcir `ProjectGenesisAPIView` avec le mixin `_WorkspaceAccessMixin`.
4. Créer `IsWorkspaceMember` DRF permission, l'appliquer aux 13 viewsets, filtrer `get_queryset` par workspace user.
5. Filtrer `projects_filter`, `sprints_filter`, `assignable_users` dans `TaskListView.get_context_data` par workspace courant.
6. Corriger `MeetingActionItemConvertToTaskView`, `MeetingActionItemCreateView`, `MeetingAIProcessView` (filtre workspace + try/except qui swallow).
7. Convertir les trois envois d'e-mails synchrones en wrappers Celery (`send_task_assignment_email_task` existe déjà, l'appeler).
8. Désactiver `DashboardView.debug_info` sauf `settings.DEBUG=True`.
9. Refactorer `AInsightDashboardView` (13 count → 1 aggregate).
10. Refactorer `ProjectListView.stats` (5 count → 1 aggregate).
11. Ajouter throttling DRF (`UserRateThrottle`) sur les actions IA (`ai/forecast`, `ai/risk-analysis`, `ai/effort-estimate`, `allocation-advice`).
12. Ajouter des index DB additifs (migration `AddIndex` avec `CONCURRENTLY` côté Postgres) sur les 5 paires de champs listées.
13. Activer `task_acks_late=True` et `task_reject_on_worker_lost=True` sur Celery.
14. Ajouter une migration vérifiant l'absence de doublons préalables à toute future `UniqueConstraint`.
15. Documenter dans `AGENTS.md` la convention « toute nouvelle vue d'objet métier doit appeler `super().get_queryset()` ou utiliser `filter_by_workspace` ».

**Livrables Phase 0** :
- 1 PR « security hardening » (points 1-6).
- 1 PR « celery async emails » (point 7).
- 1 PR « perf quick wins » (points 8-10).
- 1 PR « DRF throttle + permission » (points 4, 11).
- 1 PR « DB indexes » (point 12).
- 1 PR doc + worker config (points 13-15).

**Risque** : très faible. Toutes les corrections sont défensives (pas de changement de comportement métier).

**Tests à ajouter** : un test par fuite cross-tenant corrigée (user A ne peut pas modifier le sprint de user B), un test DRF qui vérifie que `GET /api/v1/projects/?workspace=42` ne retourne rien si l'utilisateur n'est pas membre.

### Phase 1 — UX rapide & actions (durée 2-3 semaines)

**Objectif** : livrer la valeur utilisateur immédiate demandée par la mission — actions rapides, vue « Mes actions du jour », réduction du nombre de clics.

**Feature flag** : `FEATURE_QUICK_ACTIONS=True` (par workspace via `WorkspaceSettings.feature_quick_actions`).

**Tâches** :
1. Refondre `templates/task/list.html` : vue kanban + liste switchable, filtres rapides (statut, assigné, échéance), barre de quick-actions (changer statut, assigner, snoozer, marquer terminé) accessibles inline sans rechargement.
2. Construire `templates/task/board.html` (actuellement stub vide) en composant Alpine.js + SortableJS, branché sur les endpoints existants `TaskKanbanMoveView`, `TaskQuickStatusView`.
3. Créer la vue `MyDayView` (`/my-day/`) qui agrège pour l'utilisateur connecté : tâches dues aujourd'hui, en retard, en cours, action items issus des réunions, notifications non lues, suggestions IA. Template `templates/devflow/my_day.html` engageant (citation matinale, météo des tâches, célébration des tâches terminées).
4. Endpoints DRF JSON pour les quick-actions :
   - `POST /api/v1/tasks/{id}/toggle-complete/`
   - `POST /api/v1/tasks/{id}/update-status/` (body : `status`)
   - `POST /api/v1/tasks/{id}/snooze/` (body : `until` ISO date) — nécessite champ `Task.snoozed_until`.
   - `POST /api/v1/tasks/{id}/quick-assign/` (body : `user_id?`)
   - `POST /api/v1/tasks/{id}/move-kanban/` (body : `column_id`, `position`)
   - `GET /api/v1/me/today/`
5. Composant toast global Alpine.js (`templates/layout/_toast_container.html` à finir) + helpers JS `window.devflowToast(message, type)`.
6. Simplifier la sidebar : regrouper les items « comments », « attachments », « dependencies », « checklists », « board columns », « task assignments » dans un sous-menu « Détails tâches » (ou les retirer complètement et n'exposer ces vues que depuis le détail tâche).
7. Ajouter des raccourcis clavier globaux (Alpine.js + listener `keydown`) : `J/K` pour navigation entre tâches, `C` pour terminer, `S` pour snoozer, `?` pour l'aide.
8. Empty states refondus avec illustration SVG + call-to-action explicite.
9. Skeleton loaders sur les listes longues (tâches, projets, notifications).

**Livrables Phase 1** :
- Migration `Task.snoozed_until = DateTimeField(null=True, blank=True)`.
- Module `project/views_my_day.py` (60 lignes estimées) + template.
- Refactor `templates/task/list.html` + nouveau `templates/task/board.html`.
- 6 endpoints DRF dans `project/api/views_quick.py` (nouveau fichier) + ajouts dans `api/urls.py`.
- Composant toast réutilisable + 3-4 SVG d'empty state.
- Doc raccourcis clavier dans le command palette.

**Risque** : faible. Aucune modification de modèle critique. Le seul ajout schéma est `Task.snoozed_until`, nullable.

### Phase 2 — Multi-modes projet (durée 2-3 semaines)

**Objectif** : permettre de typer un projet par méthodologie et d'adapter l'UI selon le mode (Scrum, Kanban, Agile, Waterfall, Jalons, Terrain, Immobilier, Administratif).

**Feature flag** : `FEATURE_MULTI_MODE=True`.

**Tâches** :
1. Ajouter `Project.methodology = CharField(choices=Methodology.choices, default='AGILE', db_index=True)` (migration additive).
2. Créer `ProjectPhase` (Waterfall) : `project`, `name`, `position`, `status`, `start_date`, `end_date`, `gate_required`, `progress_percent`.
3. Créer `FieldReport` (Terrain) + `FieldReportPhoto`.
4. Créer `RealEstateLot` (Immobilier).
5. Créer `AdminCase` (Administratif).
6. Étendre `BacklogItem.ItemType` avec `PHASE`, `DELIVERABLE`, `LOT`.
7. Ajouter `BoardColumn.phase = ForeignKey(ProjectPhase, SET_NULL, null=True)` pour pouvoir grouper les colonnes par phase en Waterfall.
8. Créer `ProjectViewPreference` : par `(user, project)`, stocker la vue par défaut (KANBAN/LIST/GANTT/CALENDAR/PHASES/MAP).
9. Adapter le formulaire `ProjectForm` : champ `methodology` visible, masque/affiche les champs et onglets selon la méthodologie sélectionnée (Alpine.js).
10. Adapter `templates/project/detail.html` : les onglets disponibles dépendent de `project.methodology` (Sprints + Backlog seulement si Scrum, Phases si Waterfall, FieldReports si Terrain, Lots si Immobilier, AdminCases si Administratif).
11. Templates dédiés par mode :
    - `templates/project/modes/waterfall.html` : timeline Gantt simple via SVG ou Chart.js.
    - `templates/project/modes/field.html` : feed de rapports terrain avec photos miniatures + carte.
    - `templates/project/modes/real_estate.html` : grille de lots avec statut et acquéreur.
    - `templates/project/modes/administrative.html` : table de dossiers avec SLA et deadlines.
12. Endpoints DRF :
    - `GET/POST /api/v1/projects/{id}/phases/`
    - `GET/POST /api/v1/projects/{id}/field-reports/` + photo upload
    - `GET/POST /api/v1/projects/{id}/real-estate-lots/`
    - `GET/POST /api/v1/projects/{id}/admin-cases/`
13. Adapter `ProjectAIImportService` et `ProjectGenesisService` pour qu'ils lisent `project.methodology` et génèrent la bonne structure (sprints si Scrum, phases si Waterfall, etc.). Ajustement de `project_structure.py`.
14. Adapter les filtres de `ProjectListView` : nouveau filtre `methodology`.

**Livrables Phase 2** :
- Migration `0024_project_methodology`.
- Migration `0025_project_phase_field_report_real_estate_lot_admin_case`.
- Migration `0026_backlog_item_extend_choices_boardcolumn_phase_project_view_preference`.
- 4 templates de mode + adapter `project/detail.html`.
- 4 endpoints DRF + serializers.
- Refactor IA `project_structure.py` (60-80 lignes).
- Tests : un test par méthodologie qui vérifie que l'IA Genesis génère bien la bonne structure.

**Risque** : moyen. Le champ `methodology` modifie le comportement de Genesis IA et de l'UI projet — feature flag obligatoire et campagne de communication aux utilisateurs existants (par défaut, leurs projets restent en `AGILE`, comportement identique à aujourd'hui).

### Phase 3 — Budget & TJM renforcés (durée 1-2 semaines)

**Objectif** : combler les gaps budget identifiés — baseline snapshot, EAC, alertes périodiques, prévisions IA persistées.

**Feature flag** : `FEATURE_BUDGET_V2=True`.

**Tâches** :
1. Créer `ProjectBudgetSnapshot` : `project`, `label`, `snapshot_date`, `payload JSONField` (figer tous les chiffres `ProjectBudget` + agrégats `EstimateLine` à la date).
2. Endpoint `POST /api/v1/projects/{id}/budgets/snapshot/` → crée un snapshot baseline manuel ou automatique.
3. Vue HTML `templates/project/budget/snapshots.html` : liste des snapshots avec comparaison côte-à-côte (Baseline V1 vs Forecast actuel).
4. Tâche Celery beat `scan_budget_overruns` (1×/jour) qui parcourt tous les projets actifs, calcule `budget_consumption_percent`, et émet une `Notification` + `AInsight` si seuil `ProjectBudget.alert_threshold_percent` dépassé.
5. Ajouter `Project.computed_eac` et `Project.computed_cost_variance` (champs `DecimalField` recalculés par tâche périodique, non saisis utilisateur) pour ne pas recalculer à chaque affichage.
6. Persister les forecasts IA : modèle `ProjectBudgetForecastRun` (snapshot d'un `BudgetForecast` IA à une date donnée) pour mesurer la précision IA dans le temps.
7. Ajouter `BillingRate` : `is_internal_cost`, `is_billable_rate` déjà présents — étendre `BillingRate` avec `project` (nullable, FK) pour permettre un TJM négocié projet-spécifique.
8. Corriger le doublon de `@property` dans `CostCategory` (lignes 524-559).
9. Cohérence `ProjectBudget.status` ↔ `ProjectEstimateLine.budget_stage` : ajouter une méthode `ProjectBudget.transition_to(status)` qui propage le `budget_stage` sur les lignes actives, et désactiver les transitions arbitraires hors d'une whitelist (DRAFT → ESTIMATED → BASELINE → APPROVED → REVISED → CLOSED).
10. Endpoint `GET /api/v1/projects/{id}/budgets/alerts/` qui retourne les alertes actives + historique.

**Livrables Phase 3** :
- 3 migrations additives (`ProjectBudgetSnapshot`, `ProjectBudgetForecastRun`, `BillingRate.project`).
- 1 migration data optionnelle qui crée un snapshot initial pour chaque `ProjectBudget` existant (idempotente).
- Tâche Celery `scan_budget_overruns` + cron beat 6h Africa/Abidjan.
- Vue HTML snapshots + endpoint DRF.
- 3-4 tests supplémentaires dans `tests_budget.py`.

**Risque** : faible-moyen. Le seul point sensible est la création automatique du snapshot initial — à faire en `RunPython` idempotent avec `try/except` sur chaque projet.

### Phase 4 — IA pragmatique enrichie (durée 2-3 semaines)

**Objectif** : compléter la couche IA — résumé projet, recommandations, génération streaming, bibliothèque de prompts, quotas workspace.

**Feature flag** : `FEATURE_AI_V2=True`.

**Tâches** :
1. Créer `AIPromptTemplate` (workspace, name, intent, template, is_default).
2. Migrer les prompts hardcodés des 9 services vers `AIPromptTemplate` (seed par data migration).
3. Créer `AIUsageQuota` (workspace, monthly_token_limit, monthly_tokens_used, period_start) + signal `post_save Workspace` pour seeder, + check préalable à chaque appel provider.
4. Implémenter un mode streaming pour le chat IA : endpoint SSE `GET /api/v1/ai/chat/stream/<session_id>/` + adaptation `OpenAIProvider.generate_stream()`.
5. Endpoint `GET /api/v1/projects/{id}/ai/summary/` : résumé projet 3 paragraphes (état d'avancement, risques principaux, recommandations).
6. Endpoint `GET /api/v1/projects/{id}/ai/recommendations/` : recommandations d'action prioritaires (top 5).
7. Endpoint `POST /api/v1/projects/{id}/ai/generate-roadmap/?stream=true` : génération de roadmap streamée.
8. Améliorer `LocalProvider.is_available` avec un ping HTTP `HEAD /v1/models` mis en cache 60 secondes (au lieu de toujours retourner True).
9. Refactorer `chat.py` (1556 lignes) en sous-modules : `chat/context.py`, `chat/intents.py`, `chat/streaming.py`, `chat/service.py`.
10. Page admin `templates/project/ai/library.html` pour gérer les `AIPromptTemplate` et `AIUsageQuota` par workspace.
11. Anonymisation optionnelle des données envoyées à OpenAI : si `WorkspaceSettings.ai_pii_anonymize=True`, remplacer les emails et noms personnels par des tokens avant l'envoi.

**Livrables Phase 4** :
- 2 migrations (`AIPromptTemplate`, `AIUsageQuota`).
- Data migration de seed des prompts par défaut.
- 4 endpoints DRF + serializers.
- Page admin + UX modifiable.
- Refactor `chat.py` en 4 sous-modules (~400 lignes chacun).
- Tests : un test par endpoint, un test de quota dépassé qui retourne `429 Too Many Requests`.

**Risque** : moyen. Le passage en streaming exige du frontend des modifications du chat panel (`templates/layout/_ai_panel.html`). À faire derrière feature flag.

### Phase 5 — Notifications intelligentes & rapports IA (durée 2 semaines)

**Objectif** : transformer les notifications en flux intelligent (regroupement, priorité) et produire des rapports projet auto-générés par IA.

**Feature flag** : `FEATURE_SMART_NOTIFS=True`, `FEATURE_AI_REPORTS=True`.

**Tâches** :
1. Modèle `NotificationDigest` : agrégation périodique (`hourly`/`daily`) par utilisateur, regroupant N notifications de même `notification_type` ou même projet.
2. Service `services/smart_notifications.py` : règles de regroupement, throttle (« 3+ tâches assignées dans la même heure » → 1 seule notif), priorisation par sévérité.
3. Préférences utilisateur (`UserPreference`) : canaux (in-app/email/digest), fréquence (immédiat/horaire/quotidien), heures de calme.
4. Email digest quotidien (8h Africa/Abidjan) via Celery beat : récap des actions en attente, des projets à risque, des notifications non lues.
5. Modèle `ProjectAIReport` (project, period_start, period_end, content_markdown, generated_at, used_provider, status). Tâche Celery `generate_project_weekly_report_task` (lundi 6h).
6. Endpoint `GET /api/v1/projects/{id}/ai/reports/` (liste) + `POST /api/v1/projects/{id}/ai/reports/generate/` (sync ou async).
7. Vue HTML `templates/project/ai_reports/list.html` + `detail.html` (rendu markdown du rapport).
8. Notification dédiée quand un rapport est prêt + lien direct.
9. Webhook pour envoyer les rapports à Slack ou e-mail externe.

**Livrables Phase 5** :
- 3 migrations additives (`NotificationDigest`, `UserPreference.channels_*`, `ProjectAIReport`).
- 2 services (`smart_notifications.py`, extension `services/ai/services/project_report.py`).
- 2 endpoints DRF + 2 vues HTML.
- 2 tâches Celery + beat schedule.
- Tests : digest avec 10 notifs → 1 email, génération de rapport idempotente.

**Risque** : faible-moyen. Le digest e-mail doit éviter de spammer en cas de panne provider — ajouter un cooldown et un opt-out facile.

### Synthèse phases

| Phase | Durée | Risque | Valeur métier |
|---|---|---|---|
| 0 — Stabilisation | 1-2 sem | Très faible | Sécurité prod + perf |
| 1 — UX rapide | 2-3 sem | Faible | Engagement utilisateur (gain de clics) |
| 2 — Multi-modes | 2-3 sem | Moyen | Élargissement du marché (terrain, immobilier, administratif) |
| 3 — Budget V2 | 1-2 sem | Faible-moyen | Pilotage financier précis |
| 4 — IA V2 | 2-3 sem | Moyen | Différenciation produit |
| 5 — Notif & rapports | 2 sem | Faible-moyen | Productivité quotidienne |

---

## 4. Backlog features prioritaires

Liste consolidée des features demandées par la mission, mappées aux phases.

| # | Feature | Phase | Effort | Statut actuel |
|---|---|---|---|---|
| 1 | Actions rapides sur les tâches | 1 | M | Backend existe (TaskQuick*View), frontend à exposer en JSON |
| 2 | Mise à jour en un clic des statuts | 1 | S | Backend existe, manque l'endpoint DRF JSON |
| 3 | Vue « Mes actions du jour » | 1 | M | Absent — à créer |
| 4 | Alertes projets à risque | 3 | M | `RiskAnalysisService` existe, manque la diffusion via Notification |
| 5 | Recommandations IA | 4 | M | `AllocationAdviceService` + endpoint à exposer |
| 6 | Génération auto roadmap/sprint/milestone/tâches | 2 + 4 | L | `ProjectGenesisService` existe, à adapter pour multi-modes |
| 7 | Support multi-modes projet (8 méthodologies) | 2 | XL | Absent — phase la plus lourde |
| 8 | Tableaux de bord plus dynamiques | 1 + 5 | M | Dashboard riche existant, à enrichir par graphes temps réel |
| 9 | Notifications intelligentes | 5 | M | Système notif basique, à enrichir (digest, regroupement) |
| 10 | Rapports projet générés par IA | 5 | M | Absent — à créer (`ProjectAIReport`) |

**Priorisation recommandée** : 0 → 1 → 2 → 3 → 4 → 5 (séquentiel pour éviter les conflits de migration). Possibilité de paralléliser 3 et 4 si deux développeurs.

---

## 5. Modèles & migrations à prévoir

### 5.1 Migrations Phase 0 (sécurité + perf)

Aucune nouvelle migration de schéma. Uniquement des migrations `AddIndex` pour :

```python
# project/migrations/00XX_add_indexes_perf.py
from django.db import migrations, models

class Migration(migrations.Migration):
    atomic = False  # nécessaire pour CONCURRENTLY sur Postgres
    dependencies = [("project", "0023_merge_...")]
    operations = [
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["workspace", "status"], name="task_ws_status_idx"),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["due_date"], name="task_due_date_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["recipient", "is_read", "-created_at"], name="notif_unread_idx"),
        ),
        migrations.AddIndex(
            model_name="timesheetentry",
            index=models.Index(fields=["user", "entry_date"], name="ts_user_date_idx"),
        ),
        migrations.AddIndex(
            model_name="project",
            index=models.Index(fields=["workspace", "status", "priority"], name="proj_ws_status_prio_idx"),
        ),
    ]
```

> En Postgres, transformer en `RunSQL(\"CREATE INDEX CONCURRENTLY ...\")` pour éviter de verrouiller la table. À tester avec `--plan` puis `--fake-initial` si nécessaire.

### 5.2 Migrations Phase 1 (UX rapide)

```python
# Task.snoozed_until
class Migration(migrations.Migration):
    dependencies = [("project", "00XX_add_indexes_perf")]
    operations = [
        migrations.AddField(
            model_name="task",
            name="snoozed_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
```

### 5.3 Migrations Phase 2 (multi-modes)

Trois migrations additives :

```python
# 1) Project.methodology
migrations.AddField(
    model_name="project",
    name="methodology",
    field=models.CharField(
        max_length=20,
        choices=[
            ("SCRUM", "Scrum"), ("KANBAN", "Kanban"), ("AGILE", "Agile"),
            ("WATERFALL", "Waterfall"), ("MILESTONE", "Jalons"),
            ("FIELD", "Terrain"), ("REAL_ESTATE", "Immobilier"),
            ("ADMINISTRATIVE", "Administratif"),
        ],
        default="AGILE",
        db_index=True,
    ),
),

# 2) ProjectPhase, FieldReport, FieldReportPhoto, RealEstateLot, AdminCase
# (CreateModel pur — aucune ré-écriture de table existante)

# 3) BoardColumn.phase FK nullable + BacklogItem.item_type choices étendus
#    + ProjectViewPreference (CreateModel)
```

### 5.4 Migrations Phase 3 (budget V2)

```python
# ProjectBudgetSnapshot
class ProjectBudgetSnapshot(models.Model):
    project = models.ForeignKey("project.Project", on_delete=models.CASCADE,
                                 related_name="budget_snapshots")
    label = models.CharField(max_length=80)
    snapshot_date = models.DateField()
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

# ProjectBudgetForecastRun (persistance des forecasts IA)
# BillingRate.project = ForeignKey(Project, SET_NULL, null=True, blank=True)
# Project.computed_eac, Project.computed_cost_variance (DecimalField default=0)
```

### 5.5 Migrations Phase 4 (IA V2)

```python
# AIPromptTemplate, AIUsageQuota
# + data migration de seed des prompts

class Migration(migrations.Migration):
    dependencies = [...]
    operations = [
        migrations.CreateModel("AIPromptTemplate", ...),
        migrations.CreateModel("AIUsageQuota", ...),
        migrations.RunPython(seed_default_prompts, reverse_code=migrations.RunPython.noop),
    ]
```

### 5.6 Migrations Phase 5 (notifs & rapports)

```python
# NotificationDigest, ProjectAIReport
# + UserPreference.channel_*, notify_frequency, quiet_hours_*
```

### 5.7 Recommandations transverses

- **Toutes les migrations sont additives**. Aucune `RemoveField`, aucun `AlterField` qui réduit `max_length` ou rend NOT NULL un champ existant.
- **Aucun renommage** de modèle ou de champ existant — même la coquille `AInsight` est conservée.
- **Tester chaque migration en dry-run sur une copie de la base prod** avant déploiement.
- **Tester la migration `0019_invoicing_and_team_constraints` rétroactivement** : si la prod contient des doublons `TeamMembership(user, team=NULL)`, la contrainte conditionnelle bloquera lors d'un futur `migrate --plan`.
- **Verrouiller la concurrence** lors du déploiement : si possible, mettre l'app en mode lecture seule 5 secondes le temps que les migrations `AddIndex CONCURRENTLY` se posent.

---

## 6. Vues & API à ajouter ou modifier

### 6.1 Vues HTML à ajouter

| Vue | Phase | Template |
|---|---|---|
| `MyDayView` | 1 | `templates/devflow/my_day.html` |
| Vue refondue `task/list.html` (kanban + liste) | 1 | `templates/task/list.html` (refonte) |
| Vue kanban réelle `task/board.html` | 1 | `templates/task/board.html` (création) |
| `ProjectModeWaterfallView` | 2 | `templates/project/modes/waterfall.html` |
| `ProjectModeFieldView` | 2 | `templates/project/modes/field.html` |
| `ProjectModeRealEstateView` | 2 | `templates/project/modes/real_estate.html` |
| `ProjectModeAdministrativeView` | 2 | `templates/project/modes/administrative.html` |
| `ProjectPhaseListView`, `*CreateView`, `*UpdateView`, `*DeleteView` | 2 | `templates/project/phase/*.html` |
| `FieldReportListView`, `*Create`, `*Detail` | 2 | `templates/project/field_report/*.html` |
| `RealEstateLotListView`, `*Create`, `*Update` | 2 | `templates/project/real_estate_lot/*.html` |
| `AdminCaseListView`, `*Create`, `*Update` | 2 | `templates/project/admin_case/*.html` |
| `ProjectBudgetSnapshotListView`, `*CreateView`, `*CompareView` | 3 | `templates/project/budget/snapshots.html` |
| `AIPromptTemplateListView`, `*CreateView`, `*UpdateView` | 4 | `templates/project/ai/library.html` |
| `ProjectAIReportListView`, `*DetailView` | 5 | `templates/project/ai_reports/*.html` |

### 6.2 Vues HTML à modifier

| Vue | Phase | Modification |
|---|---|---|
| `MilestoneListView.get_queryset` | 0 | Appeler `super().get_queryset()` |
| `sprint_status_update` | 0 | Ajouter `@login_required @require_POST` + filtre workspace |
| `task_status_update` | 0 | Filtre workspace |
| `ProjectGenesisAPIView` | 0 | Mixin `_WorkspaceAccessMixin` |
| `TaskListView.get_context_data` | 0 + 1 | Filtres par workspace + nouvelle structure kanban/liste |
| `AInsightDashboardView` | 0 | Remplacer 13 count par 1 aggregate |
| `ProjectListView.stats` | 0 | 5 count → 1 aggregate |
| `DashboardView` | 0 + 1 | Désactiver debug_info, ajouter widget « ma journée » |
| `ProjectDetailView` | 2 | Adapter les onglets selon `project.methodology` |
| `ProjectForm` | 2 | Champ `methodology` + masque dynamique |
| `MeetingActionItemConvertToTaskView`, `*CreateView`, `MeetingAIProcessView` | 0 | Filtre workspace |
| `ProjectBudgetService.regenerate_estimate_lines_from_tasks` | 0 | `bulk_create` |
| `ProjectBudgetService.build_portfolio_overview` | 0 | Agrégat GROUP BY |

### 6.3 Endpoints DRF à ajouter

**Phase 0** (sécurité) :
- Permission `IsWorkspaceMember` appliquée aux 13 viewsets existants + filtre `get_queryset` par workspace.
- `throttle_classes = [UserRateThrottle]` sur les actions IA.

**Phase 1** (UX rapide) :
```
POST   /api/v1/tasks/{id}/toggle-complete/
POST   /api/v1/tasks/{id}/update-status/        body: {status}
POST   /api/v1/tasks/{id}/snooze/                body: {until}
POST   /api/v1/tasks/{id}/quick-assign/          body: {user_id?}
POST   /api/v1/tasks/{id}/move-kanban/           body: {column_id, position}
GET    /api/v1/me/today/
```

**Phase 2** (multi-modes) :
```
GET/POST /api/v1/projects/{id}/phases/
GET/POST /api/v1/projects/{id}/field-reports/
POST     /api/v1/field-reports/{id}/photos/      multipart
GET/POST /api/v1/projects/{id}/real-estate-lots/
GET/POST /api/v1/projects/{id}/admin-cases/
GET      /api/v1/projects/{id}/view-preference/  per-user
PUT      /api/v1/projects/{id}/view-preference/
```

**Phase 3** (budget V2) :
```
POST     /api/v1/projects/{id}/budgets/snapshot/        body: {label?}
GET      /api/v1/projects/{id}/budgets/snapshots/
GET      /api/v1/projects/{id}/budgets/forecast/
GET      /api/v1/projects/{id}/budgets/alerts/
POST     /api/v1/projects/{id}/budgets/freeze/
POST     /api/v1/projects/{id}/budgets/unfreeze/
```

**Phase 4** (IA V2) :
```
GET   /api/v1/projects/{id}/ai/summary/
GET   /api/v1/projects/{id}/ai/recommendations/
POST  /api/v1/projects/{id}/ai/generate-roadmap/        ?stream=true
GET   /api/v1/ai/chat/stream/{session_id}/              SSE
GET   /api/v1/ai/prompt-templates/                       admin
POST  /api/v1/ai/prompt-templates/                       admin
GET   /api/v1/ai/usage-quota/                           workspace courant
```

**Phase 5** (notifs & rapports) :
```
GET   /api/v1/notifications/digest/                      digest du jour
POST  /api/v1/notifications/preferences/                 canal, fréquence, quiet hours
GET   /api/v1/projects/{id}/ai/reports/
POST  /api/v1/projects/{id}/ai/reports/generate/         body: {period_start, period_end}
GET   /api/v1/projects/{id}/ai/reports/{report_id}/
```

---

## 7. Templates Tailwind/Alpine prêts à intégrer

### 7.1 Composant « Quick action button » (Phase 1)

À placer dans `templates/components/_quick_action_button.html` :

```html
{% comment %}
Usage: {% include "components/_quick_action_button.html" with
        endpoint="/api/v1/tasks/42/toggle-complete/"
        label="Terminer" icon="check" variant="green" %}
{% endcomment %}
<button
    type="button"
    x-data="{ loading: false }"
    :disabled="loading"
    @click="loading = true;
            fetch('{{ endpoint }}', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfCookie(), 'Content-Type': 'application/json' }
            })
            .then(r => r.ok ? window.devflowToast('{{ label }}', 'success') : window.devflowToast('Erreur', 'error'))
            .finally(() => loading = false);"
    class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium
           bg-devbg3 text-devtext1 hover:bg-devbg4 transition
           disabled:opacity-50 disabled:cursor-wait"
>
    <span x-show="!loading">{{ label }}</span>
    <span x-show="loading">…</span>
</button>
```

### 7.2 Composant « Toast container »

`templates/layout/_toast_container.html` :

```html
<div
    x-data="{
        toasts: [],
        show(message, type='info') {
            const id = Date.now();
            this.toasts.push({ id, message, type });
            setTimeout(() => this.toasts = this.toasts.filter(t => t.id !== id), 3500);
        }
    }"
    x-init="window.devflowToast = (m, t) => $data.show(m, t)"
    class="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-sm"
>
    <template x-for="toast in toasts" :key="toast.id">
        <div
            x-transition:enter="transition transform duration-200"
            x-transition:enter-start="translate-y-2 opacity-0"
            x-transition:enter-end="translate-y-0 opacity-100"
            class="rounded-lg shadow-mdsoft px-4 py-3 text-sm flex items-center gap-2"
            :class="{
                'bg-devgreen text-white': toast.type === 'success',
                'bg-devred text-white': toast.type === 'error',
                'bg-devbg3 text-devtext1 border border-devborder': toast.type === 'info',
            }"
        >
            <span x-text="toast.message"></span>
        </div>
    </template>
</div>
```

À inclure dans `templates/layout/base.html` juste avant `</body>` : `{% include "layout/_toast_container.html" %}`.

### 7.3 Vue « Mes actions du jour »

`templates/devflow/my_day.html` (extrait) :

```html
{% extends "layout/base.html" %}
{% block title %}DevFlow — Ma journée{% endblock %}
{% block page_title %}{{ greeting }}, {{ request.user.first_name|default:request.user.username }}{% endblock %}
{% block breadcrumb %}Aujourd'hui · {{ today|date:"l j F" }}{% endblock %}

{% block content %}
<div class="space-y-6">

    {# Bandeau d'ambiance #}
    <div class="rounded-2xl bg-gradient-to-r from-devaccent/15 to-devaccent2/15 p-6">
        <div class="text-sm text-devtext2">{{ quote_of_day }}</div>
        <div class="mt-2 flex gap-6 text-xs text-devtext1">
            <span><strong>{{ stats.due_today }}</strong> dues aujourd'hui</span>
            <span><strong>{{ stats.overdue }}</strong> en retard</span>
            <span><strong>{{ stats.in_progress }}</strong> en cours</span>
            <span><strong>{{ stats.unread_notifs }}</strong> notifs non lues</span>
        </div>
    </div>

    {# Section actions #}
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {# Tâches du jour #}
        <div class="card p-5 lg:col-span-2">
            <div class="flex items-center justify-between mb-4">
                <div class="card-title">À traiter aujourd'hui</div>
                <a href="{% url 'task_list' %}" class="text-xs text-devaccent">Tout voir →</a>
            </div>
            {% for task in tasks_today %}
                <div class="flex items-center justify-between py-2 border-b border-devborder/40 last:border-b-0">
                    <div>
                        <a href="{% url 'task_detail' task.pk %}" class="text-sm font-medium text-devtext1">
                            {{ task.title }}
                        </a>
                        <div class="text-xs text-devtext3 mt-0.5">
                            {{ task.project.name }} · échéance {{ task.due_date|date:"d M" }}
                        </div>
                    </div>
                    {% include "components/_quick_action_button.html" with
                       endpoint='/api/v1/tasks/'|add:task.pk|stringformat:"s"|add:'/toggle-complete/'
                       label="Terminer" variant="green" %}
                </div>
            {% empty %}
                <div class="text-center py-8 text-devtext3 text-sm">
                    Aucune tâche pour aujourd'hui — bonne journée !
                </div>
            {% endfor %}
        </div>

        {# Action items réunion + insights IA #}
        <div class="space-y-4">
            <div class="card p-5">
                <div class="card-title mb-3">Suivi réunions</div>
                {% for item in meeting_action_items %}
                    <div class="text-sm py-1.5">{{ item.title }}</div>
                {% empty %}
                    <div class="text-xs text-devtext3">Aucune action en suspens.</div>
                {% endfor %}
            </div>
            <div class="card p-5">
                <div class="card-title mb-3">Insights IA</div>
                {% for insight in ai_insights %}
                    <div class="text-sm py-1.5">
                        <span class="badge {% if insight.severity == 'HIGH' %}b-amber{% else %}b-cyan{% endif %}">
                            {{ insight.severity }}
                        </span>
                        {{ insight.title }}
                    </div>
                {% empty %}
                    <div class="text-xs text-devtext3">Aucun signal IA détecté.</div>
                {% endfor %}
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

### 7.4 Switcher de méthodologie sur `ProjectForm`

À ajouter dans `templates/project/_generic_form.html` (Phase 2) :

```html
<div x-data="{ method: '{{ form.methodology.value|default:'AGILE' }}' }" class="space-y-4">

    <div>
        <label class="block text-xs text-devtext2 mb-1">Méthodologie</label>
        <select x-model="method" name="methodology"
                class="w-full rounded-shell border border-devborder bg-devbg3 px-4 py-3 text-sm">
            <option value="SCRUM">Scrum</option>
            <option value="KANBAN">Kanban</option>
            <option value="AGILE">Agile</option>
            <option value="WATERFALL">Waterfall</option>
            <option value="MILESTONE">Jalons</option>
            <option value="FIELD">Terrain</option>
            <option value="REAL_ESTATE">Immobilier</option>
            <option value="ADMINISTRATIVE">Administratif</option>
        </select>
        <p class="mt-1 text-xs text-devtext3">
            Détermine les vues, les modèles et la génération IA disponibles pour ce projet.
        </p>
    </div>

    {# Champs spécifiques par mode #}
    <div x-show="method === 'FIELD'" x-transition>
        {{ form.location_name }}
    </div>
    <div x-show="method === 'WATERFALL'" x-transition>
        <p class="text-xs text-devtext2">
            Les phases du projet pourront être ajoutées après création.
        </p>
    </div>
</div>
```

### 7.5 Badge d'alerte budget

À ajouter dans `templates/project/budget/detail.html` (Phase 3) :

```html
{% if budget.is_over_alert_threshold %}
<div class="flex items-center gap-3 rounded-shell border border-devred/30 bg-devred/10 p-4">
    <svg class="w-5 h-5 text-devred" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
    </svg>
    <div class="flex-1">
        <div class="text-sm font-semibold text-devred">Budget en alerte</div>
        <div class="text-xs text-devtext2">
            Consommé : {{ budget.budget_consumption_percent }}%
            (seuil d'alerte : {{ budget.alert_threshold_percent }}%)
        </div>
    </div>
    <a href="{% url 'project_budget_snapshot_create' project.pk %}" class="btn-soft text-xs">
        Figer un baseline
    </a>
</div>
{% endif %}
```

---

## 8. Services métier à factoriser

### 8.1 Nouveau service `services/feature_flags.py`

```python
from django.conf import settings
from project import models as dm

def is_enabled(flag_name: str, workspace=None) -> bool:
    if not getattr(settings, flag_name, False):
        return False
    if workspace and hasattr(workspace, "settings"):
        return bool(getattr(workspace.settings, f"feature_{flag_name.lower()}", True))
    return True
```

Permet d'isoler chaque phase derrière `FEATURE_QUICK_ACTIONS`, `FEATURE_MULTI_MODE`, etc.

### 8.2 Nouveau service `services/smart_notifications.py` (Phase 5)

Regroupe la logique de digest, throttle, regroupement. Remplace progressivement les appels directs à `dm.Notification.objects.create(...)` dispersés dans le code.

### 8.3 Refactor `services/ai/services/chat.py` en sous-modules (Phase 4)

Du fichier actuel de 1556 lignes :
- `chat/context.py` : `DevFlowContextBuilder` (env. 400 lignes).
- `chat/intents.py` : intents pré-câblés (env. 400 lignes).
- `chat/streaming.py` : adaptation SSE (env. 200 lignes).
- `chat/service.py` : `AIChatService` orchestrateur (env. 400 lignes).
- `chat/__init__.py` : re-exporte pour compatibilité.

### 8.4 Nouveau service `services/budget_snapshots.py` (Phase 3)

```python
from decimal import Decimal
from django.utils import timezone
from project import models as dm
from project.services.budget import ProjectBudgetService

class BudgetSnapshotService:
    @classmethod
    def capture(cls, project, label=None):
        overview = ProjectBudgetService.build_budget_overview(project)
        return dm.ProjectBudgetSnapshot.objects.create(
            project=project,
            label=label or f"Snapshot {timezone.now():%Y-%m-%d}",
            snapshot_date=timezone.localdate(),
            payload=overview,
        )

    @classmethod
    def compare(cls, snapshot_a, snapshot_b):
        # diff par clé numérique
        ...
```

### 8.5 Corriger `services/notifications.py`

Passer en async via Celery :

```python
# AVANT
def notify_task_assignment(task, ...):
    send_assignment_email(...)  # SMTP sync

# APRÈS
from project.tasks import send_task_assignment_email_task
def notify_task_assignment(task, ...):
    send_task_assignment_email_task.delay(task.pk, ...)
```

---

## 9. Checklist de déploiement production

### 9.1 Pré-déploiement (à faire avant chaque release de phase)

- [ ] Migrations testées en dry-run sur copie de la base prod (`python manage.py migrate --plan` + `--fake` si besoin).
- [ ] Backup logique récent (`pg_dump`) accessible et restaurable.
- [ ] Feature flags positionnés à `False` par défaut côté `settings.py` prod, à `True` côté staging.
- [ ] Test de non-régression sur les fonctionnalités touchées par la phase (`python manage.py test project.tests_budget project.tests_security project.tests_quick_actions`).
- [ ] Lint et types passés (`ruff check`, `mypy --strict` si configuré).
- [ ] Revue de code par au moins une autre personne sur les changements sensibles (vues d'auth, migrations, IA).
- [ ] Communication interne : ce qui change pour l'utilisateur, ce qui reste inchangé.
- [ ] Workers Celery prévus avec nombre suffisant pour absorber les nouvelles tâches (digest, snapshots, scan overruns).

### 9.2 Déploiement

- [ ] Mise en mode maintenance courte (5 secondes) si migrations `CONCURRENTLY` non possibles.
- [ ] Exécution `python manage.py migrate --plan` puis `migrate`.
- [ ] Redéploiement code derrière le load balancer (rolling restart).
- [ ] Redémarrage des workers Celery (`celery -A ProjectFlow worker -l info` + beat).
- [ ] Vérification logs durant 5 minutes (Sentry, journald, fichier app).
- [ ] Smoke tests manuels : login, dashboard, créer une tâche, ouvrir un projet, déclencher une action IA.
- [ ] Activation progressive du feature flag : 10% utilisateurs internes → 50% → 100% sur 48h.

### 9.3 Post-déploiement

- [ ] Surveillance des métriques pendant 24h : taux d'erreur HTTP 5xx, temps de réponse moyen P95, longueur de la file Celery, coût IA quotidien.
- [ ] Vérification des nouvelles entités créées (tableau de bord SQL ou Django admin).
- [ ] Récupération des feedbacks utilisateurs (canal Slack, formulaire intégré).
- [ ] Rétrospective de phase : ce qui a marché, ce qui a cassé, ce qu'on retient pour la phase suivante.

### 9.4 Rollback

Chaque phase prévoit un rollback simple :
- **Phase 0** : revert du code ; les index ajoutés ne gênent pas, on peut les laisser.
- **Phase 1** : feature flag `FEATURE_QUICK_ACTIONS=False` désactive les nouveaux endpoints. La migration `Task.snoozed_until` reste (nullable, sans impact).
- **Phase 2** : feature flag `FEATURE_MULTI_MODE=False` ré-affiche les onglets Scrum/Kanban systématiquement. Le champ `methodology` reste avec sa valeur par défaut `AGILE`.
- **Phase 3** : feature flag désactive les snapshots et alertes ; la table reste en base, inerte.
- **Phase 4** : feature flag désactive le streaming et les nouveaux endpoints. Les `AIPromptTemplate` peuvent rester (vides), `AIUsageQuota` également.
- **Phase 5** : feature flag désactive le digest et les rapports IA ; les tables persistent.

Aucun rollback ne nécessite de drop de table — toutes les migrations sont conçues additives et idempotentes.

---

## 10. Recommandations anti-régression

### 10.1 Conventions à inscrire dans `AGENTS.md`

1. **Toute nouvelle CBV qui override `get_queryset` DOIT appeler `super().get_queryset()` ou utiliser `filter_by_workspace`.** Pas d'exception.
2. **Tout nouveau viewset DRF DOIT déclarer `permission_classes = [IsAuthenticated, IsWorkspaceMember]` et filtrer `get_queryset` par workspace.** Pas d'exception.
3. **Tout nouvel envoi d'e-mail passe par Celery**, jamais `send_mail` synchrone dans une vue.
4. **Tout nouveau champ modèle est nullable + default**, jamais NOT NULL + default lors d'un `AddField` sur une table existante.
5. **Toute nouvelle feature est derrière un feature flag**, off par défaut en prod, on en staging.
6. **Toute action IA payante a un `throttle_classes` et consulte `AIUsageQuota`** avant l'appel provider.
7. **Toute nouvelle vue qui modifie plusieurs modèles est encapsulée dans `transaction.atomic()`**.
8. **Toute nouvelle tâche Celery a `task_acks_late=True`, `bind=True`, et un `try/except` global avec `logger.exception`**.

### 10.2 Tests de non-régression à ajouter

À chaque phase, ajouter au minimum :
- 1 test par fuite cross-tenant corrigée (Phase 0).
- 1 test par endpoint quick-action (Phase 1).
- 1 test par méthodologie qui vérifie que l'IA Genesis génère la bonne structure (Phase 2).
- 1 test de transition `ProjectBudget.status` (Phase 3).
- 1 test de quota IA dépassé → 429 (Phase 4).
- 1 test de digest 10 notifs → 1 email (Phase 5).
- Tests d'intégration smoke testant le bonheur path de chaque phase.

### 10.3 Documentation à maintenir

- `AUDIT_DEVFLOW_PLAN_EVOLUTION.md` (ce document) : tenir à jour les phases complétées.
- `MIGRATIONS.md` : journal de chaque migration avec impact, durée, plan de rollback.
- `FEATURE_FLAGS.md` : liste des flags actifs, leur statut prod/staging, date de dépose prévue.
- `AI_PROMPTS.md` : versioning des prompts IA, exemple d'entrée/sortie.
- `API_CHANGELOG.md` : pour les consommateurs externes de l'API REST.

### 10.4 Indicateurs à surveiller en continu

- Taux d'erreur HTTP 5xx (cible < 0,5%).
- Temps de réponse P95 du dashboard et de la liste projets (cible < 800 ms).
- Coût IA quotidien (cible < N tokens par workspace selon le pricing).
- Taille de la file Celery (cible < 100 en pointe).
- Taux d'adoption des quick-actions (cliques / utilisateur actif jour).
- Taux d'utilisation des modes Waterfall/Field/RealEstate/Administrative.
- Précision du forecast IA (écart entre `BudgetForecast` IA et `actual` à 30 jours).

### 10.5 Risques résiduels

- **Tailwind par CDN** : en cas de coupure du CDN, l'UI perd son style. Recommandation hors phases : passer à une compilation Tailwind locale (Vite ou django-tailwind) en Phase 6 si nécessaire.
- **Aucun monitoring Celery (Flower/Sentry)** : sans observabilité, une tâche qui échoue silencieusement passe inaperçue. Recommandation : Sentry intégré au worker en Phase 0 (ou avant Phase 5 au plus tard).
- **Coquille `AInsight`** : laissée en l'état pour éviter migration coûteuse. Documenter dans `AGENTS.md` pour éviter que de nouveaux contributeurs essaient de la corriger.
- **Doublon TJM `BillingRate` vs `UserProfile`** : maintenir le fallback aussi longtemps que des données legacy existent ; planifier une migration de nettoyage en Phase 6.
- **Branches Git fusionnées en désordre (migrations 0021/0022)** : vérifier l'état de `django_migrations` en prod avant la première nouvelle migration de Phase 0.

---

## Annexes

### Annexe A — Glossaire

- **Workspace** : tenant logique du SaaS DevFlow. Tout est cloisonné par workspace.
- **TJM** : taux journalier moyen. Variable selon `BillingRate.unit` (HOURLY/DAILY/MONTHLY) et la période valid_from/valid_to.
- **Baseline** : version figée du budget à un instant T, sert de référence pour mesurer les écarts.
- **Forecast** : projection actuelle du coût final.
- **RAF** : reste à faire, calcul d'effort restant.
- **EAC** : Estimate at Completion, coût total prévu en fin de projet (= dépensé + RAF).
- **Cost Variance** : écart entre baseline et forecast.

### Annexe B — Outils d'audit utilisés

- Lecture statique des fichiers Django (`models.py`, `views.py`, `services/`, `api/`, `templates/`).
- Croisement avec `outputs_audit/orphan_templates.json` et `unused_url_names.json` (audit existant dans le repo).
- Exploration parallèle via sous-agents pour gagner du temps sur les 8 700 lignes de `views.py`.

### Annexe C — Fichiers de référence

```
/Users/ogahserge/Documents/ProjectFlow/project/models.py                                3 558 lignes
/Users/ogahserge/Documents/ProjectFlow/project/views.py                                 8 762 lignes
/Users/ogahserge/Documents/ProjectFlow/project/views_budget.py                            568 lignes
/Users/ogahserge/Documents/ProjectFlow/project/views_ai_chat.py                                   .
/Users/ogahserge/Documents/ProjectFlow/project/views_ai_genesis.py                        217 lignes
/Users/ogahserge/Documents/ProjectFlow/project/views_ai_proposal.py                       599 lignes
/Users/ogahserge/Documents/ProjectFlow/project/views_meeting.py                           242 lignes
/Users/ogahserge/Documents/ProjectFlow/project/views_financial_ai.py                              .
/Users/ogahserge/Documents/ProjectFlow/project/services/budget.py                         811 lignes
/Users/ogahserge/Documents/ProjectFlow/project/services/ai/base.py                         62 lignes
/Users/ogahserge/Documents/ProjectFlow/project/services/ai/factory.py                      53 lignes
/Users/ogahserge/Documents/ProjectFlow/project/services/ai/openai_provider.py             102 lignes
/Users/ogahserge/Documents/ProjectFlow/project/services/ai/local_provider.py               90 lignes
/Users/ogahserge/Documents/ProjectFlow/project/services/ai/services/ (9 modules)        4 207 lignes
/Users/ogahserge/Documents/ProjectFlow/project/api/viewsets.py                            215 lignes
/Users/ogahserge/Documents/ProjectFlow/project/api/urls.py                                 53 lignes
/Users/ogahserge/Documents/ProjectFlow/project/tasks.py                                   161 lignes
/Users/ogahserge/Documents/ProjectFlow/project/tests_budget.py                            224 lignes
/Users/ogahserge/Documents/ProjectFlow/templates/                                       ~150 templates dont 49 orphelins
/Users/ogahserge/Documents/ProjectFlow/outputs_audit/orphan_templates.json
/Users/ogahserge/Documents/ProjectFlow/outputs_audit/unused_url_names.json
```

---

*Fin du document. Toute mise à jour future devra être versionnée et datée en tête de fichier.*
