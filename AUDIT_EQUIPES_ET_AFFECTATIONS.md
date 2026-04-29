# Audit DevFlow — Processus Équipes Projet, Création de Membres & Affectation des Tâches

Date : 2026-04-29
Périmètre : `project/models.py`, `project/views.py`, `project/forms.py`, `project/signals.py`, `project/services/notifications.py`, `templates/project/{team,team_membership,project_member,task_assignment}/`, `ProjectFlow/urls.py`.

L'audit porte spécifiquement sur trois flux : (1) création / gestion des **équipes** et de leurs membres, (2) **invitation et création d'utilisateurs** dans le workspace, (3) **affectation des tâches** (Task.assignee + TaskAssignment).

---

## 1. Synthèse exécutive

Le socle de données est solide : `Workspace → Team → TeamMembership → ProjectMember → Task → TaskAssignment` est correctement modélisé, indexé, et la traçabilité (ActivityLog, Notification, signals) existe. Mais le flux applicatif réel souffre de bugs structurels qui cassent l'expérience utilisateur en production :

| Domaine | Couverture fonctionnelle | Bugs critiques | Action |
|---|---|---|---|
| Modèles équipes / membres | 90 % | 1 | Patch contrainte unique |
| Vues CRUD Team / Membership / ProjectMember | 60 % | 3 | Templates dédiés + filtrage workspace |
| Affectation tâches (`assignee` + `TaskAssignment`) | 55 % | 4 | Déduplication de la classe + source de vérité unique |
| Invitation workspace | 30 % | 4 | Workflow complet à implémenter |
| Validation de capacité / allocation | 0 % | – | À créer |
| Filtrage workspace dans les `ModelForm` | 20 % | 2 | Sécuriser tous les `ChoiceField` |

Trois bugs sont **bloquants en production** : `TaskQuickAssignView` est défini deux fois et la seconde version casse silencieusement la précédente ; les écrans `Team`, `TeamMembership`, `ProjectMember`, `TaskAssignment` n'ont pas de template `form.html` dédié et tombent sur `project/create.html` codé en dur pour le modèle Project ; et l'acceptation d'invitation ne crée ni `TeamMembership`, ni `UserProfile`, ni utilisateur si nécessaire.

---

## 2. Bugs critiques (bloquants)

### 2.1 `TaskQuickAssignView` défini deux fois (et la 2ᵉ régresse la sécurité)

`project/views.py` contient deux classes du même nom :

- **Ligne 3818** — version « propre » : hérite de `DevflowBaseMixin`, utilise `filter_by_workspace`, écrit dans l'`ActivityLog`, gère la dé-assignation (`assignee_id` vide → `task.assignee = None`), lit `request.POST.get("assignee")`.
- **Ligne 3942** — version « réécrite » : hérite uniquement de `LoginRequiredMixin`, n'effectue **aucune vérification de workspace**, n'écrit pas d'`ActivityLog`, ne gère pas la dé-assignation, et lit `request.POST.get("user")`.

En Python, la dernière définition l'emporte ; c'est donc la version dégradée qui est exécutée. Les conséquences :

1. **Faille trans-workspace** — n'importe quel utilisateur authentifié peut assigner une tâche d'un autre workspace s'il en connaît l'ID.
2. **Boutons HTML cassés** — les templates qui envoient le champ `assignee` (cohérent avec le FK Django `Task.assignee`) ne sont plus reconnus, l'assignation rapide silencieusement n'a aucun effet.
3. **Plus de log d'activité** sur l'assignation rapide → trou dans l'historique.

`TaskQuickCommentView` est dans le même cas (lignes 3894 et 3968). Mêmes symptômes : disparition du `filter_by_workspace`, perte du log, perte de l'incrément `comments_count` correctement protégé contre les races (la 2ᵉ version utilise `task.comments.count()` après save, ce qui est plus correct mais n'est plus protégé par le mixin).

**Correctif** : supprimer les versions dupliquées, conserver une seule classe par vue, et faire une revue rapide pour confirmer qu'aucune URL ne pointe encore sur l'ancienne signature.

