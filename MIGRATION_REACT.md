# Migration du frontend DevFlow vers React

> Fichier de suivi : on reprend toujours à partir du **dernier état validé** (section 5).

## 1. Décisions d'architecture

| Sujet | Décision | Raison |
|---|---|---|
| Frontend | `frontend/` — React 19 + TypeScript strict + Vite | Demandé, indépendant de Django |
| Coexistence | React servi par Django sous **`/app/`** ; l'ancien frontend reste servi sur ses routes actuelles | Bascule réversible, zéro interruption |
| Dev | `npm run dev` (Vite :5173) proxifie `/api`, `/ws`, `/media`, `/accounts` vers Django :8000 | Même origine perçue → cookies de session |
| Auth | **Session Django** (cookie HttpOnly) + CSRF (cookie `csrftoken` → en-tête `X-CSRFToken`) | Déjà supportée par DRF (`SessionAuthentication`), aucun jeton dans `localStorage` |
| Sécurité | Toutes les permissions restent côté Django (`WorkspaceScopedViewSetMixin`, `IsWorkspaceMember`, RBAC). React ne masque qu'à titre d'UX | Exigence §9 |
| Temps réel | 1 client WebSocket centralisé (reconnexion avec backoff) vers les consumers Channels existants (`/ws/channels/<id>/`) | Pas de connexions multiples |
| UI | Tailwind v4 + composants façon shadcn/ui (Radix) + Lucide, thème clair/sombre aux couleurs DevFlow | Demandé |
| Données | TanStack Query (cache, dédup), TanStack Table, RHF + Zod, Zustand (thème, workspace, sidebar) | Demandé |

## 2. Matrice de référence (audit du 04/11/2026)

Routes HTML comptées via le résolveur Django (CRUD inclus). API existantes = `project/api/urls.py`.

