# Audit DevFlow — Bugs & fonctionnalités manquantes

**Date** : 6 octobre 2026 · **Branche** : `main` @ `457fc86` · **Mode** : lecture seule (aucun fichier applicatif modifié)

**Méthode** : contrôles exécutés (`manage.py check`, `makemigrations --check`, suite de tests sur une copie isolée) + 6 auditeurs IA par domaine (sécurité, modèles, finance, IA, collaboration, frontend) + 3 relecteurs adversariaux chargés de réfuter chaque constat en relisant le code. Les constats critiques principaux ont en plus été revérifiés manuellement.

**Résultat** : 140 constats confirmés par relecture + 5 problèmes bloquants d'infrastructure (section 1). Répartition : 25 critiques, 48 hauts, 63 moyens, 4 bas — 50 sécurité, 53 bugs, 12 fonctionnalités manquantes, 12 intégrité, 9 perf, 4 UX.

> ⚠️ Limites honnêtes : les relecteurs ont confirmé 100 % des constats (aucun réfuté), ce qui peut traduire une relecture indulgente sur les sévérités moyennes. Environ 10 constats sont des doublons sémantiques d'un même problème vu par deux domaines (signalés « doublon de » ci-dessous). Les zones non lues par les auditeurs sont listées en section 6.

---

## 1. Bloquants d'infrastructure (vérifiés par exécution)