### 2.2 Templates manquants pour `Team`, `TeamMembership`, `ProjectMember`, `TaskAssignment`

`DevflowCreateView` et `DevflowUpdateView` ont pour valeurs par défaut `template_name = "project/create.html"` et `"project/update.html"`. Or `templates/project/create.html` est **codé en dur** pour le modèle `Project` : il référence `form.name`, `form.code`, `form.category`, `form.team`, `form.workspace`, `form.tech_stack`, `form.description`, `form.image`, `form.owner`, `form.product_manager`, `form.status`, `form.priority`, `form.health_status`, `form.start_date`, `form.target_date`, `form.delivered_at`, `form.budget`, `form.is_favorite`, etc.

Quand on ouvre `team/create/`, `team-memberships/create/`, `project-members/create/` ou `task-assignments/create/` :
- la moitié des champs spécifiques (`role`, `allocation_percent`, `is_primary`, `lead`, `velocity_target`, `team_type`, `assigned_by`, `is_active`…) ne s'affiche pas — ils ne sont rendus nulle part dans le template ;
- les labels affichés (`Owner`, `Product manager`, `Date cible`, `Budget`) sont incorrects et trompent l'utilisateur ;
- la création peut quand même réussir grâce au `form.save()` Django (champs non rendus → utilisent les `default`), mais l'utilisateur ne contrôle plus rien.

C'est pourquoi le processus « créer une équipe et y ajouter des membres » paraît cassé.

**Correctif** : créer les fichiers manquants `templates/project/team/form.html`, `team_membership/form.html`, `project_member/form.html`, `task_assignment/form.html` et déclarer `template_name = "project/team/form.html"` (etc.) sur les vues correspondantes.

### 2.3 Workflow d'invitation incomplet

Le modèle `WorkspaceInvitation` (ligne 1915) prévoit `email`, `role`, `team`, `token`, `expires_at`, `status`. Mais :

- `WorkspaceInvitationForm` (forms.py l. 1661) **expose `token` à l'utilisateur** au lieu de le générer côté serveur. Risque : un invité peut se forger une invitation avec un token connu.
- Aucun envoi d'email d'invitation n'est branché sur la création (`WorkspaceInvitationCreateView` est un simple `DevflowCreateView`).
- `WorkspaceInvitationAcceptView` (l. 6666) ne fait que `status = ACCEPTED` ; **elle ne crée ni `User`, ni `UserProfile`, ni `TeamMembership`**. Conséquence : accepter une invitation ne donne jamais accès au workspace.
- L'acceptation passe par `filter_by_workspace`, ce qui suppose que l'utilisateur appartient déjà au workspace — paradoxe pour un flow d'onboarding.
- `is_expired()` n'est pas vérifié à l'acceptation.

**Correctif** : refondre `WorkspaceInvitationForm` (retirer `token`, `accepted_at`, `status` ; auto-générer `token = secrets.token_urlsafe(48)` dans le `save()` du form / vue), brancher `send_mail` dans `form_valid`, et créer une vue publique `/invitations/<token>/accept/` qui crée l'utilisateur si nécessaire, le `UserProfile`, le `TeamMembership` correspondant et marque l'invitation acceptée. Cf. §6.2 pour un patch concret.

### 2.4 Double source de vérité `Task.assignee` vs `TaskAssignment`

Le modèle `Task` possède un FK `assignee` (l. 1117) ET une relation M2M via `TaskAssignment` (l. 1149). Dans le code actuel :

- `TaskCreateView.form_valid` (l. 4371) crée le `TaskAssignment` à partir de `assignee` — bien.
- `TaskUpdateView` n'effectue **aucune** synchronisation : si on change `assignee` dans le form, on a un nouvel assignee FK mais l'ancien `TaskAssignment` reste actif et le nouveau n'est pas créé.
- `TaskQuickAssignView` (1ʳᵉ version) update le FK ET crée le `TaskAssignment`, mais à la dé-assignation on remet juste `task.assignee = None` sans désactiver les `TaskAssignment` existants.
- Les services (`task_reminder`, `notify_pm_on_task_change`, dashboards) lisent tantôt `assignee`, tantôt `assignments`. À long terme c'est une bombe.

