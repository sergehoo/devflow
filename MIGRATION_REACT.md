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

### 1.1 Design system (refonte UI — 09/11/2026)

Référence visuelle : maquette « Dashboard » beige / crème / jaune solaire fournie le 09/11/2026.
- **Tokens** (`frontend/src/styles/index.css`, clair + sombre) : fond `#F5F1E8`, cartes `#FFFFFF`, crème `#FAF8F3`, survol `#F3EFE6`, bordures `#EAE6DE`, texte `#202020` / `#77736D`, `primary` `#FFD44F` (remplissages, texte foncé dessus), `primary-soft` `#FFE9A0`, `primary-faint`, `primary-strong`, `brand` `#8A6400` (texte / icône d'accent, contraste AA ; le jaune n'est jamais utilisé comme couleur de texte), succès / alerte / erreur adoucis. Police Inter. Rayons : cartes 22 px, conteneurs 26 px, boutons en pilule.
- **Composants** : `Card`, `Button` (pilules), `Badge`, `Avatar`, `DataTable`, menus, `EmptyState`, `Tooltip` (Radix, accessible clavier) ; `PageHeader` (titre 34 px) ; widgets du tableau de bord (`features/dashboard/widgets.tsx` : `StatCard`, `RingGauge`, `TickGauge`, `ActivityHeatmap`, `TaskFocusList`, `ProjectHealth`, `UpcomingEvents`, `ProjectsCard`, `RecentActivity`, `ProgressBar`).
- **Coque** : barre latérale compacte à icônes (92 px, ≥ lg) avec indicateur jaune, infobulles et panneaux contextuels pour les groupes à sous-pages, réglages + déconnexion en bas ; tiroir libellé sur mobile / tablette. Barre supérieure : date et salutation, recherche globale (⌘K : pages, projets, tâches), workspace, messagerie, notifications, thème, profil. Fil d'Ariane au-dessus du contenu dès le 2e niveau.
- **Tableau de bord** : grille 23 / 52 / 25 % (≥ xl), 2 colonnes (≥ md), empilée sur mobile. Données réelles uniquement (`GET dashboard/insights/?weeks=` + `dashboard/summary/`) : « Ma journée » = tâches du jour terminées / prévues (pas de score inventé) ; santé des projets = actifs hors terminés / annulés, « à risque » = statut Bloqué ou `risk_score ≥ 70` (seuil du tableau de bord historique), « en retard » = statut Retard ; heatmap = tâches terminées par jour (`completed_at`, 8 à 52 semaines) ; priorités = mes tâches ouvertes (priorité puis échéance, action « terminer » contrôlée par Django) ; à venir (7 jours) = mes tâches, mes réunions, jalons du workspace. Sections historiques conservées sous « Pilotage du workspace » (analyses, finances, répartition, charge, sprint actif, TJM).
- **Correctif** : `rest_framework.filters.SearchFilter` activé — les `search_fields` des viewsets étaient inopérants (la recherche des listes Projets / Tâches ne filtrait rien).

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
| Réunions & enregistrements | Réunions, séries, décisions, comptes-rendus, enregistrements audio, transcription | 44 | `meetings/*` (lectures = vues Django sérialisées, écritures = pont), `meetings/<id>/recordings/upload` (throttle IA), `meetings/recordings/*` | — | L | **Migré (09/11/2026) — détail et réserves §2.2** : pages dédiées `/meetings`, `/meetings/dashboard`, `/meetings/decisions`, `/meetings/series`, `/meetings/:id`, `/meetings/:id/recordings/:rid`. Restent à valider hors recette locale : capture micro réelle, transcription AssemblyAI et synthèse IA réelles, génération Word/PDF (bibliothèques Docker) |
| Messagerie | DM uniques, conversations équipe/projet, temps réel, pièces jointes, réactions, non-lus, présence | 40 (anciennes routes → `/chat/`) | `me/chat/*` complet, `me/presence`, WS `/ws/channels/<id>/` | flux personnel WS `/ws/me/` (activité chat) | M | ✅ Phase 4 — parité à valider |
| Notifications & activité | Centre de notifications, marquage lu, journal d'activité, préférences | 14 | — | `me/notifications/` (liste, summary, read, read-all, delete), `me/notification-preferences/`, WS `/ws/me/` ; journal d'activité → phase 5 | S | ✅ Phase 4 (notifications) — parité à valider |
| IA | Insights, suggestions de structure, Genesis, chat IA (SSE), rapports, prévisions | 23 | `ai-insights`, `project-ai-reports`, `ai/chat/stream`, `projects/<id>/ai/*` | ai-proposals (list/apply) | M | **Phase 5 ✅ partiel** : analyses IA (ignorer), propositions IA (liste/fiche). **Restent legacy** : appliquer/valider une proposition, Genesis, chat IA (SSE), copilote projet |
| Méthodologies | Administration des méthodologies, espaces Scrum/Kanban | 1 (+ espaces projet) | — | methodologies | S | **Phase 5 ✅ — parité à valider** : administration (superuser) en CRUD générique + espaces projet. Ajout de statuts/rôles/KPI (sous-actions) non migré |
| Modes métier | Rapports terrain, lots immobiliers, dossiers administratifs, pull requests | 16 | `field-reports`, `real-estate-lots`, `admin-cases` | pull-requests | S | Pull requests ✅ (CRUD générique). Rapports terrain, lots, dossiers : API DRF seulement (aucune page Django), écrans à concevoir |

