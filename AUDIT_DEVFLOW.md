# Audit DevFlow — Module Financier (TJM) & Couche IA

Date: 2026-04-26
Périmètre : `project/models.py`, `project/services/budget.py`, `project/views_budget.py`, `project/forms_budget.py`, `project/api/`, `project/services/*ai*`, `templates/project/budget/*`, `templates/project/expense/*`, `ProjectFlow/settings/*`.

---

## 1. Synthèse

DevFlow est techniquement bien armé : Django 4.2 + DRF + Channels + Celery + Redis, 2520 lignes de modèles, services métier séparés, templates riches en Tailwind. La logique TJM/budget existe et tient la route conceptuellement (BillingRate → Tâche → EstimateLine → ProjectBudget → ExpenseService → Overview). Mais plusieurs points d'arrêt empêchent le module financier de fonctionner correctement en production, et la couche IA est partiellement câblée seulement.

État synthétique :

| Domaine | Couverture | Bugs critiques | Action |
|---|---|---|---|
| Modèles financiers | 90% | 0 | OK + ajouts utiles |
| Service budget (`services/budget.py`) | 75% | 3 | Refactor partiel |
| Vues budget (`views_budget.py`) | 80% | 2 | Patch + harmonisation |
| API REST (`project/api/`) | 0% | – | À créer entièrement |
| Couche IA générique | 30% | 1 | Architecture pluggable à introduire |
| Services IA financiers | 0% | – | À créer (estimation, risques, prévisions) |
| Templates budget | 85% | 1 | Patch + harmonisation visuelle |
| Signaux financiers | 0% | – | À créer (TimesheetCostSnapshot auto) |
| Tests financiers | 0% | – | À créer |

---

## 2. Bugs critiques (bloquants)

### 2.1 `views_budget.py` — méthode inexistante
- **Lignes 514, 534** : `self.can_view_financial_data(project)` appelé alors que la méthode du mixin s'appelle `can_view_financials`.
- **Impact** : `AttributeError` au premier appel des vues `GenerateEstimateLinesFromTasksView` et `RecalculateProjectBudgetView`, donc deux URLs cassées (`project_generate_estimates`, `project_recalculate_budget`).
- **Correctif** : renommer les appels et factoriser la garde.

### 2.2 `services/project_ai_import_service.py` — import inexistant
- **Ligne 13** : `from project.services.project_budget_service import ProjectBudgetService` — le module est en réalité `project.services.budget`.
- **Impact** : `ImportError` immédiat dès qu'on charge le service d'import IA → toute la fonctionnalité d'import projet par IA est cassée.
- **Correctif** : `from project.services.budget import ProjectBudgetService`.

### 2.3 `services/project_document_ai_service.py` — `NotImplementedError`
- **Ligne 88** : la méthode `call_llm_to_structured_json` lève `NotImplementedError`.
- **Impact** : l'import d'un document via IA ne peut jamais aboutir, même si tout le reste fonctionne.
- **Correctif** : implémenter via le client OpenAI (déjà présent dans `services/openai_client.py`) ou via un backend pluggable.

### 2.4 `services/budget.py` — calculs erronés sur revenus & dépenses
- `summarize_revenues` : `invoiced = planned`. Faux. Il faut sommer `invoiced_amount`.
- `summarize_revenues` : `received` somme `amount` au lieu de `received_amount`. Faux pour les paiements partiels.
- `summarize_expenses` : tout `DRAFT` est mappé à la fois à `estimated`, `forecast` et `committed`. Cela entraîne du double-comptage dans `forecast_final_cost = actual + committed + raf`.
- `summarize_expenses` : `committed` n'utilise pas le statut `COMMITTED` réellement présent dans `ProjectExpense.ExpenseStatus`.
- `summarize_timesheets` : `logged_sale = 0` toujours, alors que le TJM de vente est connu.
- **Impact** : la marge prévisionnelle, le `forecast_consumption_percent`, les KPI de cockpit sont faussés.