**Correctif recommandé** (option A, la plus propre) : faire de `Task.assignee` une propriété calculée renvoyant le `TaskAssignment` actif primaire (ou `is_primary=True`). Ajouter un champ `is_primary` à `TaskAssignment`, faire une migration `data_migration` qui copie l'actuel `assignee` dans un `TaskAssignment` primaire si absent, puis retirer le FK.

**Correctif minimal** (option B, sans data migration) : centraliser l'écriture dans une méthode `Task.assign(user, by=None, allocation=100)` qui maintient simultanément le FK et le `TaskAssignment`, et l'appeler depuis toutes les vues.

---

## 3. Bugs majeurs (non bloquants mais à risque élevé)

### 3.1 Contrainte d'unicité contournable sur `TeamMembership`

`TeamMembership.Meta.unique_together = [("workspace", "user", "team")]`. Or `team` est `null=True, blank=True`. Sous PostgreSQL, deux NULL ne sont jamais considérés égaux : on peut donc créer N membership « sans équipe » pour le même utilisateur dans le même workspace. → doublons silencieux.

**Correctif** : ajouter une `UniqueConstraint` partielle :
```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["workspace", "user", "team"],
            name="uniq_membership_with_team",
            condition=Q(team__isnull=False),
        ),
        models.UniqueConstraint(
            fields=["workspace", "user"],
            name="uniq_membership_no_team",
            condition=Q(team__isnull=True),
        ),
    ]
```

### 3.2 `signals.create_user_profile` rattache au mauvais workspace

`project/signals.py` l. 12 : à la création d'un `User`, on lui crée un `UserProfile` lié à `Workspace.objects.first()`. C'est un piège pour la production multi-tenant : tout nouvel utilisateur invité dans un workspace B se retrouve quand même rattaché par défaut au workspace A.

**Correctif** : ne plus créer de profil dans ce signal — laisser la responsabilité au flow d'invitation (qui connaît le bon workspace) ou au flow de signup explicite. Conserver une création de profil seulement si on peut déterminer le workspace via un attribut transient `instance._invited_workspace`.

### 3.3 Attribution erronée de `assigned_by` dans le signal d'assignation

`signals.notify_on_task_assignee_change` (l. 53) passe `assigned_by=instance.reporter`. Le reporter, c'est l'auteur de la tâche, pas la personne qui assigne. Si la tâche est créée par Alice puis ré-assignée par Bob à Charlie, Charlie reçoit la notification « assignée par Alice ».

**Correctif** : exposer un attribut transient `instance._assigned_by` posé par les vues juste avant le save. C'est la même technique que `_skip_budget_refresh`.

### 3.4 Querysets non filtrés par workspace dans plusieurs `ModelForm`

| Form | Champ | Problème |
|---|---|---|
| `ProjectMemberForm` | `user`, `team`, `project` | Aucun filtre — on peut affecter un user d'un workspace B à un projet du workspace A. |
| `TaskAssignmentForm` | `task`, `user`, `assigned_by` | Idem. Pas de check que `user` appartient au projet de la tâche. |
| `TeamForm` | `lead` | Pas de filtre — on peut désigner comme lead un user hors workspace. |
| `TeamMembershipForm` | `user`, `team` | Pas de filtre par workspace courant. |
| `WorkspaceInvitationForm` | `team` | Pas de filtre par workspace courant. |

**Correctif** : injecter le `current_workspace` via `kwargs` (déjà fait par `DevflowCreateView.get_form_kwargs`) puis dans `__init__` :
```python
ws = kwargs.pop("current_workspace", None)
super().__init__(*args, **kwargs)
if ws:
    self.fields["user"].queryset = User.objects.filter(devflow_memberships__workspace=ws).distinct()
    self.fields["team"].queryset = Team.objects.filter(workspace=ws)
    self.fields["project"].queryset = Project.objects.filter(workspace=ws, is_archived=False)
```

