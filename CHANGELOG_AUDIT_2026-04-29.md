# Changelog — Application des corrections d'audit & Module Facturation

Date : 2026-04-29
Périmètre : suite directe du document `AUDIT_EQUIPES_ET_AFFECTATIONS.md`.

---

## 1. Corrections appliquées (équipes / affectations)

### 1.1 Doublons de vues supprimés
`project/views.py` — la seconde définition de `TaskQuickAssignView` (héritant uniquement de `LoginRequiredMixin`, sans filtrage workspace, sans `ActivityLog`, qui lisait `request.POST.get("user")` au lieu de `assignee`) a été retirée. Idem pour `TaskQuickCommentView`. La version canonique est conservée et a été renforcée pour utiliser la nouvelle méthode `Task.assign()` / `Task.unassign()`. Elle accepte indifféremment `assignee` et `user` dans le POST pour rester rétro-compatible avec les templates existants.

### 1.2 Templates `form.html` créés
Quatre nouveaux templates dédiés au lieu de retomber sur `templates/project/create.html` codé en dur pour `Project` :
- `templates/project/_generic_form.html` (template réutilisable qui itère sur `form` et applique le style DevFlow)
- `templates/project/team/form.html`
- `templates/project/team_membership/form.html`
- `templates/project/project_member/form.html`
- `templates/project/task_assignment/form.html`

Les vues `TeamCreateView`, `TeamUpdateView`, `TeamMembershipCreate/UpdateView`, `ProjectMemberCreate/UpdateView`, `TaskAssignmentCreate/UpdateView` ont été modifiées pour pointer sur leur template dédié. `ProjectMemberCreateView` et `TaskAssignmentCreateView` lisent désormais `?project=…` / `?task=…` dans `get_initial()` pour permettre la création contextuelle depuis une fiche projet ou tâche.

### 1.3 Source unique de vérité pour l'affectation
`Task` expose maintenant deux méthodes :
- `task.assign(user, *, assigned_by=None, allocation_percent=100)` met à jour le FK `Task.assignee`, l'`update_or_create` du `TaskAssignment` correspondant, désactive automatiquement les autres affectations actives sur la tâche, et écrit un `ActivityLog`.
- `task.unassign(actor=None)` désactive toutes les `TaskAssignment` actives et nettoie le FK.

Les vues quick-assign passent désormais par ces méthodes.

### 1.4 Patch UniqueConstraint TeamMembership
`TeamMembership.Meta.unique_together` a été remplacé par deux `UniqueConstraint` partielles (avec `condition=Q(team__isnull=False)` et `Q(team__isnull=True)`). Cela supprime le bug Postgres où plusieurs memberships « sans équipe » pouvaient coexister pour le même (workspace, user). L'`ordering` est aussi passé sur `(-status, last_name, first_name)`.

`TeamMembership.save()` pré-remplit maintenant `avatar_color` avec une palette stable basée sur l'ID utilisateur.

### 1.5 Correction des signaux
`project/signals.py` :
- `create_user_profile` ne rattache plus aveuglément au premier workspace existant. Il lit l'attribut transient `_invited_workspace` (posé par le flow d'invitation) et ne tombe sur le 1er workspace que s'il n'en existe qu'un seul (mode mono-tenant).
- `notify_on_task_assignee_change` utilise désormais `instance._assigned_by` (posé par `Task.assign()`) plutôt que le reporter, qui n'est pas l'auteur de l'affectation.

### 1.6 Filtrage workspace des `ModelForm`
`TeamForm`, `TeamMembershipForm`, `ProjectMemberForm`, `TaskAssignmentForm`, `WorkspaceInvitationForm` filtrent désormais leurs querysets (`user`, `team`, `project`, `task`, `lead`, `assigned_by`) sur le `current_workspace` injecté par `BaseStyledModelForm`. Ajout de `clean()` qui :
- empêche les doublons (`TeamMembership`, `ProjectMember`) ;
- vérifie qu'un user affecté à une tâche est bien membre du projet ;
- bloque les sur-allocations cumulées > 100 % par utilisateur sur les projets actifs.

### 1.7 Workflow d'invitation complet
Refonte côté form, vue et templates :
- `WorkspaceInvitationForm` n'expose plus `token`, `accepted_at`, `status`. Le token est généré via `secrets.token_urlsafe(48)` dans `save()`. Si `expires_at` n'est pas fourni, on prend `now + 14 jours`. Anti-doublon sur (workspace, email, status=PENDING).
- `WorkspaceInvitationCreateView.form_valid` envoie l'email d'invitation via le nouveau service `project/services/invitations.py`.
- Nouvelle vue **publique** `WorkspaceInvitationPublicAcceptView` (URL `invitations/<token>/`) :
  - Vérifie l'état (PENDING + non expiré).
  - Si l'utilisateur n'existe pas, demande prénom/nom/mot de passe et crée le `User` avec `_invited_workspace` posé pour le signal.
  - Crée systématiquement le `UserProfile` et le `TeamMembership` avec le rôle/équipe de l'invitation.
  - Notifie le demandeur (`invited_by`) que l'invitation a été acceptée.
  - Connecte automatiquement l'utilisateur si le compte vient d'être créé.