### 2.2 Matrice de parité — Réunions (09/11/2026)

**Règle de statut (toutes matrices)** : **Migré** = toutes les actions de la page historique sont opérationnelles dans React **et** couvertes par des tests automatisés (Django + Vitest) **et** vérifiées en recette navigateur. **À valider** = code et tests présents, une condition réelle reste à vérifier (périphérique, fournisseur externe, environnement Docker). **Partiel** = des actions manquent. **Non migré** = page seulement dans l'ancienne interface (un lien vers l'ancienne interface n'est jamais une migration). Un bouton présent n'est pas une preuve : chaque ligne indique la preuve.

| Page Django | Page React | Actions | Statut | Preuve |
|---|---|---|---|---|
| `/meetings/` (liste) | `/meetings` | recherche `?q=` (URL), filtres type / statut / `?project=` (non numérique → liste vide, plus de 500), à venir / passées, pagination, création (`?project=` prérempli) | Migré | `tests_api_meetings` (lecture, filtres, scoping), Vitest liste, recette |
| `/meetings/dashboard/` | `/meetings/dashboard` | indicateurs du mois, 14 prochains jours, mini-calendrier, 7 derniers jours, top projets, temps de parole, taux d'exécution | Migré | `MeetingDashboardView.build_context` partagé (page historique rendue, testé), Vitest, recette API |
| `/meetings/<id>/` (fiche) | `/meetings/:id` | en-tête, indicateurs (participants, actions, pièces jointes, sprint), modifier, supprimer | Migré | tests lecture / écriture / 404 inter-tenant, recette mobile + sombre |
| ″ — ordre du jour | onglet Notes & ordre du jour | ajouter, modifier (notes), statut rapide, supprimer, réordonner (glisser-déposer + boutons clavier) | Migré | tests pont `MeetingAgendaItem*`, Vitest (ajout / réordonnancement) |
| ″ — notes, points bloquants, décisions texte | onglet Notes | affichage HTML nettoyé (`safe_html`) | Migré (édition riche : voir réserve) | tests lecture ; édition via formulaire (textarea, pas d'éditeur riche) |
| ″ — participants | onglet Participants | RSVP (accepte / peut-être / décline), « je confirme ma présence », pointage par l'organisateur (droit calculé par Django), externes, statistiques | Migré | tests droits de pointage, Vitest RSVP / présences |
| ″ — actions de suivi | onglet Actions | ajout (titre, priorité, échéance, responsable du workspace), conversion en tâche (RBAC `task.create` ou responsable du projet), lien tâche | Migré | tests (bug historique « Action invalide » corrigé, RBAC conversion), Vitest |
| ″ — revue des projets | onglet Tour de table | formset `MeetingProjectReview` (ajout, édition, suppression) | Migré | test formset, Vitest |
| ″ — décisions | onglet Décisions + `/meetings/decisions` | registre filtrable (statut, catégorie) | Migré | tests, Vitest |
| ″ — pièces jointes | indicateur | l'ancienne interface n'affiche que le compteur (aucune vue d'ajout ou de consultation de `MeetingAttachment`) | Migré (parité : compteur) | — |
| ″ — IA réunion | boutons Analyser par IA / Résumé IA | `MeetingAIProcessView`, `MeetingMinutesAISummaryView`, quota IA partagé avec l'ancienne interface | Migré | tests throttle + heuristiques (`AI_BACKEND=none`), recette (heuristique) |
| ″ — compte rendu | boutons Word / PDF / Envoyer | téléchargement sans quitter React (échec → message, plus de bascule vers l'ancienne page), envoi via Celery uniquement (option externes) | À valider | tests Vitest `download.test.tsx`, tests Celery ; génération Word/PDF non exécutable en local (python-docx / WeasyPrint absents) → à vérifier en préproduction Docker |
| ″ — historique | pied de fiche | créée / mise à jour par, lien série | Migré | tests lecture |
| `recorder_widget.html` | panneau « Enregistrement & CR IA » (toujours monté sous les onglets) | consentement obligatoire (capture **et** import), permission micro + erreurs, démarrer / pause / reprendre / arrêter, chronomètre, niveau audio, tranches de 5 s, sauvegarde locale IndexedDB (reprise après coupure), avertissement avant de quitter, libération du micro | À valider | Vitest (refus micro, capture, pause / reprise, envoi, onglets sans arrêt de la capture) ; recette : consentement et refus micro vérifiés — **capture réelle à valider sur un poste avec micro** (le navigateur de recette bloque le micro) |
| ″ — import audio | bouton Importer un audio | type, taille (≤ `MAX_RECORDING_UPLOAD_MB` = 600 Mo), progression, nouvel essai, même endpoint et même format | Migré | Vitest (fichier trop gros / non audio), tests upload + throttle + 404 inter-tenant, recette (import WAV réel) |
| `recording_status_fragment.html` | suivi « Traitement en cours » | étapes Upload → Transcription → Voix → Mapping → Synthèse, polling, erreurs, relancer, supprimer | Migré | tests statut, Vitest `recording-progress.test.tsx`, recette (échec affiché, suppression, panneau retiré) |
| `recordings_list.html` | onglet Enregistrements | liste, liens, suppression | Migré | tests, recette |
| `/meetings/<m>/recordings/<r>/speakers/` | `/meetings/:id/recordings/:rid` (Identifier les voix) | extraits audio, suggestions IA, association aux participants du workspace, confirmation (bloquée si associations non enregistrées) | Migré | tests mapping (participant d'un autre tenant refusé), Vitest |
| `/meetings/<m>/recordings/<r>/summary/` | même page | transcription horodatée, résumé, décisions / actions / suggestions à valider (droits RBAC), conversion en tâches / projet, régénérer (suivi automatique), envoyer par e-mail (Celery), Word / PDF, lecteur audio complet | À valider | tests extractions + RBAC + envoi asynchrone ; lecteur : requêtes `Range` (206) pour Safari / iOS et le déplacement (test + recette) ; transcription AssemblyAI et synthèse DeepSeek / Claude / Ollama réelles non déclenchées (aucun appel payant en test) → à valider en préproduction |
| `/meetings/series/…` | `/meetings/series`, `/meetings/series/:id` | liste, création, modification, suppression, occurrences, régénération 60 jours | Migré | tests (création via pont corrigée), Vitest |

**Sécurité vérifiée (module Réunions)** : formulaires réunion / série / revue limités au workspace courant (fuite inter-tenant corrigée, refus si aucun workspace), réunions et enregistrements d'un autre workspace → 404, fichiers audio servis après contrôle d'accès (session + workspace, ou jeton HMAC), quota IA (`DEVFLOW_AI_RATE_LIMIT`) appliqué à l'upload et partagé avec les routes historiques, plus aucun envoi d'e-mail synchrone, aucune clé IA dans le frontend (appels uniquement côté Django), micro libéré à l'arrêt et au démontage, envois dupliqués empêchés pendant un upload.

**Réserves (décisions produit)** : pas de renommage libre d'une voix externe (règle métier `confirm_all_mappings`, identique à l'ancienne interface) ; champ `notes` sans éditeur riche (TinyMCE absent du frontend, concerne aussi tâches et projets) ; les e-mails de rappel pointent toujours vers les URL historiques (convention plateforme).

### 2.3 Matrice de parité globale (pages Django → React, 09/11/2026)

| Zone | Page(s) React | Statut |
|---|---|---|
| Connexion / session | `/login` | Migré (inscription, mot de passe oublié : pages allauth historiques) |
| Tableau de bord, Ma journée | `/`, `/my-day` | À valider (parité non revue action par action) |
| Workspaces, paramètres, identité | `/workspaces/*`, `/branding`, `/m/workspace-*` | À valider |
| Projets — liste, formulaire | `/projects`, `/projects/new`, `/projects/:id/edit` | À valider |
| Projets — fiche détaillée complète (onglets, KPI, documents, facturation, IA financière) | `/projects/:id` (fiche simplifiée) | **Partiel** — chantier préparé, non intégré |
| Projets — Genesis, propositions IA, import documentaire IA, copilote | — (`/m/ai-proposal` en lecture, `/m/project-import` générique) | **Non migré** — chantier préparé, non intégré |
| Tâches, checklists, dépendances, labels | `/tasks/*` | À valider |
| Équipes, membres | `/teams/*` | À valider |
| Timesheets | `/timesheets/*` | À valider |
| Messagerie, notifications | `/messenger`, `/notifications/*` | À valider |
| Réunions & enregistrements | `/meetings/*` | Migré, avec réserves §2.2 |
| Sprints, backlog, roadmaps, jalons, OKR, risques, finance, factures, méthodologies | `/m/<module>` (pages génériques) | **Partiel** — CRUD générique ; board de sprint, `shift_dates`, cockpit financier IA, allocation IA, lignes / paiements / génération de factures, sous-actions de méthodologie non migrés |
| Chat IA (SSE) | — | **Non migré** |

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
- Bascule (Phase 7) **active** : `/` et la redirection après connexion (`LOGIN_REDIRECT_URL`) mènent à `/app/` (`DEVFLOW_REACT_DEFAULT`, défaut `True`). Ancien tableau de bord : `/dashboard/classic/`. Les pages historiques restent servies sur leurs routes (liens profonds, e-mails, modules §5.2).
- Rollback sans code : variable `DEVFLOW_REACT_DEFAULT=False` dans Dokploy puis redéploiement.

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
| 7 — Bascule | Mise en production réversible | ✅ `/` → `/app/` (rollback : `DEVFLOW_REACT_DEFAULT=False`) |

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

- **09/11/2026 — Correction de la régression Réunions** : la fiche React `/app/m/meeting/<id>` (page générique) n'offrait ni enregistrement, ni transcription, ni compte rendu IA. Module migré en pages dédiées (voir §2.2), sans moteur ni pipeline recréés (vues, services `recording/*`, tâches Celery et endpoint d'upload existants réutilisés ; `/m/meeting*` redirige vers les nouvelles pages).
  - Corrections serveur : fuite inter-tenant des formulaires réunion / série / revue (projets, sprints et personnes de tous les workspaces proposés et acceptés), RBAC sur les conversions en tâche / projet, quota IA sur l'upload audio et partagé avec les routes historiques, envois de compte rendu uniquement via Celery, lecture audio par plages (206, Safari / iOS), filtre `?project` non numérique (500 → liste vide), bugs historiques (ajout rapide d'action toujours refusé, suggestion IA → tâche jamais créée, création de série en 400).
  - Pont : un message Django laissé par une requête précédente (ex. export historique en échec) faisait échouer l'action suivante en 400 (constaté en recette sur une suppression) → le pont ignore désormais les messages antérieurs (`stale_message_count` / `new_messages`, test de non-régression vérifié par mutation).
  - Tests : `tests_api_meetings` 32 ; 154 tests des suites du pont OK ; suite complète 361 tests, **34 échecs = référence historique** (aucun dans les réunions ; 37 à l'origine, 3 corrigés en phase 5). Vitest 61 (dont `meetings`, `download`, `recording-progress`), tsc, ESLint, build OK.
  - Recette navigateur (daphne + SQLite jetable, clés IA et AssemblyAI vides) : consentement obligatoire, refus du micro expliqué, import d'un WAV réel (upload, pipeline, échec affiché, relance / suppression), lecteur audio (206), exports en échec sans quitter React, IA heuristique, envoi via Celery, isolation (réunion d'un autre tenant → 404), mobile 375 px sombre sans débordement (onglet actif ramené dans la barre).

- **09/11/2026 — Refonte UI (design de référence)** : design system centralisé (tokens clair / sombre, Inter, cartes 22 px, pilules), barre latérale compacte + navigation contextuelle, barre supérieure (recherche globale ⌘K), tableau de bord reconstruit (§1.1) sur un nouvel endpoint en lecture seule `dashboard/insights/` (scopé au workspace courant, tests d'isolation), cartes des modules harmonisées (timesheets, réunions, membres, modules génériques, messagerie encadrée). Aucune règle métier modifiée ; recherche API réparée (`SearchFilter`).
  - Tests : `tests_api_dashboard` (+4 : santé, priorités, à venir, heatmap, bornes, isolation), `tests_api_projects` (+1 recherche scopée) ; 152 tests des suites API OK ; suite complète 371 tests, **34 échecs = référence historique**. Vitest 63 (dashboard réécrit : grille, période de la heatmap, action « terminer »), tsc, ESLint, build OK.
  - Recette navigateur (SQLite jetable) : desktop 1440 / 1500, mobile 375 (aucun débordement), mode sombre, panneau contextuel « Projets », recherche globale (projets + tâches réels), projets, tâches, timesheets, réunions, messagerie, modules génériques, fiche projet.

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
- IA : application / validation des propositions, Genesis, chat IA (SSE), copilote projet.
- Méthodologies : ajout de statuts, rôles et KPI ; board de sprint ; décalage de dates de roadmap (`shift_dates`, FBV).
- Les fiches génériques affichent les champs du modèle : les pages Django riches (onglets, graphiques) restent accessibles par « Ouvrir dans l'interface historique ».

### Points ouverts
- **Déploiement (Dokploy)** : le `Dockerfile` compile le frontend dans une étape `node:22-alpine` et copie le build dans `/opt/devflow/frontend` (`DEVFLOW_FRONTEND_DIST`), hors de `/app` que le compose recouvre par le code (`.:/app`). Chaque déploiement Dokploy reconstruit donc le frontend, sans Node dans le conteneur Django. `devflowweb` lance `collectstatic` à chaque démarrage avant gunicorn (en cas d'échec : avertissement dans les logs, statiques précédents conservés, le site démarre). Sans build, `/app/` répond 503 sans impact. `.dockerignore` minimal ajouté (`frontend/node_modules`, `frontend/dist`, `venv`, `__pycache__`). Les fichiers de `deploy/docker/` restent une alternative hors Dokploy.
- **Stockage des enregistrements (MinIO)** : en production, l'upload échouait (`NoSuchBucket`) car le bucket `RECORDING_S3_BUCKET` n'existait pas dans MinIO (même échec dans l'ancienne interface). `python manage.py ensure_recordings_bucket` le crée s'il manque (idempotent, lancée au démarrage de `devflowweb`, échec non bloquant) ; le message d'upload n'expose plus de détail technique (tests `tests_recordings_storage`).
- **WebSocket en production** : `/ws/me/` réutilise le préfixe `/ws/` déjà proxifié pour `/ws/channels/` ; à vérifier sur le proxy lors de l'activation.
- **Bundle** : chunk applicatif 122 Ko (38 Ko gzip) + vendeurs React 302 Ko (96 Ko gzip), Radix 116 Ko, Query 90 Ko ; à surveiller en phase 6.
- **Changements de comportement (phase 5)** : un membre ne peut plus modifier / supprimer / archiver une tâche hors de ses droits depuis l'ancienne interface (403) ; les notifications d'autrui renvoient 404 ; `billing-rates` / `project-budgets` / dépenses / revenus / estimations (API) exigent l'action RBAC (403 sinon) ; la création de tâche reste ouverte à tout membre (comportement existant conservé).
- **Méthodologie** : `_resolve_methodology` (existant) choisit la méthodologie par code sans filtrer le workspace — un code personnalisé identique dans un autre workspace pourrait être utilisé ; à arbitrer.
- **Formulaire workspace historique** : le champ `owner` propose les utilisateurs de tous les workspaces de l'éditeur (le transfert React et l'API exigent un membre du workspace).
- **Intégrations externes par jeton** : un client qui écrivait des temps pour autrui, modifiait une semaine soumise ou éditait une tâche sans droit reçoit désormais 403 / 409.
- **Notifications** : pas de « marquer comme non lu » (absent de l'existant) ; journal d'activité en phase 5.
- **Playwright** : installé en phase 6 (E2E).