### 3.5 Pas de garde-fou de capacité d'allocation

`ProjectMember.allocation_percent` et `TaskAssignment.allocation_percent` sont validés individuellement (0-100) mais pas globalement : un même utilisateur peut être affecté à 100 % sur cinq projets simultanément, ou affecté à 5 tâches actives à 50 % chacune. Combiné à `UserProfile.availability_percent`, on n'a aucune alerte de surcharge.

**Correctif** : ajouter une validation côté `clean()` qui somme les allocations actives :
```python
def clean(self):
    super().clean()
    user = self.cleaned_data.get("user")
    if user:
        active_alloc = ProjectMember.objects.filter(
            user=user, project__is_archived=False
        ).exclude(pk=self.instance.pk).aggregate(s=Sum("allocation_percent"))["s"] or 0
        if active_alloc + (self.cleaned_data.get("allocation_percent") or 0) > 100:
            raise ValidationError("Cette affectation porterait %s à plus de 100 %% d'allocation totale." % user)
```

Ne pas bloquer dur : afficher en warning sur le form (`self.add_error(None, ...)` avec niveau `WARNING` côté template) ou en bandeau messages.

---

## 4. Bugs mineurs / dette technique

- **`TeamMembership.role` choices = `Role`** mais beaucoup des rôles décrits (CTO, PO, SM…) appartiennent au niveau workspace, pas au niveau équipe. Le couplage rend la modélisation confuse. Recommandation : séparer `WorkspaceRole` (admin/membre) de `TeamRole` (developer/qa/devops…).
- **Pas d'avatar par défaut** : `TeamMembership.avatar_color` est calculé nulle part. Ajouter un `save()` qui pré-remplit avec un palette pseudo-aléatoire stable (hash du user_id).
- **`Team.velocity_current` non recalculé** : aucun signal/scheduled task ne le met à jour à partir des sprints terminés.
- **`ProjectMember.role` est un `CharField` libre** : une typo et le filtrage devient inopérant. Préférer un `TextChoices` partagé avec `TeamMembership.Role`.
- **Le bouton « Ajouter membre projet » du dashboard projet** (`views.py` l. 2942) pointe vers `/project-members/create/?project={pk}` — mais `ProjectMemberCreateView` ne lit pas le paramètre `project` dans les `initial`. Patch : `get_initial()` qui lit `request.GET.get("project")`.
- **`TeamMembership.ordering = ["user__username"]`** ignore l'identité réelle (firstname/lastname). Préférer `["-status", "user__last_name", "user__first_name"]`.
- **Absence de tests** : `project/tests.py` n'a aucun test pour le flow équipe/affectation.
- **Le formulaire `TeamMembershipForm` n'expose pas un mode « ajout multi »** : pour onboarder une équipe entière il faut N créations manuelles. Voir §6.4.
- **`ProjectMemberForm` n'expose pas le champ `is_primary`** logiquement, mais ne valide pas qu'il y ait au plus un membre primaire par projet.

---

## 5. Diagnostic du processus métier

Mise en perspective du parcours utilisateur tel qu'il fonctionne aujourd'hui :

```
[Admin] → Créer Workspace ✓
       → Créer Team
              ↳ formulaire affiché avec un template prévu pour "Project" → champs Team invisibles ✗
       → Inviter par email
              ↳ token saisi à la main, pas d'envoi d'email ✗
              ↳ acceptation = bouton qui ne crée ni user ni membership ✗
       → Créer manuellement TeamMembership puis ProjectMember
              ↳ deux écrans différents pour ce qui devrait être un seul flow ✗
       → Créer une tâche
              ↳ Task.assignee est rempli côté form, TaskAssignment créé en parallèle ✓
              ↳ mais TaskUpdate ne re-synchronise pas les deux ✗
       → Réassigner depuis le board
              ↳ TaskQuickAssignView duplicaté → la version dégradée tourne ✗
```

En résumé : la donnée modèle est prête à porter un workflow professionnel, mais la couche vues + templates n'a jamais été alignée dessus. Les utilisateurs ressentent ça comme « ça ne s'enregistre pas », « je ne vois pas le membre que j'ai invité », « la tâche perd son responsable ».