Templates ajoutés : `templates/emails/workspace_invitation.txt`, `templates/emails/workspace_invitation.html`, `templates/project/workspace_invitation/accept.html`.

URL ajoutée : `path("invitations/<str:token>/", WorkspaceInvitationPublicAcceptView.as_view(), name="workspace_invitation_public_accept")`.

---

## 2. Module Facturation (nouveau)

### 2.1 Modèles
Quatre nouveaux modèles dans `project/models.py` :

- **`InvoiceClient`** — carnet d'adresses des clients destinataires (workspace, nom, raison sociale, identifiant fiscal, adresse complète, contact, notes). Soft-deletable.
- **`Invoice`** — facture client liée à un projet et à un client. Champs principaux : `number` (auto `FAC-AAAA-NNNN`, unique par workspace), `title`, `issue_date`, `due_date` (auto `+30j`), `period_start/end`, `subtotal_ht`, `discount_amount`, `tax_rate` (défaut 18 %), `tax_amount`, `total_ttc`, `paid_amount`, `currency` (défaut XOF), `status` (DRAFT/ISSUED/SENT/PARTIALLY_PAID/PAID/OVERDUE/CANCELLED), `billing_mode` (FIXED / TIME_AND_MATERIALS / MILESTONE / MANUAL). Index sur `(workspace, status)`, `(project, status)`, `(due_date)`.
  - Méthode `Invoice.generate_number(workspace)` — numérotation séquentielle.
  - Méthode `Invoice.recompute_totals()` — recalcule sous-total, TVA, TTC, paiements, et bascule automatiquement le statut (PAID / PARTIALLY_PAID / OVERDUE).
  - Property `remaining_due`.
- **`InvoiceLine`** — ligne de facture. `line_type` (SERVICE / TIME / EXPENSE / MILESTONE / DISCOUNT / OTHER), `quantity × unit_price = total_amount` (calculé au save). FK optionnels vers la `ProjectEstimateLine`, le `Milestone` ou le `User` source pour la traçabilité.
- **`InvoicePayment`** — paiement enregistré. `method` (BANK_TRANSFER / CARD / CASH / CHECK / MOBILE_MONEY / OTHER), `status` (PENDING / CONFIRMED / REFUNDED / FAILED). Lié à `Invoice` ; les paiements `CONFIRMED` sont sommés pour mettre à jour `paid_amount` et `status`.

### 2.2 Service de génération automatique
`project/services/invoicing.py` — classe `InvoiceGenerator(project, ...)` avec trois méthodes :

- `from_estimate_lines(budget_stage="BASELINE")` — mode forfait : crée une facture à partir des `ProjectEstimateLine` validées du projet (par défaut le stage BASELINE), une ligne par estimation.
- `from_timesheets(only_approved=True, only_billable=True, period_start=…, period_end=…, group_by_user=True)` — mode régie : somme les `TimesheetEntry` approuvées et facturables sur la période, calcule le tarif horaire vente à partir de `BillingRate.get_user_sale_daily_rate(user) / capacity_hours_per_day`. Une ligne par utilisateur (mode groupé) ou par entrée (mode détaillé).
- `from_milestones(milestones=None)` — mode jalon : si `milestones` non fourni, prend tous les jalons livrés non encore facturés et facture leur `payment_amount`/`amount`.

Façade simple : `generate_invoice_for_project(project, mode="FIXED|TIME_AND_MATERIALS|MILESTONE", issued_by=request.user, ...)`.

### 2.3 Vues, formulaires, URLs
Nouvelles vues dans `project/views.py` :
- CRUD complet `InvoiceClient*View` et `Invoice*View` (List / Create / Detail / Update / Delete / Print).
- `InvoiceListView` calcule les agrégats (total TTC, encaissé, reste, nombre de factures en retard / brouillon).
- `InvoiceDetailView` précharge lignes & paiements et expose un `InvoicePaymentForm` pour saisie inline.
- `InvoiceIssueView`, `InvoiceMarkSentView`, `InvoiceCancelView` — transitions de statut.
- `InvoiceLineCreate/Update/DeleteView` — gestion des lignes ; `recompute_totals()` est appelé après chaque mutation.
- `InvoicePaymentCreateView` — POST inline depuis la fiche facture.
- `InvoiceGenerateFromProjectView` — formulaire de génération automatique avec sélection du mode (forfait / régie / jalon), période, taux TVA, devise, titre, notes.

Nouveaux formulaires dans `project/forms.py` : `InvoiceClientForm`, `InvoiceForm`, `InvoiceLineForm`, `InvoicePaymentForm`, `InvoiceGenerateForm`.

Nouvelles URLs (préfixe `/billing/`) :