| # | Problème | Preuve | Impact |
|---|---|---|---|
| M1 | **Graphe de migrations cassé** : `0034_channelmembership_last_read_at` dépend de `0034_merge_20260601_1049`, fichier absent du dépôt (commit `ebf894a`). | `manage.py test` → `NodeNotFoundError` | Aucun test ne peut tourner ; tout `migrate` sur un clone neuf échoue. Le fichier n'existe probablement que sur le serveur de prod. |
| M2 | **Deux migrations 0027 créent les mêmes tables** : `0027_phase3_budget_v2` et `0027_projectbudgetforecastrun_projectbudgetsnapshot_and_more` font toutes deux `CreateModel ProjectBudgetForecastRun/ProjectBudgetSnapshot` (fusionnées par `0031_merge_20260530_2100`). | Avec M1 contourné : `OperationalError: table "project_projectbudgetforecastrun" already exists` | Installation neuve, CI et tests impossibles même après M1. En prod, l'une des deux a forcément été `--fake`. |
| M3 | **Dérive modèles ↔ migrations** : `makemigrations --check` génère 133 opérations (35 renommages d'index, ~90 `AlterField` dont `id`, 2 `Meta`). | `makemigrations --check --dry-run` | Les migrations 0036+ ont été écrites à la main ; le prochain `makemigrations` produira une migration massive et risquée. |
| M4 | **Données versionnées** : `db.sqlite3`, `celerybeat-schedule.db` et `media/` (logos, pièces jointes) sont suivis par git malgré le `.gitignore`. | `git ls-files` | Fuite potentielle de données/PII dans l'historique ; conflits binaires. |
| M5 | `'weasyprint'` dans `INSTALLED_APPS` (ce n'est pas une app Django). | `manage.py check` plante sans pango/gobject | Le projet ne démarre pas sur une machine sans libs natives ; à importer paresseusement dans le service PDF uniquement. |

**Correctif recommandé (sans risque prod)** : récupérer `0034_merge_20260601_1049.py` depuis le serveur et le committer ; transformer la seconde 0027 en `SeparateDatabaseAndState` (state only) pour qu'une base neuve ne crée les tables qu'une fois ; puis `git rm --cached db.sqlite3 celerybeat-schedule.db -r media/`.

---

## 2. Synthèse par cause racine (à corriger en priorité)

Une grande partie des 140 constats découle de **6 causes racines**. Les corriger à la source ferme des dizaines de failles d'un coup.

### A. `filter_by_workspace` ne protège pas (≈ 40 vues) — 🔴
[project/views.py:160-221](project/views.py:160) :
1. `get_workspace_id()` renvoie `?workspace=<id>` **sans vérifier l'appartenance** → Update/Delete/Archive cross-tenant (F6).
2. Sur une vue qui hérite de `DevflowBaseMixin` **sans** `WorkspaceSecurityMixin`, la méthode fait `return queryset` non filtré (F5) : factures PDF/DOCX/émission/annulation/paiement, actions rapides de tâches, dashboard IA.
3. Si le modèle n'a aucun champ reconnu (ex. `Workspace`), fallthrough `return queryset` (F3) → liste/édition/suppression de **tous** les workspaces.
4. ~21 `get_queryset()` repartent de `dm.X.objects` sans `super()` (F4) — violation de la convention n°1 d'AGENTS.md (ex. `ProjectDetailView`, `WorkspaceListView`).

➡️ Fix : valider `?workspace` contre `get_user_workspaces()`, faire hériter `DevflowBaseMixin` de la logique de sécurité (ou `queryset.none()` par défaut), et ajouter `super().get_queryset()` aux 21 vues. Tests de non-régression dans `project/tests_security.py`.

### B. Formulaires non scopés — 🔴
- `UserProfileForm` expose `workspace` avec `Workspace.objects.filter(is_archived=False)` ([views.py:628](project/views.py:628)) : **n'importe quel utilisateur se rattache au tenant de son choix** (F1) — faille la plus grave du projet.
- `DevflowUpdateView` ne passe pas `current_workspace`/`allowed_workspaces` au formulaire (seul `DevflowCreateView` le fait) → tout le scoping des formulaires est inactif en édition (F28, F31, F54).
- `BaseStyledModelForm` ne filtre aucune FK ; ~20 ModelForms listent projets/tâches/utilisateurs de toute la plateforme (F29, F23, F55, F99).

### C. API DRF — 🔴
- Serializers : FK `workspace/project/sprint/assignee/user` écrivables sans `validate_*` → création/déplacement d'objets dans un autre tenant (F7).
- `destroy()` sans RBAC : un CLIENT peut supprimer physiquement un workspace (F8) ; `HasRBACPermission` ignore list/create/actions custom (F11).

### D. Chat temps réel — 🔴
- `ChatConsumer` (`ws/chat/<id>/`) : `group_add` + `accept()` sans aucune vérification, écriture dans n'importe quel canal ([consumers.py:265](project/consumers.py:265)) (F2).
- `channel_chat_views.py` : `get_object_or_404(DirectChannel, pk=pk)` sans membership (F9) ; CRUD générique Message/ChannelMembership avec auteur libre (F98).

### E. Configuration production — 🟠
- `DEBUG=True` forcé dans `prod.py` et `DJANGO_ENV` absent du docker-compose (F14).
- `/media/` servi sans authentification : factures, enregistrements audio, empreintes vocales (F15, F100, F89).
- Tailwind Play CDN en prod + deux design systems concurrents (F139).

### F. Moteur financier incohérent — 🟠
- Le **coût réel ignore temps × TJM** ; deux moteurs de KPI divergent (F59, F129).
- Recalcul du budget à **chaque sauvegarde de tâche**, qui écrase un budget APPROVED/CLOSED (F38/F58).
- Double comptage des lignes d'estimation (F57), main-d'œuvre comptée 2× dans la prévision IA (F60), allocation 0 % comptée 100 % (F67).
- Résolution TJM : tarifs archivés appliqués, tarifs d'équipe ignorés (F35) ; `BillingRate` sans workspace (F36).
- Factures Forfait/Jalons vides (F61), double facturation régie possible (F62), facturation déconnectée du budget (F63), snapshot de baseline qui plante silencieusement (F56).
- Auto-approbation des timesheets (F13) et validation des dépenses sans séparation des tâches (F50).

---

## 3. Écrans cassés (erreurs 500 / formulaires inutilisables)

| ID | Écran / action | Emplacement |
|---|---|---|
| F124 | 57 vues Create/Update génériques affichent le formulaire Projet : les formulaires sont inutilisables | [project/views.py:340](project/views.py:340) |
| F64 | Les boutons « Créer / éditer budget » et « Réviser budget » plantent (500) dès qu'un budget existe | [project/views_budget.py:161](project/views_budget.py:161) |
| F75 | Workspace Scrum en 500 systématique et outil copilote generate_user_stories cassé : BacklogItem n'a pas de champ status | [project/views_methodology.py:98](project/views_methodology.py:98) |
| F123 | La page Scrum plante toujours : filtre de template `split` inexistant | [templates/project/methodology/scrum_workspace.html:79](templates/project/methodology/scrum_workspace.html:79) |
| F125 | Namespace `project:` inexistant : 500 après modification ou suppression de jalons et de roadmaps | [project/views.py:7087](project/views.py:7087) |
| F126 | Commentaire rapide depuis le Kanban des tâches : 500 systématique | [project/views.py:4457](project/views.py:4457) |
| F71 | GET /api/v1/workspaces/{id}/portfolio/ renvoie 500 dès que le workspace a un projet | [project/api/viewsets.py:84](project/api/viewsets.py:84) |
| F18 | Acceptation d'invitation impossible (500) pour un utilisateur existant déjà rattaché à un autre workspace | [project/views.py:8072](project/views.py:8072) |
| F51 | Aucun UserProfile pour les inscriptions directes dès qu'il existe 2 workspaces : pages profil en erreur 500 | [project/signals.py:27](project/signals.py:27) |
| F101 | Ajout manuel d'une action de réunion toujours refusé (« Action invalide ») | [project/forms_meeting.py:357](project/forms_meeting.py:357) |
| F102 | Conversion d'une suggestion IA en tâche toujours en échec (kwarg created_by inexistant) | [project/views_meeting.py:914](project/views_meeting.py:914) |
| F136 | « Archiver » le projet renvoie 405 ; archivage sans interface ailleurs et sans restauration | [templates/project/partials/_hero_header.html:325](templates/project/partials/_hero_header.html:325) |
| F84 | Codes de statut des méthodologies incompatibles avec Task.Status : Kanban vide en « À faire », workflow engine contourné | [project/views_methodology.py:147](project/views_methodology.py:147) |
| F127 | Listes paginées à 25 sans pagination affichée : Kanban et KPI tronqués | [project/views.py:251](project/views.py:251) |

---

## 4. Fonctionnalités manquantes ou à moitié faites

| ID | Fonctionnalité | Emplacement |
|---|---|---|
| F39 | Compteurs dénormalisés jamais recalculés : story points et vélocité des sprints, avancement du projet | [project/models.py:1244](project/models.py:1244) |
| F50 | Validation des dépenses à 2 niveaux sans séparation des tâches | [project/models.py:2788](project/models.py:2788) |
| F63 | Revenus facturés et encaissés jamais alimentés : module facturation déconnecté du budget | [project/forms_budget.py:183](project/forms_budget.py:183) |
| F72 | Fonctionnalités financières inaccessibles ou à moitié faites (pages orphelines, liens en 404, absence de gestion des TJM) | [project/views_financial_ai.py:29](project/views_financial_ai.py:29) |
| F91 | Pipeline « import de document → projet généré par IA » non branché | [project/ia_create_view.py:26](project/ia_create_view.py:26) |
| F92 | Services IA (Genesis, prévision, risques, résumé, recommandations, rapport, estimation) sans point d'entrée UI | [project/views_financial_ai.py:38](project/views_financial_ai.py:38) |
| F94 | Mapping projet → méthodologie incomplet : 4 types de projet sans méthodologie, 6 méthodologies seedées inatteignables | [project/views_methodology.py:32](project/views_methodology.py:32) |
| F108 | Registre des décisions (MeetingDecision) jamais alimenté ; décisions et risques IA non convertis | [project/views_recording.py:302](project/views_recording.py:302) |
| F116 | Relances de tâches : arbitrage PM des retards jamais planifié, couverture des statuts incohérente | [project/services/task_overdue.py:132](project/services/task_overdue.py:132) |
| F117 | Préférences de notification non appliquées : dispatcher jamais appelé, mode HOURLY sans beat, pas d'UI | [project/services/smart_notifications.py:49](project/services/smart_notifications.py:49) |
| F133 | Board Kanban du projet vide (partial stub) et espace Kanban méthodologie en lecture seule | [templates/project/partials/_taches.html:125](templates/project/partials/_taches.html:125) |
| F135 | Fiches équipe et tâche incomplètes (données calculées non affichées, aucune action) | [templates/project/team/detail.html:9](templates/project/team/detail.html:9) |
| F131 | Bouton « Nouveau projet » et palette ⌘K factices : faux messages de succès | [templates/layout/base.html:2354](templates/layout/base.html:2354) |
| F136 | « Archiver » le projet renvoie 405 ; archivage sans interface ailleurs et sans restauration | [templates/project/partials/_hero_header.html:325](templates/project/partials/_hero_header.html:325) |

---

## 5. Liste détaillée des constats (triés par sévérité)

Chaque constat contient la preuve, l'impact, le correctif proposé et la note du relecteur adversarial. La sévérité affichée est celle **après** relecture (si elle a été réajustée, l'originale est indiquée).

### 🔴 Critique (25)

#### F1 — Prise de contrôle cross-tenant : l'utilisateur peut rattacher son profil à n'importe quel workspace
*Sécurité · Sécurité / multi-tenant · vu aussi par : Finance / TJM / facturation, Templates / routage / vues* — [project/views.py:628](project/views.py:628)

- **Preuve** : ProfileUpdateView.get_form() : `form.fields["workspace"].queryset = dm.Workspace.objects.filter(is_archived=False)`, c'est-à-dire TOUS les workspaces de la plateforme. UserProfileForm (forms.py:251) expose "workspace". Or get_user_workspace_ids() (utils/workspaces.py) ajoute profile.workspace aux workspaces accessibles, et RBACService.get_role_for() renvoie MEMBER si profile.workspace_id == ws_id (rbac.py:178-187). Le même formulaire laisse aussi l'utilisateur modifier ses propres cost_per_day, billable_rate_per_day et performance_score.
- **Impact** : N'importe quel utilisateur authentifié poste profile/update/ avec workspace=<id cible> et obtient aussitôt l'accès MEMBER à tout le tenant visé : projets, tâches, chat, API. C'est une fuite et une compromission totale entre tenants. Il peut aussi modifier son propre TJM de repli, qui sert aux calculs de coût.
- **Correctif** : Retirer "workspace" (et les champs financiers et de performance) de UserProfileForm pour l'utilisateur final. Si le choix doit rester, limiter le queryset à Workspace.objects.filter(id__in=get_user_workspace_ids(user)). Ajouter un test de non-régression dans tests_security.py.
- **Relecture** : views.py:628 remplace le queryset du champ workspace par Workspace.objects.filter(is_archived=False), soit tous les tenants. UserProfileForm (forms.py:251) expose workspace, cost_per_day, billable_rate_per_day et performance_score. Or get_user_workspace_ids (utils/workspaces.py:62-66), WorkspaceSecurityMixin.get_user_workspaces (views.py:109-111) et RBACService.get_role_for (rbac.py:178-187) comptent profile.workspace comme une appartenance : un utilisateur peut donc rejoindre n'importe quel workspace.

#### F2 — WebSocket ws/chat/<id>/ (ChatConsumer) sans authentification ni contrôle d'appartenance
*Sécurité · Sécurité / multi-tenant · vu aussi par : Réunions / chat / Celery* — [project/consumers.py:265](project/consumers.py:265)

- **Preuve** : ChatConsumer.connect() fait group_add puis accept() sans vérifier user.is_authenticated ni l'appartenance au canal. receive() fait `DirectChannel.objects.aget(pk=self.channel_id)` puis `Message.objects.acreate(channel=channel, author=user, ...)` sans aucun contrôle. Le panneau de chat principal s'en sert : templates/layout/chat_pannel.html:527 (`/ws/chat/${id}/`).
- **Impact** : Tout utilisateur connecté, quel que soit son tenant, peut écouter en temps réel les messages de n'importe quel canal, y compris privé ou DM, et poster des messages persistés dans n'importe quel canal d'un autre workspace en itérant sur les ID.
- **Correctif** : Supprimer ChatConsumer et faire pointer chat_pannel.html vers ws/channels/<id>/ (ChannelChatConsumer, qui vérifie workspace et membership). À défaut, réutiliser user_in_channel() dans connect() et fermer la connexion avec le code 4401/4403.
- **Relecture** : consumers.py:265-271 : connect() fait group_add puis accept() sans vérifier l'utilisateur ni le membership, et receive() (l.290-295) fait aget(pk) puis acreate sans contrôle. AuthMiddlewareStack (asgi.py) se contente d'identifier l'utilisateur, et routing.py:7 expose bien ws/chat/<id>/, utilisé par layout/chat_pannel.html:527 (inclus dans base.html:2854). Un utilisateur d'un autre tenant peut donc lire et écrire dans le canal, et un anonyme peut écouter le groupe chat_<id>.

#### F3 — Vues Workspace HTML non scopées : liste, détail, modification (owner compris), suppression et archivage de tout workspace
*Sécurité · Sécurité / multi-tenant* — [project/views.py:1297](project/views.py:1297)

- **Preuve** : WorkspaceListView.get_queryset (1297) et WorkspaceDetailView.get_queryset (1323) renvoient dm.Workspace.objects... sans super(). Update, Delete et Archive (1394, 1407, 1419) passent par filter_by_workspace(). Pour le modèle Workspace, aucun champ workspace/project/team... n'existe, donc la méthode tombe sur `return queryset` (views.py:221) et ne filtre rien. WorkspaceForm inclut "owner" (forms.py:332).
- **Impact** : Tout utilisateur voit la liste et le détail de tous les tenants (projets, membres, intégrations). Il peut aussi modifier un workspace étranger, y compris se déclarer owner (prise de contrôle WORKSPACE_OWNER), ou le supprimer physiquement, ce qui efface en CASCADE projets, tâches, timesheets et factures.
- **Correctif** : Dans filter_by_workspace, traiter `model is dm.Workspace` par `queryset.filter(id__in=get_user_workspace_ids(user))`. Faire appeler super().get_queryset() aux get_queryset des vues Workspace. Retirer "owner" du formulaire, ou le réserver au owner actuel. Exiger RBAC workspace.manage / workspace.delete.
- **Relecture** : WorkspaceListView/DetailView (views.py:1297, 1323) n'appellent pas super(), et Workspace n'a aucun des champs testés par filter_by_workspace, qui retombe donc sur `return queryset` (views.py:221) pour Update, Delete et Archive (1394-1419). WorkspaceForm expose bien `owner` sans restriction de queryset (forms.py:332). Vecteur voisin non listé : ProfileUpdateView.get_form propose tous les workspaces au champ profile.workspace (views.py:628), ce qui permet à un utilisateur de s'auto-rattacher à n'importe quel tenant.

#### F4 — Une vingtaine de List/DetailView redéfinissent get_queryset sans super() : lecture cross-tenant
*Sécurité · Sécurité / multi-tenant · vu aussi par : Templates / routage / vues* — [project/views.py:2400](project/views.py:2400)

- **Preuve** : Vues dont get_queryset part de dm.X.objects sans super() ni filtre workspace : ProjectDetailView (2400), ProjectDocumentImportList/Detail (3636/3724 ; le ?workspace= n'y est pas vérifié), SprintList/Detail (4109/4183), TaskDetailView (4795), RiskList/Detail (5397/5437), AInsightList/Detail (5644/5684), MilestoneDetail (6954), MilestoneTaskList/Detail (7117/7153), ReleaseList/Detail (7237/7279), RoadmapList/Detail (7379/7526), RoadmapItemList/Detail (7698/7735), KeyResultList/Detail (8482/8515). Cela viole la convention n°1 d'AGENTS.md.
- **Impact** : Les fiches projet (membres, tâches, sprints, budget affichés), tâches, risques, insights IA, roadmaps, OKR et documents importés de tous les tenants sont lisibles en itérant sur les pk. Les listes agrègent les données de tous les tenants.
- **Correctif** : Remplacer `dm.X.objects` par `super().get_queryset()` dans chacune de ces méthodes, en gardant select_related/prefetch/annotate. Ajouter un test 404 cross-tenant par vue dans tests_security.py.
- **Relecture** : Les 21 get_queryset cités (2400 … 8515) partent tous de dm.X.objects, sans super() ni filter_by_workspace, ce qui écrase DevflowListView.get_queryset (l.311-319) et DevflowDetailView.get_queryset (l.334-335). Aucun get_object, middleware ou décorateur d'URL ne compense, et tests_security.py ne couvre que les endpoints DRF.

#### F5 — Vues héritant de DevflowBaseMixin sans WorkspaceSecurityMixin : filter_by_workspace ne filtre rien (écritures et factures cross-tenant)
*Sécurité · Sécurité / multi-tenant* — [project/views.py:190](project/views.py:190)

- **Preuve** : filter_by_workspace : sans ?workspace=, si la vue n'a pas get_current_workspace, la méthode fait `return queryset` (ligne 190). Vues concernées (DevflowBaseMixin, View) qui font `.get(pk=pk)` : TaskQuickAssignView 4363, TaskQuickStatusView 4390, TaskQuickCommentView 4426, TaskToggleFlagView 4460, TaskMoveView 4976, TaskMarkDoneView 5111, AInsightDashboardView 5512, AInsightDismissView 5770, WorkspaceInvitationAcceptView 7980, InvoiceIssue/MarkSent/Cancel 8880-8912, InvoicePDFView 8930, InvoiceDocxView 8960, InvoicePaymentCreateView 9057, InvoiceGenerateFromProjectView 9080. Le commentaire d'InvoiceDocxView annonce un filtrage strict, ce qui est faux.
- **Impact** : Modification de statut, commentaires et assignation de tâches d'autres tenants. Téléchargement du PDF ou DOCX de n'importe quelle facture (coordonnées bancaires, montants). Émission, annulation ou ajout de paiements sur des factures étrangères. Génération de factures à partir d'un projet étranger.
- **Correctif** : Ajouter WorkspaceSecurityMixin à ces vues, ou mieux, faire échouer filter_by_workspace par défaut (queryset.none()) en l'absence de workspace résolu. Utiliser get_object_or_404 plutôt que .get() pour éviter les erreurs 500 DoesNotExist.
- **Relecture** : views.py:179-187 : DevflowBaseMixin(LoginRequiredMixin) n'a pas get_current_workspace, donc sans ?workspace la méthode fait `return queryset` non filtré, et avec ?workspace la valeur est utilisée sans vérification d'appartenance. Les vues listées (4363-4460, 4976, 5111, 5512, 5770, 7980, 8880-9080) héritent de DevflowBaseMixin seul et sont routées (urls.py:180-194, 229, 235, 391, 806-819). Aucun middleware ne compense (settings/base.py:100). AInsightDashboardView affiche les insights de tous les tenants, et le docstring d'InvoiceDocxView (« filtrage strict ») est faux.

#### F6 — filter_by_workspace accepte ?workspace=<id> sans vérifier l'accès : Update/Delete/Archive cross-tenant
*Sécurité · Sécurité / multi-tenant* — [project/views.py:160](project/views.py:160)

- **Preuve** : get_workspace_id() renvoie `self.kwargs.get("workspace_id") or self.request.GET.get("workspace")`, et filter_by_workspace filtre directement sur cet ID (195-219) sans le comparer aux workspaces de l'utilisateur. Le contrôle d'accès n'existe que dans get_current_workspace(), appelé par get_context_data. Or un POST valide sur UpdateView ou DeleteView (Django 4.2 : form_valid puis redirect) et ArchiveObjectView.post (501) ne rendent jamais de contexte.
- **Impact** : POST /tasks/<pk>/update/?workspace=<W2>, /projects/<pk>/delete/?workspace=<W2>, /…/archive/?workspace=<W2> modifient, suppriment ou archivent les objets d'un autre tenant, pour tous les DevflowUpdateView, DeleteView et ArchiveObjectView.
- **Correctif** : Dans filter_by_workspace, résoudre le workspace via get_current_workspace() (qui lève 404 si l'accès est refusé), ou faire l'intersection avec get_user_workspace_ids(request.user) avant de filtrer.
- **Relecture** : get_workspace_id (views.py:160-161) renvoie ?workspace= tel quel et filter_by_workspace (180-219) filtre dessus sans le comparer à get_user_workspaces ; seul get_current_workspace valide, et il n'est appelé que par get_context_data. En Django 4.2, BaseDeleteView.post et UpdateView.post (formulaire valide) font get_object, form_valid puis redirect, sans jamais rendre de contexte ; ArchiveObjectView.post (501) non plus. À noter aussi : InvoiceIssueView/InvoiceMarkSentView héritent de DevflowBaseMixin sans WorkspaceSecurityMixin, donc filter_by_workspace y renvoie le queryset non filtré.

#### F7 — API DRF : FK des serializers non restreintes, création ou déplacement d'objets dans un autre tenant
*Sécurité · Sécurité / multi-tenant* — [project/api/serializers.py:290](project/api/serializers.py:290)

- **Preuve** : TaskSerializer expose en écriture workspace, project, sprint, assignee, reporter. ProjectSerializer (36) workspace, team, owner. ProjectMemberSerializer (78) project, user. TeamSerializer workspace. ProjectExpense, Revenue, Budget et EstimateLine exposent project. Ce sont des PrimaryKeyRelatedField avec queryset=all() par défaut. WorkspaceScopedViewSetMixin ne filtre que get_queryset, et IsWorkspaceMember.has_object_permission n'est pas appelé sur create.
- **Impact** : POST /api/v1/projects/ {workspace: W2} ou /api/v1/tasks/ {workspace: W2, project: P2} crée des objets dans le tenant d'autrui. PATCH d'une tâche vers project=P2 la déplace. POST /project-expenses/ {project: P2} injecte des dépenses dans la comptabilité d'un autre tenant. Cela viole la convention n°4.
- **Correctif** : Dans chaque serializer, restreindre les querysets des FK dans __init__ selon get_user_workspace_ids(request.user), ou valider dans validate() avec user_can_access_workspace. Rendre workspace read-only et le dériver du projet, et vérifier la cohérence workspace entre project, sprint et assignee.
- **Relecture** : TaskSerializer (serializers.py:290-315) et ProjectSerializer (36-75) exposent workspace, project, sprint, assignee, team et owner en écriture, sans validate_* ni restriction de queryset. TaskViewSet et ProjectViewSet (viewsets.py:117, 395) n'ont pas de perform_create, et WorkspaceScopedViewSetMixin (permissions.py:155-160) ne filtre que get_queryset. Task.save/full_clean ne vérifie pas non plus la cohérence workspace/project.

#### F8 — API : tout membre (y compris CLIENT) peut supprimer physiquement un workspace ou un projet ; la création de workspace plante
*Intégrité des données · Sécurité / multi-tenant* — [project/api/viewsets.py:75](project/api/viewsets.py:75)

- **Preuve** : WorkspaceViewSet(ModelViewSet) et ProjectViewSet utilisent DEFAULT_PERMISSIONS = [IsAuthenticated, IsWorkspaceMember] sans RBAC. Le modèle Workspace (SoftDeleteModel, models.py:22-33) ne redéfinit pas delete(), et tous ses FK sont en on_delete=CASCADE. WorkspaceSerializer ne contient pas owner (non nullable, PROTECT) et perform_create n'est pas redéfini.
- **Impact** : DELETE /api/v1/workspaces/<id>/ par un simple MEMBER ou CLIENT efface tout le tenant (perte de données irréversible). POST /api/v1/workspaces/ provoque une IntegrityError (500).
- **Correctif** : Ajouter HasRBACPermission avec rbac_action_map (workspace.delete, project.delete…) sur ces viewsets, ou rendre le destroy logique via archive(). Implémenter perform_create(owner=request.user) ou désactiver create.
- **Relecture** : viewsets.py:75 : WorkspaceViewSet et ProjectViewSet sont des ModelViewSet avec DEFAULT_PERMISSIONS (IsAuthenticated, IsWorkspaceMember) sans RBAC. destroy() appelle Model.delete(), car SoftDeleteModel (models.py:22-33) ne surcharge pas delete(), et les FK workspace sont en CASCADE : tout membre, CLIENT compris, peut supprimer physiquement un workspace. De plus, WorkspaceSerializer (serializers.py:22) déclare un champ `currency` absent du modèle Workspace et omet owner (PROTECT, non nul) : list, retrieve et create plantent (ImproperlyConfigured ou IntegrityError), mais DELETE fonctionne puisqu'il ne sérialise rien.

#### F9 — Chat HTML et AJAX : lecture et envoi de messages dans n'importe quel canal
*Sécurité · Sécurité / multi-tenant* — [project/channel_chat_views.py:70](project/channel_chat_views.py:70)

- **Preuve** : channel_chat_page (l.14), channel_panel_detail (l.70) et channel_send_message (l.97) font `get_object_or_404(DirectChannel, pk=pk)` sans filtre workspace ni membership, puis renvoient les 80 derniers messages ou créent un Message.
- **Impact** : Lecture des DM et canaux privés de tous les tenants, et usurpation de présence dans leurs conversations. Cela viole la convention n°2 (FBV non scopées).
- **Correctif** : Résoudre le canal avec workspace_id__in=get_user_workspace_ids(user) et, pour les canaux privés, exiger ChannelMembership. Réutiliser ChatService.get_channel_for().
- **Relecture** : channel_chat_page (channel_chat_views.py:14), channel_panel_detail (l.70) et channel_send_message (l.97) font `get_object_or_404(DirectChannel, pk=pk)` sans filtre de workspace ni de membership. Ces vues sont routées en premier sur channels/<pk>/ (urls.py:251-255), avant DirectChannelDetailView.

#### F10 — FBV et vues sans scope workspace : export Excel du budget, décalage de roadmap, déclenchement IA
*Sécurité · Sécurité / multi-tenant (initialement high) · vu aussi par : Finance / TJM / facturation* — [project/views.py:2067](project/views.py:2067)

- **Preuve** : ProjectBudgetExportExcelView.get : `get_object_or_404(dm.Project..., pk=pk)` sans scope (lignes d'estimation, coûts, TJM). roadmap_item_shift_dates (7481) : `get_object_or_404(dm.RoadmapItem, pk=item_id)` puis sauvegarde des dates. views_ai_proposal.py:456 (ProjectAIProposalTriggerView.post) et 542 (StatusView.get) : `get_object_or_404(dm.Project, pk=project_pk)`.
- **Impact** : Exfiltration du budget détaillé de n'importe quel projet. Modification du planning d'autres tenants. Déclenchement payant de génération IA (sans throttle) qui crée des ProjectAIProposal dans un workspace étranger.
- **Correctif** : Ajouter workspace_id__in=get_user_workspace_ids(request.user) (roadmap__workspace_id__in pour RoadmapItem), plus un contrôle RBAC budget.view sur l'export et AIActionRateThrottle ou un quota sur le déclenchement IA.
- **Relecture** : views.py:2063-2073 : ProjectBudgetExportExcelView, routée en urls.py:121, fait `get_object_or_404(dm.Project, pk=pk)` avec seulement LoginRequiredMixin, ce qui permet d'exporter les lignes d'estimation, les coûts et les TJM de n'importe quel tenant. C'est une fuite financière cross-tenant, d'où la sévérité relevée à critical. roadmap_item_shift_dates (7481) et views_ai_proposal.py:456/542 sont confirmés aussi (doublons de F121/F73).

#### F27 — UserProfileForm permet à tout utilisateur de se rattacher à n'importe quel workspace (escalade cross-tenant)
*Sécurité · Modèles / formulaires / signaux · doublon de F1* — [project/forms.py:251](project/forms.py:251)

- **Preuve** : UserProfileForm.Meta.fields contient "workspace". ProfileUpdateView.get_form (views.py:628) fixe son queryset à `Workspace.objects.filter(is_archived=False)`, donc tous les workspaces de tous les tenants. Le template account/profile_update.html affiche tous les champs (`{% for field in form %}`). Or get_user_workspace_ids (utils/workspaces.py:62-66) et WorkspaceSecurityMixin.get_user_workspaces (views.py:109-111) considèrent `profile.workspace` comme une appartenance, et get_current_workspace (views.py:145-148) le choisit en priorité.
- **Impact** : N'importe quel compte peut ouvrir /profile/update/, choisir le workspace d'un autre client et enregistrer. Il obtient alors un accès complet en lecture et en écriture à ce tenant (projets, budgets, factures, TJM) dans toutes les CBV, FBV et l'API. La liste déroulante dévoile aussi le nom de tous les workspaces.
- **Correctif** : Retirer "workspace" de UserProfileForm, ou le limiter à `get_user_workspace_ids(user)` hors profil. Ne plus traiter profile.workspace comme une appartenance dans get_user_workspace_ids ni dans get_user_workspaces : seuls owner et TeamMembership doivent compter. Ajouter un test dans tests_security.py.
- **Relecture** : Doublon de F1, vérifié : forms.py:251 inclut workspace, views.py:628 ouvre le choix à tous les workspaces non archivés et profile_update.html:59 rend `{% for field in form %}`. get_current_workspace (views.py:145-148) choisit ensuite ce workspace en priorité.

#### F28 — Vues d'édition : formulaires non scopés, déplacement et liaison d'objets vers d'autres tenants (factures incluses)
*Sécurité · Modèles / formulaires / signaux* — [project/forms.py:180](project/forms.py:180)

- **Preuve** : BaseStyledModelForm.__init__ (180-184) lit current_workspace et allowed_workspaces mais ne restreint jamais les querysets. Ce scoping dépend des vues. DevflowCreateView le fait (views.py:345-392), mais DevflowUpdateView (views.py:439) ne redéfinit ni get_form_kwargs ni get_form. Conséquences dans les formulaires : InvoiceForm.__init__ et clean (2156-2218) sautent tout le bloc « SECURITY » quand ws vaut None, ce qui est le cas dans InvoiceUpdateView (views.py:8859). Le champ workspace devient alors visible avec tous les workspaces, et project et client couvrent tous les tenants. InvoiceLineForm (2245) fait de même pour le FK invoice dans InvoiceLineUpdateView (9020), puis `self.object.invoice.recompute_totals()`. ProjectForm (567-587) propose les teams et teams de tous les tenants dans ProjectUpdateView (3864). MeetingSeriesForm (232) propose les participants et projets de tous les tenants dans MeetingSeriesUpdateView (views_meeting.py:466).
- **Impact** : En modifiant un objet de son propre workspace, un membre peut le déplacer dans le workspace d'un autre tenant. Il peut aussi rattacher une ligne de facture à la facture d'un autre client, ce qui modifie ses totaux, ou lier les équipes d'un autre tenant à son projet. get_assignable_memberships expose alors les membres de ces équipes à l'affectation IA. Les listes déroulantes dévoilent les projets, clients et utilisateurs de tous les tenants.
- **Correctif** : Ajouter à DevflowUpdateView le même get_form_kwargs et get_form que DevflowCreateView (current_workspace, allowed_workspaces, request). Dans BaseStyledModelForm, appliquer par défaut allowed_workspaces au champ workspace et un filtre workspace à tout FK vers Project, Team, Task, Sprint, Invoice ou InvoiceClient. Dans les formulaires sensibles, faire échouer la validation quand current_workspace vaut None au lieu de désactiver les contrôles.
- **Relecture** : forms.py:180-184 : BaseStyledModelForm stocke current_workspace sans rien filtrer. DevflowUpdateView (views.py:439-450) ne redéfinit pas get_form_kwargs, donc ws=None dans InvoiceForm (2157-2218) : workspace, project et client gardent des querysets globaux et le contrôle croisé de clean() est sauté (InvoiceUpdateView 8858). Même chose pour InvoiceLineForm (2245), ProjectForm (team/teams) dans ProjectUpdateView (3864) et MeetingSeriesForm (le fichier réel est forms_meeting.py:232) dans MeetingSeriesUpdateView (views_meeting.py:466).

#### F29 — Une vingtaine de ModelForm sans aucun filtrage des FK, même en création (projets, tâches, canaux et utilisateurs de tous les tenants)
*Sécurité · Modèles / formulaires / signaux* — [project/forms.py:907](project/forms.py:907)

- **Preuve** : Ces formulaires n'ont pas de __init__ de scoping, ou ignorent current_workspace : SprintForm (907, project, team), SprintMetricForm, SprintReviewForm et SprintRetrospectiveForm (sprint), BacklogItemForm (1009), TaskAttachmentForm, TaskDependencyForm, TaskChecklistForm, ChecklistItemForm, PullRequestForm (1358), RiskForm (1383), AInsightForm (1410), NotificationForm (1436, recipient), ActivityLogForm, DirectChannelForm (members), ChannelMembershipForm (1489, channel et user), MessageForm (1503, channel), ReactionForm, TimesheetEntryForm (1556), TaskLabelForm, ProjectLabelForm, MilestoneTaskForm, ReleaseForm (tasks et sprints), BoardColumnForm, ObjectiveForm et KeyResultForm. RoadmapItemForm retombe sur `Milestone.objects.all()` (1830). DevflowCreateView.get_form ne restreint que le champ workspace. Toutes ces vues sont routées (urls.py : sprint_create, risk_create, notification_create, channel_membership_create, message_create, timesheet_entry_create…).
- **Impact** : Les listes déroulantes dévoilent le nom de tous les projets, tâches, sprints et canaux, ainsi que les noms et e-mails (via _user_choice_label) de tous les utilisateurs de la plateforme. Un membre peut créer un risque, un sprint ou un PR rattaché au projet d'un autre tenant. Il peut s'ajouter à un canal privé étranger, poster dans ce canal ou envoyer une notification avec une URL arbitraire à n'importe quel utilisateur.
- **Correctif** : Créer un helper `scope_form_fk(form, workspace)` appelé dans BaseStyledModelForm, qui filtre chaque ModelChoiceField selon son modèle cible (workspace, project__workspace, users_in_workspaces). Ajouter dans chaque clean() une vérification `obj.project.workspace_id == workspace.id`. Retirer de l'interface CRUD générique les formulaires techniques (Notification, ActivityLog, ChannelMembership, DashboardSnapshot).
- **Relecture** : SprintForm, RiskForm, NotificationForm, ChannelMembershipForm, MessageForm, TimesheetEntryForm, etc. (forms.py:907-1569) n'ont aucun __init__ de scoping, et BaseStyledModelForm (172-240) ne filtre aucun queryset. DevflowCreateView.get_form (views.py:365-389) ne restreint que le champ workspace, et RoadmapItemForm retombe sur Milestone.objects.all() (1830). Les modèles n'ont pas de clean() de cohérence (Sprint.clean, models.py:1264, ne vérifie que les dates).

#### F30 — TaskCommentQuickForm : commentaire possible sur la tâche de n'importe quel tenant
*Sécurité · Modèles / formulaires / signaux* — [project/forms.py:1266](project/forms.py:1266)

- **Preuve** : `self.fields["task"].queryset = Task.objects.select_related("project")…` n'est pas filtré et le champ est un simple HiddenInput modifiable. TaskCommentListView.get_task (views.py:5227-5234) fait `get_object_or_404(dm.Task…, pk=task_id)` sans workspace, et get_context_data expose `dm.Task.objects…[:100]` de tous les tenants (views.py:5243). post() enregistre le commentaire puis met à jour comments_count.
- **Impact** : Il suffit de modifier le champ caché task pour écrire un commentaire sur la tâche d'un autre client. La page liste aussi les titres des 100 dernières tâches de toute la plateforme et affiche la tâche ou le projet étranger passé en ?task=.
- **Correctif** : Passer user_workspace_ids au formulaire et filtrer `Task.objects.filter(workspace_id__in=ids)`. Scoper get_task avec `workspace_id__in=get_user_workspace_ids(request.user)` et la liste ctx["tasks"] de la même façon. Ajouter le test 404 cross-tenant.
- **Relecture** : forms.py:1266 met le queryset du champ task à Task.objects sans filtre, en HiddenInput. TaskCommentListView.get_task (views.py:5227-5234) fait get_object_or_404 sans workspace, et le contexte expose dm.Task.objects[:100] de tous les tenants (5243). post() sauvegarde le commentaire sur la tâche postée.

#### F31 — TaskForm n'est scopé que via user.profile.workspace : édition de tâche ouverte sur tous les tenants
*Sécurité · Modèles / formulaires / signaux* — [project/forms.py:1086](project/forms.py:1086)

- **Preuve** : Le filtrage de project, sprint, backlog_item, parent et assignee n'a lieu que `if user and user.is_authenticated` et si `user.profile.workspace` existe (1086-1136). TaskUpdateView (views.py:4947) ne passe pas `user`, donc tous les querysets sont globaux. Les utilisateurs sans profil (cf. signals.py:27-31) ne sont pas filtrés non plus. Task.save (models.py:1413-1414) ne réaligne workspace que s'il est vide, et aucun clean() ne vérifie `project.workspace_id == workspace_id`.
- **Impact** : Depuis l'édition d'une tâche, on voit et on peut choisir les projets, sprints, tâches et utilisateurs de tous les clients. Une tâche peut être rattachée au projet d'un autre tenant tout en gardant son workspace d'origine. Les filtres et budgets deviennent incohérents, et l'utilisateur étranger affecté est notifié par e-mail.
- **Correctif** : Scoper TaskForm sur current_workspace, transmis par la vue en création comme en édition, et non sur profile.workspace. Dans Task.clean(), vérifier que project, sprint, backlog_item, parent et assignee appartiennent à self.workspace. Dans Task.save, toujours aligner workspace sur project.workspace.
- **Relecture** : TaskForm (forms.py:1086-1136) ne filtre que si `user` est passé et que profile.workspace existe. TaskUpdateView (views.py:4947) n'a pas de get_form_kwargs, contrairement à TaskCreateView (4905), donc project, sprint, backlog_item, parent et assignee listent tous les tenants. Task.save (models.py:1412-1414) ne réaligne workspace que s'il est vide, et Task n'a pas de clean(). Une tâche peut ainsi être rattachée au projet d'un autre tenant.

#### F32 — Suppression physique d'un projet sans RBAC : CASCADE sur toutes les données financières
*Intégrité des données · Modèles / formulaires / signaux* — [project/models.py:2657](project/models.py:2657)

- **Preuve** : Les modèles suivants sont en `on_delete=models.CASCADE` vers Project : ProjectExpense.project (2657), ProjectRevenue (1170), ProjectBudget (852), ProjectEstimateLine (1062), ProjectBudgetSnapshot (5860), ProjectBudgetForecastRun (5910), ProjectMeeting (3135), Sprint, Task et Milestone. ProjectDeleteView (views.py:3886, route projects/<pk>/delete/) hérite de DevflowDeleteView, dont `rbac_delete_action = None` ; aucune sous-classe ne le définit (grep vide). Invoice.project est en PROTECT (4510), mais la ProtectedError n'est pas interceptée.
- **Impact** : N'importe quel membre du workspace, VIEWER ou CLIENT compris, peut effacer définitivement un projet avec ses dépenses validées, revenus, budget baseline, snapshots, réunions et comptes-rendus. Si le projet a des factures, la suppression renvoie une erreur 500.
- **Correctif** : Fixer `rbac_delete_action="project.delete"` sur ProjectDeleteView, ou remplacer la suppression physique par l'archivage. Passer ProjectExpense, ProjectRevenue et ProjectBudget en PROTECT, ou les conserver avec project=NULL. Intercepter ProtectedError avec un message clair.
- **Relecture** : ProjectDeleteView (views.py:3886) hérite de DevflowDeleteView avec rbac_delete_action=None (459), et aucune sous-classe ne le définit (grep). Project n'a pas de delete() soft (SoftDeleteModel, models.py:22, n'offre qu'archive()). La suppression est donc physique, en CASCADE vers ProjectExpense (2657) et les autres modèles, et la ProtectedError due à Invoice.project PROTECT n'est interceptée nulle part.

#### F52 — Vues facture (émettre/envoyer/annuler/PDF/DOCX/paiement/génération) sans filtrage workspace : IDOR cross-tenant
*Sécurité · Finance / TJM / facturation · doublon de F5* — [project/views.py:8930](project/views.py:8930)

- **Preuve** : InvoiceIssueView (8880), InvoiceMarkSentView (8895), InvoiceCancelView (8905), InvoicePDFView (8930), InvoiceDocxView (8960), InvoicePaymentCreateView (9057) et InvoiceGenerateFromProjectView (9080) héritent seulement de `DevflowBaseMixin, View`, sans WorkspaceSecurityMixin. Or `DevflowBaseMixin.filter_by_workspace` (l.179-190) fait `return queryset` sans filtre quand il n'y a pas de ?workspace et que `get_current_workspace` n'existe pas. `self.filter_by_workspace(dm.Invoice.objects.all()).get(pk=pk)` renvoie donc n'importe quelle facture. Avec `?workspace=<id>`, le filtre porte sur un workspace arbitraire, sans aucun contrôle d'appartenance. Le docstring d'InvoiceDocxView affirme le contraire (« aucune fuite cross-tenant »).
- **Impact** : N'importe quel utilisateur connecté peut, en énumérant les PK : télécharger le PDF ou le DOCX des factures des autres tenants (client, lignes avec les TJM, montants), les émettre, les annuler ou les marquer envoyées, y enregistrer des paiements (la facture passe en PAID), et générer une facture sur n'importe quel projet. Dans ce dernier cas, un client et des lignes sont créés à partir des timesheets du tenant victime.
- **Correctif** : Résoudre l'objet avec `get_object_or_404(dm.Invoice, pk=pk, workspace_id__in=get_user_workspace_ids(request.user))` (idem pour Project dans la génération), ou ajouter WorkspaceSecurityMixin dans le MRO. Faire renvoyer `queryset.none()` par défaut à filter_by_workspace (fail-closed). Ajouter les tests de non-régression dans tests_security.py.
- **Relecture** : Les vues Issue, MarkSent, Cancel, PDF, Docx, PaymentCreate et GenerateFromProject (views.py:8880-9136) héritent de DevflowBaseMixin sans WorkspaceSecurityMixin. Sans ?workspace, filter_by_workspace (l.179-190) renvoie donc le queryset brut, et avec ?workspace=X il filtre sans vérifier l'appartenance. Aucun décorateur n'est posé sur les routes (urls.py:806-819).

#### F53 — API DRF : clés étrangères écrivables non scopées, ce qui permet d'écrire dans les données financières d'autres tenants
*Sécurité · Finance / TJM / facturation · doublon de F7* — [project/api/serializers.py:226](project/api/serializers.py:226)

- **Preuve** : Les ModelSerializer génèrent `PrimaryKeyRelatedField(queryset=<Model>.objects.all())` pour : `project` (ProjectBudgetSerializer l.137, ProjectEstimateLineSerializer l.175, ProjectRevenueSerializer l.204, ProjectExpenseSerializer l.231, avec aussi task/sprint/milestone), `user`/`team` (BillingRateSerializer l.107) et `workspace`/`project`/`user` (TimesheetEntrySerializer l.323). Aucun `validate_*` n'est défini. WorkspaceScopedViewSetMixin ne filtre que get_queryset ; IsWorkspaceMember.has_permission renvoie True et has_object_permission n'est jamais appelé sur un create. AGENTS.md §4 n'est pas respectée.
- **Impact** : Un POST /api/v1/project-expenses/ (ou project-revenues, project-budgets, project-estimate-lines) avec le `project` d'un autre tenant fausse ses coûts, marges et budget. Un BillingRate créé pour un utilisateur d'un autre tenant modifie ses TJM, car le lookup ne se fait que par user. Un POST /api/v1/timesheets/ avec un `workspace`/`project` étranger et approval_status=APPROVED injecte des heures qui seront facturées en régie.
- **Correctif** : Ajouter validate_project/validate_workspace/validate_user/validate_task en contrôlant avec get_user_workspace_ids / user_can_access_workspace. Restreindre les querysets des champs dans __init__ via self.context['request'].user. Dans TimesheetEntryViewSet.perform_create, forcer user=request.user et un workspace vérifié.
- **Relecture** : serializers.py:98-338 : les FK project, task, sprint, milestone, user, team et workspace sont écrivables, sans aucun validate_* (grep vide). Les viewsets financiers (viewsets.py:303-386) n'ont pas de perform_create qui vérifie le workspace. HasRBACPermission.has_permission (rbac.py:336-340) et IsWorkspaceMember.has_permission renvoient True, et has_object_permission n'est pas appelé sur un create. On peut donc créer une dépense ou un revenu sur le projet d'un autre tenant.

#### F54 — Formulaires d'édition facturation instanciés sans current_workspace : listes et déplacements cross-tenant
*Sécurité · Finance / TJM / facturation · doublon de F28 · vu aussi par : Templates / routage / vues* — [project/views.py:439](project/views.py:439)

- **Preuve** : DevflowUpdateView (l.439-451) ne surcharge pas get_form_kwargs, contrairement à DevflowCreateView. InvoiceForm reçoit donc current_workspace=None : dans __init__ (forms.py l.2156-2186) et dans clean(), tout le scoping est sous `if ws:`, donc ignoré. Résultat sur InvoiceUpdateView (8859) : les champs `workspace` (queryset Workspace.objects.all), `project` et `client` ne sont pas restreints. Même chose pour InvoiceLineForm (champ `invoice`, forms.py l.2245-2251) via InvoiceLineUpdateView (9020), et pour InvoiceClientForm (`workspace`) via InvoiceClientUpdateView (8610).
- **Impact** : Les listes déroulantes affichent les projets, clients, workspaces et factures de tous les tenants. Un utilisateur peut déplacer une facture, une ligne ou un client vers un autre workspace, ou rattacher sa facture au projet d'un autre tenant.
- **Correctif** : Ajouter à DevflowUpdateView le même get_form_kwargs que DevflowCreateView (current_workspace, allowed_workspaces, request). Rendre InvoiceForm/InvoiceLineForm fail-closed : si ws est None, querysets vides. Retirer le champ `workspace` des formulaires d'édition.
- **Relecture** : Seules les lignes 346, 3804 et 4905 de views.py définissent get_form_kwargs, et DevflowUpdateView (439-451) n'en fait pas partie. InvoiceForm reçoit donc current_workspace=None, et tout le scoping de __init__ et de clean() est sous `if ws:` (forms.py:2158-2196). InvoiceUpdateView (8859), InvoiceLineUpdateView et InvoiceClientUpdateView acceptent ainsi un workspace, un projet, un client ou une facture d'un autre tenant.

#### F74 — Import de document : le formulaire liste les projets de tous les tenants et accepte un projet ou workspace étranger
*Sécurité · IA / méthodologies* — [project/views.py:3787](project/views.py:3787)

- **Preuve** : ProjectDocumentImportCreateView.get_project() fait `get_object_or_404(dm.Project..., pk=project_id, is_archived=False)` et get_workspace() fait `get_object_or_404(dm.Workspace, pk=workspace_id)`, tous deux sans scope. Sans paramètre (lien de document_import/list.html:37), ProjectDocumentImportForm met `Project.objects.filter(is_archived=False)` en queryset du champ project (forms.py:817-821), et form.html:71 affiche ce select.
- **Impact** : N'importe quel utilisateur connecté voit dans le select le nom de tous les projets de tous les tenants. Il peut aussi téléverser un document rattaché au projet ou au workspace d'un autre tenant (via ?project=ID ou le select). C'est une fuite de données et une écriture cross-tenant.
- **Correctif** : Scoper get_project et get_workspace par get_user_workspace_ids. Dans le formulaire, restreindre le queryset à `Project.objects.filter(workspace_id__in=user_ws_ids)` par défaut et ne jamais retomber sur tous les projets. Retirer `status` des champs éditables.
- **Relecture** : get_project() et get_workspace() (views.py:3783-3800) lisent GET ou POST et font get_object_or_404 sans scope. Sans paramètre, ProjectDocumentImportForm met Project.objects.filter(is_archived=False) en queryset (forms.py:816-821), affiché par form.html:71 depuis le lien de list.html:37. Un `project` étranger passé en POST fixe aussi obj.workspace = project.workspace en form_valid, car get_current_workspace ne contrôle que ?workspace en GET.

#### F97 — Chat legacy (FBV) : lecture/écriture de n'importe quel canal, tous tenants confondus
*Sécurité · Réunions / chat / Celery · doublon de F9* — [project/channel_chat_views.py:67](project/channel_chat_views.py:67)

- **Preuve** : channel_chat_page (l.14), channel_panel_detail (l.67) et channel_send_message (l.94) font `get_object_or_404(DirectChannel, pk=pk)` sans filtre workspace ni contrôle de membership. Routés dans ProjectFlow/urls.py l.251-255 (`channels/<pk>/`, `channels/<pk>/panel/`, `channels/<pk>/messages/send/`). Les IDs sont séquentiels. channel_panel_data (l.46) liste aussi tous les canaux privés (noms « DM @a / @b ») du workspace.
- **Impact** : Tout utilisateur connecté lit les 80 derniers messages de n'importe quel DM/groupe privé d'un autre tenant et peut y poster des messages en son nom. Fuite cross-tenant directe.
- **Correctif** : Résoudre le canal via `ChatService.get_channel_for(request.user, pk)` (workspace + membership) et renvoyer 404 sinon ; poster via `ChatService.post_message`. Ajouter un test dans tests_security.py (user A / canal W2 → 404). Supprimer ces FBV si l'UI ne les utilise plus (le panneau legacy n'est plus inclus dans base.html).
- **Relecture** : channel_chat_views.py:14, 69 et 96 font `get_object_or_404(DirectChannel, pk=pk)` sans filtre workspace ni membership. Ces vues sont importées et routées dans urls.py:10 et 251-255 : lecture des 80 derniers messages et écriture dans n'importe quel canal, tous tenants confondus. channel_panel_data (l.46) liste aussi les canaux privés du workspace sans contrôle de membership.

#### F98 — CRUD générique Message/ChannelMembership : poster sous n'importe quel auteur, rejoindre n'importe quel canal
*Sécurité · Réunions / chat / Celery* — [project/views.py:6013](project/views.py:6013)

- **Preuve** : MessageCreateView (views.py l.6013) et ChannelMembershipCreateView (l.5967) utilisent MessageForm (forms.py l.1503 : champs channel, author, parent) et ChannelMembershipForm (l.1489 : channel, user) sans aucun filtrage de queryset (BaseStyledModelForm ne filtre rien ; DevflowCreateView.get_form ne restreint que le champ `workspace`, et Message n'a pas de workspace). Routés : `messages/create/`, `channel-memberships/create/`. Par ailleurs MessageListView (l.5990) et DirectChannelDetailView (l.5915) filtrent seulement par workspace : tout membre lit les DM privés de ses collègues.
- **Impact** : Création de messages dans les canaux de n'importe quel tenant avec un auteur arbitraire (usurpation d'identité), ajout de soi-même à un DM privé (puis lecture complète via /api/v1/me/chat), et listes déroulantes qui énumèrent les canaux, les messages et les utilisateurs de toute la plateforme.
- **Correctif** : Désactiver ces vues CRUD (le chat passe par ChatService), ou forcer author=request.user, filtrer channel par `ChatService.channels_qs_for(user)` et user par `users_in_workspaces(channel.workspace_id)`, et restreindre Message/Detail aux canaux où l'utilisateur est membre. Ajouter des tests de non-régression.
- **Relecture** : MessageCreateView (views.py:6013) et ChannelMembershipCreateView (5967) utilisent MessageForm (champs channel, author et parent, forms.py:1503) et ChannelMembershipForm (channel et user, 1489) sans aucun filtrage. Message n'a pas de champ workspace, donc get_form ne restreint rien. DirectChannelDetailView (5915) ne filtre que par workspace et ignore is_private.

#### F120 — Une dizaine d'écrans de liste et le dashboard IA affichent les données de tous les tenants
*Sécurité · Templates / routage / vues · doublon de F4* — [project/views.py:4109](project/views.py:4109)

- **Preuve** : Ces get_queryset partent de `dm.X.objects` sans super() : SprintListView (4109), WorkspaceListView (1297), RiskListView (5397), AInsightListView (5644), MilestoneTaskListView (7117), ReleaseListView (7237), RoadmapListView (7379), RoadmapItemListView (7698), KeyResultListView (8482). ProjectDocumentImportListView (3636) ne filtre que si ?workspace est fourni et expose `workspace_list` = tous les workspaces. AInsightDashboardView (5512) hérite de DevflowBaseMixin sans WorkspaceSecurityMixin, donc filter_by_workspace renvoie le queryset non filtré (ligne 187). TaskListView expose `projects_filter`, `sprints_filter` et `assignees_filter` non scopés (4733-4740), rendus dans task/list.html:114. Effet de bord : search_fields et filter_fields déclarés (ex. 4091-4099) sont ignorés.
- **Impact** : Liste globale des workspaces, sprints, risques, insights IA, releases, roadmaps, KR et imports de tous les clients. Les noms de projets et d'utilisateurs des autres tenants apparaissent dans les filtres de la liste des tâches. La recherche et les filtres ne fonctionnent pas sur ces écrans.
- **Correctif** : Appeler `super().get_queryset()` dans chaque override, ou scoper explicitement via get_user_workspaces() pour WorkspaceListView. Faire hériter AInsightDashboardView de WorkspaceSecurityMixin. Scoper les querysets de filtres de TaskListView sur get_current_workspace().
- **Relecture** : Les get_queryset listés n'appellent pas super() (vérifié, y compris WorkspaceListView:1297). AInsightDashboardView (5510) hérite de DevflowBaseMixin seul, donc filter_by_workspace renvoie le queryset brut (l.187). projects_filter, sprints_filter et assignees_filter ne sont pas scopés (4733-4740), et ProjectDocumentImportListView expose workspace_list=tous les workspaces (3700).

#### F121 — Actions rapides POST non scopées : modification de tâches et d'insights de n'importe quel tenant
*Sécurité · Templates / routage / vues · doublon de F5* — [project/views.py:4371](project/views.py:4371)

- **Preuve** : TaskQuickAssignView (4363), TaskQuickStatusView (4390), TaskQuickCommentView (4426), TaskToggleFlagView (4460), TaskMarkDoneView (5111), AInsightDismissView (5770) et WorkspaceInvitationAcceptView (7980) héritent de DevflowBaseMixin seul. Dans filter_by_workspace (179-187), sans ?workspace et sans get_current_workspace, la méthode fait `return queryset` non filtré, puis `.get(pk=pk)`. roadmap_item_shift_dates (7475-7481) fait `get_object_or_404(dm.RoadmapItem, pk=item_id)` sans workspace_id__in (règle 2). TaskQuickAssignView accepte aussi n'importe quel `User` actif (4380), et plusieurs vues font `redirect(next_url)` sur un POST['next'] non validé.
- **Impact** : Tout utilisateur connecté peut changer le statut, marquer comme terminée, commenter, flagger ou réassigner une tâche de n'importe quel client. Il peut aussi décaler les dates de sa roadmap, masquer ses insights ou accepter ses invitations. S'y ajoutent l'assignation à des utilisateurs externes et une redirection ouverte.
- **Correctif** : Ajouter WorkspaceSecurityMixin, ou utiliser `get_object_or_404(..., workspace_id__in=get_user_workspace_ids(request.user))`. Restreindre l'assigné à users_in_workspaces([task.workspace_id]). Valider `next` avec url_has_allowed_host_and_scheme. Ajouter les tests de non-régression.
- **Relecture** : Mêmes vues que F5 (views.py:4363-4470, 5111, 5770, 7980) : filter_by_workspace de DevflowBaseMixin renvoie le queryset complet, puis `.get(pk=pk)`. roadmap_item_shift_dates (l.7481) n'est pas scopé. TaskQuickAssignView (l.4380) accepte tout User actif. `redirect(request.POST.get('next'))` sans url_has_allowed_host_and_scheme crée une redirection ouverte.

#### F122 — filter_by_workspace utilise ?workspace= sans contrôle : suppression, édition et archivage cross-tenant
*Sécurité · Templates / routage / vues · doublon de F6* — [project/views.py:180](project/views.py:180)

- **Preuve** : `workspace_id = self.get_workspace_id()` renvoie `self.request.GET.get("workspace")` (160-161), injecté tel quel dans `queryset.filter(workspace_id=workspace_id)` sans vérifier l'appartenance à get_user_workspaces(). Seul get_current_workspace() valide, et il n'est appelé que dans get_context_data. DeleteView.post (Django 4.2) fait get_object → form_valid → delete sans jamais rendre de contexte. Idem pour UpdateView.post quand le formulaire est valide et pour ArchiveObjectView.post (500-505).
- **Impact** : `POST /projects/<pk>/delete/?workspace=<id_victime>` supprime le projet d'un autre client, en cascade sur ses tâches, sprints et budgets. La même requête sur /archive/ ou /update/ archive ou modifie l'objet. C'est une perte de données exploitable.
- **Correctif** : Dans filter_by_workspace, résoudre le workspace via get_current_workspace(), qui lève Http404 s'il n'appartient pas à l'utilisateur, ou intersecter avec get_user_workspaces(). Ajouter des tests delete/archive avec ?workspace d'un autre tenant.
- **Relecture** : Doublon de F6, même preuve : `queryset.filter(workspace_id=workspace_id)` (views.py:195) utilise la valeur brute de ?workspace (160-161). DeleteView.post et UpdateView.post (formulaire valide) de Django 4.2, ainsi qu'ArchiveObjectView.post (500-505), ne passent jamais par get_current_workspace, qui est le seul contrôle d'appartenance.

### 🟠 Haute (48)

#### F11 — HasRBACPermission ne contrôle ni list, ni create, ni les actions personnalisées : TJM visibles, approbation de dépenses par un MEMBER
*Sécurité · Sécurité / multi-tenant · vu aussi par : Finance / TJM / facturation* — [project/services/rbac.py:336](project/services/rbac.py:336)

- **Preuve** : has_permission() renvoie toujours True (l.340), et has_object_permission() n'est appelé que sur les actions detail. Une action absente de rbac_action_map passe (`return True`, l.346). Les actions approve_level1, approve_level2 et reject de ProjectExpenseViewSet (viewsets.py:368-385) ne sont pas mappées et appellent directement expense.approve_level1(user), sans les can_approve_level1/2 de l'interface HTML (views_budget.py:79-117).
- **Impact** : Un MEMBER peut lister tous les BillingRate (TJM coût et vente) via GET /api/v1/billing-rates/, créer budgets, revenus et dépenses, et approuver aux niveaux 1 et 2 ses propres dépenses par l'API. Le circuit de validation financière est contourné.
- **Correctif** : Dans has_permission, appliquer rbac_action_map pour list et create, avec le workspace résolu via request.data.project ou le workspace courant. Refuser par défaut les actions non mappées. Mapper approve_level1/2 et reject vers budget.approve et réutiliser les règles can_approve_*.
- **Relecture** : has_permission renvoie True pour tout utilisateur authentifié (rbac.py:336-340), et has_object_permission n'est invoqué que sur les actions detail. Un list sur BillingRateViewSet ('billing.view', viewsets.py:310) passe donc pour tout membre. Les actions approve_level1, approve_level2 et reject (viewsets.py:368-385) ne sont pas mappées (`return True`, rbac.py:346), et les méthodes du modèle (models.py:2768-2823) ne vérifient aucun rôle.

#### F12 — ProjectFinancialPermissionMixin contourné sur les vues par pk : modification du budget approuvé par tout membre
*Sécurité · Sécurité / multi-tenant* — [project/views_budget.py:132](project/views_budget.py:132)

- **Preuve** : dispatch() appelle ensure_financial_permission() avant le chargement de l'objet : self.object vaut None et get_project_from_request() ne lit que ?project= ou kwargs project_id. Pour ProjectBudgetUpdateView et ProjectBudgetDetailView (urls : project-budgets/<pk>/...) et ProjectExpenseDetail/UpdateView (project-expenses/<pk>/...), project vaut None, donc `if project and not ...` ne refuse jamais (l.129).
- **Impact** : Tout MEMBER ou CLIENT du workspace peut lire le détail financier et modifier approved_budget, planned_revenue et target_margin_percent, faussant marges et alertes. Le RBAC (budget.edit réservé à l'owner) n'est pas appliqué.
- **Correctif** : Faire le contrôle après get_object() (redéfinir get_object pour appeler ensure_financial_permission sur obj.project) et distinguer budget.view pour la lecture de budget.edit pour l'écriture.
- **Relecture** : dispatch (views_budget.py:133-136) appelle ensure_financial_permission avec self.object=None. get_project_from_request ne lit que ?project= ou kwargs project_id, absents des routes project-budgets/<pk>/ et project-expenses/<pk>/ (urls.py:132-141). project vaut donc None et le contrôle est sauté (l.129). L'accès reste intra-tenant grâce au filtre workspace de DevflowDetail/UpdateView.

#### F13 — Auto-approbation des timesheets (HTML et API), base des coûts réels et de la facturation
*Sécurité · Sécurité / multi-tenant* — [project/views.py:6098](project/views.py:6098)

- **Preuve** : TimesheetWeekValidateView.post : aucun contrôle de rôle. `target_user = get_object_or_404(User, pk=user_id)`, puis action=approve pose approval_status=APPROVED et approved_by=request.user. Côté API, TimesheetEntrySerializer (serializers.py:318-338) laisse approval_status et user en écriture. Le filtrage MEMBER de TimesheetEntryViewSet (viewsets.py:428) se base sur get_default_workspace_for_user et non sur le workspace de l'entrée.
- **Impact** : Un MEMBER valide ses propres semaines, ou crée par l'API des entrées APPROVED pour d'autres utilisateurs. Coûts réels, EAC et factures en mode TIMESHEET sont falsifiables. Un utilisateur PM dans W1 et MEMBER dans W2 voit tous les timesheets de W2, avec le computed_cost issu des TJM.
- **Correctif** : Exiger RBACService.can(user, "timesheet.approve", workspace=ws) et interdire l'auto-approbation. Rendre approval_status read-only dans le serializer et passer par une action dédiée. Forcer user=request.user pour les rôles MEMBER. Calculer le rôle par workspace de l'objet.
- **Relecture** : views.py:6098-6158 : aucun contrôle de rôle (timesheet.approve), donc tout membre du workspace courant peut approuver sa propre semaine ou celle d'un autre. Le filtre workspace limite l'effet au même tenant. TimesheetEntrySerializer (serializers.py:318-338) laisse user et approval_status écrivables. Le filtre MEMBER (viewsets.py:420-432) repose sur get_default_workspace_for_user, pas sur le workspace de l'entrée.

#### F14 — DEBUG=True forcé en production (prod.py et dev.py), DJANGO_ENV absent du docker-compose
*Sécurité · Sécurité / multi-tenant* — [ProjectFlow/settings/prod.py:5](ProjectFlow/settings/prod.py:5)

- **Preuve** : prod.py:5 `DEBUG = True` en dur. dev.py:13 `DEBUG = True` et dev.py:6 `ALLOWED_HOSTS = ['*']`. settings/__init__.py:3 prend 'dev' par défaut, et docker-compose.yml ne définit pas DJANGO_ENV (seulement DEBUG=False, qui est ensuite écrasé). Les cookies sécurisés sont évalués dans base.py avant cet écrasement.
- **Impact** : Les erreurs 500 affichent des pages de debug (stack, requêtes SQL, variables locales). ALLOWED_HOSTS='*' (empoisonnement du Host et des liens de reset). Django sert /media/ et /preview/error/ (urls.py:905-929).
- **Correctif** : Supprimer DEBUG=True de prod.py (`DEBUG = config("DEBUG", default=False, cast=bool)`), définir DJANGO_ENV=prod dans compose, faire échouer le démarrage si SECRET_KEY vaut la valeur par défaut, et activer SECURE_SSL_REDIRECT et HSTS par défaut en prod.
- **Relecture** : prod.py:5 et dev.py:13 fixent `DEBUG = True`, et dev.py:6 fixe `ALLOWED_HOSTS=['*']`. settings/__init__.py:3 prend 'dev' par défaut, docker-compose ne définit pas DJANGO_ENV, et le .env local vaut DJANGO_ENV=dev. Les cookies Secure sont calculés sous `if not DEBUG` dans base.py:56-63, avant l'écrasement.

#### F15 — Médias servis sans authentification et uploads non validés (IDOR et XSS stockée)
*Sécurité · Sécurité / multi-tenant* — [ProjectFlow/urls.py:929](ProjectFlow/urls.py:929)

- **Preuve** : `urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` (DEBUG est toujours actif, cf. constat précédent). deploy/nginx/media.conf:4 sert /media/ en public (Cache-Control public). TaskQuickAttachmentView (views.py:4494-4506) enregistre `request.FILES['file']` sans contrôle d'extension, de type ni de taille. Les chemins prévisibles sont devflow/tasks/attachments/<nom original>, devflow/invoices/, devflow/project_imports/, devflow/messages/attachments/.
- **Impact** : Pièces jointes, factures PDF, documents contractuels importés et enregistrements audio (stockage par défaut) accessibles sans connexion à quiconque connaît ou devine l'URL. Un fichier .html ou .svg uploadé est servi depuis l'origine de l'application (XSS stockée).
- **Correctif** : Servir les médias sensibles via une vue authentifiée scopée par workspace (X-Accel-Redirect nginx) ou des URL S3 signées. Whitelister extensions et MIME, limiter la taille, forcer Content-Disposition: attachment et nosniff.
- **Relecture** : prod.py:5 force DEBUG = True, donc urls.py:929 sert MEDIA via static(). media.conf sert /media/ en public. TaskQuickAttachmentView (views.py:4494-4506) et TaskAttachment.file (models.py:1523) n'ont aucun validateur d'extension, de type ou de taille.

#### F16 — Assignation de tâche à un utilisateur de n'importe quel tenant
*Sécurité · Sécurité / multi-tenant* — [project/api/views_quick.py:195](project/api/views_quick.py:195)

- **Preuve** : TaskQuickAssignJSONView : `assignee = get_object_or_404(User, pk=user_id, is_active=True)`. Le commentaire renvoie à Task.assign(), mais models.py:1430-1472 ne valide aucune appartenance au workspace. Même problème dans views.py:4379 (TaskQuickAssignView).
- **Impact** : L'utilisateur étranger reçoit une notification et un email (titre et contexte de la tâche, donc fuite de données). La tâche apparaît dans son calendrier de timesheets via TaskAssignment (signals.py:89-94). Les données d'affectation et de coût TJM sont faussées.
- **Correctif** : Restreindre aux users_in_workspaces({task.workspace_id}) avant assign(), et ajouter cette validation dans Task.assign() lui-même.
- **Relecture** : api/views_quick.py:195 : `get_object_or_404(User, pk=user_id, is_active=True)`. Task.assign (models.py:1430-1472) ne valide aucune appartenance, et full_clean ne vérifie pas le workspace de l'assignee. L'utilisateur externe reçoit une notification et un e-mail avec le titre et le projet de la tâche.

#### F17 — Suppressions HTML sans RBAC : le check PR28 n'est jamais actif
*Sécurité · Sécurité / multi-tenant · vu aussi par : Templates / routage / vues* — [project/views.py:459](project/views.py:459)

- **Preuve** : `rbac_delete_action: str | None = None`. Aucune sous-classe ne le définit (grep « rbac_delete_action = » sans résultat), donc le contrôle de dispatch (465-488) ne s'exécute jamais. En Django 4.2, les delete() redéfinis (491, 1414) ne sont pas appelés : DeleteView passe par form_valid, et les messages de succès sont perdus.
- **Impact** : Tout MEMBER ou CLIENT d'un workspace peut supprimer physiquement projets, tâches, sprints, timesheets, factures, etc. (CASCADE).
- **Correctif** : Définir rbac_delete_action par défaut à « <model_name>.delete » ou par sous-classe (project.delete, task.delete…), et déplacer le message dans form_valid().
- **Relecture** : `rbac_delete_action = None` (views.py:459) n'est surchargé nulle part (grep), donc le bloc de dispatch (465-488) est mort. En Django 4.2, BaseDeleteView.post appelle form_valid et non delete() : les delete() redéfinis (491, 1414) et leurs messages de succès ne s'exécutent pas.

#### F18 — Acceptation d'invitation impossible (500) pour un utilisateur existant déjà rattaché à un autre workspace
*Bug · Sécurité / multi-tenant* — [project/views.py:8072](project/views.py:8072)

- **Preuve** : WorkspaceInvitationPublicAcceptView.post : `dm.UserProfile.objects.get_or_create(user=user, workspace=invitation.workspace)`. Or UserProfile.user est un OneToOneField (models.py:252). Si le profil existe avec un autre workspace, le lookup échoue, la création viole l'unicité de user_id, une IntegrityError est levée et la transaction est annulée.
- **Impact** : Le flux d'onboarding multi-workspace est cassé : un utilisateur existant ne peut pas rejoindre un second workspace (erreur 500, invitation bloquée en PENDING).
- **Correctif** : Utiliser get_or_create(user=user, defaults={"workspace": invitation.workspace}). L'appartenance au nouveau workspace passe par TeamMembership, qui est déjà créé.
- **Relecture** : views.py:8072 fait get_or_create(user=user, workspace=invitation.workspace). UserProfile.user est un OneToOneField (models.py:252) : si le profil existe avec un autre workspace, la création viole l'unicité. L'IntegrityError n'est pas capturée dans le bloc transaction.atomic, d'où un 500.

#### F19 — ProjectDocumentImportCreateView : workspace et projet POST non vérifiés
*Sécurité · Sécurité / multi-tenant* — [project/views.py:3800](project/views.py:3800)

- **Preuve** : get_workspace() fait `get_object_or_404(dm.Workspace, pk=workspace_id, is_archived=False)` avec workspace lu dans GET/POST, sans user_can_access_workspace. get_project() (3787) est non scopé. form_valid fixe ensuite obj.workspace et obj.project avec ces valeurs.
- **Impact** : Création de documents importés (et du pipeline IA associé) dans le workspace ou le projet d'un autre tenant. Cela viole la convention n°4.
- **Correctif** : Vérifier user_can_access_workspace(request.user, ws) et scoper le projet avec workspace_id__in=get_user_workspace_ids(user).
- **Relecture** : views.py:3783-3801 : get_project et get_workspace ne sont pas scopés, et ProjectDocumentImportForm (forms.py:816-821) propose sans workspace les projets de tous les tenants. Nuance : obj.workspace est ensuite réécrit par DevflowCreateView.form_valid (super(), l.3842) avec le workspace courant, et ?workspace étranger en GET lève une 404 via get_current_workspace. En revanche, obj.project peut pointer vers un projet d'un autre tenant.

#### F22 — Invitations workspace sans RBAC : tout membre invite avec n'importe quel rôle
*Sécurité · Sécurité / multi-tenant (initialement medium)* — [project/views.py:7874](project/views.py:7874)

- **Preuve** : WorkspaceInvitationCreateView, ResendView, RevokeView, UpdateView et l'acceptation côté admin (7980, sans WorkspaceSecurityMixin) ne vérifient pas members.invite ni members.manage. WorkspaceInvitationForm expose "role" (forms.py:1913).
- **Impact** : Un MEMBER ou CLIENT peut faire entrer des tiers dans le tenant avec un rôle élevé (ADMIN, CTO…), ce qui débloque le repli financier legacy de can_view_financials (views_budget.py:69-76).
- **Correctif** : Exiger RBACService.can(user, "members.invite", workspace=ws) et limiter les rôles attribuables à ceux inférieurs ou égaux au rôle de l'invitant.
- **Relecture** : WorkspaceInvitationCreateView, Update, Resend et Revoke (views.py:7874-7972) ne font aucun contrôle RBAC, et le rôle choisi peut être ADMIN ou CTO (models.py:2306-2309), rôles que can_view_financials accepte (views_budget.py:69-75). De plus, WorkspaceInvitationAcceptView (7980) hérite de DevflowBaseMixin seul : filter_by_workspace n'y filtre pas, donc n'importe qui peut accepter une invitation d'un autre tenant. Sévérité relevée : escalade de privilèges.

#### F23 — TeamMembershipForm énumère tous les utilisateurs actifs de la plateforme
*Sécurité · Sécurité / multi-tenant (initialement medium) · vu aussi par : Modèles / formulaires / signaux* — [project/forms.py:403](project/forms.py:403)

- **Preuve** : `self.fields["user"].queryset = User.objects.filter(is_active=True)` (commentaire : « Tous les users actifs »). Le sélecteur rend noms et prénoms de tous les comptes, tous tenants confondus.
- **Impact** : Fuite de l'annuaire complet des clients de la plateforme, et rattachement d'un utilisateur d'un autre tenant sans son consentement.
- **Correctif** : Limiter à users_for_user(request.user) et passer par le flux d'invitation pour les nouveaux utilisateurs.
- **Relecture** : forms.py:409-412 : `User.objects.filter(is_active=True)` affiche noms et usernames de tous les comptes de la plateforme, et permet d'ajouter un utilisateur d'un autre tenant dans son workspace sans consentement. Sévérité relevée à high : c'est une énumération cross-tenant de données personnelles.

#### F33 — Champs d'identité et d'audit exposés : usurpation d'auteur et approbations falsifiées
*Sécurité · Modèles / formulaires / signaux* — [project/forms.py:1508](project/forms.py:1508)

- **Preuve** : MessageForm expose "author" (1508), TaskCommentForm "author" et "edited_at" (1280), ReactionForm "user", ActivityLogForm "actor", TaskAttachmentForm "uploaded_by" et "size", ChecklistItemForm "checked_by", TaskLabelForm "added_by" et TaskAssignmentForm "assigned_by". TimesheetEntryForm expose "user", "approved_by" et "approved_at" (1560-1569). APIKeyForm expose "created_by", "key_hash" et "key_prefix" (2015-2018) : l'utilisateur saisit lui-même le hash et aucune clé n'est générée. IntegrationForm affiche access_token_encrypted et refresh_token_encrypted en clair (1975-1976).
- **Impact** : Un membre peut publier un message ou un commentaire au nom d'un autre utilisateur. Il peut saisir des heures pour un collègue et poser approved_by/approved_at sur ses propres heures, ou forger le journal d'activité. La création de clé API depuis l'interface ne fonctionne pas, et les jetons d'intégration apparaissent dans le HTML.
- **Correctif** : Retirer ces champs des formulaires et les remplir côté serveur (request.user, timezone.now()). Générer les clés API côté serveur (secrets.token_urlsafe, SHA-256) et n'afficher la clé qu'une seule fois. Ne jamais rendre les jetons d'intégration dans un formulaire.
- **Relecture** : Les Meta.fields exposent bien author (MessageForm 1508, TaskCommentForm 1280), user/approved_by/approved_at (TimesheetEntryForm 1560-1569), created_by/key_hash/key_prefix (APIKeyForm 2015-2018) et les tokens chiffrés (IntegrationForm 1975-1976). Aucune vue Create ne réécrit ces champs avec request.user, et APIKey n'a aucune logique de génération de clé (models.py).

#### F35 — Résolution du TJM : tarifs archivés appliqués, tarifs d'équipe ignorés, tarif d'un autre projet utilisé
*Bug · Modèles / formulaires / signaux · vu aussi par : Finance / TJM / facturation* — [project/models.py:731](project/models.py:731)

- **Preuve** : `filter_kwargs = {"user": user, "valid_from__lte": today}` ne filtre ni `is_archived=False` ni team. Le signal create_or_update_timesheet_snapshot (signals.py:137-146) cherche `BillingRate.objects.filter(user_id=…, is_internal_cost=True…)` sans projet, sans is_archived et sans équipe. invoicing.py:188/217 appelle `get_user_sale_daily_rate(user)` sans project, ce qui utilise le mode « tous tarifs confondus ». L'admin propose pourtant une action « Archiver les tarifs » (admin.py:901), et BillingRate.clean autorise des tarifs par équipe ou par nom seul (671-675) qu'aucun calcul n'utilise.
- **Impact** : Un tarif archivé reste appliqué. Un TJM négocié pour le projet B est figé dans le snapshot de coût et dans la facture régie du projet A. Les tarifs d'équipe saisis par l'utilisateur ne sont jamais pris en compte, et les coûts réels et marges deviennent faux.
- **Correctif** : Centraliser une seule méthode `BillingRate.resolve(user, project, on_date, kind)` qui filtre `is_archived=False` et applique l'ordre projet > utilisateur générique > équipe (via TeamMembership) > profil. L'utiliser dans le signal snapshot et dans InvoiceGenerator en passant le projet de l'entrée.
- **Relecture** : models.py:731 : filter_kwargs ne contient ni is_archived=False (BillingRate est un SoftDeleteModel, l.603) ni team. signals.py:137-146 cherche sans projet ni is_archived et peut donc prendre le tarif spécifique d'un autre projet. invoicing.py:188/217 appelle get_user_sale_daily_rate(user) sans project. Aucun lookup BillingRate n'utilise team (grep).

#### F36 — BillingRate sans workspace : TJM partagés et divulgués entre tenants
*Sécurité · Modèles / formulaires / signaux* — [project/models.py:618](project/models.py:618)

- **Preuve** : BillingRate n'a pas de FK workspace. Ses seules cibles sont user, team et project (618-656). La résolution du coût filtre uniquement `user=user` (731). L'API scope via `Q(team__workspace…) | Q(user__profile__workspace_id__in=…)` (api/permissions.py:96-100). Un utilisateur membre de deux workspaces via TeamMembership a un seul profil (UserProfile.user est un OneToOne).
- **Impact** : Le tarif d'un consultant saisi par le tenant B est lu et appliqué dans les budgets du tenant A. Il est aussi listé par l'API pour le tenant A si le profil du consultant pointe vers A. Les tarifs génériques (nom seul) sont invisibles partout.
- **Correctif** : Ajouter `workspace = FK(Workspace)` obligatoire, avec une migration qui le remplit depuis team.workspace, project.workspace ou user.profile.workspace. Filtrer la résolution et le scoping par ce workspace.
- **Relecture** : BillingRate n'a de FK que vers user, team et project (models.py:618-656). Le tarif générique est résolu par `user=user` seul (filter_kwargs ~l.731), et l'API scope via `user__profile__workspace_id__in` (api/permissions.py:96-100). Un tarif saisi par W2 pour un utilisateur dont le profil est dans W1 est donc visible dans W1 et utilisé dans ses calculs (cas des utilisateurs multi-workspaces).

#### F37 — Signal post_save Task : e-mail au chef de projet envoyé de façon synchrone dans la requête HTTP
*Performance · Modèles / formulaires / signaux* — [project/signals.py:331](project/signals.py:331)

- **Preuve** : notify_pm_on_task_change appelle `TaskUpdateNotifier.notify_pm(instance, before, actor=None)`. Cette méthode exécute `send_mail(...)` directement (services/task_reminder.py:380), ce qui enfreint la convention n°6 d'AGENTS.md. Comme actor vaut toujours None, le test `pm == actor` (task_reminder.py:335) ne réussit jamais.
- **Impact** : Chaque changement de statut ou d'assignation (déplacement kanban, édition) bloque la requête sur le serveur SMTP, avec risque de timeout si SMTP est lent. Le chef de projet reçoit aussi un e-mail pour ses propres modifications.
- **Correctif** : Remplacer send_mail par une tâche Celery `.delay()` déclenchée via transaction.on_commit. Transmettre l'acteur réel (instance._assigned_by ou un attribut posé par la vue) pour éviter l'auto-notification.
- **Relecture** : signals.py:331 appelle TaskUpdateNotifier.notify_pm avec actor=None. La méthode exécute send_mail en synchrone (task_reminder.py:378-385), à chaque post_save d'une tâche, ce qui enfreint la convention n°6. Le test `pm == actor` (l.335) n'est jamais vrai.

#### F38 — Recalcul du budget à chaque sauvegarde de tâche : écrase un budget APPROVED ou CLOSED et casse les liens de facture
*Intégrité des données · Modèles / formulaires / signaux* — [project/signals.py:363](project/signals.py:363)

- **Preuve** : refresh_project_budget_on_task_change lance `refresh_project_budget_task.delay(project_id)` à chaque post_save de Task, sans transaction.on_commit ni dédoublonnage. La tâche appelle refresh_project_financials, qui (1) supprime et recrée toutes les ProjectEstimateLine de source TASK (budget.py:466-469), alors que InvoiceLine.estimate_line est en SET_NULL (models.py:4697), et (2) regenerate_budget_from_estimates réécrit les champs estimated_* et `budget.save()` (budget.py:668-690) quel que soit ProjectBudget.status.
- **Impact** : Un budget APPROVED, BASELINE ou CLOSED voit ses coûts estimés modifiés à chaque mouvement de tâche, ce qui contourne la machine à états transition_to. Les lignes de facture forfait perdent leur traçabilité. Appliquer une proposition IA de 50 tâches lance 50 recalculs complets, parfois avant le commit.
- **Correctif** : Utiliser transaction.on_commit avec un verrou ou un cache de debounce par projet. Ne rien réécrire si `budget.status in {BASELINE, APPROVED, CLOSED}` (alimenter seulement le forecast). Mettre à jour les lignes TASK au lieu de les supprimer.
- **Relecture** : signals.py:362-391 : `.delay(project_id)` à chaque post_save de Task, sans on_commit ni dédoublonnage. refresh_project_financials (budget.py:812-820) appelle regenerate_estimate_lines_from_tasks(replace_existing=True) (delete l.466-469), alors que InvoiceLine.estimate_line est en SET_NULL (models.py:4697). regenerate_budget_from_estimates (627-690) fait budget.save() sans tester status APPROVED ou CLOSED.

#### F40 — ProjectForm empêche d'enregistrer tout projet en retard et écrase le health_status saisi
*UX · Modèles / formulaires / signaux* — [project/forms.py:739](project/forms.py:739)

- **Preuve** : `if target and target < timezone.now().date() and progress < 100: self.add_error("target_date", "Ce projet est en retard…")`, alors que Project.Status.DELAYED existe. save() (763-779) recalcule health_status à partir de `obj.risk_score`, qui n'est pas encore recalculé puisque Project.save le fait après. La valeur de health_status saisie dans le formulaire est donc toujours écrasée, et vaut GRAY à la création.
- **Impact** : Impossible de modifier un projet en retard (statut, description, équipe) sans repousser sa date cible ou le passer à 100 %. Le champ « santé » est affiché mais sans effet.
- **Correctif** : Transformer ce contrôle en avertissement non bloquant (message ou statut DELAYED automatique). Soit retirer health_status du formulaire, soit le calculer après `compute_risk_score(obj)`.
- **Relecture** : forms.py:739 ajoute une erreur bloquante dès que la date cible est passée et l'avancement < 100, même pour modifier une description, alors que Project.Status.DELAYED existe (models.py:367). save() (763-779) recalcule health_status depuis l'ancien risk_score (Project.save le recalcule après), ce qui écrase la valeur saisie (GRAY à la création).

#### F50 — Validation des dépenses à 2 niveaux sans séparation des tâches
*Fonctionnalité manquante · Modèles / formulaires / signaux (initialement medium)* — [project/models.py:2788](project/models.py:2788)

- **Preuve** : approve_level2 vérifie seulement `approval_state == LEVEL1_APPROVED`, sans exclure `level1_approved_by` ni `created_by`. can_approve_level1 et can_approve_level2 (views_budget.py:80-120) permettent au même utilisateur, par exemple un TECH_LEAD propriétaire du projet, de valider les deux niveaux.
- **Impact** : Une même personne peut créer une dépense, la valider au niveau 1 puis au niveau 2 : le circuit à quatre yeux est contournable.
- **Correctif** : Dans approve_level1 et approve_level2, lever une ValidationError si `user == created_by` ou `user == level1_approved_by`. Ajouter les tests correspondants.
- **Relecture** : models.py:2768-2806 : approve_level2 ne vérifie que l'état, et can_approve_level1/2 (views_budget.py:80-120) se recoupent (un TECH_LEAD propriétaire du projet a les deux). Aggravation relevée à high : côté API, approve_level1 et approve_level2 (viewsets.py:368-378) sont absentes de rbac_action_map, et HasRBACPermission renvoie True (rbac.py:345-346). Tout membre peut donc valider les deux niveaux.

#### F55 — Création de ligne d'estimation ou de dépense : les listes tâche/sprint/jalon contiennent les objets de tous les tenants
*Sécurité · Finance / TJM / facturation (initialement critical)* — [project/forms_budget.py:154](project/forms_budget.py:154)

- **Preuve** : ProjectEstimateLineForm (l.154-180) et ProjectExpenseForm (l.207-245) exposent task, sprint et milestone avec les querysets par défaut (Task/Sprint/Milestone.objects.all()), et StyledModelForm ne filtre rien. ProjectEstimateLineCreateView (views_budget.py l.180-196) et ProjectExpenseCreateView (l.502-518) ne restreignent pas ces champs ; seul ProjectExpenseUpdateView.get_form le fait (l.231-237). Les templates estimate_line/form.html et expense/form.html affichent {{ form.task }} et {{ form.sprint }}.
- **Impact** : Fuite des titres de tâches, sprints et jalons de tous les workspaces. Une ligne ou une dépense peut aussi être rattachée à un objet d'un autre tenant.
- **Correctif** : Dans get_form des vues de création, filtrer les querysets sur le projet résolu (et scopé) depuis ?project. Dans clean(), vérifier que task.project_id == project.id.
- **Relecture** : ProjectEstimateLineForm et ProjectExpenseForm (forms_budget.py:154-245) gardent les querysets par défaut, et StyledModelForm ne filtre rien. Les CreateView (views_budget.py:180, 502) ne restreignent pas ces champs, contrairement à ExpenseUpdateView.get_form (231-237), et les templates rendent {{ form.task }}/{{ form.sprint }}/{{ form.milestone }}. Sévérité abaissée : la fuite se limite aux libellés de tâches, sprints et jalons dans les listes déroulantes.

#### F56 — BudgetSnapshotService.capture plante dès qu'un ProjectBudget existe (budget_obj non sérialisable) ; la baseline est perdue sans erreur visible
*Bug · Finance / TJM / facturation* — [project/services/budget_snapshots.py:94](project/services/budget_snapshots.py:94)

- **Preuve** : capture() sérialise le résultat de build_budget_overview, qui contient `"budget_obj": budget`, une instance ProjectBudget (budget.py l.754). _serialize_for_json (l.39-49) laisse passer tel quel tout ce qui n'est pas Decimal, date, dict ou liste. JSONField.get_prep_value appelle alors json.dumps(..., cls=None), qui lève TypeError (Django 4.2). transition_to('BASELINE') avale l'exception (`except Exception: pass`, models.py l.946-958). POST /api/v1/projects/{id}/budget/snapshot/ renvoie 500. Le test test_baseline_transition_creates_snapshot (tests_budget_v2.py l.272) ne peut pas passer.
- **Impact** : Aucune baseline n'est figée, la comparaison baseline/forecast est impossible, et l'échec est silencieux.
- **Correctif** : Retirer budget_obj du payload (ou le remplacer par son id), ou utiliser encoder=DjangoJSONEncoder. Logger l'exception dans transition_to au lieu de l'ignorer.
- **Relecture** : build_budget_overview renvoie `"budget_obj": budget` (budget.py:754). _serialize_for_json (budget_snapshots.py:39-49) le laisse passer, et ProjectBudgetSnapshot.payload est un JSONField sans encoder : TypeError à l'acreate dès qu'un ProjectBudget existe (Django 4.2.30). transition_to avale l'exception (models.py:946-958). Les tests ne peuvent de toute façon pas tourner : le graphe de migrations est cassé (NodeNotFoundError 0034_merge_20260601_1049).

#### F57 — Double comptage des lignes d'estimation : toutes les étapes sont additionnées et les lignes sont dupliquées
*Bug · Finance / TJM / facturation* — [project/services/budget.py:262](project/services/budget.py:262)

- **Preuve** : summarize_estimate_lines additionne cost_amount de toutes les lignes, quel que soit budget_stage (l.262-263). regenerate_budget_from_estimates fait de même (l.630-666) pour calculer estimated_labor_cost. Or : (a) l'import IA crée une ligne ESTIMATED par tâche plus une ligne BASELINE agrégée « Feature » du même coût (project_ai_import_service.py l.259-287) ; (b) RefreshProjectFinancialsView (views_budget.py l.566-575) ajoute des lignes RAF pour les mêmes tâches ; (c) GenerateEstimateLinesFromTasksView passe replace=False par défaut (l.531), ce qui duplique les lignes à chaque clic. Le calcul raf_cost (l.292-301) réapplique le ratio de reste aux lignes RAF, qui valent déjà le reste. Enfin, replace_existing supprime toutes les lignes source_type=TASK, RAF comprises (l.466-469).
- **Impact** : Le coût estimé, le budget main-d'œuvre, le RAF, forecast_final_cost, l'EAC et les alertes sont gonflés, typiquement ×2 après un import IA.
- **Correctif** : Agréger par étape : ESTIMATED pour l'estimatif, BASELINE à part, RAF uniquement pour raf_cost. Dédoublonner par tâche (update_or_create sur task + stage). Ne supprimer que l'étape régénérée.
- **Relecture** : summarize_estimate_lines somme toutes les lignes quel que soit budget_stage (budget.py:262-263), comme regenerate_budget_from_estimates (630-666). Or l'import IA crée une ligne ESTIMATED par tâche plus une ligne BASELINE agrégée de même coût (project_ai_import_service.py:259-287), RefreshProjectFinancialsView ajoute des lignes RAF (views_budget.py:571-575), et replace=False est la valeur par défaut (l.531). Le ratio RAF est réappliqué aux lignes RAF (budget.py:292-301).

#### F58 — Le rafraîchissement automatique à chaque sauvegarde de tâche écrase le budget saisi, même approuvé ou clos
*Intégrité des données · Finance / TJM / facturation · doublon de F38* — [project/services/budget.py:668](project/services/budget.py:668)

- **Preuve** : Le signal post_save Task (signals.py l.363-394) déclenche refresh_project_budget_task (tasks.py l.273-292), puis refresh_project_financials et regenerate_budget_from_estimates. Cette dernière réécrit sans condition estimated_labor_cost, estimated_software_cost, estimated_infra_cost, estimated_subcontract_cost et estimated_other_cost depuis les lignes (l.668-677), quel que soit budget.status (APPROVED, CLOSED…).
- **Impact** : Chaque modification de tâche efface les montants logiciel, infra ou sous-traitance saisis dans ProjectBudgetForm quand ils ne viennent pas de lignes d'estimation. Un budget approuvé ou clos change donc après coup.
- **Correctif** : Ne pas toucher au budget si status n'est ni DRAFT ni ESTIMATED. Ne recalculer que estimated_labor_cost, ou modéliser les montants manuels comme des lignes MANUAL. Debouncer le recalcul.
- **Relecture** : Chaîne vérifiée : signals.py:363-394, puis refresh_project_budget_task (tasks.py:273-292), refresh_project_financials (budget.py:811-821) et regenerate_budget_from_estimates. Ce dernier réécrit estimated_* (l.668-677) sans tester budget.status.

#### F59 — Coût réel, EAC, alertes et marge réelle ignorent le temps consommé × TJM ; deux moteurs de KPI divergent
*Bug · Finance / TJM / facturation* — [project/services/budget.py:711](project/services/budget.py:711)

- **Preuve** : actual_cost = dépenses PAID + VALIDATED (l.711) et forecast_final_cost = actual + committed + raf (l.716). Le coût des timesheets n'entre que dans labor_cost (l.725-727). Par conséquent real_margin (l.795), forecast_consumption_percent (utilisé par BudgetAlertService, budget_snapshots.py l.235) et l'EAC (ProjectEACService, l.317) ignorent les jours déjà consommés. À l'inverse, direct_cost et other_cost (l.362-381) incluent les dépenses DRAFT, ESTIMATED et FORECAST dans le net_profit « réel ». ProjectDetailView recalcule ses propres KPI avec d'autres formules : planned = expected_revenue_amount (views.py l.3163), gross_margin sur le reçu au lieu du facturé (l.3179), net_profit sans other_cost (l.3181), main-d'œuvre via is_labor_cost.
- **Impact** : Les dépassements des projets en régie/TJM ne sont pas détectés, l'EAC est sous-estimé, la marge réelle surestimée, et la page projet affiche d'autres chiffres que les pages budget et portfolio.
- **Correctif** : Définir actual_cost = dépenses décaissées + coût des timesheets approuvés, sans les dépenses LABOR déjà issues des temps. Exclure DRAFT, ESTIMATED et FORECAST des coûts réels. Supprimer le calcul dupliqué de ProjectDetailView et utiliser build_budget_overview.
- **Relecture** : budget.py:711-716 : actual_cost = paid + validated et forecast = actual + committed + raf, sans logged_cost (qui ne sert qu'à labor l.725). real_margin (l.795), forecast_consumption_percent (l.750) et l'EAC (budget_snapshots.py:317) l'ignorent donc. summarize_expenses (l.362-381) inclut tout ce qui n'est pas REJECTED. ProjectDetailView (views.py:3162-3181) utilise d'autres formules : planned = expected_revenue_amount, gross sur le reçu, net = operating.

#### F60 — Prévision budgétaire IA : la main-d'œuvre future est comptée deux fois (RAF + projection membres)
*Bug · Finance / TJM / facturation · vu aussi par : IA / méthodologies* — [project/services/ai/services/budget_forecast.py:98](project/services/ai/services/budget_forecast.py:98)

- **Preuve** : base_cost = actual_cost + committed_cost + raf_cost + members_cost (l.98-103). raf_cost correspond aux heures restantes × TJM des tâches assignées. members_cost correspond aux jours ouvrés d'aujourd'hui à l'horizon × allocation × TJM des mêmes membres (l.86-95). Le même travail futur est donc compté deux fois, et optimistic/pessimistic (×0,92/×1,18) en héritent.
- **Impact** : Coût attendu et risque de dépassement surestimés, marge sous-estimée : le cockpit IA envoie de fausses alertes.
- **Correctif** : Ne projeter la capacité des membres que pour la part non couverte par des tâches estimées (par exemple max(RAF, capacité) par membre), ou choisir une seule des deux sources.
- **Relecture** : base_cost additionne raf_cost (reste des lignes d'estimation des tâches) et members_cost (jours ouvrés jusqu'à l'horizon × allocation × TJM des membres), voir budget_forecast.py:86-103. Le même travail futur est compté deux fois, et les scénarios ×0,92 et ×1,18 en héritent.

#### F61 — Génération de facture : les modes Forfait et Jalons produisent des factures vides
*Bug · Finance / TJM / facturation* — [project/services/invoicing.py:278](project/services/invoicing.py:278)

- **Preuve** : MILESTONE lit `ms.payment_amount` ou `ms.amount` (l.278-283), mais Milestone (models.py l.2066-2088) n'a aucun de ces champs : montant 0 et ligne ignorée. FIXED filtre budget_stage=BASELINE par défaut (l.87, l.349-354), alors que regenerate_estimate_lines_from_tasks crée des lignes ESTIMATED et que le formulaire de ligne n'expose pas budget_stage (défaut ESTIMATED). InvoiceGenerateFromProjectView (views.py l.9080) crée quand même la facture DRAFT vide avant d'afficher l'avertissement.
- **Impact** : Deux des trois modes de facturation automatique ne fonctionnent pas, et chaque essai laisse un brouillon vide.
- **Correctif** : Ajouter un champ montant/pourcentage de facturation à Milestone (ou lier les jalons à ProjectRevenue de type MILESTONE). Pour FIXED, utiliser ESTIMATED (ou BASELINE puis ESTIMATED en repli) et proposer l'étape dans le formulaire. Ne créer la facture que s'il y a des lignes.
- **Relecture** : Milestone (models.py:2066-2100) n'a ni payment_amount ni amount, donc chaque jalon est ignoré (invoicing.py:278-283). FIXED filtre sur BASELINE (87, 349-354), alors que l'UI ne crée que des lignes ESTIMATED ou RAF (budget.py:522, 602) : BASELINE n'est réglable que par l'API. La vue (views.py:9080+) crée la facture DRAFT vide puis affiche un warning.

#### F62 — Facturation régie : aucun suivi des heures déjà facturées, d'où une double facturation possible
*Intégrité des données · Finance / TJM / facturation* — [project/services/invoicing.py:151](project/services/invoicing.py:151)

- **Preuve** : from_timesheets sélectionne toutes les TimesheetEntry approuvées et facturables du projet sur la période (l.151-164), sans exclure celles déjà facturées. TimesheetEntry (models.py l.1843-1870) n'a aucun lien vers une facture, et InvoiceLine n'a qu'un FK `user`. Sans période, tout l'historique est facturé. En plus, le prix horaire est arrondi avant la multiplication (l.199-208), ce qui crée des écarts d'arrondi.
- **Impact** : Relancer la génération, ou utiliser des périodes qui se chevauchent, refacture les mêmes heures au client.
- **Correctif** : Ajouter TimesheetEntry.invoice_line (FK) ou une table de liaison, exclure les entrées déjà facturées (hors factures CANCELLED), et les verrouiller après émission. Calculer le montant en jours × TJM puis arrondir.
- **Relecture** : invoicing.py:151-164 : sélectionne toutes les entrées APPROVED et facturables du projet, sans exclusion des entrées déjà facturées. TimesheetEntry (models.py:1843+) n'a aucun lien vers une facture, et InvoiceLine n'a que estimate_line, milestone et user. unit_price est quantifié avant la multiplication (l.199-208).

#### F63 — Revenus facturés et encaissés jamais alimentés : module facturation déconnecté du budget
*Fonctionnalité manquante · Finance / TJM / facturation* — [project/forms_budget.py:183](project/forms_budget.py:183)

- **Preuve** : ProjectRevenueForm (l.183-204) n'expose ni status, ni invoiced_amount, ni received_amount, ni is_received : le widget is_received est déclaré mais le champ est absent, donc {{ form.is_received }} s'affiche vide dans templates/project/revenue/form.html l.97. Il n'existe pas de vue de modification d'un revenu. Aucun code ne met à jour ProjectRevenue depuis Invoice ou InvoicePayment (invoiced_amount n'apparaît que dans des agrégations). summarize_revenues (budget.py l.407-413) n'exclut pas les revenus CANCELLED.
- **Impact** : invoiced_revenue et received_revenue restent à 0 dans l'interface : gross_margin, net_profit, real_margin, profit_margin_percent et le taux d'encaissement sont faux.
- **Correctif** : Calculer le facturé et l'encaissé du projet à partir des Invoice (ISSUED et au-delà, hors CANCELLED) et des InvoicePayment CONFIRMED, ou synchroniser ProjectRevenue par signal. Exclure CANCELLED. Ajouter l'édition des revenus.
- **Relecture** : ProjectRevenueForm (forms_budget.py:183-204) n'inclut ni status, ni invoiced_amount, ni received_amount, ni is_received, alors que le template affiche {{ form.is_received }} (revenue/form.html:97). Il n'existe qu'une vue Create (views_budget.py:199), et aucun code ne relie Invoice ou InvoicePayment à ProjectRevenue (rien dans budget.py). summarize_revenues (407-413) n'exclut pas CANCELLED. Seuls l'API et l'admin permettent de saisir ces montants à la main.

#### F64 — Les boutons « Créer / éditer budget » et « Réviser budget » plantent (500) dès qu'un budget existe
*Bug · Finance / TJM / facturation* — [project/views_budget.py:161](project/views_budget.py:161)

- **Preuve** : Les liens de _budget_estimatif.html l.10, _budget_previsionnel.html l.14, lastdetails.html l.673/818 et des quick actions (views.py l.3265, 3270) pointent toujours vers /project-budgets/create/?project=<pk>. ProjectBudgetCreateView.form_valid enregistre un nouveau ProjectBudget alors que project est un OneToOneField (models.py l.852). `project` est hors du formulaire, donc l'unicité n'est pas validée et on obtient une IntegrityError. Sans ?project, les vues de création budget, ligne d'estimation, revenu et dépense (l.161-166, 190-196, 209-214, 512-518) enregistrent project_id NULL, d'où une IntegrityError.
- **Impact** : Crash du parcours principal de révision du budget, et des créations financières lancées sans paramètre.
- **Correctif** : Rediriger vers project_budget_update si un budget existe (get_or_create puis update). Exiger et valider ?project (scopé au workspace) dans dispatch, avec un 404 sinon.
- **Relecture** : ProjectBudget.project est un OneToOneField (models.py:852) hors du formulaire, donc validate_unique l'ignore. Les liens /project-budgets/create/?project= sont inconditionnels (_budget_estimatif.html:10, _budget_previsionnel.html:14, views.py:3265/3270). Comme regenerate_budget_from_estimates crée souvent le budget via get_or_create, on obtient une IntegrityError. Sans ?project, project_id est NULL.

#### F65 — Contrôle d'accès financier HTML défaillant : objets non vérifiés, permissions Django globales, IA, factures sans RBAC
*Sécurité · Finance / TJM / facturation* — [project/views_budget.py:121](project/views_budget.py:121)

- **Preuve** : ensure_financial_permission (l.121-131) s'exécute au dispatch, quand self.object vaut None, et ne lit que ?project ou project_id. Pour ProjectBudgetDetailView/UpdateView, ProjectExpenseDetailView/UpdateView et ProjectExpenseListView sans ?project, aucun contrôle n'a donc lieu. can_view_financials (l.61-78) accepte des permissions Django globales (has_perm sans workspace) et des rôles legacy (TECH_LEAD). Les vues qui modifient des données (GenerateEstimates l.523, Recalculate l.543, Refresh l.561, Approve/Reject l.259, 278, 300) résolvent les objets par `get_object_or_404(..., pk=...)` non scopé (AGENTS.md §2) : un détenteur d'une permission globale agit donc sur les autres tenants. Le PROJECT_MANAGER, censé être en lecture seule (rbac.py l.83), peut tout modifier. Les vues IA financières ne vérifient qu'une TeamMembership active (views_financial_ai.py l.80-90). Les vues facture (HTML et AJAX) n'appliquent aucune RBAC invoice.*, et rbac_delete_action n'est jamais renseigné : tout membre peut supprimer une facture émise, avec ses paiements (CASCADE).
- **Impact** : Membres et clients accèdent aux budgets, dépenses, marges du portfolio et factures, et peuvent les modifier ou supprimer. Un utilisateur doté d'une permission globale agit sur les autres tenants.
- **Correctif** : Contrôler l'accès dans get_object ou get_context_data à partir de l'objet. Scoper tous les get_object_or_404 avec get_user_workspace_ids. Distinguer budget.view de budget.edit, et invoice.view d'invoice.edit. Utiliser RBACService dans les vues IA et facture. Définir rbac_delete_action='invoice.delete'.
- **Relecture** : views_budget.py:121-135 : au dispatch, self.object vaut None et get_project_from_request ne lit que ?project ou kwargs project_id, donc aucun contrôle pour Detail, Update et List sans paramètre. Les vues d'écriture (523, 543, 561) ne vérifient que can_view_financials (budget.view, que PROJECT_MANAGER possède, rbac.py:83). Les has_perm globaux sont acceptés (l.65, 86, 108). rbac_delete_action n'est défini par aucune sous-classe, et InvoicePayment.invoice est en CASCADE (models.py:4741).

#### F73 — Déclenchement et statut des propositions IA non scopés par workspace (cross-tenant)
*Sécurité · IA / méthodologies (initialement critical)* — [project/views_ai_proposal.py:456](project/views_ai_proposal.py:456)

- **Preuve** : ProjectAIProposalTriggerView.post : `project = get_object_or_404(dm.Project, pk=project_pk)` sans `workspace_id__in=get_user_workspace_ids(...)`, puis `ProjectAIProposal.objects.create(project=project, workspace=project.workspace, ...)` (AJAX) ou `generate_for_project(...)` synchrone (POST classique). Même chose dans ProjectAIProposalStatusView.get (l.542) qui renvoie proposal_id, status, used_provider et tokens_used du dernier run de n'importe quel projet.
- **Impact** : Un utilisateur du tenant A peut créer des propositions IA dans le workspace du tenant B et lancer une génération payante sur son projet. Le prompt contient les emails, le budget et les objectifs du tenant B. L'utilisateur peut aussi énumérer les projets et la consommation IA des autres tenants. Cela viole la convention n°2 d'AGENTS.md.
- **Correctif** : Résoudre le projet avec `get_object_or_404(dm.Project, pk=project_pk, workspace_id__in=get_user_workspace_ids(request.user))` dans les deux vues, puis ajouter un test cross-tenant (404 attendu) dans tests_security.py.
- **Relecture** : views_ai_proposal.py:456 et 542 : `get_object_or_404(dm.Project, pk=project_pk)` sans scope, ce qui permet de créer une ProjectAIProposal dans le workspace d'un autre tenant et de consommer son IA, ou de lire le statut, le provider et les tokens. Je descends la sévérité à high : le contenu de la proposition reste protégé, car ai_proposal_detail passe par AIProposalAccessMixin (l.45-82), scopé par workspace.

#### F75 — Workspace Scrum en 500 systématique et outil copilote generate_user_stories cassé : BacklogItem n'a pas de champ status
*Bug · IA / méthodologies (initialement critical)* — [project/views_methodology.py:98](project/views_methodology.py:98)

- **Preuve** : `project.backlog_items.exclude(status__in=["DONE","CLOSED","CANCELLED"])`. Vérifié via l'ORM : `FieldError: Cannot resolve keyword 'status' into field`, levée dès l'appel à exclude(). Dans tool_registry.py:255-263, `dm.BacklogItem.objects.create(..., status="BACKLOG")` lève `TypeError: BacklogItem() got unexpected keyword arguments: 'status'`, avalé par le try/except de chaque story. Le KPI story_completion (kpis.py) filtre aussi sur status et renvoie toujours _empty().
- **Impact** : La page /projects/<pk>/scrum/ plante (500) pour tous les projets. Le copilote annonce « 0 user stories créées » après avoir consommé un appel IA.
- **Correctif** : Retirer le filtre status (ou ajouter un vrai champ status avec migration) et filtrer par `is_archived=False`. Dans generate_user_stories, supprimer `status=` et renseigner `acceptance_criteria` et `reporter=user`.
- **Relecture** : BacklogItem (models.py:1288-1322) n'a pas de champ status. exclude(status__in=…) à views_methodology.py:98 lève donc une FieldError dès la construction de la requête. tool_registry.py:262 passe status="BACKLOG" à create() (TypeError avalée par le try), et kpis.py:143 filtre sur status (except → _empty()). Sévérité abaissée : une page secondaire en 500, sans perte de données.

#### F79 — XSS stockée dans le panneau DevFlow AI (x-html brut avant DOMPurify)
*Sécurité · IA / méthodologies* — [templates/layout/_ai_panel.html:72](templates/layout/_ai_panel.html:72)

- **Preuve** : `<div class="ai-bubble" x-html="msg.html" x-init="$nextTick(() => devflowAIRender($el))">` insère le HTML brut. DOMPurify n'est appliqué qu'au tick suivant (l.359-374), voire 200 ms plus tard si marked n'est pas chargé. Le serveur interpole des noms non échappés : chat.py:632 `<strong>{sprint['name']}</strong>` (message d'accueil chargé sur toutes les pages via base.html:2218), l.651 et l.961 `<strong>{project['name']}</strong>`. Les réponses LLM sont aussi injectées telles quelles (l.670).
- **Impact** : Un membre qui nomme un sprint ou un projet `<img src=x onerror=...>` exécute du JavaScript chez tous les membres du workspace à l'ouverture du panneau IA (vol de session, actions CSRF). Une réponse LLM manipulée par injection peut faire de même.
- **Correctif** : Échapper côté serveur (django.utils.html.escape/format_html) tous les noms interpolés. Côté front, ne jamais utiliser x-html sur du contenu brut : calculer `DOMPurify.sanitize(marked.parse(...))` avant de pousser `msg.html`, ou utiliser x-text puis rendre le HTML assaini.
- **Relecture** : x-html="msg.html" (_ai_panel.html:72) affecte innerHTML avant que devflowAIRender ne passe DOMPurify au tick suivant (359-374), si bien qu'un `<img onerror>` s'exécute. fetchWelcome est appelé dans init(), sur toutes les pages via base.html. chat.py:632/651/961 interpole sprint/project['name'] sans échappement (models.name, l.177/213), et les réponses LLM sont poussées brutes (_pushBot, l.670).

#### F82 — Aucun timeout sur les clients LLM, et appels IA longs synchrones dans la requête HTTP (dans transaction.atomic)
*Performance · IA / méthodologies* — [project/services/ai/deepseek_provider.py:59](project/services/ai/deepseek_provider.py:59)

- **Preuve** : `OpenAI(api_key=..., base_url=...)` est créé sans `timeout` ni `max_retries`, de même dans openai_provider.py:39, local_provider.py:44 et anthropic_provider.py:55. Valeurs par défaut du SDK installé (openai 2.32.0) : read 600 s, 2 retries. Gunicorn tourne avec `--timeout 900` et 3 workers (docker-compose.yml:11-12). Appels synchrones : Genesis (views_ai_genesis.py:127, 215), Regenerate (views_ai_proposal.py:394), Trigger non-AJAX (l.510), `ai/generate-roadmap` et `ai/report/generate` (viewsets.py), meeting full_process (views_meeting.py:370). `generate_for_project` est décoré @transaction.atomic (project_structure.py:201) et englobe l'appel LLM.
- **Impact** : Un DeepSeek lent ou bloqué occupe un worker jusqu'à 30 min : le worker est tué avant que la chaîne de fallback n'atteigne le provider suivant, et 3 requêtes IA lentes saturent le site. La transaction DB et la connexion restent ouvertes pendant tout l'appel LLM.
- **Correctif** : Passer `timeout=httpx.Timeout(connect=5, read=settings.AI_TIMEOUT_S≈45)` et `max_retries=1` à chaque client. Déplacer Genesis, Regenerate et le rapport vers Celery (comme le Trigger AJAX) avec polling de statut. Sortir l'appel LLM du bloc atomic : générer d'abord, puis persister dans une transaction courte.
- **Relecture** : OpenAI(api_key, base_url) est instancié sans timeout ni max_retries (deepseek_provider.py:59, openai_provider.py:39, local_provider.py:44, anthropic_provider.py:55), et aucun `timeout` n'apparaît dans services/ai hors chat.py:319. Le SDK openai 2.32.0 est installé, et generate_for_project est sous @transaction.atomic (project_structure.py:201).

#### F83 — Quota IA et throttle contournables : la majorité des appels payants ne passent pas par AIQuotaService
*Sécurité · IA / méthodologies · vu aussi par : IA / méthodologies* — [project/views_ai_chat.py:74](project/views_ai_chat.py:74)

- **Preuve** : AIQuotaService.can_consume et record_usage ne sont appelés que dans project_intelligence, project_report et AIChatStreamView (grep). Ni le chat (AIChatSendView, process_user_message), ni le copilote (copilot.py:111), ni Genesis, Regenerate, Trigger et la tâche Celery (generate_for_project, prompt de 25 à 80 tâches sans quota), ni forecast, risk, allocation, effort et meeting ne vérifient ou ne comptent le quota. models.py:5962 annonce `AIQuotaService.check_and_consume`, qui n'existe pas. AIActionRateThrottle ne protège que les actions DRF : aucune limite sur /ai/chat/, /ai/genesis/, /projects/<pk>/copilot/chat/ ni /financial-ai/*.
- **Impact** : N'importe quel membre peut générer des coûts LLM illimités (boucle sur /ai/chat/ ou /ai/genesis/api/). Le quota mensuel affiché ne reflète qu'une fraction de la consommation réelle.
- **Correctif** : Centraliser le contrôle dans un décorateur ou wrapper de provider (ex. `QuotaAwareProvider(workspace)`) qui appelle can_consume avant et record_usage après chaque generate. Appliquer un rate-limit (django-ratelimit ou cache) sur les vues Django IA, piloté par DEVFLOW_AI_RATE_LIMIT.
- **Relecture** : Le grep montre can_consume/record_usage uniquement dans project_intelligence.py, project_report.py et api/views_quick.py (stream). Rien dans views_ai_chat, copilot, genesis, forecast, risk, allocation, effort ou meeting. models.py:5962 cite check_and_consume, qui n'existe pas. Aucun throttle sur les vues HTML IA.

#### F84 — Codes de statut des méthodologies incompatibles avec Task.Status : Kanban vide en « À faire », workflow engine contourné
*Bug · IA / méthodologies* — [project/views_methodology.py:147](project/views_methodology.py:147)

- **Preuve** : Seeds (0045_seed_methodologies.py) : scrum et kanban utilisent `backlog` et `to_do`, waterfall `not_started`, `approved`, `delayed`, `closed`. Task.Status contient TODO, IN_PROGRESS, REVIEW, DONE, BLOCKED, CANCELLED, EXPIRED. La vue Kanban fait `status_code = status.code.upper()` puis `project.tasks.filter(status=status_code)` : « TO_DO » et « BACKLOG » ne matchent jamais. `_get_current_status_obj` (workflow_engine.py) cherche `code="todo"`, introuvable, d'où « Statut courant introuvable ». Une transition vers `approved` écrit « APPROVED », refusé par Task.full_clean.
- **Impact** : Le board Kanban méthodologie n'affiche jamais les tâches TODO. Les règles de transition et de rôles ne s'appliquent pas aux tâches TODO (task_status_update retombe en silence sur le mode legacy). Le workflow Waterfall est inutilisable sur les tâches.
- **Correctif** : Ajouter un mapping explicite MethodologyStatus.code vers Task.Status (champ `task_status` sur MethodologyStatus ou dict de correspondance), et l'utiliser dans les vues Kanban et le WorkflowEngine (lecture et écriture). Corriger les seeds par migration de données.
- **Relecture** : 0045_seed_methodologies.py:37-44/121-128/194-201 : les codes seedés sont backlog, to_do, not_started, approved, delayed et closed, alors que Task.Status (models.py:1330-1336) vaut TODO, IN_PROGRESS, etc. views_methodology.py:147-148 filtre status=code.upper(), si bien que TO_DO et BACKLOG sont toujours vides. _get_current_status_obj (workflow_engine.py:135-147) cherche « todo », introuvable : task_status_update (views.py:4057-4076) bascule alors silencieusement sur le changement legacy, sans workflow.

#### F99 — Notifications CRUD : destinataire choisi parmi tous les utilisateurs, édition/suppression des notifications des autres
*Sécurité · Réunions / chat / Celery* — [project/forms.py:1436](project/forms.py:1436)

- **Preuve** : NotificationForm (forms.py l.1436-1449) expose `recipient` avec le queryset par défaut User.objects.all(), et `url` en saisie libre. NotificationCreateView (views.py l.5825) ne restreint pas ce champ. NotificationUpdateView/DeleteView (l.5833/5841) ne filtrent pas `recipient=request.user`, contrairement à DetailView (l.5822). Le context processor (context_processors.py l.11-20) affiche les notifications du destinataire sans filtre de workspace.
- **Impact** : Énumération de tous les utilisateurs de la plateforme (noms et emails dans le select). Injection d'une notification, avec un lien de phishing, dans la cloche d'un utilisateur d'un autre tenant. Tout membre peut modifier ou supprimer les notifications d'un collègue.
- **Correctif** : Retirer la création manuelle de notifications de l'UI, ou restreindre `recipient` à `users_in_workspaces([ws])` et valider `url` (chemin relatif uniquement). Ajouter `.filter(recipient=self.request.user)` dans get_queryset des vues Update et Delete.
- **Relecture** : NotificationForm expose recipient (User.objects.all() par défaut) et url (forms.py:1436-1449). NotificationCreateView, UpdateView et DeleteView (views.py:5825-5845) ne filtrent pas recipient=request.user, contrairement à DetailView (5822). Le context processor affiche ensuite ces notifications au destinataire (context_processors.py:11-20).

#### F100 — Fichiers audio et extraits de voix servis publiquement via /media/ quand le bucket S3 n'est pas configuré
*Sécurité · Réunions / chat / Celery* — [project/models.py:3514](project/models.py:3514)

- **Preuve** : _recording_storage (models.py l.3514-3525) retombe sur default_storage (FileSystemStorage MEDIA_ROOT) si `storages['recordings']` n'existe pas, ce qui est le cas quand RECORDING_S3_BUCKET est vide (absent du .env versionné, base.py l.443). Les chemins sont prédictibles : `devflow/recordings/<ws>/<meeting>/recording.webm` (nom par défaut du widget) et `.../samples/SPEAKER_A/SPEAKER_A.mp3` (l.3533, 3542). Le conteneur devflowmedia (docker-compose) sert /media/ sans authentification (deploy/nginx/media.conf l.4-9, Cache-Control public).
- **Impact** : Les enregistrements complets de réunions de tous les tenants deviennent téléchargeables sans authentification en itérant les IDs. Cela contourne le contrôle HMAC/session de stream_recording_audio. Les MeetingAttachment (devflow/meetings/) sont aussi exposés.
- **Correctif** : Refuser l'upload (ou utiliser un FileSystemStorage dédié hors MEDIA_ROOT) quand le storage 'recordings' n'est pas configuré. Exclure `devflow/recordings/` et `devflow/meetings/` de nginx (`location ^~ /media/devflow/ { internal; }`) et servir via X-Accel-Redirect après contrôle d'accès. Ajouter un suffixe aléatoire au nom des fichiers.
- **Relecture** : _recording_storage (models.py:3514-3525) retombe sur default_storage si storages['recordings'] est absent, ce qui arrive quand RECORDING_S3_BUCKET ou S3_ENDPOINT sont vides (base.py:389-409). Le .env utilisé par docker-compose (env_file) ne contient aucune clé S3. Les chemins sont prédictibles (l.3527-3542) et media.conf sert /media/ en public.

#### F101 — Ajout manuel d'une action de réunion toujours refusé (« Action invalide »)
*Bug · Réunions / chat / Celery* — [project/forms_meeting.py:357](project/forms_meeting.py:357)

- **Preuve** : MeetingActionItemForm.Meta.fields inclut 'status' (l.357), champ CharField(choices, default=OPEN) sans blank=True, donc required=True. Le __init__ ne rend facultatifs que description/owner/due_date (l.369-371). Le formulaire de templates/project/meeting/detail.html (l.353-366) n'envoie que title, priority et due_date. Vérifié : `MeetingActionItemForm({'title':'x','priority':'HIGH','due_date':''}).is_valid()` → False, erreur {'status': ['This field is required.']}. La vue (views_meeting.py l.293-295) affiche alors « Action invalide. ».
- **Impact** : La fonction « Ajouter une action » de la fiche réunion ne crée jamais d'action. C'est un flux principal du compte-rendu.
- **Correctif** : Retirer 'status' des fields du formulaire de création (ou `self.fields['status'].required = False` avec initial OPEN). Ajouter un champ owner limité aux participants dans le template. Ajouter un test positif de création.
- **Relecture** : forms_meeting.py:357 inclut status, un CharField avec default mais sans blank, donc required. __init__ (369-371) ne relâche que description, owner et due_date. Le formulaire de meeting/detail.html:353-366 n'envoie que title, priority et due_date : is_valid() échoue toujours, et la vue (views_meeting.py:292-294) affiche « Action invalide. ».

#### F102 — Conversion d'une suggestion IA en tâche toujours en échec (kwarg created_by inexistant)
*Bug · Réunions / chat / Celery* — [project/views_meeting.py:914](project/views_meeting.py:914)

- **Preuve** : RecordingConvertSuggestionView construit task_kwargs avec "created_by": request.user (l.914). Task n'a pas de champ created_by (models.py l.1328-1394, seulement reporter). Vérifié : `Task(created_by=None)` lève TypeError « unexpected keyword arguments: 'created_by' ». Le fallback (l.923-925) ne retire que 'assignee' et relève la même erreur, avalée par `except Exception` (l.941-942).
- **Impact** : Aucune TASK_SUGGESTION issue d'un enregistrement ne peut être convertie en tâche. L'échec est silencieux : created_tasks=0, aucun message, extraction non acceptée.
- **Correctif** : Remplacer created_by par `reporter=request.user`, supprimer le fallback aveugle et remonter l'erreur à l'utilisateur via messages.error.
- **Relecture** : task_kwargs contient "created_by": request.user (views_meeting.py:914), alors que Task n'a ni champ ni propriété created_by (seulement reporter ; TimeStampedModel n'a que created_at/updated_at). Le fallback (923-925) ne retire que 'assignee' et relève la même TypeError, avalée par l'except de 941-942.

#### F104 — Pipeline d'enregistrement soumis à la limite Celery globale de 300 s, avec décodage audio complet répété pour chaque speaker
*Performance · Réunions / chat / Celery* — [project/tasks.py:850](project/tasks.py:850)

- **Preuve** : process_recording_task (l.850-866) ne surcharge pas soft_time_limit/time_limit, donc ce sont CELERY_TASK_SOFT_TIME_LIMIT=300 et CELERY_TASK_TIME_LIMIT=360 qui s'appliquent (settings/base.py l.293-294). transcribe() est bloquant : upload puis polling AssemblyAI (transcription.py l.78). extract_speaker_samples re-télécharge le fichier (diarization.py l.79), puis appelle extract_sample pour chaque speaker (l.97), qui fait `AudioSegment.from_file(audio_path)` sur le fichier entier (audio_processing.py l.77), soit environ 700 Mo de PCM par décodage pour 1 h stéréo.
- **Impact** : Les réunions longues (plus d'environ 1 h, 100 à 500 Mo) dépassent 300 s : SoftTimeLimitExceeded est capturé et l'enregistrement passe en FAILED. Il n'existe pas d'action pour relancer la transcription. Risque d'OOM avec concurrency=4.
- **Correctif** : Déclarer `soft_time_limit=3600, time_limit=3900` sur process_recording_task. Décoder l'audio une seule fois (charger l'AudioSegment hors de la boucle, ou utiliser ffmpeg -ss/-t par extrait). Envisager le webhook AssemblyAI ou `submit()` suivi d'une tâche de polling.
- **Relecture** : tasks.py:850-866 : aucun time_limit propre, donc les limites globales de 300 et 360 s s'appliquent (base.py:293-294), et le worker docker-compose ne les surcharge pas. transcribe() est bloquant (transcription.py:78). extract_speaker_samples télécharge le fichier puis extract_sample fait AudioSegment.from_file sur le fichier entier pour chaque speaker (audio_processing.py:77). SoftTimeLimitExceeded est attrapé par `except Exception`, puis la tâche est relancée.

#### F123 — La page Scrum plante toujours : filtre de template `split` inexistant
*Bug · Templates / routage / vues (initialement critical)* — [templates/project/methodology/scrum_workspace.html:79](templates/project/methodology/scrum_workspace.html:79)

- **Preuve** : `{% for status_label in 'TODO IN_PROGRESS REVIEW DONE'|split:' ' %}`. Le template ne charge que `humanize`, et aucun filtre `split` n'existe : devflow_extras.py définit seulement attr, has_perm, get_item, short_amount, safe_html, full_amount et user_can. Django compile tout le template au chargement, donc TemplateSyntaxError « Invalid filter: 'split' » même hors du bloc {% if sprint_items %}. Vue concernée : ProjectScrumWorkspaceView (views_methodology.py:79), liée depuis _methodology_toolbar.html:25 et methodology/dashboard.html:32.
- **Impact** : /projects/<pk>/scrum/ renvoie une erreur 500 pour tous les projets : l'espace Scrum (backlog, sprint actif, burndown) est inaccessible.
- **Correctif** : Construire la liste des statuts côté vue (ex. `ctx['scrum_columns'] = ['TODO','IN_PROGRESS','REVIEW','DONE']`) et itérer dessus, ou ajouter un filtre `split` dans devflow_extras et faire `{% load devflow_extras %}`. Ajouter un test GET de la vue.
- **Relecture** : scrum_workspace.html:79 utilise |split, mais le template ne charge que humanize. Le seul module de tags (project/templatetags/devflow_extras.py) n'a pas de filtre split, et TEMPLATES n'a pas de builtins. TemplateSyntaxError à la compilation. Sévérité high : même page Scrum que F75, pas le flux principal.

#### F124 — 57 vues Create/Update génériques affichent le formulaire Projet : les formulaires sont inutilisables
*Bug · Templates / routage / vues* — [project/views.py:340](project/views.py:340)

- **Preuve** : DevflowCreateView.template_name = "project/create.html" et DevflowUpdateView.template_name = "project/update.html" (440). Ces deux templates sont spécifiques au Projet : ils rendent form.name, form.code, form.category, form.teams, form.workspace et form.tech_stack, sans aucune boucle `for field in form`. 57 sous-classes n'ont pas de template_name, entre autres BacklogItem (4335/4343), SprintReview et SprintRetrospective (8284-8330), TaskComment, TaskAttachment, TaskDependency, TaskChecklist, ChecklistItem, BoardColumn (7820), Label, TimesheetEntry (6172), Webhook, APIKey, WorkspaceSettings et ObjectiveUpdateView (8449). Par exemple, BacklogItemForm (title, project, sprint, item_type, story_points…) n'a presque aucun champ rendu.
- **Impact** : Créer un item de backlog, une review ou rétrospective de sprint, une colonne de board ou une checklist, ou modifier un objectif, est impossible : les champs requis comme `title` ne sont pas affichés, le formulaire est rejeté et l'erreur n'est pas montrée. Les libellés « Nom du projet » et « Stack technique » s'affichent à tort.
- **Correctif** : Définir dans DevflowCreateView et DevflowUpdateView un template générique (project/_generic_form.html avec `{% for field in form %}`), et réserver project/create.html et project/update.html à ProjectCreateView et ProjectUpdateView.
- **Relecture** : Analyse AST de views.py : 57 sous-classes de DevflowCreateView/DevflowUpdateView sans template_name, donc rendues avec project/create.html ou update.html. Ces templates n'affichent que les champs du Projet (form.name, code, category, teams, tech_stack…) et ne contiennent aucune boucle `for field in form`.

#### F125 — Namespace `project:` inexistant : 500 après modification ou suppression de jalons et de roadmaps
*Bug · Templates / routage / vues* — [project/views.py:7087](project/views.py:7087)

- **Preuve** : `success_list_url_name = "project:milestone_list"` sur MilestoneUpdateView (7087), MilestoneDeleteView (7102) et MilestoneArchiveView (7107). On trouve aussi "project:milestone_task_list" (7227, MilestoneTaskDeleteView), "project:roadmap_list" (7662, RoadmapUpdateView) et "project:roadmap_item_list" (7787, RoadmapItemUpdateView). `app_name = "project"` dans le ROOT_URLCONF (urls.py:91) est ignoré par Django et aucun include ne déclare ce namespace : reverse_lazy lève NoReverseMatch au moment de HttpResponseRedirect, après save(), delete() ou archive(). ATOMIC_REQUESTS n'est pas activé.
- **Impact** : L'édition d'un jalon, d'une roadmap ou d'un élément de roadmap, ainsi que la suppression ou l'archivage d'un jalon, se terminent en erreur 500 alors que l'écriture a eu lieu. L'utilisateur, désorienté, recommence l'opération.
- **Correctif** : Remplacer par les noms sans namespace ("milestone_list", "milestone_task_list", "roadmap_list", "roadmap_item_list") et ajouter un test de redirection.
- **Relecture** : Les vues aux lignes 7087, 7102, 7107, 7227, 7662 et 7787 utilisent "project:…". urls.py:82 déclare app_name dans le ROOT_URLCONF, sans effet hors d'un include() et sans namespace déclaré. DevflowUpdateView.get_success_url (l.445) et ArchiveObjectView (l.505) font reverse_lazy, évalué dans HttpResponseRedirect après save, delete ou archive. Il n'y a pas d'ATOMIC_REQUESTS.

#### F126 — Commentaire rapide depuis le Kanban des tâches : 500 systématique
*Bug · Templates / routage / vues* — [project/views.py:4457](project/views.py:4457)

- **Preuve** : TaskQuickCommentView termine par `return redirect(next_url or "task_detail")`. Le formulaire du Kanban (project/task/list.html:358-377) n'envoie pas de champ `next`, donc redirect("task_detail") est appelé sans pk. resolve_url relance alors NoReverseMatch (pas de '/' dans le nom).
- **Impact** : Chaque commentaire posté depuis la liste ou le Kanban des tâches est enregistré, puis l'utilisateur reçoit une page d'erreur 500.
- **Correctif** : `return redirect(next_url or reverse('task_detail', kwargs={'pk': task.pk}))` après validation de next, ou ajouter `<input type="hidden" name="next" value="{{ request.get_full_path }}">` au formulaire.
- **Relecture** : views.py:4457 : `redirect(next_url or 'task_detail')`. Les formulaires task/list.html:358-377 et _task_kanban_card.html:132 n'envoient pas `next`, et submitCommentForm (l.699-706) laisse le submit natif se faire. resolve_url relance NoReverseMatch (nom sans '/' ni '.'), d'où une 500 systématique après l'enregistrement du commentaire.

#### F127 — Listes paginées à 25 sans pagination affichée : Kanban et KPI tronqués
*Bug · Templates / routage / vues* — [project/views.py:251](project/views.py:251)

- **Preuve** : DevflowListView.paginate_by = 25. Aucun des templates suivants n'utilise page_obj ou is_paginated : project/task/list.html, sprint/list.html, milestone/list.html, risk/list.html, roadmap/list.html, release/list.html, objective/list.html, key_result/list.html, ai_insight/list.html, roadmap_item/list.html, milestone_task/list.html, notification/list.html, timesheet_entry/list.html. Les vues calculent aussi `stats = ctx["object_list"].aggregate(...)` (4667/4711, 4158, 5407, 6931, 7257, 7412, 7712, 8491) sur la page découpée. À l'inverse, ProjectListView affiche la pagination mais construit category_sections et history_rows depuis `self.get_queryset()` complet (1925) : la même liste s'affiche sur toutes les pages, avec tous les projets et leurs tâches chargés.
- **Impact** : Le Kanban des tâches n'affiche que les 25 premières tâches, triées par nom de projet. Les tâches, sprints, jalons et risques au-delà sont inaccessibles, et les compteurs (total, en retard…) plafonnent à 25. La pagination de la liste des projets est sans effet.
- **Correctif** : Ajouter un partial de pagination commun, ou fixer paginate_by=None sur les vues Kanban et charger les colonnes par statut côté serveur. Calculer les stats sur self.object_list (queryset complet) plutôt que sur la page. Dans ProjectListView, construire les sections depuis ctx['object_list'].
- **Relecture** : paginate_by=25 (views.py:251), et aucune des listes citées (task, sprint, milestone, risk…) n'utilise page_obj ou is_paginated. Les stats sont calculées sur ctx["object_list"], c'est-à-dire la page découpée (4158, 4667/4711…). ProjectListView reconstruit les sections depuis self.get_queryset() complet (1925).

#### F129 — Dashboard : consommation budgétaire et marge réelle ignorent le coût main-d'œuvre (TJM)
*Intégrité des données · Templates / routage / vues · doublon de F59* — [project/views.py:1057](project/views.py:1057)

- **Preuve** : `budget_usage_percent = pct(actual_expenses_total, approved_budget_total)` et `actual_margin = received_revenue_total - actual_expenses_total` (1063). actual_expenses_total ne somme que les ProjectExpense au statut PAID (1037-1043). `logged_cost_total` (coût timesheet × TJM, 1053) est calculé mais exclu des deux indicateurs, et aucune écriture ne transforme ce coût en ProjectExpense (seul seed_devflow crée des dépenses). L'alerte « Budget consommé à plus de 100% » (build_analysis_cards, 734) repose sur ce ratio. La devise est figée à "XOF" (1078).
- **Impact** : Pour un projet IT dont le coût est surtout humain, le dashboard affiche une consommation proche de 0 % et une marge surestimée, et les alertes budgétaires ne se déclenchent pas.
- **Correctif** : Coût réel = logged_cost_total + dépenses (PAID, voire COMMITTED et ACCRUED), avec une variante engagée. Réutiliser le service budgétaire existant (ProjectBudget / recalculate) au lieu d'agréger à la main, et prendre la devise du workspace ou du budget.
- **Relecture** : views.py:1025-1031 : actual_expenses_total ne compte que les dépenses PAID. budget_usage_percent (1057-1060) et actual_margin (1063) excluent logged_cost_total (1049-1055). La seule création de ProjectExpense est dans seed_devflow.py:203. L'alerte (l.734) repose sur ce ratio, et currency est figé à 'XOF' (l.1078).

#### F130 — Dashboard d'accueil : finances et TJM des collaborateurs visibles par tous les rôles
*Sécurité · Templates / routage / vues* — [templates/dashboard/index.html:428](templates/dashboard/index.html:428)

- **Preuve** : Le dashboard (route "") affiche sans condition RBAC le budget approuvé, les dépenses, le CA encaissé et la marge (lignes 176-194), ainsi que « Profils les plus coûteux » avec `{{ profile.cost_per_day }} {{ profile.currency }}` (428-439). DashboardView fournit top_cost_members (views.py:1259) sans contrôle de rôle. ProjectDetailView, elle, masque ces données via can_view_financials (views.py:2573).
- **Impact** : Un développeur ou un invité voit le TJM de coût de ses collègues (donnée assimilable à un salaire) et la situation financière consolidée du workspace.
- **Correctif** : Calculer `can_view_financials` (rôles ADMIN, CTO, PM… ou RBACService.can(user,'budget.view')) dans DashboardView, ne remplir finance et top_cost_members que dans ce cas, et conditionner les blocs du template.
- **Relecture** : dashboard/index.html affiche les KPI financiers (176-194) et cost_per_day (428-439) sans aucune condition de rôle. DashboardView (views.py:676-1259) ne contient aucun appel RBAC ni can_view_financials.

#### F131 — Bouton « Nouveau projet » et palette ⌘K factices : faux messages de succès
*UX · Templates / routage / vues* — [templates/layout/base.html:2354](templates/layout/base.html:2354)

- **Preuve** : Le bouton « Nouveau projet » de la topbar (_topbar.html:111) ouvre _new_project_modal.html. Ses champs n'ont pas d'attribut name, les équipes et les dates (2026-04-08) sont codées en dur, et `createProject()` se contente de `closeModal(); showToast("✅ Projet créé avec succès !")` sans aucune requête. Dans la palette (_command_palette.html:14), « Nouvelle tâche » appelle `showToast('Tâche créée',var(--green))`, ce qui est une erreur de syntaxe JS. Les items de navigation se limitent à `onclick="closePalette()"` et `filterCmd(v){ return v; }` (2339) ne filtre rien. base.html contient aussi des réponses IA factices codées en dur (`aiReplies`, 2382).
- **Impact** : Sur chaque page, l'utilisateur croit avoir créé un projet alors que rien n'est enregistré. La recherche globale et la palette de commandes ne fonctionnent pas.
- **Correctif** : Faire pointer le bouton vers {% url 'project_create' %} (ou poster le modal vers ProjectCreateView avec CSRF). Implémenter une palette réelle : liens de navigation et endpoint de recherche JSON scopé workspace (projets, tâches, sprints). Supprimer le code mock (createProject, aiReplies, sendAI legacy).
- **Relecture** : createProject() (base.html:2354-2357) se contente de closeModal() et showToast("Projet créé"). Les champs de _new_project_modal.html n'ont pas d'attribut name, et la date 2026-04-08 est codée en dur (l.22). Dans _command_palette.html:14, showToast(...,var(--green)) est une erreur de syntaxe JS. filterCmd renvoie v sans filtrer (2339), et aiReplies est codé en dur (2382).

### 🟡 Moyenne (63)

#### F20 — Endpoints IA payants sans throttle (SSE chat, prévisions, risques, allocation)
*Performance · Sécurité / multi-tenant* — [project/api/views_quick.py:270](project/api/views_quick.py:270)

- **Preuve** : AIChatStreamView n'a pas de throttle_classes (le quota n'est vérifié que si un workspace est résolu, avec 500 tokens estimés). Côté HTML, ProjectBudgetForecastView, ProjectRiskAnalysisView et WorkspaceAllocationAdviceView (views_financial_ai.py:28-99) appellent use_ai=True sans limitation, et ProjectAIProposalTriggerView n'en a pas non plus.
- **Impact** : Facturation DeepSeek/OpenAI non bornée par simple boucle d'appels (même risque que ce que corrige le throttle de l'API DRF).
- **Correctif** : Ajouter AIActionRateThrottle sur AIChatStreamView et un rate-limit équivalent (cache, décorateur) sur les vues HTML IA. Vérifier le quota avant chaque appel.
- **Relecture** : AIChatStreamView (api/views_quick.py:269-322) n'a pas de throttle_classes, et le quota n'est vérifié que pour 500 tokens estimés. Les vues HTML ProjectBudgetForecastView, ProjectRiskAnalysisView et WorkspaceAllocationAdviceView (views_financial_ai.py:28-99), ainsi que ProjectAIProposalTriggerView, appellent use_ai=True sans aucune limitation de débit (aucun DEFAULT_THROTTLE dans REST_FRAMEWORK).

#### F21 — Envoi synchrone du compte-rendu d'enregistrement à des adresses arbitraires
*Sécurité · Sécurité / multi-tenant* — [project/views_recording.py:721](project/views_recording.py:721)

- **Preuve** : RecordingSendEmailView.post appelle send_recording_email() dans la requête HTTP. Celle-ci boucle sur `EmailMessage(...).send(fail_silently=True)` (services/recording/export.py:383-399) avec le DOCX en pièce jointe. extra_emails est extrait librement du POST par regex. `sent += 1` est compté même en cas d'échec.
- **Impact** : Requête bloquée sur SMTP (viole la convention n°6). Tout membre peut exfiltrer le compte-rendu complet vers n'importe quelle adresse externe, ou utiliser le SMTP de l'application comme relais. Le compteur affiché est faux.
- **Correctif** : Passer par une tâche Celery (sur le modèle de send_meeting_minutes_email_async), restreindre extra_emails par RBAC ou domaine, et ne compter que les envois réussis (fail_silently=False dans un try).
- **Relecture** : RecordingSendEmailView.post (views_recording.py:705-728) extrait par regex des adresses arbitraires du POST et appelle send_recording_email en synchrone, sans contrôle de rôle. La boucle export.py:380-400 fait `send(fail_silently=True)` puis `sent += 1`, donc un échec est compté comme envoi.

#### F24 — Accès IA financière refusé aux owners et méthodologies custom non administrables
*Bug · Sécurité / multi-tenant* — [project/views_financial_ai.py:86](project/views_financial_ai.py:86)

- **Preuve** : _WorkspaceAccessMixin n'accepte que TeamMembership ACTIVE, ce qui exclut Workspace.owner et profile.workspace (contrairement à get_user_workspace_ids). Dans views_methodology_admin.py:40, `RBACService.can(user, "workspace.manage")` est appelé sans workspace et renvoie toujours False (rbac.py:266-269) pour un non-superuser.
- **Impact** : Un owner sans membership reçoit 403 sur le cockpit portefeuille et l'allocation. Aucun owner ne peut créer ni éditer de méthodologie custom (fonctionnalité inaccessible).
- **Correctif** : Utiliser user_can_access_workspace() dans _WorkspaceAccessMixin, et passer le workspace courant à RBACService.can dans _user_is_admin.
- **Relecture** : _WorkspaceAccessMixin n'accepte que TeamMembership ACTIVE (views_financial_ai.py:80-91), ce qui exclut le owner et profile.workspace. _user_is_admin appelle RBACService.can(user, "workspace.manage") sans workspace (views_methodology_admin.py:40), et can() renvoie False quand workspace=None (rbac.py:266-269).

#### F25 — Annulation de facture sans contrôle d'état (factures payées)
*Bug · Sécurité / multi-tenant* — [project/views.py:8908](project/views.py:8908)

- **Preuve** : InvoiceCancelView.post fixe `invoice.status = CANCELLED` sans contrôler le statut actuel (PAID, PARTIALLY_PAID) et sans RBAC invoice.*. InvoiceMarkSentView fait de même pour SENT.
- **Impact** : Une facture payée peut passer à l'état annulé : chiffre d'affaires encaissé et suivi des revenus faussés.
- **Correctif** : N'autoriser l'annulation que depuis DRAFT/ISSUED/SENT sans paiement (ou via un avoir), et exiger RBAC invoice.manage.
- **Relecture** : InvoiceCancelView.post (views.py:8905-8911) passe la facture en CANCELLED sans tester son statut (PAID inclus) ni RBAC. InvoiceMarkSentView (8895-8902) fait de même pour SENT.

#### F34 — BillingRate.project en SET_NULL : un TJM négocié devient tarif générique à la suppression du projet
*Intégrité des données · Modèles / formulaires / signaux (initialement high)* — [project/models.py:650](project/models.py:650)

- **Preuve** : `project = models.ForeignKey("Project", on_delete=models.SET_NULL, null=True…, help_text="Si renseigné, ce tarif ne s'applique qu'à ce projet.")`. Dans _daily_amount_for_user (751-761), les tarifs avec `project__isnull=True` servent de repli générique pour tous les projets. Lorsque `project=None`, il n'y a même aucun filtre sur project.
- **Impact** : Dès qu'un projet est supprimé, son TJM spécifique (remise ou majoration client) s'applique silencieusement à tous les autres projets de l'utilisateur s'il est le plus récent. Les coûts, les ventes, les factures en régie et les marges deviennent faux.
- **Correctif** : Passer en `on_delete=models.CASCADE`, ou archiver le tarif (is_archived=True) dans un pre_delete sur Project. Exclure explicitement les tarifs archivés de la résolution.
- **Relecture** : models.py:650-656 déclare project en on_delete=SET_NULL, et _daily_amount_for_user (751-761) utilise les tarifs project__isnull=True comme repli générique. Sévérité abaissée : il faut une suppression physique du projet (l'archivage est le cas courant) et que le tarif orphelin soit le plus récent.

#### F39 — Compteurs dénormalisés jamais recalculés : story points et vélocité des sprints, avancement du projet
*Fonctionnalité manquante · Modèles / formulaires / signaux (initialement high)* — [project/models.py:1244](project/models.py:1244)

- **Preuve** : Sprint.velocity_completed, total_story_points, completed_story_points et remaining_story_points (1244-1248) ne sont écrits que par SprintForm ou l'admin : aucun signal ni service ne les calcule (grep). Les KPI velocity, burndown_sprint et sprint_success_rate (services/methodology/kpis.py:65, 92-93, 119-120) et le chat IA (chat.py:168-186) les lisent. burndown utilise `remaining_story_points or total_sp`, donc 0 restant est affiché comme « tout reste ». Project.progress_percent (448) n'est jamais dérivé des tâches, et risk_score n'est recalculé qu'au save().
- **Impact** : Vélocité, burndown, taux de succès des sprints et avancement projet restent à 0 ou à des valeurs saisies à la main. Les recommandations IA et le score de risque reposent sur des données fausses ou obsolètes.
- **Correctif** : Recalculer les compteurs du sprint (somme de BacklogItem.story_points, terminés vs restants) dans un service appelé on_commit après modification d'une tâche ou d'un item. Dériver Project.progress_percent des tâches, avec un mode manuel optionnel. Faire passer une tâche Celery quotidienne pour risk_score. Corriger `or total_sp` en `is None`.
- **Relecture** : Aucune écriture de velocity_completed, total_story_points, completed_story_points ou remaining_story_points hors SprintForm et admin (grep), et Project.progress_percent n'est que borné au save (models.py:526). burndown_sprint utilise `sprint.remaining_story_points or total_sp` (kpis.py:93), donc 0 restant est affiché comme « tout reste ». Sévérité ramenée à medium : KPI faux, mais ni perte de données ni faille.

#### F41 — Affectation de tâche : double notification, double e-mail, activité en triple et requêtes redondantes
*Bug · Modèles / formulaires / signaux* — [project/signals.py:97](project/signals.py:97)

- **Preuve** : Task.assign() sauvegarde l'assignee. post_save notify_on_task_assignee_change (50-87) envoie alors notify_task_assignment avec un e-mail Celery et un log, puis `TaskAssignment.update_or_create` déclenche notify_on_task_assignment_created (97-121), qui notifie une seconde fois. assign() crée aussi son propre ActivityLog MEMBER_ASSIGNED (models.py:1458). TaskCreateView fait de même (views.py:4926-4936). Deux receivers pre_save relisent chacun la tâche (39 et 281), plus une requête User, et Task.save appelle full_clean() (models.py:1422), soit environ 7 requêtes de validation de FK par save.
- **Impact** : L'assigné reçoit 2 notifications et 2 e-mails, et l'historique compte 3 entrées pour une seule affectation. Environ 10 requêtes supplémentaires par sauvegarde de tâche (kanban, import IA).
- **Correctif** : Notifier dans un seul receiver (sur TaskAssignment, ou sur Task avec un flag `_skip_assign_notify` posé par assign()). Fusionner les deux pre_save en un seul `only(...)`. Remplacer full_clean() dans save() par une validation ciblée.
- **Relecture** : signals.py:50-87 (post_save Task) et 97-121 (post_save TaskAssignment created) appellent tous deux notify_task_assignment, ce qui donne une notification et un e-mail Celery en double, plus deux log_activity. Task.assign crée en plus un ActivityLog (models.py:1458). Deux pre_save relisent la tâche (l.39 et 281), et Task.save appelle full_clean (models.py:1422).

#### F42 — Signaux de feuille de temps : entrée de plus de 24 h créée, snapshot de coût obsolète quand les heures passent à 0
*Intégrité des données · Modèles / formulaires / signaux* — [project/signals.py:459](project/signals.py:459)

- **Preuve** : reverse_spent_hours_to_timesheet_on_done crée une seule entrée avec `hours=delta` via `TimesheetEntry.objects.create` (459-472), sans full_clean, alors que TimesheetEntry.clean interdit plus de 24 h (models.py:1886). create_or_update_timesheet_snapshot fait `if not instance.hours: return` (133) sans remettre le snapshot à zéro. summarize_timesheets additionne `cost_snapshot__computed_cost` (budget.py:207).
- **Impact** : Une tâche clôturée avec spent_hours=40 génère une entrée de 40 h sur une seule journée. Une entrée ramenée à 0 h via TimesheetEntryForm garde son ancien coût dans le coût réel du projet.
- **Correctif** : Répartir le delta sur plusieurs jours avec un plafond de capacité journalière, ou créer un brouillon à valider. Dans le signal snapshot, supprimer ou mettre à zéro le snapshot quand hours vaut 0.
- **Relecture** : TimesheetEntry.objects.create(hours=delta) (signals.py:459-472) passe outre clean(), qui interdit plus de 24 h (models.py:1886), car TimesheetEntry ne surcharge pas save(). create_or_update_timesheet_snapshot sort par `if not instance.hours: return` (signals.py:133) sans remettre le snapshot à zéro.

#### F43 — Task.completed_at non persisté lors d'un changement de statut avec update_fields
*Bug · Modèles / formulaires / signaux* — [project/models.py:1419](project/models.py:1419)

- **Preuve** : Task.save fixe `self.completed_at = timezone.now()` quand le statut passe à DONE, mais sans l'ajouter à update_fields. task_status_update (fallback legacy du kanban) fait `task.save(update_fields=["status", "updated_at"])` (views.py:4078). completed_at n'est jamais remis à None quand une tâche est rouverte. Le rapport IA hebdomadaire filtre sur `completed_at__date__gte` (services/ai/services/project_report.py:241).
- **Impact** : Les tâches terminées par glisser-déposer ont completed_at à NULL en base : elles sont absentes des rapports hebdomadaires et faussent lead time et cycle time. Une tâche rouverte garde une date de fin.
- **Correctif** : Dans save(), si update_fields est fourni et que completed_at change, l'ajouter à update_fields. Remettre completed_at à None quand le statut n'est plus DONE.
- **Relecture** : Task.save (models.py:1419-1420) fixe completed_at en mémoire, mais le repli legacy (views.py:4078) sauve avec update_fields=[status, updated_at], donc la valeur n'est pas persistée. Aucun signal ni Task.save ne remet completed_at à None à la réouverture : seuls quelques chemins le font à la main (views.py:4406, views_quick.py:96).

#### F44 — Facture : le statut ne redescend jamais et la suppression d'une ligne ne recalcule pas les totaux
*Bug · Modèles / formulaires / signaux* — [project/models.py:4641](project/models.py:4641)

- **Preuve** : recompute_totals ne fait que passer à PAID, PARTIALLY_PAID ou OVERDUE : si paid retombe à 0 (paiement REFUNDED ou FAILED dans l'admin) ou si InvoiceForm a forcé status=PAID (champ éditable, 2146), la facture reste PAID avec paid_amount=0 et paid_at conservé. InvoiceLineDeleteView redéfinit `delete()` (views.py:9049-9053), méthode que Django 4.2 n'appelle pas sur un POST (c'est form_valid qui l'est).
- **Impact** : Des factures apparaissent « Payée » sans encaissement, ce qui fausse le suivi du cash et les relances. Après suppression d'une ligne, le total TTC reste l'ancien.
- **Correctif** : Recalculer le statut de façon déterministe à partir des paiements (repasser à ISSUED ou SENT et vider paid_at si paid vaut 0). Retirer "status" du formulaire au profit d'actions explicites. Déplacer le recalcul dans form_valid de InvoiceLineDeleteView, ou dans un signal post_delete sur InvoiceLine et InvoicePayment.
- **Relecture** : models.py:4641-4651 : le statut n'est poussé que vers PAID, PARTIALLY_PAID ou OVERDUE, sans retour en arrière si paid retombe à 0 (paid_at conservé), et status est éditable dans InvoiceForm (2146). Il n'y a aucun signal sur InvoiceLine ou InvoicePayment. Le delete() surchargé d'InvoiceLineDeleteView (views.py:9049-9053) n'est pas appelé sous Django 4.2.30 (form_valid).

#### F45 — ProjectMemberForm : l'allocation est cumulée sur tous les tenants et les projets terminés
*Bug · Modèles / formulaires / signaux* — [project/forms.py:885](project/forms.py:885)

- **Preuve** : `ProjectMember.objects.filter(user=user, project__is_archived=False)` ne filtre ni le workspace ni le statut du projet (DONE ou CANCELLED restent comptés). Au-delà de 100 %, une ValidationError bloque l'enregistrement.
- **Impact** : Un consultant affecté à 100 % sur un projet terminé non archivé, ou dans un autre workspace, ne peut plus être ajouté à aucun projet. Le message révèle aussi indirectement son allocation chez un autre client.
- **Correctif** : Filtrer sur `project__workspace=ws` et exclure les statuts DONE et CANCELLED, ainsi que les projets dont target_date est passée. Envisager un avertissement plutôt qu'un blocage.
- **Relecture** : `ProjectMember.objects.filter(user=user, project__is_archived=False)` (forms.py:885) ne filtre ni le workspace ni le statut DONE/CANCELLED du projet, et une ValidationError bloquante est levée au-delà de 100 % (893-899).

#### F46 — MilestoneForm construit ses querysets à partir du workspace POSTé, avant validation
*Sécurité · Modèles / formulaires / signaux* — [project/forms.py:1691](project/forms.py:1691)

- **Preuve** : `workspace_id = self.initial.get("workspace") or self.data.get("workspace") or …` puis `Project.objects.filter(workspace_id=workspace_id)` et `Workspace.objects.get(pk=workspace_id).memberships…` (1691-1700) sont calculés dans __init__, avant la validation du champ workspace. En GET sans initial, le queryset du champ project reste `Project.objects` (tous).
- **Impact** : Un POST avec workspace=<id d'un autre tenant> renvoie le formulaire invalide, réaffiché avec les projets et les membres (noms et e-mails) de ce tenant. Un id inexistant ou non numérique provoque une erreur 500 (DoesNotExist ou ValueError).
- **Correctif** : Ne lire que current_workspace passé par la vue, ou valider workspace_id contre allowed_workspaces avant de l'utiliser. Utiliser `.filter().first()` plutôt que `.get()`.
- **Relecture** : forms.py:1691-1700 lit workspace depuis self.data avant validation et construit les querysets project et owner du workspace posté. Le champ workspace est ensuite rejeté (queryset limité par DevflowCreateView.get_form), mais le re-rendu affiche les projets et membres de l'autre tenant. Un ID inexistant donne un DoesNotExist (500), et sans initial le queryset project reste global.

#### F47 — Impossible de réinviter un e-mail après révocation, expiration ou refus
*Bug · Modèles / formulaires / signaux* — [project/models.py:2318](project/models.py:2318)

- **Preuve** : WorkspaceInvitation a `unique_together = [("workspace", "email")]`, alors que WorkspaceInvitationForm.clean_email ne contrôle que les invitations PENDING (1938-1947). Les deux champs étant dans le formulaire, validate_unique rejette toute nouvelle invitation, quel que soit le statut de l'ancienne.
- **Impact** : Une invitation révoquée ou expirée bloque définitivement cet e-mail pour ce workspace : il faut supprimer la ligne en base. Le bouton « Révoquer » rend même la réinvitation impossible.
- **Correctif** : Remplacer la contrainte par une UniqueConstraint conditionnelle (`condition=Q(status="PENDING")`), ou réutiliser l'invitation existante en la repassant à PENDING avec un nouveau jeton.
- **Relecture** : models.py:2318 : unique_together (workspace, email), alors que clean_email (forms.py:1938-1947) ne teste que les invitations PENDING. WorkspaceInvitationResendView (views.py:7927) refuse les invitations non PENDING. Une nouvelle invitation est donc rejetée par validate_unique, ou échoue en IntegrityError si workspace n'est pas posté.

#### F49 — Indicateurs ProjectBudget trompeurs : « consommation » calculée sur l'estimé, marge % qui est en fait un markup
*Bug · Modèles / formulaires / signaux* — [project/models.py:1036](project/models.py:1036)

- **Preuve** : budget_consumption_percent vaut `total_estimated_cost / approved_budget` et sert à is_over_alert_threshold (badge « Seuil d'alerte dépassé », templates/project/budget/detail.html:17). estimated_margin_percent vaut `margin / cost` (1006-1010), exporté comme « Marge estimée (%) » (views.py:2275), alors que le service calcule profit_margin_percent = net / revenu (budget.py:741). BillingRate.margin_percent rapporte lui aussi la marge au coût (825).
- **Impact** : L'alerte budget se déclenche ou se tait sans lien avec la consommation réelle. Une « marge » de 25 % affichée correspond en réalité à 20 % de marge sur le prix de vente, ce qui donne de mauvaises décisions de pricing.
- **Correctif** : Calculer la consommation sur le coût réel (actual_cost de build_budget_overview). Renommer le calcul actuel en markup_percent et exposer une vraie marge rapportée au revenu.
- **Relecture** : budget_consumption_percent vaut total_estimated_cost / approved_budget (models.py:1036-1040) et pilote is_over_alert_threshold. estimated_margin_percent divise la marge par le coût (1006-1010), ce qui est un markup, et l'export l'appelle « Marge estimée (%) » (views.py:2275). Le service calcule net / revenu (budget.py:741). BillingRate.margin_percent rapporte aussi au coût (825).

#### F51 — Aucun UserProfile pour les inscriptions directes dès qu'il existe 2 workspaces : pages profil en erreur 500
*Bug · Modèles / formulaires / signaux* — [project/signals.py:27](project/signals.py:27)

- **Preuve** : create_user_profile ne crée un profil que si `_invited_workspace` est posé ou si un seul workspace existe (27-31). L'inscription allauth (CustomSignupForm, adapters.py) ne pose pas _invited_workspace. ProfileDetailView et ProfileUpdateView font `return self.request.user.profile` (views.py:516, 623).
- **Impact** : En multi-tenant, tout compte créé par inscription directe obtient une erreur 500 (RelatedObjectDoesNotExist) sur /profile/. Ses formulaires de tâche ne sont pas scopés non plus (TaskForm s'appuie sur profile).
- **Correctif** : Utiliser `get_object_or_404(UserProfile, user=request.user)` ou rediriger vers un onboarding. Créer le profil (sans privilège workspace) à l'acceptation d'une invitation ou à la création d'un workspace.
- **Relecture** : create_user_profile (signals.py:22-31) ne crée rien sans _invited_workspace dès qu'il existe au moins 2 workspaces. CustomSignupForm.save et AccountAdapter ne posent pas cet attribut, et ProfileDetailView/ProfileUpdateView font `return self.request.user.profile` (views.py:516, 623), ce qui lève RelatedObjectDoesNotExist puis une erreur 500.

#### F66 — Workflows contournés : statut du budget et statut des dépenses modifiables librement
*Bug · Finance / TJM / facturation* — [project/forms_budget.py:112](project/forms_budget.py:112)

- **Preuve** : ProjectBudgetForm expose `status` (l.112). La machine à états ALLOWED_STATUS_TRANSITIONS/transition_to (models.py l.893-962) n'est appelée nulle part hors des tests (grep) : retour CLOSED → DRAFT possible, aucun snapshot BASELINE, aucun verrou sur un budget APPROVED. ProjectExpenseForm expose `status` (l.217) : on peut créer ou modifier une dépense directement en PAID ou VALIDATED alors que approval_state vaut PENDING, et elle entre alors dans actual_cost (budget.py l.711). Le serializer API laisse aussi `status` en écriture (serializers.py l.240).
- **Impact** : La validation à deux niveaux des dépenses et la gouvernance du budget sont contournables, et les KPI sont faussés.
- **Correctif** : Passer status en lecture seule dans les formulaires et les serializers. Ne changer de statut que par des actions dédiées (transition_to, approve_level*, mark_paid) protégées par la RBAC.
- **Relecture** : ProjectBudgetForm expose status (forms_budget.py:112), et transition_to n'est appelé que dans tests_budget_v2.py (grep). ProjectExpenseForm expose status (l.217), et summarize_expenses agrège PAID et VALIDATED par status seul, sans regarder approval_state. Le serializer laisse status en écriture (approval_state y est en lecture seule).

#### F67 — Une allocation de 0 % est comptée à 100 % dans la projection de coût des membres
*Bug · Finance / TJM / facturation* — [project/services/budget.py:154](project/services/budget.py:154)

- **Preuve** : estimate_member_period_cost fait `cls._safe_decimal(allocation_percent or 100)`. Ses appelants passent `member.allocation_percent or 0` (budget.py l.180 et budget_forecast.py l.93) : une allocation de 0 devient `0 or 100`, soit 100 %. ProjectDetailView traite pourtant 0 comme 0 (views.py l.2639).
- **Impact** : Les membres déclarés à 0 % (observateurs, membres sortis) gonflent la prévision de coût à temps plein.
- **Correctif** : Remplacer par `100 if allocation_percent is None else allocation_percent`.
- **Relecture** : budget.py:154 : `_safe_decimal(allocation_percent or 100)`, alors que les appelants passent `member.allocation_percent or 0` (budget.py:180, budget_forecast.py:93) : 0 devient 100 %. ProjectDetailView (views.py:2639) traite 0 comme 0.

#### F68 — summarize_timesheets compte les heures DRAFT/REJECTED, mélange snapshot et calcul, et fait environ 3 requêtes par entrée
*Performance · Finance / TJM / facturation* — [project/services/budget.py:198](project/services/budget.py:198)

- **Preuve** : qs contient toutes les entrées, quel que soit approval_status (l.198), et logged_cost alimente labor_cost via max(...) (l.725) : les heures rejetées ou en brouillon sont donc coûtées. La boucle (l.219-238) fait 2 lookups BillingRate plus 1 accès profil par entrée (select_related('user') ne couvre pas le profil), même quand des snapshots existent, puis son résultat est écrasé (l.241-244). Si une partie seulement des entrées a un snapshot (bulk_create ou update contournent le signal), le total des snapshots remplace tout et les autres entrées disparaissent. Le portfolio, les alertes et l'EAC appellent cette fonction pour chaque projet (l.835-836).
- **Impact** : Coût main-d'œuvre faux, et O(N) requêtes par page portfolio ou par passage Celery.
- **Correctif** : Exclure REJECTED (et DRAFT selon la règle de gestion). Sommer les snapshots, puis ne calculer que les entrées où cost_snapshot__isnull=True. Mettre les TJM en cache par user et par date.
- **Relecture** : qs inclut toutes les entrées, DRAFT et REJECTED comprises (budget.py:198), et logged_cost alimente total_labor_cost via max() (l.725). La boucle (219-238) appelle BillingRate et le profil pour chaque entrée, puis `if snapshot_cost > 0: logged_cost = snapshot_cost` (241-244) écrase tout, même si seules certaines entrées ont un snapshot. Le portfolio appelle cela pour chaque projet (835-836).

#### F69 — Cycle de vie facture : numérotation fragile, numéro perdu au passage SENT, statuts de paiement faux, factures émises modifiables
*Bug · Finance / TJM / facturation* — [project/models.py:4597](project/models.py:4597)

- **Preuve** : generate_number trie par `-number` en ordre lexical (l.4603) : après FAC-AAAA-9999, il régénère 10000 indéfiniment. L'année prise est celle du jour, pas d'issue_date. Il n'y a ni verrou ni retry : deux appels concurrents à InvoiceIssueView (views.py l.8880) provoquent une IntegrityError. InvoiceMarkSentView (l.8895-8902) appliquée à un DRAFT fait save(update_fields=[status, sent_at]) : le numéro calculé dans save() (l.4664-4665) n'est pas persisté. recompute_totals (l.4640-4650) ne rétrograde jamais un statut PAID après remboursement (paid_at est conservé). InvoicePaymentCreateView (l.9057-9077) accepte le trop-perçu et les paiements sur des factures DRAFT ou CANCELLED. InvoiceCancelView annule une facture PAID sans avoir. InvoiceForm expose `status` (forms.py l.2145), ce qui permet de repasser ISSUED → DRAFT. InvoiceLineCreate/UpdateView (l.8996-9035) ne vérifient pas le statut DRAFT.
- **Impact** : Numérotation légale non fiable, factures envoyées sans numéro, factures émises modifiables, soldes et statuts erronés.
- **Correctif** : Compteur par workspace et par année, sous select_for_update. Inclure 'number' dans update_fields. Status non éditable, transitions contrôlées, paiements limités au reste dû sur les factures ISSUED/SENT/PARTIALLY_PAID/OVERDUE, recompute capable de rétrograder le statut. Ajouter les avoirs.
- **Relecture** : generate_number trie -number lexicalement (models.py:4603), sans verrou, malgré la UniqueConstraint (workspace, number). MarkSent sur un DRAFT utilise update_fields sans number (views.py:8899), donc le numéro n'est pas persisté. Les paiements sont acceptés sur DRAFT ou CANCELLED et en trop-perçu (9057-9077), et les lignes ne vérifient pas DRAFT. Nuance : recompute_totals rétrograde bien PAID en PARTIALLY_PAID si paid > 0, mais pas quand paid retombe à 0.

#### F70 — Totaux de facture incohérents sur les documents : remise affichée après un sous-total déjà remisé
*Bug · Finance / TJM / facturation* — [project/models.py:4623](project/models.py:4623)

- **Preuve** : subtotal_ht est enregistré déjà net de remise (`lines_total - discount`, l.4623). Pourtant pdf.html (l.362-367), print.html (l.83-84) et invoice_docx.py (l.487-491) affichent « Sous-total HT = subtotal_ht » puis « Remise - X ». Exemple : lignes 1000 et remise 100 donnent l'affichage Sous-total 900, Remise -100, TVA 162, TTC 1062.
- **Impact** : Les calculs imprimés sur la facture ne se recoupent pas, ce qui pose un problème de conformité d'un document légal.
- **Correctif** : Afficher le total brut des lignes, puis la remise, puis la base HT nette, puis la TVA, puis le TTC. Au besoin, stocker séparément lines_total et net_ht.
- **Relecture** : models.py:4622-4623 : subtotal_ht = lines_total - discount. Pourtant pdf.html:360-367, print.html:83-84 et invoice_docx.py:487-491 affichent « Sous-total HT » (déjà remisé) puis « Remise - X ». Le document semble appliquer la remise deux fois, même si le TTC calculé est correct.

#### F71 — GET /api/v1/workspaces/{id}/portfolio/ renvoie 500 dès que le workspace a un projet
*Bug · Finance / TJM / facturation* — [project/api/viewsets.py:84](project/api/viewsets.py:84)

- **Preuve** : `return Response(ProjectBudgetService.build_portfolio_overview(projects))` : chaque élément de rows contient `"project": project`, une instance de modèle (budget.py l.839), que le JSONEncoder DRF ne sait pas sérialiser (TypeError). Les totaux additionnent en outre des montants de devises différentes (champ currency par projet ignoré).
- **Impact** : L'endpoint portfolio de l'API est inutilisable.
- **Correctif** : Sérialiser le projet (id, name, code) et typer la réponse avec un serializer. Agréger par devise.
- **Relecture** : rows contient `"project": project`, une instance de modèle (budget.py:839), renvoyée telle quelle par Response (viewsets.py:84). Le JSONEncoder de DRF, inspecté dans le venv, n'a pas de branche pour un Model (ni __getitem__ ni __iter__), d'où une TypeError et une erreur 500. Les totaux additionnent aussi des devises différentes.

#### F72 — Fonctionnalités financières inaccessibles ou à moitié faites (pages orphelines, liens en 404, absence de gestion des TJM)
*Fonctionnalité manquante · Finance / TJM / facturation* — [project/views_financial_ai.py:29](project/views_financial_ai.py:29)

- **Preuve** : ProjectBudgetForecastView déclare template_name=forecast.html mais son GET renvoie du JSON (l.31-39), et aucune vue n'affiche templates/project/budget/forecast.html. Les routes risks, generate-estimates, recalculate-budget et refresh-financials n'ont aucun bouton (grep templates). Il n'existe aucune vue liste, modification ou suppression pour ProjectRevenue et ProjectEstimateLine (urls : create uniquement), et le lien « Voir les revenus client » vers /project-revenues/ (views.py l.3274) renvoie 404. quick_actions['facturation_client'] est écrasé pour les utilisateurs habilités à la finance (l.3272), qui perdent « Générer une facture ». Aucune interface BillingRate ou CostCategory (TJM historisé ou par projet uniquement via l'admin ou l'API). ProjectBudgetForecastRun n'est jamais créé. Pas de relances, pas de tâche planifiée OVERDUE, pas d'envoi de facture par email (MarkSent ne change que le statut), pas d'avoirs, pas de rentabilité réelle par membre (_build_member_cost_summary est uniquement prévisionnel).
- **Impact** : Des fonctions IA et budget livrées côté backend restent invisibles. Les utilisateurs ne peuvent ni corriger une ligne d'estimation ou un revenu, ni gérer les TJM, ni relancer les impayés.
- **Correctif** : Ajouter une vue HTML pour la prévision (et le JSON sur ?format=json), des boutons pour les recalculs et les snapshots, le CRUD Revenue/EstimateLine/BillingRate, la persistance des ForecastRun, une tâche Celery de relance et de passage OVERDUE (envoi email via Celery), un modèle d'avoir et un rapport de rentabilité par membre (heures approuvées × (vente − coût)).
- **Relecture** : Vérifié : ProjectBudgetForecastView renvoie du JSON (views_financial_ai.py:31-39) et forecast.html n'est rendu par aucune vue. Aucun template n'appelle project_generate_estimates, recalculate_budget, refresh_financials ni financial_ai_risks. Seule la route project-revenues/create/ existe, donc /project-revenues/ renvoie 404. quick_actions['facturation_client'] est écrasé (views.py:3272), et aucun ProjectBudgetForecastRun n'est créé.

#### F76 — Genesis : double génération IA et proposition PENDING orpheline à chaque création
*Bug · IA / méthodologies (initialement high)* — [project/services/ai/services/project_genesis.py:114](project/services/ai/services/project_genesis.py:114)

- **Preuve** : `Project.objects.create(...)` déclenche le signal `trigger_ai_proposal_on_project_creation` (signals.py:196). Ce signal crée une proposition P0 PENDING sans items et programme `generate_project_ai_proposal_task` via on_commit (AI_AUTO_TRIGGER_ON_PROJECT_CREATE vaut True par défaut ; `_skip_ai_trigger` n'est pas positionné). Genesis voit P0 sans items (l.141) et génère P1, appliquée. Après le commit, la tâche Celery (tasks.py:200-212) retrouve P0 (PENDING, sans items) et relance `generate_for_project` : P2 READY.
- **Impact** : Deux appels LLM coûteux (structure de 25 à 80 tâches) par projet Genesis. Une proposition READY P2 reste à appliquer : si quelqu'un l'applique, sprints et tâches sont dupliqués. La proposition P0 reste PENDING pour toujours. Même schéma d'orphelin PENDING dans ProjectAIProposalTriggerView (AJAX).
- **Correctif** : Positionner `project._skip_ai_trigger = True` avant le save dans Genesis (instancier puis save). Dans la tâche Celery et le Trigger, réutiliser la proposition PENDING existante (la passer en paramètre à generate_for_project) au lieu d'en créer une nouvelle.
- **Relecture** : Project.objects.create (project_genesis.py:114) déclenche le signal (signals.py:196-250), qui crée P0 PENDING et enqueue la tâche Celery ; _skip_ai_trigger n'est jamais positionné (grep). Genesis génère P1 puis l'applique (VALIDATED), et la tâche Celery (tasks.py:202-212) retrouve P0 sans items et régénère P2 via un create (project_structure.py:212). Sévérité ramenée à medium : double coût IA et propositions orphelines, sans perte de données.

#### F77 — Copilote : outils exécutés sans confirmation, flag destructive et json_schema jamais appliqués, RBAC permissif en cas d'erreur
*Sécurité · IA / méthodologies (initialement high)* — [project/services/methodology/copilot.py:148](project/services/methodology/copilot.py:148)

- **Preuve** : Si le LLM renvoie `{"action":"tool_call"}`, chat() appelle directement `execute_tool(tool_name=..., **args)`. La confirmation des actions destructives ne repose que sur le prompt (l.64). execute_tool (tool_registry.py:104-170) ne lit jamais `spec.destructive` et ne valide pas `json_schema`, contrairement à la docstring l.10-12. `_check_permission` renvoie True sur exception (l.100-101). Le contexte injecté contient `project.description` (ai_service._build_context_block), éditable par d'autres membres. Des outils irréversibles (issue_invoice, delete_invoice_line, assign_task) sont exposés.
- **Impact** : Injection de prompt indirecte : une consigne cachée dans la description du projet peut faire émettre une facture ou supprimer des lignes avec les droits de l'utilisateur qui consulte le copilote, sans validation humaine. Des kwargs inattendus (ex. `project`) provoquent un TypeError non capturé, donc une 500.
- **Correctif** : Pour tout outil destructive ou irréversible, renvoyer une action « pending_confirmation » (AIActionLog PENDING) et exiger un POST de confirmation explicite. Valider `args` avec jsonschema et une liste blanche de clés. Rendre `_check_permission` fermé par défaut (False sur exception).
- **Relecture** : copilot.py:148-153 exécute directement le tool renvoyé par le LLM. execute_tool (tool_registry.py:104-170) ne lit ni spec.destructive ni json_schema, _check_permission renvoie True sur exception (l.100-101), et project.description est injecté (ai_service.py:52-53). Sévérité abaissée : les tools restent scopés au workspace et au RBAC de l'utilisateur, donc il faut une injection de prompt intra-tenant.

#### F78 — Outils facture du copilote : RBAC vérifié sur le workspace du projet, pas sur celui de la facture
*Sécurité · IA / méthodologies (initialement high)* — [project/services/methodology/tool_registry.py:725](project/services/methodology/tool_registry.py:725)

- **Preuve** : `_ai_get_invoice(invoice_id, user)` accepte toute facture d'un des workspaces de l'utilisateur (`inv.workspace_id not in ws_ids`). Or execute_tool vérifie `_check_permission(user, spec.required_permission, workspace)` avec `workspace = project.workspace` (l.119, 141). Même schéma dans delete_invoice_line (filtre `invoice__workspace_id__in=ws_ids`).
- **Impact** : Un utilisateur ADMIN dans W1 et simple MEMBER dans W2 peut, depuis le copilote d'un projet W1, émettre (issue_invoice, irréversible) ou modifier des factures de W2 sans y avoir `invoice.issue` ou `invoice.update`. Cela contredit la « règle d'or » documentée l.692.
- **Correctif** : Dans chaque outil facture, refaire `RBACService.can(user, perm, workspace=inv.workspace)` sur le workspace de la facture, ou exiger `inv.workspace_id == project.workspace_id` quand un projet est en contexte.
- **Relecture** : tool_registry.py:119/141 : la RBAC est vérifiée sur project.workspace, alors que _ai_get_invoice (725-737) accepte toute facture des workspaces de l'utilisateur. delete_invoice_line (1351-1354) suit le même schéma. Sévérité ramenée à medium : il s'agit d'une escalade entre workspaces d'un même utilisateur multi-membre, pas d'une fuite cross-tenant.

#### F80 — Application d'une proposition IA : échec total sur des sorties LLM courantes, et affectations hors source de vérité
*Intégrité des données · IA / méthodologies (initialement high)* — [project/services/ai/services/proposal_apply.py:138](project/services/ai/services/proposal_apply.py:138)

- **Preuve** : La priorité stockée vaut `str(ti.get("priority")).upper()[:20]` sans validation (project_structure.py:743). `Task.objects.create(priority=...)` passe ensuite par Task.save, qui appelle `full_clean()` (models.py:1421) : ValidationError non capturée pour « URGENT », « HAUTE », etc. Les `try/except` autour de `TaskDependency.objects.create` (l.168-177) et de `TaskAssignment.objects.create` (l.186-196, unique_together) avalent des IntegrityError dans un bloc @transaction.atomic : sous PostgreSQL (prod), la transaction est abortée et la requête suivante échoue. `dependency_type=payload.get("type")` n'est pas validé (max_length 20). Les tâches sont créées avec `assignee=` direct, sans `Task.assign()`, donc sans TaskAssignment.
- **Impact** : Un seul doublon de dépendance ou une priorité hors liste fait échouer toute l'application de la proposition. Dans Genesis, cela donne un projet vide avec une proposition VALIDATED impossible à appliquer. Les tâches affectées n'apparaissent pas dans les feuilles de temps, qui itèrent sur TaskAssignment.
- **Correctif** : Normaliser et valider priority, dependency_type et estimate_hours lors de `_instantiate_items` (mapping FR/EN vers les choix, valeur par défaut MEDIUM). Envelopper chaque create optionnel dans `with transaction.atomic():` (savepoint) ou utiliser get_or_create. Créer les tâches puis appeler `task.assign(user, assigned_by=actor)`.
- **Relecture** : La priorité est stockée telle quelle (project_structure.py:743), et Task.save→full_clean (models.py:1421) lève une ValidationError non capturée si elle sort des choix. apply est @transaction.atomic (proposal_apply.py:28), et les try/except sans savepoint (168-196) laisseraient la transaction PostgreSQL abortée. Les tâches sont créées avec assignee= sans TaskAssignment. Sévérité abaissée : le prompt impose LOW|MEDIUM|HIGH|CRITICAL (l.457).

#### F81 — Parsing de la structure IA : une sortie mal typée fait planter Genesis et la régénération au lieu de basculer sur l'heuristique
*Bug · IA / méthodologies (initialement high)* — [project/services/ai/services/project_structure.py:246](project/services/ai/services/project_structure.py:246)

- **Preuve** : `_instantiate_items` est appelé hors du try qui protège `_call_ai`. Il fait `ri.get("title", "")[:200]` (l.674 : TypeError si title vaut null, AttributeError si l'élément n'est pas un dict), `int(si.get("velocity_target") or 0)` (l.710 : ValueError sur « 20 pts ») et `Decimal(str(ti.get("estimate_hours") or 0))` (l.745 : InvalidOperation sur « 8h »). Le prompt (l.443 puis 455) définit deux fois la clé "risks" (string puis liste), et `proposal.risks_summary = (payload.get("risks") or "")[:5000]` peut recevoir une liste.
- **Impact** : La création Genesis (ValueError/Exception affichée), ProjectAIProposalRegenerateView (500 non capturée) et la tâche Celery (retries payants) échouent alors que l'heuristique existe.
- **Correctif** : Valider le payload (schéma pydantic ou jsonschema, ou coercition défensive) avant instanciation, et retomber sur `_heuristic_payload` si la validation échoue. Corriger le schéma du prompt (risks_summary string, risks liste).
- **Relecture** : project_structure.py:246 : _instantiate_items est appelé hors du try de _call_ai, et `ri.get('title','')[:200]` (l.674), `int(...velocity_target)` (l.710) et `Decimal(str(...estimate_hours))` (l.745) lèvent des exceptions sur des sorties mal typées, ce qui fait planter Genesis (project_genesis.py:146, non protégé). Nuance : « risks » sous forme de liste ne plante pas (le slicing d'une liste passe, puis str() via TextField). Sévérité ramenée à medium, car l'aléa dépend du LLM.

#### F85 — WorkflowEngine.apply_transition : crash si aucun workflow, completed_at non persisté, journal d'activité jamais écrit
*Bug · IA / méthodologies* — [project/services/methodology/workflow_engine.py:248](project/services/methodology/workflow_engine.py:248)

- **Preuve** : can_transition renvoie `(True, "")` quand workflow est None (l.199), puis apply_transition fait `workflow.methodology.statuses...` (l.248) : AttributeError pour les projets MILESTONE, FIELD, REAL_ESTATE et ADMINISTRATIVE (aucune Methodology seedée). `obj.save(update_fields=["status","updated_at"])` (l.272) ignore le `completed_at` calculé par Task.save. `ActivityLog.objects.create(action_type=..., description=...)` (l.283) : TypeError vérifié (le champ s'appelle activity_type et title est requis), avalé par le except.
- **Impact** : L'outil copilote update_task_status échoue (AttributeError) pour 4 types de projet sur 8. Les tâches passées DONE via le workflow n'ont pas de completed_at (KPI et reporting faux). Aucune transition n'est auditée.
- **Correctif** : Dans apply_transition, si workflow est None, appliquer directement le statut (ou lever TransitionError). Ajouter `completed_at` aux update_fields quand le statut est DONE. Corriger l'appel ActivityLog (activity_type=..., title=...).
- **Relecture** : workflow_engine.py:199 renvoie (True, '') sans workflow, puis l.248 fait `workflow.methodology` (AttributeError). update_fields (l.272) exclut completed_at. ActivityLog.create(action_type=..., description=...) (l.283) est invalide (les champs sont activity_type et title, models.py:1782-1785) et l'erreur est avalée (l.296). Nuance : le crash est rattrapé par les appelants (views.py:4073 bascule en legacy, et execute_tool marque FAILED).

#### F86 — Copilote : un outil en échec est rapporté « ✓ Action exécutée », et assign_task choisit un utilisateur arbitraire
*Bug · IA / méthodologies* — [project/services/methodology/tool_registry.py:163](project/services/methodology/tool_registry.py:163)

- **Preuve** : Les outils renvoient `{"error": "Tâche introuvable..."}` (update_task_status, assign_task, TransitionError). execute_tool marque pourtant le résultat SUCCESS (l.151-163), et copilot.py:156 affiche `r.get("message", "✓ Action exécutée.")`. assign_task : `Q(username__icontains=hint) | ...` puis `.first()` (l.404-408). Un hint vide ou court ("a") matche n'importe qui, et `task.assignee = assignee; task.save(...)` (l.411) contourne Task.assign() : pas de TaskAssignment, pas d'_assigned_by.
- **Impact** : L'utilisateur croit qu'une action a réussi alors qu'elle a échoué, et l'AIActionLog est marqué SUCCESS. Des tâches peuvent être assignées à la mauvaise personne sans désambiguïsation.
- **Correctif** : Dans execute_tool, traiter `isinstance(result, dict) and result.get("error")` comme FAILED. Dans assign_task, exiger un match unique (exact sur email ou username, sinon renvoyer la liste des candidats) et utiliser `task.assign(assignee, assigned_by=user)`.
- **Relecture** : execute_tool marque SUCCESS tout retour sans exception, y compris {"error": ...} (tool_registry.py:151-163), et copilot.py:156 affiche alors « ✓ Action exécutée. ». assign_task filtre `icontains` sur hint puis prend .first() (l.404-408), et un hint vide matche tout le monde. Il fait ensuite task.save(update_fields=["assignee"]) sans Task.assign() ni TaskAssignment.

#### F87 — Extraction JSON des réponses LLM cassée pour les blocs ```json (retourne toujours {})
*Bug · IA / méthodologies* — [project/services/ai/openai_provider.py:136](project/services/ai/openai_provider.py:136)

- **Preuve** : `text = text.split("```", 2)[-1]` : pour "```json\n{...}\n```", split donne ['', 'json\n{...}\n', ''] et [-1] vaut '' (testé en Python). Le même code est dupliqué dans deepseek_provider.py:176, anthropic_provider.py:140, budget_forecast._safe_json, capabilities._parse_json_tolerant, copilot.py:129 et meeting_intelligence.py:149. Par ailleurs, `isinstance(provider, OpenAIProvider)` n'est jamais vrai en mode auto (FallbackChainProvider), et les services font alors `json.loads(response.text)` brut.
- **Impact** : Avec les providers de secours sans json_mode (Local/Ollama, Anthropic), qui entourent souvent la réponse de balises, toutes les fonctions IA renvoient {} en silence. Meeting intelligence renvoie un résultat vide sans heuristique (le provider est marqué comme ayant répondu), et le copilote n'exécute jamais d'outil.
- **Correctif** : Créer un helper unique `extract_json(text)` (regex sur ```(?:json)?\s*(.*?)``` puis repli sur le premier '{' et le dernier '}'), l'utiliser partout et supprimer les branches isinstance(provider, OpenAIProvider).
- **Relecture** : Testé en Python : "```json\n{...}\n```".split("```",2)[-1] == '', puis json.loads échoue et on obtient {}. Le motif est dupliqué dans 11 fichiers (grep). isinstance(provider, OpenAIProvider) est utilisé dans 5 services alors que le mode auto renvoie FallbackChainProvider (fallback.py:42).

#### F88 — Chaîne de fallback « auto » non conforme : OpenAI absent, provider local toujours « disponible », stream re-émis
*Bug · IA / méthodologies* — [project/services/ai/factory.py:79](project/services/ai/factory.py:79)

- **Preuve** : Les valeurs par défaut sont `["deepseek","local"]` (factory.py:79) et `AI_FALLBACK_CHAIN="deepseek,anthropic,local"` (settings/base.py:343), alors qu'AGENTS.md et base.py:313 annoncent DeepSeek → OpenAI → Local → Null. Une installation avec seulement OPENAI_API_KEY n'utilise donc jamais OpenAI. `LocalProvider.is_available()` renvoie `bool(self.base_url)`, toujours vrai avec la valeur par défaut http://localhost:11434/v1 : `_NullProvider` n'est jamais retourné et chaque appel tente localhost. Dans FallbackChainProvider.generate_stream, la boucle `for chunk in stream: yield chunk` est dans le try (l.186-195) : une erreur en cours de stream bascule sur le provider suivant, qui ré-émet toute la réponse, à l'inverse de la docstring.
- **Impact** : OpenAI est ignoré malgré une clé valide. Les services ne détectent jamais l'absence d'IA (ex. copilote « Erreur IA : Connection error » au lieu du message d'indisponibilité, latence de retries). Le texte streamé peut être partiel puis dupliqué.
- **Correctif** : Chaîne par défaut "deepseek,openai,anthropic,local". LocalProvider disponible seulement si AI_LOCAL_BASE_URL est explicitement défini (sans valeur par défaut). Dans generate_stream, sortir la boucle post-premier-chunk du try, ou lever l'exception une fois engagé.
- **Relecture** : factory.py:79 (défaut deepseek,local) et settings/base.py:343 (deepseek,anthropic,local) : OpenAI est absent de la chaîne auto. LocalProvider.is_available (local_provider.py:50-53) renvoie bool(base_url), toujours vrai (défaut localhost, .env ollama), donc _NullProvider n'est jamais atteint. fallback.py:185-195 : la boucle `for chunk in stream` est dans le try, ce qui provoque un changement de provider et une ré-émission en cours de stream, contrairement à la docstring (l.144-146).

#### F89 — Export Excel du chat IA écrit dans /media public avec un nom prévisible
*Sécurité · IA / méthodologies* — [project/services/ai/services/chat.py:577](project/services/ai/services/chat.py:577)

- **Preuve** : `filename = f"exports/devflow_projets_risque_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"` puis `default_storage.save(...)` (FileSystemStorage) et lien `default_storage.url(...)`. En prod, nginx sert /media/ sans authentification (deploy/nginx/media.conf:4-5).
- **Impact** : La liste des projets à risque d'un workspace (noms, scores, retards) est téléchargeable par n'importe qui en devinant l'horodatage à la seconde. Les fichiers ne sont jamais purgés.
- **Correctif** : Servir l'export via une vue authentifiée qui streame le fichier (HttpResponse/FileResponse) sans le persister, ou le stocker sous un chemin aléatoire (uuid4) dans un stockage privé avec URL signée et expiration.
- **Relecture** : Le fichier est nommé à partir d'un horodatage à la seconde (chat.py:577) et enregistré via le FileSystemStorage par défaut (base.py:400-403). Le dossier /media est servi publiquement par nginx (media.conf:4-8, Cache-Control public) et par Django via static() quel que soit DEBUG (urls.py:929).

#### F90 — Analyse de risques : chaque relance ré-active les risques ignorés et accumule des AInsight IA
*Bug · IA / méthodologies* — [project/services/ai/services/risk_analysis.py:237](project/services/ai/services/risk_analysis.py:237)

- **Preuve** : `_persist_signals` fait `AInsight.objects.update_or_create(..., title=signal.title, defaults={..., "is_dismissed": False})`. Les titres générés par l'IA varient d'un run à l'autre, et les signaux heuristiques qui ne sont plus détectés ne sont jamais clôturés.
- **Impact** : Un risque ignoré par le PM réapparaît à chaque analyse (POST financial-ai/risks ou API). Les insights IA s'empilent indéfiniment et le tableau de bord des risques devient bruité.
- **Correctif** : Ne pas écraser is_dismissed (le retirer de defaults). Clé de dédoublonnage par code de signal (stocker `code`). Marquer comme résolus les insights RISK non retrouvés dans le run courant.
- **Relecture** : risk_analysis.py:226-238 fait update_or_create avec la clé title et is_dismissed=False dans les defaults, ce qui réactive les insights ignorés. Comme les titres IA varient, les insights s'accumulent, et aucune clôture des signaux disparus n'existe.

#### F91 — Pipeline « import de document → projet généré par IA » non branché
*Fonctionnalité manquante · IA / méthodologies* — [project/ia_create_view.py:26](project/ia_create_view.py:26)

- **Preuve** : ProjectDocumentImportView est la seule vue qui appelle ProjectImportOrchestrator (extraction PDF/DOCX → LLM → ProjectAIImportService), mais aucune route ne pointe vers elle (grep dans ProjectFlow/urls.py). La vue routée ProjectDocumentImportCreateView (views.py:3776) se contente d'enregistrer le fichier en statut UPLOADED. Aucun signal ni tâche Celery ne traite les imports UPLOADED, et le détail (document_import/detail.html) n'a pas de bouton d'analyse.
- **Impact** : La fonctionnalité visible « Importer un document projet » n'aboutit jamais : les imports restent UPLOADED et la section « Payload IA » reste vide.
- **Correctif** : Ajouter une tâche Celery `process_document_import(import_id)` lancée en on_commit après création (ou via un bouton « Analyser avec l'IA »), qui appelle l'orchestrateur, met à jour status, ai_payload et project. Utiliser `file.open()` plutôt que `.path` pour la compatibilité S3, et scoper `_find_user_by_email` au workspace.
- **Relecture** : ProjectImportOrchestrator n'est utilisé que par ia_create_view.py:54, et ce module n'est importé nulle part (grep vide dans urls.py et project). La vue routée ProjectDocumentImportCreateView (urls.py:318) enregistre seulement l'import en UPLOADED. Aucune tâche ni signal ne traite les imports, et document_import/detail.html n'a aucune action d'analyse.

#### F92 — Services IA (Genesis, prévision, risques, résumé, recommandations, rapport, estimation) sans point d'entrée UI
*Fonctionnalité manquante · IA / méthodologies* — [project/views_financial_ai.py:38](project/views_financial_ai.py:38)

- **Preuve** : ProjectBudgetForecastView déclare `template_name = "project/budget/forecast.html"` mais GET renvoie `JsonResponse(forecast.to_dict())` : le template forecast.html (qui fetch la même URL) n'est rendu par aucune vue. Aucun template ne fait référence à `ai_project_genesis` ni à `project_financial_ai_risks`. Les actions DRF ai/summary, ai/recommendations, ai/report/generate et ai/effort-estimate ne sont appelées par aucun template ou JS (grep sur templates/static).
- **Impact** : L'estimation des délais, la prévision budgétaire TJM, l'analyse de risques et la création Genesis, mises en avant dans la mission, sont inaccessibles aux utilisateurs non techniques (accès uniquement par URL ou API).
- **Correctif** : Séparer la page HTML (TemplateView rendant forecast.html) de l'endpoint JSON. Ajouter des boutons « Analyser les risques », « Résumé IA », « Estimer » dans la fiche projet et la fiche tâche (htmx/Alpine), et un CTA « Créer avec l'IA » dans la liste des projets ou la sidebar vers /ai/genesis/.
- **Relecture** : ProjectBudgetForecastView.get renvoie un JsonResponse (views_financial_ai.py:31-38), et forecast.html n'est rendu par aucune vue. Dans les templates, ai_project_genesis et project_financial_ai_risks n'apparaissent que dans une condition `current_url ==` de la sidebar (l.266), jamais en lien. Les chemins ai/summary, ai/recommendations, ai/report/generate et ai/effort-estimate n'apparaissent dans aucun template ni JS.

#### F93 — Estimation d'effort IA : heuristique basée sur des champs inexistants (task_type, story_points)
*Bug · IA / méthodologies* — [project/services/ai/services/effort_estimation.py:63](project/services/ai/services/effort_estimation.py:63)

- **Preuve** : `getattr(task, "task_type", "")` et `getattr(task, "story_points", None)` (l.63, l.76) : vérifié via l'ORM, Task ne possède aucun de ces champs. Le type vaut donc toujours « TASK » (6 h) et sp_factor 1.0. Le payload envoyé au LLM contient les mêmes valeurs vides. L'estimation existante (`task.estimate_hours`, `spent_hours`) et les SP du `backlog_item` sont ignorés.
- **Impact** : L'estimation des délais (objectif IA n°1) renvoie 5,1 à 7,8 h pour toute tâche, quel que soit son contenu : la baseline et le fallback sont inutilisables.
- **Correctif** : Utiliser `task.backlog_item.item_type` et `story_points` quand ils existent, l'historique (moyenne des spent_hours des tâches DONE similaires du projet) et estimate_hours. Exposer le résultat dans la fiche tâche.
- **Relecture** : Task (models.py:1326-1400) n'a ni task_type ni story_points, d'où toujours TASK (6 h) et sp_factor 1.0 (effort_estimation.py:63, 76). Au passage, TaskSerializer (serializers.py:311) déclare aussi story_points, qui n'existe pas sur Task.

#### F94 — Mapping projet → méthodologie incomplet : 4 types de projet sans méthodologie, 6 méthodologies seedées inatteignables
*Fonctionnalité manquante · IA / méthodologies* — [project/views_methodology.py:32](project/views_methodology.py:32)

- **Preuve** : `_resolve_methodology` fait `Methodology.objects.filter(code=project.methodology.lower())`. Project.Methodology contient SCRUM, KANBAN, AGILE, WATERFALL, MILESTONE, FIELD, REAL_ESTATE et ADMINISTRATIVE, mais les seeds 0045 et 0050 ne créent que scrum, kanban, waterfall, agile, prince2, pmbok, safe, devops, lean et hybrid.
- **Impact** : Les projets MILESTONE, FIELD, REAL_ESTATE et ADMINISTRATIVE n'ont ni dashboard KPI, ni persona copilote, ni workflow. PRINCE2, PMBOK, SAFe, DevOps, Lean et Hybride ne peuvent être choisis par aucun projet (code mort côté UI).
- **Correctif** : Ajouter un FK `Project.methodology_obj` (déjà anticipé dans workflow_engine), ou étendre les choix et seeder les 4 méthodologies manquantes. Proposer le choix de méthodologie (système et custom du workspace) dans le formulaire projet.
- **Relecture** : views_methodology.py:32-42 mappe Project.methodology.lower() vers Methodology.code. Les choix MILESTONE, FIELD, REAL_ESTATE et ADMINISTRATIVE (models.py:397-400) n'ont pas de seed, et prince2, pmbok, safe, devops, lean et hybrid (0050) ne sont pas dans les choix. Project n'a aucune FK vers Methodology (methodology_obj est absent du modèle).

#### F95 — Admin méthodologies : création impossible pour les admins workspace, alors que modification et suppression sont ouvertes à tout membre
*Bug · IA / méthodologies* — [project/views_methodology_admin.py:41](project/views_methodology_admin.py:41)

- **Preuve** : `_user_is_admin` appelle `RBACService.can(user, "workspace.manage")` sans workspace, et RBACService.can renvoie False quand workspace est None (rbac.py:266-269) : seuls les superusers peuvent créer. À l'inverse, Update, Delete et Add* (l.155-286) n'appellent que `_get_editable_methodology`, qui vérifie l'appartenance au workspace, pas le rôle. Une méthodologie custom avec workspace=None (possible si get_current_workspace renvoie None, l.125) passe le test `elif methodology.workspace_id and ...` pour tous les tenants.
- **Impact** : La fonctionnalité « méthodologie personnalisée par workspace » est inaccessible aux admins. Un simple MEMBER peut supprimer ou modifier les méthodologies custom de son workspace, et une méthodologie sans workspace est éditable cross-tenant.
- **Correctif** : Passer le workspace courant à RBACService.can, appliquer `_user_is_admin(user, methodology.workspace)` sur toutes les vues d'écriture, refuser la création sans workspace, et traiter `workspace_id is None and not is_system` comme non éditable.
- **Relecture** : _user_is_admin appelle can() sans workspace, qui renvoie False pour un non-superuser (rbac.py:266-269) : la création est donc réservée aux superusers. Update, Delete et Add* n'appellent que _get_editable_methodology (views_methodology_admin.py:155-286), qui vérifie l'appartenance mais pas le rôle, et laisse passer workspace_id=None (l.52).

#### F103 — scan_budget_overruns : les AInsight de dépassement budgétaire ne sont jamais créés
*Bug · Réunions / chat / Celery (initialement high)* — [project/tasks.py:395](project/tasks.py:395)

- **Preuve** : dm.AInsight.objects.create(..., description=(...), recommendation=..., score=...) (l.395-416). AInsight n'a pas de champ `description` : le champ obligatoire est `summary` (models.py l.1654). Vérifié : `AInsight(description='x')` lève TypeError, capturé l.418-420 (stats['errors'] += 1 chaque jour).
- **Impact** : L'alerte budgétaire IA (type RISK) n'apparaît jamais dans les insights ni dans « Mes actions du jour ». Seule la notification in-app est créée. Le job signale des erreurs quotidiennes que personne ne voit.
- **Correctif** : Renommer `description=` en `summary=`. Ajouter un test unitaire du sweep qui vérifie la création de l'AInsight.
- **Relecture** : AInsight (models.py:1630+) n'a pas de champ description, le champ obligatoire est summary (l.1654). AInsight.objects.create(description=…) à tasks.py:395 lève donc une TypeError, capturée l.418-420. Sévérité abaissée : la Notification de dépassement (étape 1) est bien créée.

#### F105 — Enregistrements bloqués ou faussement « terminés » selon le chemin d'erreur
*Intégrité des données · Réunions / chat / Celery* — [project/views_recording.py:362](project/views_recording.py:362)

- **Preuve** : api_upload_recording met le statut à UPLOADING (l.362-363). Si le stockage échoue (l.377-383), il renvoie 502 sans remettre le statut, et le JS ne récupère pas recording_id en cas d'erreur (recorder_widget.html l.683-690) : chaque retry crée un nouvel enregistrement orphelin. Si `.delay` échoue (l.386-390), le statut reste UPLOADED sans fallback. RecordingRegenerateSummaryView autorise FAILED (l.447-451) mais appelle finalize_recording : si l'échec venait de la transcription, le transcript est vide, generate_summary renvoie '' et le statut passe à COMPLETED (pipeline.py l.82-108). Un ré-upload avec recording_id ajoute de nouveaux SpeakerSegment sans purger les anciens (transcription.py l.150).
- **Impact** : Des enregistrements restent indéfiniment « Upload en cours » ou « Audio reçu ». Un échec de transcription est maquillé en compte-rendu vide « Terminé » avec notification. Les transcripts peuvent mélanger deux fichiers audio.
- **Correctif** : Passer en FAILED avec error_message dans le except du stockage et du dispatch Celery. Ajouter une action « Relancer la transcription » (process_recording_task) pour FAILED/UPLOADED. N'autoriser regenerate que si des segments existent. Au début de process_recording, supprimer segments, speakers et extractions existants.
- **Relecture** : Le statut UPLOADING (views_recording.py:362) n'est jamais réinitialisé en cas d'erreur de stockage. La réponse 502 contient recording_id, mais le JS (recorder_widget.html:683-690) ne le lit qu'en 2xx. Un échec de .delay laisse UPLOADED. finalize_recording passe à COMPLETED même avec un transcript vide (pipeline.py:82-108), et aucun delete() des SpeakerSegment n'est fait avant le bulk_create.

#### F106 — Rapports IA hebdomadaires : tous les projets de tous les tenants traités dans une seule tâche limitée à 360 s
*Performance · Réunions / chat / Celery* — [project/tasks.py:476](project/tasks.py:476)

- **Preuve** : generate_project_weekly_reports parcourt séquentiellement tous les projets actifs de la plateforme (l.476-535) avec un appel IA par projet (use_ai=True). La tâche n'a pas de time_limit propre, donc la limite globale de 300/360 s s'applique (base.py l.293-294). Le commentaire des settings estime une tâche IA à 20-40 s.
- **Impact** : Au-delà d'environ 8 à 15 projets, le worker est tué à 360 s et les projets suivants n'ont jamais leur rapport. Comme l'ordre est le même chaque lundi, ce sont toujours les mêmes projets qui sont privés de rapport.
- **Correctif** : Transformer la tâche en fan-out : un sweep qui enqueue `generate_project_weekly_report_task.delay(project_id)` par projet, avec un time_limit adapté. Appliquer le même schéma à send_daily_notification_digest et scan_budget_overruns.
- **Relecture** : tasks.py:458-535 : @shared_task sans time_limit, alors que la tâche boucle séquentiellement sur tous les projets actifs de tous les tenants avec use_ai=True. Les limites globales de 300 et 360 s s'appliquent (base.py:293-294) : SoftTimeLimitExceeded est compté comme une erreur, puis le hard kill coupe les projets restants.

#### F107 — Envois d'email synchrones dans le cycle HTTP, en violation de la convention n°6
*Performance · Réunions / chat / Celery* — [project/services/task_reminder.py:380](project/services/task_reminder.py:380)

- **Preuve** : TaskUpdateNotifier.notify_pm fait `send_mail(...)` (l.380) et est appelé depuis le signal post_save de Task (signals.py l.315-331), donc à chaque changement de statut ou d'assignee depuis le kanban ou un formulaire. Le signal passe actor=None, si bien que le test `pm == actor` (l.336) n'est jamais vrai et que le PM est notifié de ses propres modifications. RecordingSendEmailView appelle send_recording_email en synchrone (views_recording.py l.723), soit une génération .docx puis un envoi SMTP par destinataire (export.py l.380-400). Aucun EMAIL_TIMEOUT n'est configuré (base.py l.526).
- **Impact** : Les requêtes HTTP (drag & drop kanban, envoi de compte-rendu) sont bloquées sur SMTP, potentiellement sans limite de temps. Le PM reçoit du spam pour ses propres actions.
- **Correctif** : Passer par des tâches Celery (`send_pm_task_update_email_task.delay`, `send_recording_minutes_email_task.delay`). Transmettre l'acteur réel (via instance._actor ou un middleware thread-local). Définir EMAIL_TIMEOUT.
- **Relecture** : notify_pm_on_task_change appelle TaskUpdateNotifier.notify_pm(instance, before, actor=None) à chaque post_save de Task (signals.py:315-331). notify_pm fait un send_mail synchrone (task_reminder.py:380), et comme actor=None, `pm == actor` n'est jamais vrai. Aucun EMAIL_TIMEOUT n'est défini (base.py:526).

#### F108 — Registre des décisions (MeetingDecision) jamais alimenté ; décisions et risques IA non convertis
*Fonctionnalité manquante · Réunions / chat / Celery* — [project/views_recording.py:302](project/views_recording.py:302)

- **Preuve** : Aucune création de MeetingDecision dans le code : seules des lectures existent (views_meeting.py l.689-697 et l.805), et le modèle n'est pas exposé dans admin.py. CreateDecisionsView (l.302-320) se contente de `update(is_accepted=True)`, avec un commentaire « pas de modèle Decision dédié ». Les risques extraits ne sont qu'affichés (recording_summary.html l.260-266). CreateActionPlansView (l.282-287) ignore assignee_hint et due_date_hint. Les suggestions sprint/jalon sont seulement marquées acceptées (views_meeting.py l.933-940).
- **Impact** : La page « Registre des décisions » et le « taux d'exécution des décisions » du tableau de bord sont toujours vides ou à 0 %. Le flux réunion → décisions/risques/actions s'arrête à mi-chemin.
- **Correctif** : Dans CreateDecisionsView, créer un MeetingDecision (workspace, meeting, projects=meeting.projects, decided_by) par extraction acceptée et ajouter une FK source_extraction. Ajouter « Convertir en risque » (Risk/AInsight). Résoudre owner et due_date dans CreateActionPlansView. Ajouter une vue d'édition du statut EXECUTED.
- **Relecture** : Le grep ne trouve aucune création de MeetingDecision, seulement des lectures (views_meeting.py:689, 805). CreateDecisionsView (views_recording.py:302-320) se limite à update(is_accepted=True), et la création d'actions ignore assignee_hint et due_date_hint.

#### F109 — Séries de réunions : occurrences supprimées recréées chaque nuit, doublons après modification de l'heure
*Bug · Réunions / chat / Celery* — [project/services/meeting.py:158](project/services/meeting.py:158)

- **Preuve** : L'idempotence de generate_occurrences repose sur la seule existence d'un ProjectMeeting(series, scheduled_at) (l.158-163). ProjectMeetingDeleteView (DevflowDeleteView, Django DeleteView) supprime physiquement l'occurrence, que le sweep de 4h recrée (tasks.py l.698-707). MeetingSeriesUpdateView (views_meeting.py l.466-475) ne nettoie pas les occurrences futures : si time_local, weekday ou recurrence change, les anciennes restent et de nouvelles sont créées à côté.
- **Impact** : Les réunions annulées par suppression réapparaissent le lendemain. Le calendrier contient des réunions en double après chaque modification d'une série, avec des rappels emails envoyés en double.
- **Correctif** : Supprimer par soft-delete (archive) ou passer en CANCELLED plutôt que supprimer, et faire en sorte que generate_occurrences ignore les dates archivées. Dans MeetingSeriesUpdateView.form_valid, supprimer les occurrences futures PLANNED non modifiées puis régénérer.
- **Relecture** : services/meeting.py:158-163 : l'idempotence repose uniquement sur (series, scheduled_at). ProjectMeetingDeleteView (views_meeting.py:272) supprime physiquement l'occurrence, et le sweep (tasks.py:698-707) la recrée. MeetingSeriesUpdateView (466-475) ne purge pas les occurrences futures, d'où des doublons si l'heure ou le jour change.

#### F110 — Occurrences de série sans MeetingParticipation : présence et émargement inopérants
*Bug · Réunions / chat / Celery* — [project/services/meeting.py:179](project/services/meeting.py:179)

- **Preuve** : generate_occurrences fait `occ.internal_participants.set(...)` (l.179-181) sans créer de MeetingParticipation, alors que ProjectMeetingForm._sync_participations le fait (forms_meeting.py l.156-172). MeetingSelfPresentView répond « Vous n'êtes pas invité » si la ligne n'existe pas (views_meeting.py l.1071-1078). MeetingMarkAttendanceView n'itère que sur meeting.participations (l.1290-1306). La fiche détail calcule ses stats à partir de participations (l.142-169).
- **Impact** : Sur toutes les réunions récurrentes, la confirmation de présence et le marquage par l'organisateur ne fonctionnent pas, et les statistiques RSVP/présence restent à 0.
- **Correctif** : Extraire _sync_participations dans MeetingService et l'appeler dans generate_occurrences. Ajouter une migration de données pour les occurrences existantes. Ajouter l'auto-création dans MeetingSelfPresentView comme dans MeetingRSVPView.
- **Relecture** : generate_occurrences ne fait que internal_participants.set() (meeting.py:179-181), sans MeetingParticipation, contrairement à _sync_participations (forms_meeting.py:156-172). MeetingSelfPresentView refuse alors l'utilisateur (views_meeting.py:1071-1078). Seule MeetingRSVPView auto-crée la ligne (1035-1039), ce qui ne corrige que le cas où l'utilisateur répond d'abord au RSVP.

#### F111 — Conversion action → tâche impossible pour les réunions multi-projets
*Bug · Réunions / chat / Celery* — [project/views_meeting.py:324](project/views_meeting.py:324)

- **Preuve** : MeetingActionItemConvertToTaskView crée `Task(project=meeting.project, ...)` (l.324-336). Or ProjectMeeting.project est nullable (comités multi-projets, models.py l.3135-3139) alors que Task.project est NOT NULL (l.1345). Il en résulte une IntegrityError, affichée telle quelle via « Conversion impossible : NOT NULL constraint… » (l.337-340). La vue des suggestions, elle, utilise `meeting.projects.first()` en repli (l.868-870).
- **Impact** : Le bouton « Convertir en tâche » échoue systématiquement sur les réunions de type comité, et l'erreur SQL brute est exposée à l'utilisateur.
- **Correctif** : Utiliser le repli `meeting.project or meeting.projects.first()` ou proposer un choix de projet dans l'UI. Renvoyer un message clair si aucun projet n'est rattaché. Ne pas afficher l'exception.
- **Relecture** : views_meeting.py:324-336 crée Task(project=meeting.project), alors que ProjectMeeting.project est nullable (models.py:3135-3139). Nuance : Task.save→full_clean lève une ValidationError plutôt qu'une IntegrityError, mais la conversion échoue quand même avec le message brut (l.337-340).

#### F112 — Traitements IA de réunion non idempotents : actions, risques et extractions dupliqués à chaque relance
*Intégrité des données · Réunions / chat / Celery* — [project/services/ai/services/meeting_intelligence.py:230](project/services/ai/services/meeting_intelligence.py:230)

- **Preuve** : full_process recrée à chaque appel tous les MeetingActionItem (l.230-237) et les AInsight RISK (l.252-260), sans purge ni déduplication. Il est appelé à chaque POST sur MeetingAIProcessView (views_meeting.py l.370), sans throttle. ConfirmSpeakersView relance finalize_recording (views_recording.py l.172-174), et generate_extractions crée de nouvelles RecordingAIExtraction (ai_summary.py l.144-172) sans supprimer les précédentes non acceptées (seul RegenerateSummary le fait, l.456).
- **Impact** : Chaque clic sur « Traitement IA » duplique les actions et les risques de la réunion et pollue les insights et « Mes actions du jour ». Le coût IA est payé à chaque clic.
- **Correctif** : Avant persistance, supprimer les items générés par l'IA et non convertis (ajouter un flag source='ai'), ou dédupliquer par titre normalisé. Purger les extractions non acceptées dans finalize_recording. Ajouter un rate-limit sur la vue.
- **Relecture** : meeting_intelligence.py:217-260 : MeetingActionItem et AInsight RISK sont créés à chaque appel, sans purge (aucun delete() dans le fichier). MeetingAIProcessView (views_meeting.py:370) n'a pas de throttle. generate_extractions (ai_summary.py:106-172) recrée les extractions, et seule RegenerateSummary purge les non acceptées (views_recording.py:456).

#### F113 — Bulle de chat : WS sur un autre groupe que la page canal, messages REST non diffusés, indicateur de frappe inopérant
*Bug · Réunions / chat / Celery* — [project/api/views_chat.py:211](project/api/views_chat.py:211)

- **Preuve** : La bulle poste via REST (chat_pannel.html l.475) et écoute ws/chat/<id> (groupe `chat_<id>`, consumers.py l.267). La page canal écoute ws/channels/<id> (groupe `chat_channel_<id>`, l.17). ChatChannelMessagesView.post (l.211-220) n'appelle pas group_send et ne crée pas de Notification, contrairement à ChannelChatConsumer.create_message (l.236-248). ChatConsumer n'a pas de handler typing : les `typing.start` envoyés par la bulle (chat_pannel.html l.603) sont ignorés car le corps est vide.
- **Impact** : Pas de temps réel entre la bulle et la page canal (polling de 6 s seulement), indicateur « en train d'écrire » mort dans la bulle, et notifications de message créées ou non selon l'interface utilisée.
- **Correctif** : Unifier sur un seul consumer et un seul groupe. Dans ChatService.post_message, faire `async_to_sync(channel_layer.group_send)('chat_channel_<id>', ...)` et créer les notifications, pour que REST et WS se comportent de la même façon.
- **Relecture** : La bulle poste via REST et ouvre ws/chat/<id> (chat_pannel.html:475, 527), groupe `chat_<id>`. La page canal utilise `chat_channel_<id>` (consumers.py:17). ChatService.post_message (services/chat.py:290-310) ne fait ni group_send ni Notification, et ChatConsumer n'a pas de handler typing. Plus grave : ChatConsumer (consumers.py:265-311) accepte toute connexion et crée des messages dans n'importe quel canal, sans vérifier workspace ni membership.

#### F114 — DM et groupes créés dans le workspace par défaut de l'appelant, parfois invisibles pour le destinataire
*Bug · Réunions / chat / Celery* — [project/api/views_chat.py:74](project/api/views_chat.py:74)

- **Preuve** : ChatDirectCreateView vérifie que l'autre utilisateur partage n'importe lequel des workspaces de l'appelant (l.81-93), mais crée le canal dans `_resolve_workspace(request)`, c'est-à-dire le workspace par défaut du profil (l.74, l.101-103). ChatGroupCreateView fait de même (l.131-157). channels_qs_for filtre ensuite `workspace_id__in` les workspaces de chaque utilisateur (services/chat.py l.173-177), et ChannelChatConsumer refuse aussi l'accès (consumers.py l.186).
- **Impact** : Pour les utilisateurs multi-workspaces, le destinataire ne voit jamais le DM ou le groupe et ne reçoit pas les messages, alors que l'émetteur croit l'échange établi.
- **Correctif** : Choisir un workspace commun aux deux (ou à tous les membres), ou vérifier `other.pk in users_in_workspaces([workspace.pk])` avant de créer le canal et renvoyer 400 sinon.
- **Relecture** : views_chat.py:74 et 131 créent le canal dans _resolve_workspace, c'est-à-dire get_default_workspace_for_user (owned en priorité), et non dans un workspace partagé avec la cible. channels_qs_for filtre workspace_id__in les workspaces de chaque utilisateur (chat.py:173-177).

#### F115 — Compteurs non lus : N+1 interrogé toutes les 15 s, valeurs incohérentes
*Performance · Réunions / chat / Celery* — [project/services/chat.py:439](project/services/chat.py:439)

- **Preuve** : unread_counts_for exécute 2 requêtes par canal (membership puis count, l.439-449), appelé toutes les 15 s par onglet (_chat_runtime.html l.11, l.257). _channel_to_dict exécute 3 requêtes par canal (last_msg, membership, count, l.79-105) pour jusqu'à 100 canaux (l.190). Pour un canal public sans membership, tout l'historique des autres compte comme non lu (l.101-105). Le badge cloche (context_processors.py l.11-19) compte les notifications de tous les workspaces, alors que Mes actions du jour filtre par workspace (my_day.py l.230-234).
- **Impact** : Charge DB proportionnelle au nombre de canaux et d'onglets ouverts. Badges gonflés ou contradictoires entre la cloche, Mes actions du jour et la bulle de chat.
- **Correctif** : Calculer les non-lus en une seule requête annotée (Subquery sur last_read_at plus Count filtré). Ignorer les canaux publics non rejoints, ou partir de joined_at. Aligner le context processor sur le filtre par workspace.
- **Relecture** : services/chat.py:439-449 : 2 requêtes par canal, interrogées toutes les 15 s (_chat_runtime.html:11 et 257). _channel_to_dict (l.79-105) fait 3 requêtes par canal, sur jusqu'à 100 canaux (l.190). Un canal public sans membership compte tout l'historique comme non lu. context_processors.py:11-19 ne filtre pas par workspace, contrairement à my_day.py:230-232.

#### F116 — Relances de tâches : arbitrage PM des retards jamais planifié, couverture des statuts incohérente
*Fonctionnalité manquante · Réunions / chat / Celery* — [project/services/task_overdue.py:132](project/services/task_overdue.py:132)

- **Preuve** : scan_overdue_tasks (l.132) n'est appelé que par la commande notify_overdue_tasks. Il n'existe ni tâche Celery ni entrée dans CELERY_BEAT_SCHEDULE (base.py l.195-250), ni cron dans docker-compose. TaskReminderService et task_overdue limitent les relances aux projets PLANNED/IN_PROGRESS (task_reminder.py l.59-62, task_overdue.py l.23-26), ce qui exclut DELAYED, BLOCKED et IN_DELIVERY. Le reminder ne traite que DONE et CANCELLED comme terminaux (l.133), donc une tâche EXPIRED reçoit chaque jour une relance OVERDUE.
- **Impact** : Le flux « Reconduire / Maintenir expirée » ne se déclenche jamais en production. Les projets en retard, justement ceux qui en ont le plus besoin, ne reçoivent aucune relance. Les tâches déjà arbitrées « expirées » continuent d'être relancées.
- **Correctif** : Ajouter `scan_overdue_tasks_task` et une entrée beat quotidienne. Inclure DELAYED, BLOCKED et IN_DELIVERY dans les statuts actifs. Ajouter EXPIRED aux statuts terminaux du reminder.
- **Relecture** : scan_overdue_tasks n'est appelé que par la commande notify_overdue_tasks, que ni CELERY_BEAT_SCHEDULE, ni compose, ni deploy ne planifient (grep). Les statuts actifs se limitent à PLANNED/IN_PROGRESS (task_overdue.py:23-26, task_reminder.py:59-62), et le reminder ne considère comme terminaux que DONE et CANCELLED (l.133) : une tâche EXPIRED reçoit donc toujours des relances.

#### F117 — Préférences de notification non appliquées : dispatcher jamais appelé, mode HOURLY sans beat, pas d'UI
*Fonctionnalité manquante · Réunions / chat / Celery* — [project/services/smart_notifications.py:49](project/services/smart_notifications.py:49)

- **Preuve** : SmartNotificationDispatcher.should_send_email_now (l.62-95) n'est appelé nulle part en dehors du module. send_daily_notification_digest saute HOURLY en affirmant qu'il « a un autre beat » (tasks.py l.598-602), mais aucun beat HOURLY n'existe (base.py l.195-250). Il n'y a ni vue, ni formulaire, ni endpoint pour NotificationPreference (le grep ne trouve que models.py et tasks.py). Les emails d'assignation, les relances et les rappels de réunion ignorent channel_email, DISABLED et les heures de calme.
- **Impact** : Un utilisateur ne peut pas régler ses notifications. HOURLY ne produit aucun email. Les emails partent à toute heure (le sweep de rappels de réunion tourne toutes les heures), y compris pour les utilisateurs qui ont tout désactivé.
- **Correctif** : Brancher le dispatcher (post_save Notification vers une tâche email), filtrer les envois Celery existants avec NotificationPreferenceService, ajouter un beat horaire pour le digest HOURLY et exposer une page de préférences.
- **Relecture** : should_send_email_now n'est appelé que dans tests_smart_notifications.py. Le beat (base.py:220) ne contient que le digest quotidien, sans tâche HOURLY, alors que tasks.py:598-602 affirme le contraire. Aucune vue, formulaire ni API pour NotificationPreference.

#### F118 — SITE_URL non défini : liens relatifs, donc inutilisables, dans tous les emails asynchrones
*UX · Réunions / chat / Celery* — [project/services/recording/pipeline.py:167](project/services/recording/pipeline.py:167)

- **Preuve** : SITE_URL et DEVFLOW_BASE_URL n'existent ni dans settings ni dans .env. pipeline._send_recording_email retombe sur target_url relatif (l.167-170). TaskReminderService._task_url renvoie reverse(), un chemin relatif (task_reminder.py l.296-298), utilisé dans href (emails/task_reminder.html l.40). Le lien de emails/task_assigned.html (l.47) est codé en dur `href="/tasks/{{ task.pk }}/"`. Les liens « Reconduire/Expirer » (task_overdue.py l.47-51) et le digest (smart_notifications.py l.242) sont aussi relatifs quand il n'y a pas de requête.
- **Impact** : Les boutons d'action des emails (relances, assignation, compte-rendu prêt, arbitrage PM) ne mènent nulle part dans les clients mail.
- **Correctif** : Définir SITE_URL dans settings (via env, obligatoire en prod) et construire toutes les URLs d'email avec un helper `absolute_url(path)`, y compris dans les templates.
- **Relecture** : SITE_URL et DEVFLOW_BASE_URL sont absents des settings et du .env (grep). pipeline.py:167-170 retombe sur target_url relatif, et task_reminder.py:296-299 renvoie reverse() (relatif), utilisé dans le href de task_reminder.html:40. task_assigned.html:47 code en dur /tasks/{{ task.pk }}/, et task_overdue.py:50 et smart_notifications.py:249 utilisent SITE_URL vide.

#### F119 — Présence et throttles sur un cache LocMem par processus alors que gunicorn tourne avec 3 workers
*Bug · Réunions / chat / Celery* — [project/services/presence.py:31](project/services/presence.py:31)

- **Preuve** : PresenceService stocke last_seen dans `django.core.cache` (l.31, l.95). Le commentaire parle de « Redis en prod », mais aucun CACHES n'est défini dans ProjectFlow/settings/*, donc c'est le LocMemCache par défaut, propre à chaque processus. docker-compose lance `gunicorn ... --workers 3`. Les throttles DRF (AIActionRateThrottle) utilisent le même cache.
- **Impact** : Le heartbeat est stocké dans un worker et la lecture se fait souvent dans un autre : les contacts apparaissent hors ligne de façon aléatoire. Le rate-limit IA est multiplié par le nombre de workers.
- **Correctif** : Configurer CACHES avec django_redis ou RedisCache sur le Redis déjà présent (db séparée).
- **Relecture** : Aucun CACHES n'est défini dans ProjectFlow/settings ni dans project (grep), donc le cache est le LocMemCache par défaut. PresenceService utilise django.core.cache (presence.py:31), et gunicorn tourne avec --workers 3 (docker-compose.yml) : présence et throttles IA sont propres à chaque processus.

#### F128 — Liste des projets : P&L et temps estimé faux (champs inexistants)
*Intégrité des données · Templates / routage / vues (initialement high)* — [project/views.py:1592](project/views.py:1592)

- **Preuve** : PROJECT_FINANCE_FIELDS cherche billed dans ("billed_amount", "invoiced_amount", …) et cost dans ("cost_amount", "actual_cost", "internal_cost", "cost_total") (1595). Le modèle Project n'a aucun de ces champs, seulement `budget`, `computed_eac` et `computed_cost_variance`, donc cost vaut toujours 0. Si la catégorie est facturable, `billed = budget` (1695) puis `pnl = billed - cost` (1697), donc P&L = budget. TASK_TIME_FIELDS cherche "estimated_hours" alors que Task a `estimate_hours` (models Task l.29), donc le temps estimé vaut toujours 0. Ces valeurs alimentent section.summary.pnl et estimated_time (project/list.html:247, 273).
- **Impact** : La liste des projets montre un bénéfice égal au budget, sans aucun coût réel (TJM, dépenses), et un temps estimé nul : indicateurs financiers trompeurs pour le pilotage.
- **Correctif** : Calculer coût et revenu à partir des sources réelles : coût timesheet (cost_snapshot.computed_cost), ProjectExpense payées et engagées, ProjectRevenue et Invoice, ou ProjectBudget et computed_eac. Utiliser `estimate_hours`. Supprimer les heuristiques getattr sur des noms supposés.
- **Relecture** : Project (models.py:361-500) n'a que budget, computed_eac et computed_cost_variance : cost vaut 0 et billed=budget pour une catégorie facturable (views.py:1692-1697). Task a estimate_hours, pas estimated_hours (TASK_TIME_FIELDS l.1589), donc le temps estimé vaut 0. Sévérité abaissée : valeurs affichées seulement, rien n'est persisté.

#### F132 — Kanban des tâches : colonnes custom ignorées, EXPIRED invisible, workflow contourné, filtres vides
*Bug · Templates / routage / vues* — [templates/project/task/list.html:177](templates/project/task/list.html:177)

- **Preuve** : Le board itère `columns`, une liste codée en dur (views.py:4760) qui contient CANCELLED mais pas EXPIRED. Les `kanban_columns` et `board_columns` calculés (4672-4703) ne sont jamais utilisés. Le drop poste sur `/tasks/${taskId}/move/` (l.563) vers TaskKanbanMoveView (views.py:4516), qui ne passe pas par WorkflowEngine (seul task_status_update l'utilise, 4060), envoie toujours position=0 et ne remet pas completed_at à zéro. Les filtres Statut et Priorité bouclent sur `model.Status.choices` (l.121, 128), mais `model` n'est pas dans le contexte, donc les listes sont vides.
- **Impact** : Les tâches expirées n'apparaissent pas dans le Kanban. Les transitions et rôles des méthodologies sont contournés par simple glisser-déposer. L'ordre des cartes est perdu et les filtres statut et priorité sont inutilisables.
- **Correctif** : Rendre `kanban_columns` (colonnes BoardColumn du projet ou colonnes par défaut incluant EXPIRED). Faire passer TaskKanbanMoveView par WorkflowEngine.can_transition et apply_transition. Envoyer la vraie position. Exposer `status_choices` et `priority_choices` dans le contexte.
- **Relecture** : ctx['columns'] est codé en dur (views.py:4760+) : CANCELLED y figure, EXPIRED non. kanban_columns et board_columns ne sont pas utilisés par task/list.html. TaskKanbanMoveView (4516-4555) ne passe pas par WorkflowEngine, reçoit position=0 depuis le JS (l.559) et ne remet jamais completed_at à None. `model` est absent du contexte, donc les filtres statut et priorité sont vides (l.121, 128).

#### F133 — Board Kanban du projet vide (partial stub) et espace Kanban méthodologie en lecture seule
*Fonctionnalité manquante · Templates / routage / vues* — [templates/project/partials/_taches.html:125](templates/project/partials/_taches.html:125)

- **Preuve** : Si le projet a des BoardColumn, l'onglet Tâches inclut `{% include "partials/_kanban_board.html" %}`, qui est un stub de 123 octets contenant un document HTML vide complet (`<!DOCTYPE html><html>…<title>Title</title>`). Le vrai partial se trouve dans templates/devflow/partials/_kanban_board.html. methodology/kanban_workspace.html n'a ni drag-and-drop, ni formulaire, ni JS : les cartes sont de simples liens. ProjectKanbanWorkspaceView (views_methodology.py:148) inclut aussi les tâches archivées (`project.tasks.filter(status=...)` sans is_archived=False).
- **Impact** : La section « Board Kanban » de la fiche projet est vide et injecte un <html> imbriqué. Le Kanban méthodologie affiche les limites WIP mais ne permet pas de déplacer les cartes.
- **Correctif** : Inclure le Kanban réel (même composant que task/list.html, alimenté par project.board_columns) et ajouter le drag-and-drop branché sur task_status_update dans kanban_workspace.html. Filtrer is_archived=False. Supprimer les 34 stubs de 123 octets (templates/partials, sprint, task, team, objective, settings, message, dashboard).
- **Relecture** : _taches.html:117-125 inclut partials/_kanban_board.html, résolu vers templates/partials/_kanban_board.html (123 octets, document HTML vide). Le vrai partial se trouve dans templates/devflow/partials/. kanban_workspace.html ne contient ni form, ni script, ni draggable. views_methodology.py:148 ne filtre pas is_archived.

#### F134 — Variables de contexte manquantes : KPI des objectifs toujours à 0, membres du workspace toujours vides
*Bug · Templates / routage / vues* — [project/views.py:8419](project/views.py:8419)

- **Preuve** : ObjectiveListView (8419) ne fournit pas `stats`, utilisé par objective/list.html:36-64 (total, company, on_track, at_risk…). ObjectiveDetailView (8427) ne fournit que key_results, alors que objective/detail.html utilise `is_overdue` (l.26) et `kr_stats.total` / `avg_progress` (l.68-72). WorkspaceDetailView fournit `members` et annote `members_count` (1356-1366), alors que workspace/detail.html utilise `memberships` (l.169) et `object.memberships_count` (l.58).
- **Impact** : Les huit compteurs OKR affichent toujours 0, le badge « en retard » et les stats KR ne s'affichent jamais, et la fiche workspace indique « Aucun membre trouvé ».
- **Correctif** : Ajouter à ObjectiveListView un aggregate stats (sur le queryset complet), à ObjectiveDetailView is_overdue et kr_stats (Count, Avg progress). Aligner les noms entre WorkspaceDetailView et son template (memberships = workspace.memberships.select_related('user','team')[:10], annotate memberships_count).
- **Relecture** : ObjectiveListView (views.py:8419) ne définit pas get_context_data, alors que list.html:36-64 lit stats.*. ObjectiveDetailView ne fournit que key_results, alors que detail.html utilise is_overdue (l.26) et kr_stats (l.68). WorkspaceDetailView annote members_count et fournit `members`, alors que le template lit object.memberships_count (l.58) et `memberships` (l.169).

#### F135 — Fiches équipe et tâche incomplètes (données calculées non affichées, aucune action)
*Fonctionnalité manquante · Templates / routage / vues* — [templates/project/team/detail.html:9](templates/project/team/detail.html:9)

- **Preuve** : team/detail.html (60 lignes) est un gabarit générique : id, name, status, created_at. TeamDetailView calcule memberships, projects et sprints (views.py:1453-1456), qui ne sont jamais rendus, et la page n'offre ni bouton modifier, supprimer, ajouter un membre ou archiver. task/detail.html n'a pas de formulaire d'ajout de commentaire, d'upload de pièce jointe, de changement de statut ni de suppression : seuls task_extend et task_mark_expired sont branchés (l.77, 158, 162). Les pièces jointes ne sont affichées que par leur nombre (l.116).
- **Impact** : Pas de gestion d'équipe depuis sa fiche. Sur une tâche, impossible de commenter, joindre un fichier ou changer le statut sans repasser par le Kanban ou les écrans CRUD techniques.
- **Correctif** : Construire une vraie fiche équipe (membres et rôles, charge, projets, sprints, actions) et ajouter à la fiche tâche les formulaires commentaire et pièce jointe (task_quick_comment / task_quick_attachment avec next), le sélecteur de statut et les checklists cochables.
- **Relecture** : team/detail.html (60 lignes) n'affiche que pk, name, status et dates, sans action, alors que memberships, projects et sprints sont calculés (views.py:1454-1456). task/detail.html n'a pas de formulaire de commentaire ou d'upload, et les pièces jointes n'apparaissent que par leur nombre (l.116). Nuance : un lien task_update existe (l.82), ce qui permet de changer le statut via le formulaire d'édition.

#### F136 — « Archiver » le projet renvoie 405 ; archivage sans interface ailleurs et sans restauration
*Bug · Templates / routage / vues* — [templates/project/partials/_hero_header.html:325](templates/project/partials/_hero_header.html:325)

- **Preuve** : `<a href="{% url 'project_archive' project_obj.pk %}">Archiver</a>` fait un GET, alors qu'ArchiveObjectView ne définit que post() (views.py:500), d'où une erreur 405 Method Not Allowed. Les routes sprint_archive, milestone_archive, objective_archive, roadmap_archive, team_archive, risk_archive, release_archive, backlog_item_archive, task_archive et workspace_archive ne sont référencées par aucun template. Aucune vue ne permet de désarchiver. ArchiveObjectView fait `.get(pk=pk)`, ce qui renvoie une 500 au lieu d'une 404.
- **Impact** : L'action Archiver du menu projet ne fonctionne pas, les autres archivages sont inaccessibles depuis l'UI et un objet archivé disparaît sans moyen de le restaurer.
- **Correctif** : Remplacer le lien par un <form method=post> avec CSRF et confirmation. Ajouter les boutons d'archivage sur les fiches. Utiliser get_object_or_404. Ajouter une vue « Archivés » avec une action de restauration.
- **Relecture** : _hero_header.html:325 utilise un lien GET vers project_archive, alors qu'ArchiveObjectView (views.py:496-505) ne définit que post(), d'où une 405. Les autres routes *_archive ne sont référencées par aucun template (grep : 0), il n'existe aucune vue de désarchivage, et `.get(pk=pk)` renvoie une 500 au lieu d'une 404.

#### F137 — Factures du projet rendues dans le HTML pour les rôles sans droit finance
*Sécurité · Templates / routage / vues* — [templates/project/detail.html:188](templates/project/detail.html:188)

- **Preuve** : `{% include "project/partials/_facturation_client.html" %}` est placé hors du bloc `{% if can_view_financials %}` (152-164) et seulement masqué via x-show. ProjectDetailView remplit project_invoices et invoice_summary (total_ttc, total_paid, total_due) sans condition (views.py:3392-3420). Le partial les affiche (inv.total_ttc, inv.paid_amount, invoice_summary.*).
- **Impact** : Un membre sans droit financier retrouve montants et statuts de factures dans le code source de la page.
- **Correctif** : Inclure _facturation_client.html dans le bloc can_view_financials et ne calculer invoices et invoice_summary que si can_view_financials.
- **Relecture** : _facturation_client.html est inclus hors du bloc `{% if can_view_financials %}` (detail.html:152-164 puis 186-188), avec un simple x-show, et ne contient lui-même aucun garde de rôle. ProjectDetailView remplit project_invoices et invoice_summary sans condition (views.py:3392-3420).

#### F138 — ProjectDetailView : préchargements massifs inutilisés, requêtes en double
*Performance · Templates / routage / vues* — [project/views.py:2704](project/views.py:2704)

- **Preuve** : get_queryset précharge `tasks` avec 10 sous-prefetch (labels, assignments, checklists__items, attachments, comments__author, dépendances, releases, milestones), ainsi que sprints, backlog, milestones, releases et risks (2425-2499). get_context_data refait ensuite `project.tasks.filter(is_archived=False)`, `project.sprints.filter(...)`, `backlog_items.filter`, `milestones.filter`, `releases.filter` et `risks.filter` (2704-2710). Un .filter() ignore le cache de prefetch : tout est rechargé, et les commentaires et pièces jointes de toutes les tâches sont chargés pour rien.
- **Impact** : Sur un projet de quelques centaines de tâches, la fiche projet (écran principal) charge des milliers de lignes inutiles en plus des requêtes réelles : temps de réponse et mémoire dégradés.
- **Correctif** : Soit supprimer ces Prefetch et garder des querysets ciblés et paginés par onglet (idéalement chargés en htmx), soit utiliser Prefetch(..., queryset=filtre, to_attr=...) et réutiliser les listes préchargées sans .filter().
- **Relecture** : get_queryset précharge tasks avec checklists__items, attachments, comments__author, etc. (views.py:2425-2499). get_context_data refait ensuite project.tasks.filter(...), sprints.filter, etc. (2704-2710). Ces .filter() contournent le cache de prefetch, d'où des requêtes en double et des données chargées pour rien.

#### F139 — Tailwind Play CDN en production et deux systèmes de design concurrents
*UX · Templates / routage / vues* — [templates/layout/base.html:28](templates/layout/base.html:28)

- **Preuve** : `<script src="https://cdn.tailwindcss.com"></script>` compile les classes dans le navigateur à chaque page, ce que Tailwind déconseille en production. Alpine est chargé en `alpinejs@3.x.x`, version non figée (l.27). base.html contient environ 2 090 lignes de CSS inline (<style> l.88-2176). 116 templates utilisent les tokens `text-devtext1` / `bg-devbg2` (tailwind.config l.49) et 91 utilisent `text-[var(--text1)]` en valeurs arbitraires (un seul fichier mélange les deux), en plus des classes maison `.card`, `.badge b-*` et de styles inline.
- **Impact** : Flash de contenu non stylé, JS lourd sur chaque page, risque de rupture si le CDN ou Alpine évoluent, incompatibilité avec une CSP stricte. Les composants ne sont pas harmonisés et la maintenance est coûteuse.
- **Correctif** : Compiler Tailwind au build (tailwind CLI ou django-tailwind, avec un content scanning des templates) et servir le CSS via WhiteNoise. Figer les versions CDN avec SRI. Choisir un seul vocabulaire de tokens (dev*) et extraire les composants (card, badge, bouton) en partials ou classes @apply.
- **Relecture** : base.html:27-28 charge Alpine en alpinejs@3.x.x (version non figée) et cdn.tailwindcss.com (Play CDN). Un bloc <style> inline va de la l.88 à la l.2176. Je compte 114 templates avec les tokens devtext1/devbg2 et 87 avec text-[var(--text1)], des ordres de grandeur cohérents avec le constat.

### ⚪ Basse (4)

#### F26 — WebSocket sans validation d'origine, CORS et CSP installés mais inactifs
*Sécurité · Sécurité / multi-tenant* — [ProjectFlow/asgi.py:15](ProjectFlow/asgi.py:15)

- **Preuve** : `"websocket": AuthMiddlewareStack(URLRouter(...))` n'est pas enveloppé dans AllowedHostsOriginValidator. base.py:93-95 déclare "csp" et "corsheaders" dans INSTALLED_APPS, mais ni CSPMiddleware ni CorsMiddleware ne figurent dans MIDDLEWARE (100-110), et aucun réglage CSP ou CORS n'existe.
- **Impact** : Détournement cross-site de WebSocket possible si le cookie de session n'est pas SameSite (navigateurs anciens ou configuration modifiée). Pas de Content-Security-Policy, ce qui aggrave la XSS stockée via médias et TinyMCE.
- **Correctif** : Envelopper le routeur dans AllowedHostsOriginValidator, ajouter csp.middleware.CSPMiddleware avec une politique CONTENT_SECURITY_POLICY, et configurer ou retirer corsheaders.
- **Relecture** : asgi.py enveloppe le websocket dans AuthMiddlewareStack sans AllowedHostsOriginValidator. 'csp' et 'corsheaders' sont dans INSTALLED_APPS, mais aucun middleware CSP ou CORS n'est dans MIDDLEWARE (base.py:100-110) et aucun réglage CSP_ ou CORS_ n'existe. Le risque CSWSH est atténué par le cookie de session SameSite=Lax par défaut.

#### F48 — Approbation des feuilles de temps incohérente : approval_status jamais mis à jour par l'admin ni par le formulaire
*Bug · Modèles / formulaires / signaux (initialement medium)* — [project/admin.py:1578](project/admin.py:1578)

- **Preuve** : L'action admin approve_entries fait `queryset.update(approved_by=request.user, approved_at=timezone.now())` sans approval_status. TimesheetEntryForm expose approved_by et approved_at mais pas approval_status (forms.py:1559-1570). Le budget compte le coût approuvé via `approval_status=APPROVED` (budget.py:200).
- **Impact** : Des entrées « approuvées » dans l'admin ou le formulaire restent DRAFT : le coût approuvé et la facturation régie depuis les feuilles de temps approuvées les ignorent.
- **Correctif** : Dans l'action admin, mettre à jour approval_status=APPROVED. Retirer approved_by et approved_at du formulaire et centraliser l'approbation dans une méthode `TimesheetEntry.approve(user)`.
- **Relecture** : L'action admin (admin.py:1578-1580) et TimesheetEntryForm (forms.py:1559-1570) ne touchent pas approval_status. En revanche, le flux principal TimesheetWeekValidateView met bien à jour approval_status, approved_by et approved_at (views.py:6134-6151) : incohérence secondaire, d'où la sévérité low. Ce flux n'a par ailleurs aucun contrôle de rôle.

#### F96 — KPIs méthodologie approximatifs : cycle, lead time et throughput basés sur updated_at ; burndown faux en fin de sprint
*Bug · IA / méthodologies* — [project/services/methodology/kpis.py:193](project/services/methodology/kpis.py:193)

- **Preuve** : cycle_time filtre `status="DONE", updated_at__gte=cutoff` et calcule `(t.updated_at - t.created_at)` (l.201). throughput_weekly compte aussi par updated_at. lead_time renvoie `cycle_time(...)` (l.219). burndown fait `remaining = float(sprint.remaining_story_points or total_sp)` (l.93) : 0 SP restants s'affiche comme total. La série du burndown ne contient que la ligne idéale.
- **Impact** : Toute modification d'une tâche DONE (commentaire, renommage) la recompte dans le throughput de la semaine et gonfle le cycle time. Un sprint terminé apparaît non brûlé. Les dashboards Kanban et Scrum induisent en erreur.
- **Correctif** : Utiliser Task.completed_at (une fois persisté, cf. constat workflow) et un historique de statut pour le cycle time. Écrire `remaining = sprint.remaining_story_points if sprint.remaining_story_points is not None else total_sp`. Ajouter la série réelle depuis SprintMetric.
- **Relecture** : cycle_time (kpis.py:188-212) filtre et calcule sur updated_at - created_at, et lead_time renvoie cycle_time (l.219). burndown utilise `remaining_story_points or total_sp` (l.93), donc 0 SP restant s'affiche comme le total, et la série ne contient que la ligne idéale.

#### F140 — Routage et code mort : routes masquées, modules cassés, templates orphelins
*Bug · Templates / routage / vues* — [ProjectFlow/urls.py:185](ProjectFlow/urls.py:185)

- **Preuve** : `tasks/<int:pk>/move/` est déclaré deux fois (task_kanban_move en l.185, task_move en l.192) : TaskMoveView, par ailleurs non scopée (views.py:4976), est inatteignable et reverse('task_move') pointe vers la vue JSON. `channels/<int:pk>/` est également déclaré deux fois (channel_chat_page masque DirectChannelDetailView). project/filters.py importe `.registry`, absent du dépôt (ImportError à l'import). tables.py est vide. notification_views.py et ia_create_view.py ne sont importés nulle part. 44 templates sont orphelins, dont 34 stubs de 123 octets, lastdetails.html (1 500 lignes) et _legacy_chat_panel.html, qui appelle `/channels/panel/${id}/` et `/channels/${id}/send/`, deux routes inexistantes. DevflowDeleteView.delete() n'est jamais appelée sous Django 4.2 : pas de message de succès et DeleteViewCustomDeleteWarning. Plusieurs Update et Create ajoutent deux messages de succès (ex. TaskUpdateView 4957 + DevflowUpdateView 450).
- **Impact** : Confusion de maintenance, risque de réactiver du code non sécurisé, messages utilisateur absents ou dupliqués.
- **Correctif** : Supprimer les routes en double et les modules et templates morts. Déplacer le message de succès de delete() vers form_valid(). Ne garder qu'un seul messages.success par flux.
- **Relecture** : urls.py:186 (task_kanban_move) masque l.193 (task_move) sur tasks/<pk>/move/, et channels/<pk>/ est déclaré deux fois (l.251 et 257). filters.py importe .registry, absent du dépôt, tables.py est vide (0 octet), et notification_views et ia_create_view ne sont importés nulle part. _legacy_chat_panel.html n'est pas référencé et appelle des routes inexistantes. TaskUpdateView (4955) et DevflowUpdateView (449) ajoutent chacun un message de succès.

---

## 6. Constats écartés et zones non couvertes (transparence)

Chaque auditeur était plafonné à ~25 constats. Voici ce qu'ils ont vu mais écarté (faute de place ou de preuve suffisante), et les zones qu'ils n'ont pas pu lire en détail — **à traiter dans un second passage**.

### Sécurité / multi-tenant

Constats vus mais écartés faute de place ou de gravité, ou vérifiés seulement en partie :
- ChannelChatConsumer.create_message (consumers.py:222) : parent_id n'est pas restreint au canal, ce qui permet de rattacher un message à un parent d'un autre canal (low).
- Redirections ouvertes via POST `next` (views.py:4387, 4424, TaskQuickStatus/Comment) et via HTTP_REFERER (low).
- PresenceHeartbeatView définit throttle_scope sans ScopedRateThrottle ni DEFAULT_THROTTLE_RATES : aucun throttle effectif (low).
- api/views_chat.py:42 : `int(workspace_id)` sans try lève une erreur 500 si la valeur n'est pas numérique (low).
- HomeView(TemplateView, LoginRequiredMixin), views.py:79 : l'ordre MRO rend LoginRequiredMixin inopérant, mais la route est commentée (urls.py:87).
- get_default_workspace_for_user (utils/workspaces.py:38-42) renvoie le premier workspace de la plateforme à un utilisateur sans rattachement. Utilisé par context_processors.devflow_rbac (rôle affiché), AIChatStreamView (quota imputé à un tenant étranger) et TimesheetEntryViewSet. À corriger (renvoyer None).
- ProfileDetailView/ProfileUpdateView : `request.user.profile` lève une erreur 500 pour un compte allauth sans profil (create_user_profile ne crée rien quand il existe plus d'un workspace, signals.py:23-31).
- WorkspaceInvitationPublicAcceptView : le porteur du token peut rattacher un compte existant sans authentification (pas de connexion, faible).
- DevflowUpdateView ne passe ni current_workspace ni allowed_workspaces au formulaire (seul DevflowCreateView le fait) : les champs FK (workspace, project, user, approved_by du TimesheetEntryForm…) des formulaires d'édition ne sont pas scopés, ce qui permet de déplacer un objet vers un autre workspace par édition. Non détaillé formulaire par formulaire.
- ProjectDocumentImportCreateView appelle super().form_valid() après obj.save() : double sauvegarde et workspace potentiellement réécrit par get_current_workspace() (non vérifié en exécution).
- can_view_financials accepte en repli legacy TeamMembership.role TECH_LEAD, CTO… même quand RBAC refuse (incohérence avec la matrice).
- RBAC : DEFAULT_PERMISSIONS sur les viewsets Task, Sprint, Project et FieldReport permet à un CLIENT de lire et modifier toutes les données internes, contrairement à la matrice (« CLIENT : aucune donnée interne »). Couvert en partie par le constat API destroy.
Zones non lues ou lues partiellement : views_ai_genesis.py (contrôle ProjectGenesisAPIView non revérifié), views_ai_chat.py (seulement survolée, sessions scopées par user), views_meeting.py au-delà des lookups (globalement scopé), templates (XSS via |safe non audité), services/chat.py en détail, project/tasks.py, admin.py, la majorité des ~300 classes de views.py hors de celles citées (Integration, Webhook, ApiKey, WorkspaceSettings : le motif filter_by_workspace et les mixins s'y appliquent probablement, sans vérification ligne par ligne). Aucun test exécuté (mode lecture seule, graphe de migrations cassé déjà connu).

### Modèles / formulaires / signaux

Hors périmètre mais critique, à confier à l'audit des vues :
- **IDOR sur le chat.** project/channel_chat_views.py:13 (channel_chat_page) et :69 (channel_panel_detail) font `get_object_or_404(DirectChannel, pk=pk)` sans aucun contrôle de workspace ni d'appartenance. N'importe quel utilisateur connecté lit tous les messages de n'importe quel canal, y compris privé.
- **Repli sur un workspace étranger.** utils/workspaces.get_default_workspace_for_user renvoie « le premier workspace actif disponible » (y compris celui d'un autre tenant) si l'utilisateur n'a aucune appartenance. Ce helper est utilisé par api/views_chat.py:44, api/views_quick.py:312, views_chat.py et context_processors.py.
- **Import de document.** ProjectDocumentImportCreateView.get_project (views.py:~3783) n'est pas scopé, et ProjectDocumentImportForm retombe sur tous les projets quand workspace vaut None.
- **Crash méthodologies.** views_methodology_admin.py:128 : `ws_ids[0]` sur un set provoque une TypeError dans la branche except.

Vu mais écarté, faute de place ou d'impact suffisant :
- **Unicité globale.** Workspace.name (unique=True) et Methodology.code (unique=True) sont uniques sur toute la plateforme : on peut énumérer les noms des autres tenants et il y a des collisions de code.
- **Génération des codes et numéros.** next_sequential_code est global et lit tous les codes Project en Python (O(n)). unique_slug est global. Invoice.generate_number trie `-number` de façon lexicographique : collision et IntegrityError au-delà de 9999 factures par an.
- **Archivage d'un tarif.** BillingRate.save appelle full_clean() à chaque save : l'archivage peut échouer pour des données historiques où le tarif de vente est inférieur au coût.
- **Réapprobation d'un budget.** ProjectBudget.transition_to vers APPROVED ne met pas à jour approved_by si approved_at existe déjà.
- **Admin facture.** InvoiceAdmin ne recalcule pas les totaux après l'enregistrement des inlines.
- **Autres on_delete.** ProjectMeeting.project en CASCADE efface aussi les réunions de comité multi-projets. TimesheetEntry.user en CASCADE efface l'historique de coûts réels si un compte est supprimé dans l'admin.
- **UserProfile.** Le OneToOne interdit un profil (et un TJM de repli) par workspace.
- **Divers services.** project_import_mapper crée des Sprints avec `project.start_date` éventuellement None, d'où une ValidationError via full_clean. tool_registry.get_project_risks lit `impact`, champ inexistant (il s'agit de impact_score).
- **RoadmapItemForm.** Le jalon n'est sélectionnable que si le projet a déjà un item dans la roadmap.
- **ProjectAIProposalItemEditForm.** Il n'est scopé que si `instance` est passé en kwarg.

Migrations : les seeds 0045, 0047 et 0050 sont idempotents (update_or_create) et réversibles. Risque résiduel : 0050 fait `update_or_create(code=...)` sans `workspace=None`. Une méthodologie personnalisée nommée « Agile », « Lean » ou « Hybrid » créée avant le passage de 0050 serait convertie en méthodologie système globale (workspace=None, is_system=True). Comme 0045 à 0050 sont dans le même commit (1a6dd17), ce cas reste peu probable.

Zones non lues en détail :
- models.py 3454-3545 et 3676-4450 (enregistrements audio, séries, décisions, versions de compte-rendu, VoicePrint, AIChat, TaskReminder), 5250-5550 (rôles, cérémonies, KPI, workflows de méthodologie) ;
- admin.py 1640-1840 ;
- les migrations hors seeds ;
- forms_budget.py hors StyledModelForm.

### Finance / TJM / facturation

Constats écartés faute de place, ou jugés mineurs :
- views_invoice_ajax._to_decimal accepte "Infinity" ou "1e30" : InvoiceLine.save lève InvalidOperation, d'où un 500. "NaN" est enregistré et contamine les totaux.
- InvoiceLineDeleteView surcharge delete(). Sous Django 4.2, la suppression passe par form_valid, donc recompute_totals ne s'exécute pas : les totaux deviennent obsolètes. La route n'est pas liée dans l'UI.
- InvoiceListView additionne les factures DRAFT et CANCELLED dans total_ttc et dans « reste dû ».
- La devise est ignorée dans les agrégations (dépenses, revenus, portfolio). InvoiceGenerator prend XOF par défaut au lieu de budget.currency.
- Le terme « marge % » est incohérent : BillingRate.margin_percent et ProjectBudget.estimated_margin_percent rapportent la marge au coût, alors que profit_margin_percent et le forecast la rapportent au revenu.
- ProjectBudget.is_over_alert_threshold (affiché dans budget/detail.html l.17) compare l'estimé au budget approuvé, alors que BudgetAlertService se base sur le forecast.
- ProjectEstimateLine.markup_percent est en max_digits=5 : débordement Postgres possible si le TJM de vente dépasse 11 fois le coût dans regenerate.
- regenerate_budget_from_estimates écrit approved_by à chaque recalcul, même si le budget n'est pas approuvé (budget.py l.683-686).
- Les vues HTML de prévision et d'allocation appellent l'IA payante à chaque GET, sans throttle.
- Le PDF liste aussi les paiements PENDING, FAILED et REFUNDED, alors que print.html ne garde que les CONFIRMED.
- Le signal de snapshot ne s'exécute pas quand hours passe à 0 : le coût obsolète reste.
- estimate_project_members_costs est du code mort.
- SprintFinancialSnapshot et FeatureFinancialSnapshot sont lus mais jamais écrits.
- La séparation des tâches n'est pas assurée : le créateur peut approuver sa propre dépense en HTML.
- Il existe deux migrations 0027 (0027_phase3_budget_v2 et 0027_projectbudgetforecastrun_projectbudgetsnapshot_and_more) qui créent toutes deux ProjectBudgetSnapshot et ProjectBudgetForecastRun. Ce point relève de la catégorie migrations déjà connue, mais il est à vérifier.

Hors périmètre, à vérifier par l'audit concerné : TaskQuickAssignView, TaskQuickStatusView, TaskQuickCommentView, TaskToggleFlagView, TaskMoveView, TaskMarkDoneView, AInsightDismissView, NotificationMark*View et WorkspaceInvitationAcceptView héritent aussi de DevflowBaseMixin sans WorkspaceSecurityMixin. Elles reproduisent probablement le même filter_by_workspace non filtré (le même motif que pour les factures).

Tests : aucun test ne couvre invoicing.py ni les vues facture. Le test de snapshot BASELINE ne peut pas passer en l'état.

Zones non lues en détail : rendu complet d'invoice_docx.py, templates budget et portfolio au-delà des actions, services allocation_advice et risk_analysis, vues de validation des timesheets (views.py l.6098-6500), admin.py financier.

### IA / méthodologies

Vus mais écartés faute de place, ou de gravité moindre :
- (a) allocation_advice.py : requêtes N+1. `_compute_loads` fait une aggregate par membership. `_suggest_assignments` fait 6 projets × N profils × 2 requêtes. La charge additionne aussi les ProjectMember de projets terminés ou annulés (aucun filtre de statut projet).
- (b) services/openai_client.py est du code mort : il n'est utilisé que dans ai_project_import_service.py, entièrement commenté (0 ligne active). Doublon avec OpenAIProvider.
- (c) ProjectAIImportService._find_user_by_email cherche les users globalement (cross-tenant), mais le pipeline n'est pas routé (cf. constat import).
- (d) AIActionLog.is_reversible et undone_at existent, mais aucune fonction « annuler » n'est implémentée.
- (e) AIChatStreamView (api/views_quick.py:270) : prompt passé en query string GET (journalisé). Quota estimé sur la seule sortie (chars/4). Pas d'AIActionRateThrottle.
- (f) Actions DRF ai/summary et ai/recommendations en GET avec effet de bord (appel payant, record_usage). ai/forecast accepte aussi GET.
- (g) Le chat stocke `context_payload=ctx` (80 tâches) dans chaque message : volumétrie DB. `_infer_workspace` prend la membership la plus récente, quel que soit son statut.
- (h) ProjectAIProposalListView : `?project=abc` provoque une ValueError, donc une 500.
- (i) Anthropic : `system=None` passé au SDK si aucun message system (non vérifié contre l'API). Modèle par défaut claude-sonnet-4-5-20250929 et docstring mentionnant deepseek-coder : non signalés comme obsolètes faute de preuve.
- (j) Le prompt Genesis/structure n'a pas de max_tokens. Sur DeepSeek, la sortie est probablement tronquée (25 à 80 tâches), donc JSON invalide et heuristique, mais la limite par défaut du provider n'a pas été vérifiée.
- (k) create_sprint (copilote) : `timedelta(weeks=duration_weeks)` plante si le LLM fournit une chaîne. Numéro de sprint calculé sans verrou.
- (l) ProjectBudgetForecastView et RiskAnalysisView résolvent le projet sans scope workspace et s'appuient sur can_view_financials, dont le fallback `user.has_perm(...)` global n'est pas lié au workspace : à vérifier par le périmètre budget/RBAC.
- (m) MethodologyAIService.get_profile et _resolve_methodology utilisent `Methodology.objects.filter(code=...)` global. Une méthodologie custom nommée « field » ou « milestone » (code slug) s'appliquerait aux projets de tous les tenants. Risque faible, car la création est de fait réservée aux superusers.

Zones non lues ou partiellement lues : project_report.py (survolé : quota présent), meeting_intelligence.py (seuls _call_ai et _heuristic lus ; création des action items non auditée), methodology/capabilities.py (seules les 130 premières lignes), tool_registry.py (outils facture update_invoice_settings, add_invoice_lines_bulk, list_invoices, get_invoice et create_invoice_client non lus en détail), chat.py (_detect_intent et fonctions de réponse déterministes lues partiellement), project_import_mapper.py et prompts/ non lus, views_meeting.py hors appel full_process. Aucune exécution de tests : le graphe de migrations est cassé (problème déjà connu). Vérifications ORM faites en lecture seule via django.setup() (champs BacklogItem et Task, kwargs ActivityLog).

### Réunions / chat / Celery

J'ai vu ces points mais les ai écartés, faute de place ou parce qu'ils sont mineurs :
- **Hors périmètre mais critique, à router** : views.py l.625-628, ProfileUpdateView autorise `profile.workspace` parmi TOUS les Workspace non archivés. Un utilisateur peut donc rattacher son profil au workspace d'un autre tenant, puis get_user_workspace_ids l'inclut, ce qui donne un accès complet cross-tenant.
- RecordingDeleteView (views_recording.py l.472) et ProjectMeetingDeleteView n'ont aucun contrôle RBAC ni de propriétaire : tout membre peut supprimer définitivement audio, transcripts et réunions.
- MeetingActionItemForm.owner n'est pas filtré (forms_meeting.py l.354) : un POST forgé peut assigner un utilisateur d'un autre tenant, qui est ensuite repris comme assignee lors de la conversion en tâche.
- ChannelChatConsumer.create_message accepte un parent_id d'un autre canal ou tenant (consumers.py l.222) : intégrité et suppression en cascade.
- api_upload_recording n'impose pas consent_acknowledged côté serveur (RGPD).
- send_minutes_email et send_recording_email comptent comme « envoyé » même quand fail_silently masque un échec, et ne créent aucun MeetingFollowUp MINUTES_SENT.
- Le rappel « après réunion » part 1 à 3 h après le début, même si la réunion est plus longue ; le rappel « avant » part aussi aux participants qui ont décliné.
- NullProvider : finalize_recording marque COMPLETED avec un compte-rendu vide, sans heuristique de repli.
- ProjectMeetingUpdateView et MeetingReviewsSaveView filtrent le formulaire par le workspace courant et non par meeting.workspace (cas multi-workspace).
- MeetingDecisionListView ne couvre que le workspace courant, alors que le tableau de bord agrège tous les workspaces.
- Le mini-calendrier du tableau de bord utilise `.extra(DATE(scheduled_at))`, qui renvoie une chaîne sous SQLite : les compteurs sont à 0 en dev, mais c'est correct sous PostgreSQL.
- La conversion PROJECT_SUGGESTION crée un projet sans owner ni PM et déclenche la proposition IA.
- my_day.py compte les tâches EXPIRED dans « en retard », et la constante ACTIVE_TASK_STATUSES n'est pas utilisée.
- channel_panel_data renvoie unread_count=0 en dur (vue legacy).
- Les Content-Disposition des CR utilisent le titre brut (views_meeting.py l.562).
- Le consumer journalise en WARNING à chaque connexion.
- Le throttle_scope presence_heartbeat est ignoré (pas de ScopedRateThrottle configuré).

Vérifié et sans problème :
- Toutes les tâches du CELERY_BEAT_SCHEDULE existent dans tasks.py.
- La queue 'recordings' est bien écoutée par le worker dans docker-compose.
- Le pattern `self.retry` dans un try/except fonctionne : la retry est publiée avant que Retry soit levée.
- Aucun datetime naïf dans le périmètre (TIME_ZONE=UTC équivaut à Africa/Abidjan).

Confirmé par exécution (settings en mémoire, sans écriture) :
- MeetingActionItemForm invalide sans status.
- TypeError pour Task(created_by=...) et AInsight(description=...).

Zones lues partiellement ou non lues :
- Lues partiellement : meeting_intelligence.py, voiceprint.py, entity_detection.py, export.py (seulement docx/pdf), project/api/views_quick.py, views_my_day.py, la plupart des templates (hors recorder_widget, chat_pannel, detail et recording_summary).
- Non lues : la configuration du reverse-proxy externe (l'exposition publique de devflow-media est déduite de media.conf) et le .env de production (RECORDING_S3_BUCKET peut y être défini, ce qui rendrait le constat n°5 moins grave).

### Templates / routage / vues

Vérifications mécaniques effectuées par script. (a) Les 599 noms d'URL (urls principales, API, routeur DRF, allauth) couvrent tous les {% url %} des templates ainsi que tous les reverse/redirect côté Python : aucune référence cassée, à l'exception du namespace 'project:' utilisé dans success_list_url_name, qui est signalé. (b) Tous les template_name et render() pointent vers un fichier existant, sauf emails/notification_digest.txt/.html (smart_notifications.py:254/269) : le texte de repli est envoyé et la version HTML est perdue (mineur). (e) Le seul filtre inconnu est `split`. Le tag `static` est utilisé sans `{% load %}` dans layout/_scripts.html, qui est orphelin, et pointe vers devflow/js/app.js, fichier absent. (f) Les seuls fetch vers des routes inexistantes se trouvent dans _legacy_chat_panel.html, qui n'est pas inclus. static/js/app.js et static/css/app.css ne sont référencés nulle part.

Constats vus mais écartés ou hors périmètre :
- ProjectFlow/settings/prod.py définit DEBUG = True en dur (périmètre settings).
- nginx (deploy/nginx/media.conf) sert /media/ publiquement sans authentification : pièces jointes et PDF accessibles à qui connaît l'URL.
- urls.py ne sert MEDIA que si DEBUG, contrairement à ce qu'annonce son commentaire.
- L'admin est monté sur 'devflo/admin/back' sans slash final, ce qui produit des URL du type 'devflo/admin/backlogin/'.
- NotificationUpdateView et NotificationDeleteView ne filtrent pas sur recipient : un membre du même workspace peut modifier les notifications d'un autre.
- TaskKanbanMoveView ne remet pas completed_at à zéro et ne journalise pas l'action.
- Dans project/list.html:648, le lien « précédent » perd le paramètre category si aucun tri n'est actif.
- Les descriptions TinyMCE de milestone/detail.html:42 et risk/detail.html:52 sont rendues échappées (balises <p> visibles au lieu de passer par safe_html).
- La sidebar expose une cinquantaine d'écrans CRUD techniques (Réactions, Pièces jointes messages, Labels tâches…), ce qui alourdit l'UX.
- Le copilote (/projects/<pk>/copilot/chat/) n'a pas de throttle, mais c'est une View Django et non une action DRF.
- HomeView a un MRO inversé (TemplateView avant LoginRequiredMixin) mais n'est pas routée.
- `finance.draft_expenses_total` est affiché dans dashboard/index.html:456 alors que sa valeur est commentée dans la vue.
- ProjectCategory et Workspace.name sont uniques globalement (choix de conception).
- Les viewsets DRF de project/api/viewsets.py respectent tous WorkspaceScopedViewSetMixin + IsWorkspaceMember.

Zones non lues ou lues seulement partiellement : views_budget.py, views_meeting.py, views_recording.py, views_ai_*.py, views_invoice_ajax.py, la facturation de views.py (lignes 8560-9136), project/services/*, les models au-delà des champs vérifiés, ProjectDetailView entre les lignes 2720 et 3280 (calculs budgétaires détaillés), la majorité des 292 templates (vérifiés seulement par script, sauf les écrans principaux), le JS de roadmap/detail.html et sprint/_kanban_board.html, et MyDayService. Le chargement de Django a été impossible (GDAL et libgobject absents) : toutes les vérifications sont statiques.

---

## 7. Ordre de correction recommandé

1. **Infra (M1–M5)** — rétablir un graphe de migrations exécutable et faire repasser les 175 tests. Sans ça, aucune correction n'est vérifiable.
2. **Causes racines A→D** (sécurité multi-tenant) — un PR par cause, chacun avec ses tests `tests_security.py` (convention n°7).
3. **E** — `DEBUG=False`, médias protégés (vue authentifiée + `X-Accel-Redirect`), validation des uploads.
4. **Écrans cassés (section 3)** — corrections ponctuelles et rapides, fort gain UX.
5. **F** — refonte du moteur de coûts autour d'une seule source de vérité (timesheets × `BillingRate` résolu par date/projet/équipe), arrêt du recalcul automatique sur budget approuvé.
6. **IA** — timeouts clients LLM, appels longs déplacés dans Celery, quota appliqué partout (F82, F83), puis branchement UI des services existants (F91, F92).
7. **Fonctionnalités manquantes (section 4)**.