---

## 6. Propositions d'amélioration

### 6.1 Refonte « Création d'équipe + ajout de membres » en un seul écran (priorité 1)

**Cible UX** : un écran `team/create_with_members.html` qui combine la création de l'équipe et l'ajout initial de N membres en un seul submit.

```python
# project/forms.py
class TeamCreateWithMembersForm(BaseStyledModelForm):
    # champs Team standards…
    initial_member_emails = forms.CharField(
        widget=forms.Textarea,
        required=False,
        help_text="Un email par ligne. Les utilisateurs absents recevront une invitation."
    )
    initial_role = forms.ChoiceField(choices=TeamMembership.Role.choices, initial=TeamMembership.Role.DEVELOPER)
```

Côté vue : pour chaque email, soit on retrouve un `User` du workspace (→ création immédiate du `TeamMembership`), soit on crée une `WorkspaceInvitation` avec `team_id=team.pk` qui sera consommée à l'acceptation.

Bénéfices : on supprime l'écran `team-memberships/create/` pour le cas standard (il reste pour les cas complexes), on respecte le workflow mental réel des chefs de projet.

### 6.2 Workflow d'invitation complet (priorité 1)

```python
# project/forms.py
class WorkspaceInvitationForm(BaseStyledModelForm):
    class Meta:
        model = WorkspaceInvitation
        fields = ["email", "role", "team"]   # plus de token / accepted_at / status

    def save(self, commit=True, *, invited_by=None, workspace=None):
        self.instance.token = secrets.token_urlsafe(48)
        self.instance.expires_at = timezone.now() + timedelta(days=14)
        self.instance.invited_by = invited_by
        self.instance.workspace = workspace
        return super().save(commit=commit)
```

```python
# project/views.py
class WorkspaceInvitationCreateView(DevflowCreateView):
    ...
    def form_valid(self, form):
        invitation = form.save(
            invited_by=self.request.user,
            workspace=self.get_current_workspace(),
        )
        send_invitation_email(invitation)   # service à créer
        messages.success(self.request, f"Invitation envoyée à {invitation.email}.")
        return redirect("workspace_invitation_list")


# Vue publique d'acceptation (hors filter_by_workspace)
class WorkspaceInvitationPublicAcceptView(View):
    def get(self, request, token):
        invitation = get_object_or_404(WorkspaceInvitation, token=token, status=WorkspaceInvitation.Status.PENDING)
        if invitation.is_expired():
            invitation.status = WorkspaceInvitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            return render(request, "invitations/expired.html")
        return render(request, "invitations/accept.html", {"invitation": invitation})

    def post(self, request, token):
        invitation = get_object_or_404(WorkspaceInvitation, token=token, status=WorkspaceInvitation.Status.PENDING)
        # 1. user existant ?
        user = User.objects.filter(email__iexact=invitation.email).first()
        # 2. sinon création via SignupForm
        if not user:
            form = AcceptInvitationSignupForm(request.POST)
            if not form.is_valid():
                return render(request, "invitations/accept.html", {"form": form, "invitation": invitation})
            user = form.save(commit=False)
            user.email = invitation.email
            user.save()
        # 3. UserProfile
        UserProfile.objects.get_or_create(user=user, workspace=invitation.workspace)
        # 4. TeamMembership
        TeamMembership.objects.update_or_create(
            workspace=invitation.workspace,
            user=user,
            team=invitation.team,
            defaults={"role": invitation.role, "status": TeamMembership.Status.ACTIVE},
        )
        # 5. clore l'invitation
        invitation.status = WorkspaceInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.save(update_fields=["status", "accepted_at"])
        login(request, user)
        return redirect("dashboard")
```

### 6.3 Source unique de vérité pour l'affectation des tâches (priorité 1)

Implémenter sur `Task` :