### 2.5 Template `budget/detail.html` — variable inexistante
- Ligne 87 : `{{ overview.total_received }}` n'existe pas dans le retour de `build_budget_overview`. La clé correcte est `received_revenue`.
- **Impact** : le bloc « Reçu » du dashboard Budget affiche toujours vide.

### 2.6 API REST — fichiers vides
- `project/api/serializers.py`, `project/api/viewsets.py`, `project/api/urls.py` font tous **0 ligne**.
- **Impact** : aucune API REST disponible alors que `drf_spectacular` est installé. Frontend mobile / intégrations externes impossibles.

---

## 3. Incohérences et manques fonctionnels

### 3.1 Modèles financiers
- `ProjectExpense` a un statut riche (`DRAFT/ESTIMATED/FORECAST/COMMITTED/ACCRUED/PAID/VALIDATED/REJECTED`) mais le service `summarize_expenses` n'exploite que `DRAFT`/`VALIDATED`/`REJECTED`.
- Pas de signal `post_save` sur `TimesheetEntry` pour créer/maj `TimesheetCostSnapshot` ⇒ le coût main-d'œuvre réel basé sur les heures pointées n'est jamais calculé.
- `ProjectExpense.is_direct_cost` et `is_labor_cost` peuvent être tous deux `True` côté modèle (même si le form interdit cette combinaison) ; aucun `clean()` côté modèle ne le bloque.
- Pas de gestion multi-devise (somme directe sans conversion).
- `ProjectBudget` est `OneToOneField` avec `related_name='budgetestimatif'` → nom hors convention Django/français usurpé. Maintien possible mais à harmoniser.
- `SprintFinancialSnapshot` et `FeatureFinancialSnapshot` existent mais ne sont jamais peuplés.

### 3.2 Logique TJM
- `BillingRate.get_user_daily_cost` et `get_user_sale_daily_rate` sont presque copies-coller (même logique sauf champ). À factoriser.
- `MONTHLY → /22` jours est codé en dur. Devrait s'aligner sur le `DEFAULT_WORKING_DAYS_PER_MONTH` du service budget.
- Pas de fallback si l'utilisateur a une `availability_percent < 100` sur son profil.
- Pas de service donnant le coût d'un membre **sur une période donnée** (nécessaire pour les prévisions).

### 3.3 Vues
- Trois vues utilisent `request.GET.get("project")` pour rattacher l'objet, ce qui est fragile (URL forge possible). À sécuriser via FormView dédiée et `get_form_kwargs`.
- Pas de vue `ProjectBudgetListView` ni de vue de listing des revenus.
- Pas d'API JSON pour les graphes (le frontend appelle l'overview en context puis Chart.js, pas idéal pour le live refresh).

### 3.4 Couche IA
- Seul le flow d'import projet est tenté. Aucun service pour :
  - **estimation des délais** (effort par tâche/sprint)
  - **analyse des risques** (alimente `Project.ai_risk_label`/`risk_score`)
  - **recommandation d'allocation des ressources**
  - **prévision budgétaire** (forecast TJM × allocation × période)
- `AInsight` est un excellent stockage mais n'est jamais peuplé automatiquement.
- Pas d'abstraction provider : tout est lié à OpenAI directement, pas de fallback local possible.

### 3.5 UX / UI
- Cohérence Tailwind globalement bonne (variables `devbg2`, `devaccent`, etc.).
- Quelques templates utilisent des classes inexistantes (`prog-fill`, `pf-red`) qui sont définies dans `static/css` mais à valider.
- Pas de page « Cockpit financier portfolio » (vision multi-projets).
- Pas de visualisation Burn-up budgétaire dans `budget/detail.html`.

---

## 4. Optimisations de performance