```
/billing/clients/                        invoice_client_list
/billing/clients/create/                 invoice_client_create
/billing/clients/<pk>/                   invoice_client_detail
/billing/clients/<pk>/update/            invoice_client_update
/billing/clients/<pk>/delete/            invoice_client_delete

/billing/invoices/                       invoice_list
/billing/invoices/create/                invoice_create
/billing/invoices/<pk>/                  invoice_detail
/billing/invoices/<pk>/update/           invoice_update
/billing/invoices/<pk>/delete/           invoice_delete
/billing/invoices/<pk>/print/            invoice_print
/billing/invoices/<pk>/issue/            invoice_issue
/billing/invoices/<pk>/mark-sent/        invoice_mark_sent
/billing/invoices/<pk>/cancel/           invoice_cancel
/billing/invoices/<pk>/payments/create/  invoice_payment_create

/billing/lines/create/                   invoice_line_create
/billing/lines/<pk>/update/              invoice_line_update
/billing/lines/<pk>/delete/              invoice_line_delete

/billing/projects/<project_pk>/generate/ invoice_generate_from_project
```

### 2.4 Templates créés
- `templates/project/invoice_client/list.html`
- `templates/project/invoice_client/form.html`
- `templates/project/invoice_client/detail.html`
- `templates/project/invoice/list.html` (avec KPI agrégés)
- `templates/project/invoice/form.html`
- `templates/project/invoice/detail.html` (lignes, totaux HT/TVA/TTC, paiements inline)
- `templates/project/invoice/print.html` (vue d'impression A4)
- `templates/project/invoice/generate.html` (formulaire de génération)
- `templates/project/invoice_line/form.html`

### 2.5 Admin Django
Enregistrement dans `project/admin.py` avec inlines `InvoiceLineInline` et `InvoicePaymentInline`, action « Recalculer les totaux », autocomplete sur `project`/`client`/`issued_by`, filtres et recherche.

### 2.6 Migration
`project/migrations/0019_invoicing_and_team_constraints.py` :
1. Remplace `unique_together` de `TeamMembership` par les deux `UniqueConstraint` partielles.
2. Met à jour l'`ordering` de `TeamMembership`.
3. Crée `InvoiceClient`, `Invoice` (avec ses 3 indices et la contrainte d'unicité partielle sur `number`), `InvoiceLine`, `InvoicePayment`.

> Pour appliquer : `python manage.py migrate project 0019`.

---

## 3. Fichiers modifiés / créés

### Modifiés
- `project/models.py` (+ ~280 lignes : `Task.assign/unassign`, contraintes TeamMembership, modèles facturation)
- `project/views.py` (suppression doublons + nouvelles vues facturation + invitation publique)
- `project/forms.py` (filtrage workspace + forms facturation)
- `project/signals.py` (`create_user_profile`, `notify_on_task_assignee_change`)
- `project/admin.py` (admins facturation)
- `ProjectFlow/urls.py` (URLs facturation + invitation publique)

### Créés
- `project/services/invoicing.py`
- `project/services/invitations.py`
- `project/migrations/0019_invoicing_and_team_constraints.py`
- `templates/project/_generic_form.html`
- `templates/project/team/form.html`
- `templates/project/team_membership/form.html`
- `templates/project/project_member/form.html`
- `templates/project/task_assignment/form.html`
- `templates/project/workspace_invitation/accept.html`
- `templates/project/invoice_client/{list,form,detail}.html`
- `templates/project/invoice/{list,form,detail,print,generate}.html`
- `templates/project/invoice_line/form.html`
- `templates/emails/workspace_invitation.{txt,html}`

---

## 4. Validations effectuées

- ✅ Tous les fichiers Python parsent (`ast.parse`) et compilent (`py_compile`).
- ✅ Toutes les vues facturation citées dans les URLs sont définies.
- ✅ Tous les modèles, formulaires et templates référencés existent.
- ✅ `TaskQuickAssignView` et `TaskQuickCommentView` n'apparaissent qu'une seule fois.
- ✅ Tous les nouveaux noms d'URL sont déclarés.

> ⚠️ `manage.py check` n'a pas pu être exécuté ici parce que le venv embarqué pointe vers une installation Python compilée pour macOS (`Pillow._imaging` est un binaire `darwin.so`). À exécuter localement : `./venv/bin/python manage.py check && ./venv/bin/python manage.py migrate`.

---

## 5. Étapes recommandées après merge

1. `python manage.py migrate project 0019` pour créer les tables facturation et installer les contraintes TeamMembership.
2. Sur la fiche projet, ajouter un bouton « Générer une facture » qui pointe vers `{% url 'invoice_generate_from_project' project.pk %}`.
3. Ajouter une entrée « Facturation » dans la sidebar de navigation principale (section `billing`).
4. Mettre en place un job Celery quotidien qui appelle `Invoice.recompute_totals()` sur toutes les factures `ISSUED`/`SENT` non payées, ce qui basculera automatiquement les `OVERDUE`.
5. Tests à écrire (cf. §6.8 de l'audit) — flow équipe complet + flow facturation.