```python
# project/models.py — ajouts
class Task(...):
    ...
    def assign(self, user, *, assigned_by=None, allocation_percent=100):
        with transaction.atomic():
            self.assignee = user
            self.save(update_fields=["assignee", "updated_at"])
            TaskAssignment.objects.update_or_create(
                task=self, user=user,
                defaults={
                    "assigned_by": assigned_by,
                    "allocation_percent": allocation_percent,
                    "is_active": True,
                },
            )
            # désactive toutes les autres affectations actives
            TaskAssignment.objects.filter(task=self).exclude(user=user).update(is_active=False)

    def unassign(self):
        with transaction.atomic():
            TaskAssignment.objects.filter(task=self, is_active=True).update(is_active=False)
            self.assignee = None
            self.save(update_fields=["assignee", "updated_at"])
```

Puis remplacer **toutes** les écritures de `task.assignee = …` par des appels à `task.assign(...)` / `task.unassign()` dans `TaskQuickAssignView`, `TaskUpdateView.form_valid`, services AI, etc. Le test de régression : grep sur `\.assignee\s*=` ne devrait plus rien remonter en dehors du modèle lui-même.

### 6.4 Affectation rapide multi-utilisateurs depuis la fiche projet (priorité 2)

Sur la page `project_detail`, ajouter un widget « Affecter rapidement » qui :
- propose une autocomplétion sur `TeamMembership.user` du workspace ;
- permet de cocher plusieurs utilisateurs ;
- pour chaque utilisateur, propose un `allocation_percent` (slider) avec affichage temps réel de la capacité résiduelle (`100 - sum(active allocations)`) ;
- crée les `ProjectMember` en lot via une seule transaction ;
- déclenche optionnellement la création d'un `TaskAssignment` sur les tâches `TODO` non assignées du sprint actif.

API à créer : `POST /api/projects/<pk>/members/bulk/` avec corps `{ users: [{user_id, allocation, is_primary}, …] }`.

### 6.5 Dashboard de capacité (priorité 2)

Ajouter une vue `/team/capacity/` qui affiche, par utilisateur du workspace :
- capacité théorique (`UserProfile.capacity_hours_per_week`) ;
- charge actuelle (somme des `ProjectMember.allocation_percent` projets actifs) ;
- nombre de tâches `TODO` + `IN_PROGRESS` ;
- nombre d'heures restantes engagées (`Σ task.estimate_hours - task.spent_hours` pour les tâches actives où user est assignee) ;
- code couleur 🟢/🟠/🔴 selon dépassement.

C'est la pièce qui transforme « affectation des tâches » d'une saisie aveugle en une décision informée.

### 6.6 Permissions explicites (priorité 2)

Aujourd'hui `DevflowBaseMixin` gère le filtrage par workspace mais pas la séparation des rôles. Recommandation : ajouter un mixin `RoleRequiredMixin` qui lit le `TeamMembership.role` actif de l'utilisateur sur le workspace courant et autorise/refuse selon une liste blanche déclarative :

```python
class TeamMembershipCreateView(RoleRequiredMixin, DevflowCreateView):
    allowed_roles = {"ADMIN", "PM", "TECH_LEAD"}
    ...
```

### 6.7 Notifications fines + actor correct (priorité 3)

- Corriger `signals.notify_on_task_assignee_change` pour utiliser `instance._assigned_by` (cf. §3.3).
- Ajouter une notification dédiée `MEMBER_ADDED_TO_PROJECT` quand un `ProjectMember` est créé.
- Ajouter une notification `INVITATION_ACCEPTED` au demandeur (`invited_by`) lorsque l'invitation passe à ACCEPTED.
- Throttler les notifications PM par tâche (1 par tranche de 30 min) pour éviter le spam des « status mis à jour ».

### 6.8 Tests à introduire (priorité 3)

Le module n'a **aucun test**. Suggestion d'un premier lot de 8 tests unitaires/intégration pour figer les comportements clés :