| Module | Fonctionnalités | Routes HTML | API disponibles | API manquantes | Complexité | État |
|---|---|---|---|---|---|---|
| Authentification | Connexion, déconnexion, inscription, mot de passe oublié/réinitialisation (allauth), profil, changement de mot de passe, activation par invitation | 15 (+ profil) | — | `auth/csrf`, `auth/me`, `auth/login`, `auth/logout`, `auth/profile`, `auth/password` | M | **Phase 2 ✅ (session/me/login/logout)** |
| Tableau de bord | KPI portefeuille, projets, tâches, activité, Ma journée | 2 | `me/today` (Ma journée) | `dashboard/summary` ✅ | M | **Phase 3 ✅** (code + tests + recette navigateur) |
| Workspaces & paramètres | Workspaces, paramètres, identité/papier en-tête, labels, intégrations, webhooks, clés API, préférences | 58 | `workspaces` (+ portfolio, allocation, budget) | settings, branding, labels, integrations, webhooks, api-keys | M | **Phase 5 ✅ — parité à valider** : cœur + transfert de propriété, paramètres, invitations (renvoyer/révoquer), labels, intégrations, webhooks, clés API, journal d'activité, identité & papier en-tête (formulaire workspace) |
| Projets | CRUD, membres, équipes, méthodologie, import de document, fiche détaillée, archivage | 16 | `projects` (+ ai/*, budget), `project-members`, `project-phases`, `project-view-preferences` | documents d'import | L | **Phase 5 ✅ — parité à valider** : + import documentaire, espace méthodologie (Scrum/Kanban/Waterfall + tableau de bord KPI), budget (synthèse, budget, estimations, revenus, dépenses, recalcul, export Excel), membres/labels projet |
| Tâches | Liste/kanban, CRUD, réaffectation, mise à jour rapide, temps passé, commentaires, pièces jointes, checklists, dépendances, reconduction/expiration | 66 | `tasks` (+ ai/effort), `tasks/<id>/quick-update|quick-assign|assignees|update-status|move-kanban|toggle-complete|snooze` | édition checklists / dépendances / labels | L | **Phase 5 ✅ — parité à valider** : + checklists (création, cochage, suppression), dépendances (deux sens), labels, affectations, commentaires/pièces jointes (modules) |
| Sprints & backlog | Sprints, board, backlog, colonnes, revues, rétros, métriques | 38 | `sprints` | backlog-items, board-columns, sprint reviews/retros/metrics | M | **Phase 5 ✅ CRUD générique — parité à valider** (sprints, backlog, revues, rétros, métriques, colonnes ; archivage). Board de sprint dédié non migré |
| Roadmaps & jalons | Roadmaps, éléments, jalons, tâches de jalon, releases | 28 | — | roadmaps, roadmap-items, milestones, milestone-tasks, releases | M | **Phase 5 ✅ CRUD générique — parité à valider** (roadmaps, éléments, jalons, tâches de jalon, releases ; archivage). Décalage de dates (`shift_dates`, FBV) non migré |
| Objectifs & risques | OKR (objectifs, key results), risques | 19 | — | objectives, key-results, risks | S | **Phase 5 ✅ CRUD générique — parité à valider** (objectifs, résultats clés, risques ; archivage) |
| Équipes & membres | Équipes, onboarding employé, hiérarchie N+1, invitations, réinitialisation mot de passe, membres projet | 34 | `teams` | invitations publiques | M | **Phase 3 ✅** (équipes, membres, intégration, N+1, réinitialisation mot de passe) |
| Timesheets | Calendrier hebdo (tâches + activités libres), saisie rapide, historique, soumission/validation N+1, rejet commenté, réouverture tracée, quota/capacité, facturable | 8 | `timesheets` (CRUD brut), `tasks/<id>/quick-update` (temps passé) | voir §2.1 | M | **Phase 3 ✅ code + recette** — parité à valider par l'équipe |
| Finance & facturation | Budgets, estimations, dépenses, revenus, TJM, cockpit, prévisions IA, factures (PDF/DOCX), clients, paiements | 54 | `project-budgets`, `project-estimate-lines`, `project-expenses`, `project-revenues`, `billing-rates`, budget snapshots/forecast-runs, `workspaces/<id>/portfolio` | invoices, invoice-lines, payments, clients, exports | L | **Phase 5 ✅ partiel** : dépenses (validation N1/N2, rejet), factures (émettre, envoyée, annuler, PDF/Word/impression), clients, budget projet. **Restent legacy** : cockpit financier IA, allocation IA, édition AJAX des lignes de facture, paiements, génération de facture depuis un projet |
| Réunions & enregistrements | Réunions, séries, décisions, comptes-rendus, enregistrements audio, transcription | 44 | `meetings/<id>/recordings/upload`, `recordings/*` | meetings CRUD, series, decisions, minutes | L | **Phase 5 ✅ partiel** : réunions, séries (régénération), registre des décisions, comptes rendus PDF/Word, envoi du compte rendu. **Restent legacy** : tableau de bord réunions, ordre du jour, présences/RSVP, actions → tâches, enregistrements audio / transcription IA |
| Messagerie | DM uniques, conversations équipe/projet, temps réel, pièces jointes, réactions, non-lus, présence | 40 (anciennes routes → `/chat/`) | `me/chat/*` complet, `me/presence`, WS `/ws/channels/<id>/` | flux personnel WS `/ws/me/` (activité chat) | M | ✅ Phase 4 — parité à valider |
| Notifications & activité | Centre de notifications, marquage lu, journal d'activité, préférences | 14 | — | `me/notifications/` (liste, summary, read, read-all, delete), `me/notification-preferences/`, WS `/ws/me/` ; journal d'activité → phase 5 | S | ✅ Phase 4 (notifications) — parité à valider |
| IA | Insights, suggestions de structure, Genesis, chat IA (SSE), rapports, prévisions | 23 | `ai-insights`, `project-ai-reports`, `ai/chat/stream`, `projects/<id>/ai/*` | ai-proposals (list/apply) | M | **Phase 5 ✅ partiel** : analyses IA (ignorer), propositions IA (liste/fiche). **Restent legacy** : appliquer/valider une proposition, Genesis, chat IA (SSE), copilote projet |
| Méthodologies | Administration des méthodologies, espaces Scrum/Kanban | 1 (+ espaces projet) | — | methodologies | S | **Phase 5 ✅ — parité à valider** : administration (superuser) en CRUD générique + espaces projet. Ajout de statuts/rôles/KPI (sous-actions) non migré |
| Modes métier | Rapports terrain, lots immobiliers, dossiers administratifs, pull requests | 16 | `field-reports`, `real-estate-lots`, `admin-cases` | pull-requests | S | Pull requests ✅ (CRUD générique). Rapports terrain, lots, dossiers : API DRF seulement (aucune page Django), écrans à concevoir |

### 2.1 Audit Timesheets (complément du 04/11/2026)

**Modèles (inchangés)** : `TimesheetEntry` (user, workspace, project, task, entry_date, planned_hours, hours, description, is_billable, approval_status DRAFT/SUBMITTED/APPROVED/REJECTED, approved_by/at, cost_snapshot), `TimesheetApprovalLog` (historique des transitions), `TimesheetReminderLog`, `UserProfile.manager` (N+1), `capacity_hours_per_week`, `joined_company_at`.

**Moteur réutilisé (aucune règle nouvelle)** : `services/timesheet_workflow.py` (week_bounds, expected_hours, week_summary, consolidated_status, visible_user_ids, direct_report_users, assert_week_editable, reopen_rejected_for_correction, submit_week, review_week, reopen_week), `services/task_time.py` (record_task_time), `services/timesheet_reminders.py` (Celery, inchangé).

**Routes HTML existantes** : `/timesheets/` (calendrier hebdo), `/timesheets/calendar/save/` (saisie cellule AJAX), `/timesheets/week/validate/` (submit/approve/reject/reopen), `/timesheets/list/` (historique + semaines groupées), `/timesheets/create|<pk>|<pk>/update|<pk>/delete/`.

**Règles à préserver (appliquées côté Django)**
- Saisie, modification et suppression : uniquement ses propres lignes DRAFT/REJECTED, semaine non soumise ni validée (`assert_week_editable`) ; toute correction d'une semaine rejetée la repasse en brouillon.
- Calendrier : uniquement les tâches où l'on est affecté (assignee ou `TaskAssignment`) ; activité libre = projet du workspace + libellé obligatoire ; 0 h supprime la cellule ; heures dans 0–24.
- Soumission : par l'employé ; validation/rejet : N+1 direct uniquement, rejet avec commentaire ; réouverture : N+1, tracée.
- Visibilité : soi-même + subordonnés directs et indirects (`visible_user_ids`), toujours dans le workspace courant.
- Exports : aucun export Timesheets n'existe dans l'ancienne interface (rien à migrer).
- Écart constaté (non corrigé, à arbitrer) : l'API brute `/api/v1/timesheets/` ouvre la lecture à tout le workspace pour les rôles ≠ MEMBER et ne verrouille pas les semaines soumises ; React ne s'en sert pas.

**API à créer (enveloppes fines des services ci-dessus)** — préfixe `timesheet/` (singulier, `timesheets/<pk>/` est pris par le router)
| Endpoint | Rôle |
|---|---|
| `GET timesheet/week/?date=` | grille hebdo (lignes tâches + activités libres, totaux jour/semaine, résumé `week_summary`, droits submit/lock, projets) |
| `POST timesheet/cell/` | saisie d'une cellule (même contrat que `calendar/save`) |
| `POST timesheet/week-action/` | submit / approve / reject / reopen |
| `GET timesheet/weeks/` | semaines groupées par collaborateur (statut consolidé, `can_review`) |
| `GET timesheet/entries/` | historique filtré (collaborateur, projet, statut, facturable, période, recherche, pagination) + totaux facturable/non facturable par collaborateur et projet |
| `PATCH/DELETE timesheet/entries/<id>/` | modification/suppression selon les règles ci-dessus (formulaire Django `TimesheetEntryForm` réutilisé) |

**Dépendances** : utilisateurs et profils (N+1, capacité), workspaces (isolation), projets (activités libres), tâches et affectations (lignes du calendrier), notifications (transitions), Celery (relances).

**WebSockets** : `/ws/channels/<id>/` (messagerie, sécurisé), `/ws/chat/<id>/` (legacy).
**Celery** : relances tâches/timesheets, rapports hebdo, digests, réunions, enregistrements — inchangé (backend).
**Uploads** : pièces jointes tâches/messages, enregistrements audio, documents d'import, logos/avatars — servis par `/media/` protégé.

## 3. Coexistence et bascule

- Ancien frontend : inchangé, routes actuelles.
- Nouveau frontend : `https://<domaine>/app/…` (vue Django `spa` qui sert `frontend/dist/index.html`).
- Bascule (Phase 7, sur validation) : rediriger `/` vers `/app/`. Rollback = retirer la redirection.

## 4. Commandes

```bash
cd frontend && npm install          # dépendances
npm run dev                          # Vite :5173 (Django doit tourner sur :8000)
npm run build                        # → frontend/dist (servi par Django sous /app/)
npm run test && npm run lint && npm run typecheck
```

## 5. Avancement

| Phase | Contenu | État |
|---|---|---|
| 1 — Audit | Matrice ci-dessus | ✅ 04/11/2026 |
| 2 — Fondations | Vite/TS/Tailwind v4, router, client API (CSRF), auth session, layout (sidebar rétractable, header, thème), page Django `/app/` | ✅ 04/11/2026 |
| 3 — Modules principaux | Dashboard → Workspaces → Projets → Tâches → Timesheets → Équipes | ✅ 04/11/2026 (parité fonctionnelle à valider) |
| 4 — Collaboration | Sécurisation API brutes, Messenger, notifications, WebSocket | ✅ 04/11/2026 (parité fonctionnelle à valider) |
| 5 — Modules complémentaires | P0 droits historiques, backlog obligatoire (§5.1), pont générique des modules, Ma journée | ✅ 04/11/2026 (parité fonctionnelle à valider ; restes listés §5.2) |
| 6 — Stabilisation | Tests E2E Playwright, sécurité, perfs, a11y | — |
| 7 — Bascule | Mise en production réversible | — |

### Journal
- 04/11/2026 — **Phase 1** terminée (matrice §2).
- 04/11/2026 — **Phase 2** terminée :
  - `frontend/` : React 19, TS strict, Vite 8, Tailwind v4 (charte DevFlow clair/sombre), React Router 7 (lazy), TanStack Query, RHF + Zod, Zustand, Radix, Lucide, Sonner.
  - Client API unique (`src/services/api.ts`) : session + `X-CSRFToken`, erreurs normalisées.
  - Auth : `useMe/useLogin/useLogout/useSwitchWorkspace`, page de connexion (validation, redirection interne uniquement), garde `AppLayout`.
  - Coque : sidebar rétractable (miroir RBAC de la sidebar Django), tiroir mobile, en-tête (workspace, fil d'Ariane, thème, messagerie, notifications, menu utilisateur), 404, erreurs de route, lien « aller au contenu ».
  - Django : `project/api/views_auth.py` (`/api/v1/auth/csrf|me|login|logout|workspace/`, login via le formulaire allauth + CSRF imposé), `project/views_spa.py` (`/app/…`), `STATICFILES_DIRS` → `/static/frontend/`.
  - Tests : `project/tests_api_auth.py` (5), Vitest (6) ; tsc, ESLint et build OK.

- 04/11/2026 — **Phase 3** terminée côté code :
  - **Principe** : aucune règle métier réécrite. Deux ponts génériques exécutent les vues Django existantes et répondent en JSON (`project/api/form_bridge.py`) :
    - `GET/POST /api/v1/forms/<nom>/[<pk>/]` → formulaires Django (champs, choix filtrés par workspace, validations, `form_valid`) : `project`, `task`, `timesheet-entry`, `team`, `member` ;
    - `POST /api/v1/actions/<nom>/[<pk>/]` → vues d'action (redirections + messages → JSON) : `task-comment|attachment|flag|done|extend|expire|archive|delete`, `timesheet-cell|week|entry-delete`, `team-archive|delete`, `member-delete|password-reset`.
  - Nouvelles API de lecture : `dashboard/summary` (contexte de `DashboardView`), `projects/<id>/summary`, `tasks/<id>/overview`, `workspaces/<id>/overview`, `teams/<id>/overview`, `team-members` (périmètre `TeamMembershipListView`), `timesheet/week|weeks|entries` (contexte de `TimesheetCalendarView` / `TimesheetEntryListView`).
  - Refactorings sans changement de comportement : création de projet extraite dans `services/project_creation.py` ; `TimesheetCalendarView.get_week_context()` séparé du rendu.
  - Sécurité : `WorkspaceViewSet` applique maintenant `workspace.manage` (modification/archivage) comme la vue Django — l'API brute permettait à un membre de renommer le workspace.
  - Front : tableau de bord, workspaces, projets (TanStack Table), tâches (liste + Kanban dnd-kit + fiche), timesheets (semaine éditable, mois, historique filtré + totaux facturable/non facturable par collaborateur et projet, validation N+1), équipes et membres. Composant `LegacyForm` (RHF + Zod dynamique) piloté par les formulaires Django.
  - Tests : Django `tests_api_dashboard|workspaces|projects|tasks|timesheets|teams` (26) + suites existantes `tests_project_form`, `tests_team_timesheet` ; suite complète = 37 échecs historiques (inchangé). Vitest 24 ; tsc, ESLint, build OK.
  - Recette navigateur (base SQLite jetable) : connexion, tableau de bord, formulaire projet, Kanban, saisie d'heures, validation N+1 ; la semaine validée depuis React apparaît « Validée » dans l'ancienne interface.

- 04/11/2026 — **Phase 4** terminée côté code :
  - **Sécurité API brutes** (audit des consommateurs : aucun appel interne — templates et React passent par les actions dédiées ; seuls d'éventuels clients externes par jeton `TokenAuthentication`) — endpoints conservés en écriture, mêmes règles que Django (`project/api/guards.py`, `project/services/task_permissions.py`) :
    - `tasks` : modification selon les droits réels (RBAC `task.*` / `task.edit_team` sur le périmètre des équipes / `task.update_own` sur ses tâches, responsables du projet), réaffectation soumise à `can_reassign`, workspace et rapporteur non modifiables, cohérence projet/sprint/backlog/parent/assigné (miroir de `TaskForm.clean`), suppression réservée à `task.delete` ou aux responsables du projet ; création : workspace déduit du projet + `user_can_access_workspace`, rapporteur imposé, `TaskAssignment` créé comme `TaskCreateView`.
    - `timesheets` : lecture = soi + subordonnés (`visible_user_ids`), tout le workspace pour le propriétaire (`timesheet.*`) ; écriture = ses propres saisies seulement, en brouillon / rejet, hors semaines soumises / validées (409), statut d'approbation non falsifiable (transitions via le workflow N+1 uniquement), réouverture après rejet comme `_OwnTimesheetMixin`.
    - Tests : `project/tests_api_raw_writes.py` (21 : contournements, IDOR, non-régression) — 12 échouent sans les garde-fous.
  - **Temps réel** : `UserEventsConsumer` (`/ws/me/`, groupe `user_<id>`, aucun paramètre client, 4401 si anonyme, ping/pong), `services/realtime.py` (diffusion best effort), signal `post_save` Notification (après commit), `ChatService` pousse `chat.activity` / `chat.read`. Consumer `/ws/channels/<id>/` réutilisé tel quel.
  - **Notifications** : `project/api/views_notifications.py` (destinataire uniquement, workspaces encore accessibles) ; front : cloche (compteur + 6 dernières), centre (onglets lues/non lues, type, recherche, pagination, suppression, tout marquer comme lu), préférences `NotificationPreference`, navigation vers la route React migrée ou l'ancienne page (`src/lib/links.ts`, aucune redirection externe).
  - **Messenger** : page `/app/messenger` (`?channel=`, `?user=` comme `/chat/`), bulle flottante globale (3 fenêtres desktop, plein écran mobile), sections DM / équipes / projets / groupes, recherche conversations et collègues, historique paginé, pièces jointes (5 × 20 Mo), réactions, accusé « Vu », saisie en cours, participants avec présence, heartbeat de présence (30 s).
  - **WebSocket client** (`src/lib/realtime.ts`) : une connexion par chemin partagée (pas de doublon), backoff exponentiel + jitter (1 → 30 s), reprise immédiate au retour réseau / onglet, arrêt sur 4401/4403, heartbeat, nettoyage au dernier désabonnement, resynchronisation TanStack Query à la reconnexion, polling de secours si le socket est coupé ; fusion idempotente des messages (optimiste + HTTP + écho WS).
  - **Corrections** : favicon DevFlow (`frontend/public/favicon.svg`) ; libellés timesheets alignés sur l'ancienne interface (Brouillon / Soumise / Validée / Rejetée, bandeau « En attente de validation », « Validée — verrouillée »…) ; liens vérifiés (30 chemins legacy résolus par Django, 38 liens React vers des routes existantes).
  - **Docker (préparation, production inchangée)** : `deploy/docker/Dockerfile.frontend` (build Node → export `frontend/dist`), `deploy/docker/compose.frontend.yml` (service optionnel `frontend-build`, profil `frontend`), `deploy/docker/dockerignore.proposed`.
  - Tests : Django `tests_api_raw_writes` (21) + `tests_api_notifications` (10, dont WebSocket) + `tests_messenger` ; suite complète = 37 échecs historiques (inchangé). Vitest 38 (temps réel, liens, notifications, Messenger) ; tsc, ESLint, build OK.
  - Recette navigateur (daphne + base SQLite jetable) : message reçu en direct (badges bulle / en-tête / cloche), réponse, réaction et message entrants en direct sans doublon, toast de notification « Timesheet à valider » → page de validation, centre de notifications, coupure serveur → « reconnexion… » puis reprise automatique.

- 04/11/2026 — **Phase 5** terminée côté code :
  - **P0 — droits sur l'objet réel dans l'ancienne interface et le pont React** (`TaskRightsMixin`, `project/views.py`, source unique `services/task_permissions.py`) :
    - `TaskUpdateView` (modification `can_edit_task`, réaffectation `can_reassign` évaluée sur l'état en base), `TaskDeleteView` / `TaskArchiveView` (`can_delete_task`), `TaskMarkDoneView` / `TaskMoveView` (`can_edit_task`) ; s'applique aussi à `forms/task`, `actions/task-*` ;
    - sous-objets : affectations (`can_reassign`), checklists et éléments, dépendances (tâche source), labels, pièces jointes (édition de la tâche) ; commentaires et pièces jointes modifiables par leur auteur ou un responsable ; champs « auteur » (`author`, `uploaded_by`, `added_by`, `assigned_by`, `created_by`) imposés à l'utilisateur et verrouillés ;
    - notifications : modification / suppression / lecture restreintes au destinataire (404 sinon), destinataire et workspace non réattribuables, création manuelle réservée à `workspace.manage` avec destinataire membre, lien limité aux chemins internes (`NotificationForm.clean_url`), `mark-read` → 404 au lieu de 500 ;
    - API : `tasks/<id>/overview` expose `can_edit` / `can_delete` (boutons masqués côté React, Django reste l'autorité).
  - **Failles corrigées au passage** :
    - `HasRBACPermission` laissait passer `list` / `create` sans contrôle → un membre listait et créait des TJM (`billing-rates`), un client voyait les budgets ; désormais action RBAC requise et liste limitée aux workspaces où elle est détenue (3 échecs historiques `tests_rbac_e2e` résolus) ;
    - `projects/<id>/budget-overview` et `refresh-financials` (API) sans contrôle financier → `can_view_financials` des vues Django ;
    - vues budget Django : projet résolu par PK sans scoping workspace (`?project=` d'un autre tenant sautait le contrôle financier) → 404 ;
    - `WorkspaceViewSet` : propriétaire transmissible à n'importe quel utilisateur (y compris d'un autre tenant), création au nom d'un tiers → refusées ;
    - espace Scrum Django : filtre sur un champ `BacklogItem.status` inexistant (page en erreur) → backlog non archivé ;
    - React : un `FormData` vide est rejeté par Django (400) → actions sans paramètre (terminer, archiver, supprimer…) réparées (`actionBody`).
  - **Pont générique des modules** (`project/api/resources.py`) : registre explicite de 42 ressources ; `GET resources/<nom>/` (ListView Django : recherche, filtres GET, pagination), `GET resources/<nom>/<id>/` (DetailView : champs, actions, exports), `POST …/delete/`, `POST …/actions/<code>/` ; formulaires via `forms/<nom>/` (préremplissage `?champ=`, champs verrouillés signalés `disabled`, libellés français). Front : `/app/m/<module>` (liste, fiche, formulaire), navigation et liens legacy (`/risks/3/` → `/m/risk/3`) basculés.
  - **Backlog obligatoire (§5.1)** : 1) workspace : transfert de propriété (`POST workspaces/<id>/transfer-ownership/`, `workspace.manage`, membre actif, journal de sécurité), paramètres / invitations / labels / intégrations / webhooks / clés API / journal ; 2) import documentaire (`/m/project-import`, workspace courant) ; 3) espaces méthodologie (`projects/<id>/space/` : mêmes sélections et KPI que `views_methodology`) ; 4) budget projet (`projects/<id>/budget-panel/` + formulaires et actions `project-generate-estimates|recalculate-budget|refresh-financials`, export Excel) ; 5-7) checklists, dépendances, labels éditables dans la fiche tâche.
  - **Ma journée** (`/app/my-day`, `MyDayService` via `me/today`, terminer / reporter réservés à l'assigné côté Django) ; **Identité & papier en-tête** → formulaire workspace React (mêmes champs).
  - **Qualité** : chunk applicatif initial 421 → 122 Ko (38 Ko gzip) ; vendeurs séparés (`vendor-react`, `vendor-query`, `vendor-radix`), zod et Messenger chargés à la demande ; bulle Messenger différée ; barre d'enregistrement des formulaires non masquée par la bulle ; mobile (375 px) et sombre vérifiés.
  - Tests : Django `tests_legacy_rights` (12 — 9 échouent sans les garde-fous), `tests_api_resources` (11) ; 142 tests ciblés OK ; suite complète **34 échecs** (référence 37 : les 3 `tests_rbac_e2e` corrigés ; les 34 restants analysés un par un — fixtures `setUpClass` (`UserProfile` unique, `Workspace.owner` NOT NULL), routage IA `FallbackChainProvider`, sérialisation `ProjectBudget` dans `budget_snapshots` — sans lien avec ces modifications). Vitest 42 ; tsc, ESLint, build OK.
  - Recette navigateur (daphne + SQLite jetable) : modules génériques (liste, fiche, modification, création), checklist créée / élément coché depuis la fiche tâche, espace Scrum, budget + recalcul, dialogue de transfert (candidats membres), Ma journée en mobile sombre.

### 5.1 Backlog obligatoire avant la bascule (phase 7)
Ces fonctionnalités existent dans l'ancienne interface et **doivent être migrées avant la bascule définitive** — toutes migrées en phase 5, **parité à valider par l'équipe** :
1. Paramètres du workspace et transfert de propriété.
2. Import documentaire des projets.
3. Espaces par méthodologie.
4. Budgets projet.
5. Checklists des tâches (édition).
6. Dépendances des tâches (édition).
7. Labels des tâches.

### 5.2 Restent servis par l'ancienne interface (à migrer avant bascule)
- Cockpit financier IA (`/workspaces/<id>/financial-ai/portfolio/`) et allocation IA des ressources.
- Factures : édition AJAX des lignes, paiements, génération depuis un projet (formulaire dédié).
- Réunions : tableau de bord, ordre du jour, présences / RSVP, conversion d'actions en tâches, enregistrements audio et transcription IA.
- IA : application / validation des propositions, Genesis, chat IA (SSE), copilote projet.
- Méthodologies : ajout de statuts, rôles et KPI ; board de sprint ; décalage de dates de roadmap (`shift_dates`, FBV).
- Les fiches génériques affichent les champs du modèle : les pages Django riches (onglets, graphiques) restent accessibles par « Ouvrir dans l'interface historique ».

### Points ouverts
- **Déploiement** : intégration préparée dans `deploy/docker/` sans toucher au `Dockerfile` ni au `docker-compose.yml`. Le compose de production monte le code de l'hôte (`.:/app`) : le build doit être écrit sur l'hôte (`docker compose -f docker-compose.yml -f deploy/docker/compose.frontend.yml run --rm frontend-build`) puis `collectstatic`. Activation à valider. Sans build, `/app/` répond 503 sans impact. Absence de `.dockerignore` : `frontend/node_modules` serait copié dans l'image si présent (proposition fournie).
- **WebSocket en production** : `/ws/me/` réutilise le préfixe `/ws/` déjà proxifié pour `/ws/channels/` ; à vérifier sur le proxy lors de l'activation.
- **Bundle** : chunk applicatif 122 Ko (38 Ko gzip) + vendeurs React 302 Ko (96 Ko gzip), Radix 116 Ko, Query 90 Ko ; à surveiller en phase 6.
- **Changements de comportement (phase 5)** : un membre ne peut plus modifier / supprimer / archiver une tâche hors de ses droits depuis l'ancienne interface (403) ; les notifications d'autrui renvoient 404 ; `billing-rates` / `project-budgets` / dépenses / revenus / estimations (API) exigent l'action RBAC (403 sinon) ; la création de tâche reste ouverte à tout membre (comportement existant conservé).
- **Méthodologie** : `_resolve_methodology` (existant) choisit la méthodologie par code sans filtrer le workspace — un code personnalisé identique dans un autre workspace pourrait être utilisé ; à arbitrer.
- **Formulaire workspace historique** : le champ `owner` propose les utilisateurs de tous les workspaces de l'éditeur (le transfert React et l'API exigent un membre du workspace).
- **Intégrations externes par jeton** : un client qui écrivait des temps pour autrui, modifiait une semaine soumise ou éditait une tâche sans droit reçoit désormais 403 / 409.
- **Notifications** : pas de « marquer comme non lu » (absent de l'existant) ; journal d'activité en phase 5.
- **Playwright** : installé en phase 6 (E2E).