- `summarize_estimate_lines` boucle Python sur toutes les lignes pour répartir par catégorie ⇒ remplacer par `aggregate(... filter=Q(...))`.
- `summarize_expenses` même remarque + boucle Python pour `expense.category.category_type`.
- `ProjectExpenseListView.get_context_data` itère sur la page pour calculer 4 booléens par dépense ⇒ acceptable mais pourrait remonter au niveau queryset via annotations + permissions précomputées.
- `BillingRate.get_user_daily_cost` est appelée dans une boucle sur les membres dans `estimate_project_members_costs` ⇒ une requête par membre. À batcher avec un préchargement des `BillingRate` actifs.
- `ProjectBudgetForm` charge tinymce sur `notes` (ok) mais aussi force `data-tinymce` sur le `description` de `ProjectExpenseForm` même si déjà géré par `StyledModelForm`.

---

## 5. Recommandations prioritaires (par ordre d'impact)

1. **Patcher les bugs bloquants** (2.1 → 2.5).
2. **Créer le squelette API REST** (`/api/` viewsets + serializers + spectacular schema).
3. **Câbler le signal TimesheetEntry → TimesheetCostSnapshot** pour avoir le coût réel.
4. **Refactorer `services/budget.py`** : remplacer les boucles Python par des aggregations, corriger les mappings, exposer les services « par période ».
5. **Introduire une couche IA pluggable** (`AIProvider` interface, backends `OpenAIProvider` + `LocalProvider`).
6. **Implémenter 4 services IA financiers** : estimation tâches, prévision budgétaire, analyse risques, recommandation d'allocation.
7. **Compléter UX budget** : burn-up, fix `total_received`, page cockpit portfolio.
8. **Ajouter une suite de tests unitaires** sur les calculs TJM et la logique de marge.

---

## 6. Architecture IA proposée (hybride)

```
project/services/ai/
├── __init__.py
├── base.py              # AIProvider interface (abstract)
├── openai_provider.py   # Implémentation OpenAI Chat Completions
├── local_provider.py    # Implémentation Ollama / HTTP local
├── factory.py           # AIProviderFactory selon settings.AI_BACKEND
├── prompts/
│   ├── budget_forecast.py
│   ├── risk_analysis.py
│   ├── effort_estimation.py
│   └── allocation_advice.py
└── services/
    ├── budget_forecast.py     # Prévision budgétaire TJM-based
    ├── risk_analysis.py       # Analyse risques projet → AInsight
    ├── effort_estimation.py   # Estimation effort tâche
    └── allocation_advice.py   # Recommandation allocation membres
```

Configuration via `settings.AI_BACKEND` (`openai` | `local` | `auto`). En mode `auto`, le factory choisit OpenAI pour les tâches qualité (estimation, recommandations) et le provider local pour les tâches volumineuses ou sensibles (analyse de gros backlogs, scoring batch).

Chaque service IA garantit :
- Un fallback déterministe sans IA (heuristiques). Si l'IA échoue, le service renvoie un résultat heuristique propre — jamais d'erreur 500.
- La persistance dans `AInsight` quand pertinent (risques, alertes budget).
- Un cache court (Redis, 5 min) pour ne pas spammer le LLM sur les mêmes inputs.

---

## 7. Plan d'implémentation (livré dans cette mission)

- [x] Audit (ce document)
- [ ] `services/budget.py` v2 — corrections + agrégations + helpers TJM par période
- [ ] `views_budget.py` — fix `can_view_financial_data` + sécurisation
- [ ] `signals.py` — TimesheetEntry → TimesheetCostSnapshot auto
- [ ] `services/ai/` — couche provider hybride + 4 services
- [ ] `api/` — serializers + viewsets + urls REST
- [ ] Templates — fix `total_received`, partial cockpit budget refondu
- [ ] `tests/test_budget.py` — couverture des calculs TJM & marge
- [ ] `settings/base.py` — variables `AI_BACKEND`, `AI_LOCAL_URL`