1. Création d'équipe → présence dans `/teams/`.
2. Création d'un `TeamMembership` doublon → bloquée par la `UniqueConstraint`.
3. Invitation envoyée → email envoyé + token aléatoire + `expires_at` en J+14.
4. Acceptation invitation → `TeamMembership` + `UserProfile` créés.
5. Réassignation d'une tâche → ancien `TaskAssignment` désactivé, nouveau actif.
6. Capacité dépassée → form invalide.
7. `TaskQuickAssignView` POST `assignee` → 1 seule classe, 200, `ActivityLog` créé.
8. Filtrage workspace : un user du workspace A ne peut pas créer un `ProjectMember` sur un projet du workspace B.

---

## 7. Plan d'action recommandé (ordre de priorité)

| # | Action | Effort | Impact |
|---|---|---|---|
| 1 | Supprimer les classes dupliquées `TaskQuickAssignView` / `TaskQuickCommentView` (§2.1) | XS | Correction d'une faille trans-workspace + restauration du log |
| 2 | Créer les templates `form.html` manquants pour Team / TeamMembership / ProjectMember / TaskAssignment (§2.2) | S | Débloque la gestion d'équipe |
| 3 | Refondre le workflow d'invitation (§2.3, §6.2) | M | Onboarding fonctionne enfin |
| 4 | Centraliser l'affectation via `Task.assign()` (§2.4, §6.3) | S | Cohérence des données + plus de bug `assignee` orphelin |
| 5 | Patch `UniqueConstraint` `TeamMembership` (§3.1) | XS | Plus de doublons |
| 6 | Filtrer les querysets par workspace dans tous les forms (§3.4) | S | Sécurité multi-tenant |
| 7 | Corriger `signals.create_user_profile` (§3.2) et `assigned_by` (§3.3) | XS | Données correctes |
| 8 | Écran combiné « Créer équipe + ajouter membres » (§6.1) | M | UX |
| 9 | Validation de capacité (§3.5) | S | Évite la surallocation |
| 10 | Dashboard capacité (§6.5) | M | Visibilité managériale |
| 11 | Permissions par rôle (§6.6) | M | Sécurité |
| 12 | Tests (§6.8) | M | Non-régression |

XS ≈ < 1h, S ≈ 1-3h, M ≈ 0,5-1 jour.

---

## 8. Annexes — extraits de code à corriger

### A. Suppression du doublon `TaskQuickAssignView`

Garder la version « propre » (l. 3818) et **supprimer purement** les blocs lignes 3942-3989 (`class TaskQuickAssignView(LoginRequiredMixin, View)` et le `class TaskQuickCommentView(LoginRequiredMixin, View)` qui suit).

### B. Patch contrainte unique `TeamMembership`

```python
class TeamMembership(TimeStampedModel):
    ...
    class Meta:
        ordering = ["user__last_name", "user__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user", "team"],
                name="uniq_membership_with_team",
                condition=Q(team__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uniq_membership_no_team",
                condition=Q(team__isnull=True),
            ),
        ]
```

### C. Filtrage `TaskAssignmentForm`

```python
class TaskAssignmentForm(BaseStyledModelForm):
    class Meta:
        model = TaskAssignment
        fields = ["task", "user", "allocation_percent", "is_active"]  # assigned_by injecté côté vue

    def __init__(self, *args, **kwargs):
        ws = kwargs.pop("current_workspace", None)
        super().__init__(*args, **kwargs)
        if ws:
            self.fields["task"].queryset = Task.objects.filter(workspace=ws, is_archived=False)
            self.fields["user"].queryset = User.objects.filter(
                devflow_memberships__workspace=ws, is_active=True
            ).distinct()

    def clean(self):
        cleaned = super().clean()
        task = cleaned.get("task")
        user = cleaned.get("user")
        if task and user:
            is_member = ProjectMember.objects.filter(project=task.project, user=user).exists()
            if not is_member:
                raise ValidationError(
                    f"{user} n'est pas membre du projet « {task.project} »."
                )
        return cleaned
```

---

*Fin du rapport. Ce document peut être utilisé tel quel comme backlog technique. Les sections §6 et §8 contiennent des extraits de code prêts à être adaptés ; ils ne sont pas appliqués automatiquement, à dessein, pour permettre une revue avant merge.*
