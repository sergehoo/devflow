## Imported Claude Cowork project instructions

Je travaille sur un projet nommé DevFlow, qui est un système complet de gestion de projet intégrant des fonctionnalités avancées, notamment :

* Gestion des projets (tâches, équipes, suivi)
* Gestion financière basée sur les TJM (taux journalier moyen) des membres
* Intégration de l’intelligence artificielle pour améliorer la prise de décision, l’analyse des performances et l’optimisation des ressources

Plusieurs modules sont déjà développés dans l’application (backend Django, frontend, logique métier, etc.).

Cependant :

* Le projet n’est pas encore finalisé
* Il existe probablement des incohérences, des manques ou des optimisations possibles

⸻

🔍 Objectifs de la mission

Je souhaite que tu réalises une analyse complète du projet DevFlow afin de :

⸻

1. 🧪 Audit global

* Analyser l’architecture globale (backend, frontend, services)
* Identifier les modules existants et leur niveau de complétude
* Vérifier la cohérence entre :
    * modèles de données
    * logique métier
    * interfaces utilisateur

⸻

2. 🛠️ Corrections et améliorations

* Corriger les erreurs éventuelles (code, logique, UX)
* Optimiser les performances et la structure du code
* Améliorer la lisibilité, la maintenabilité et la scalabilité

⸻

3. 🧩 Complétion des fonctionnalités manquantes

* Identifier les fonctionnalités incomplètes ou absentes
* Proposer et implémenter :
    * modules manquants
    * endpoints API nécessaires
    * vues/templates associés

⸻

4. 🤖 Intégration intelligente de l’IA

* Identifier où l’IA peut apporter une vraie valeur ajoutée :
    * estimation des délais
    * analyse de risques projets
    * recommandation d’allocation de ressources
    * prédiction budgétaire basée sur les TJM
* Proposer une architecture d’intégration (API IA ou modèle local)

⸻

5. 💰 Optimisation de la gestion budgétaire

* Vérifier la cohérence du calcul basé sur les TJM
* Améliorer :
    * suivi des coûts
    * prévisions budgétaires
    * marges
    * rentabilité projet

⸻

6. 🎨 Amélioration UX/UI

* Identifier les incohérences d’interface
* Proposer une expérience utilisateur fluide et moderne
* Harmoniser les composants visuels

⸻

📦 Livrables attendus
* Liste des corrections et améliorations
* Code corrigé et optimisé
* Propositions d’architecture IA et outils intégrés
* Amélioration  UX/UI professionnelles
* Code prêt à intégrer (Django + Tailwind + Alpine.js si nécessaire)

---

## 🔒 Conventions production (Phase 0 — sécurité multi-tenant)

Ces règles sont **non négociables** sur toute nouvelle contribution. Elles
existent pour éviter les fuites de données entre workspaces déjà identifiées
et corrigées en Phase 0. Voir aussi `AUDIT_DEVFLOW_PLAN_EVOLUTION.md`.

### 1. Toute CBV qui override `get_queryset` DOIT appeler `super()`

Les vues DevFlow héritent en cascade de `DevflowListView` /
`DevflowDetailView`, qui appliquent automatiquement `filter_by_workspace` via
`WorkspaceSecurityMixin`. Réécrire `get_queryset()` sans appeler
`super().get_queryset()` court-circuite ce filtre — exactement le bug fixé
sur `MilestoneListView` en Phase 0.

```python
# ✅ Bon
def get_queryset(self):
    return (
        super().get_queryset()
        .select_related("project", "owner")
        .annotate(...)
    )

# ❌ Mauvais — fuite cross-tenant
def get_queryset(self):
    return dm.Milestone.objects.select_related("project").annotate(...)
```

### 2. Toute FBV qui résout un objet par PK DOIT scoper par workspace

Pour les `function-based views` (et toute `View.post` minimaliste) qui ne
peuvent pas s'appuyer sur le mixin, utiliser `get_user_workspace_ids` depuis
`project.utils.workspaces` :

```python
from project.utils.workspaces import get_user_workspace_ids

@login_required
@require_POST
def task_status_update(request):
    user_workspace_ids = get_user_workspace_ids(request.user)
    task = get_object_or_404(
        dm.Task, pk=task_id, workspace_id__in=user_workspace_ids,
    )
    ...
```

Pour les objets liés indirectement (ex. `MeetingActionItem` via `meeting`) :
utiliser `meeting__workspace_id__in=user_workspace_ids`.

### 3. Tout viewset DRF DOIT hériter de `WorkspaceScopedViewSetMixin` + `IsWorkspaceMember`

Phase 0 PR3 a livré `project/api/permissions.py` (mixin + permission) et
`project/api/throttles.py` (rate-limit IA). Convention obligatoire :

```python
from project.api.permissions import IsWorkspaceMember, WorkspaceScopedViewSetMixin

class MyViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = MyModel.objects.all()
    serializer_class = MyModelSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceMember]
```

Le mixin filtre `get_queryset` automatiquement aux workspaces du user
(via `scope_queryset_to_user_workspaces`). La permission `IsWorkspaceMember`
ajoute une vérification object-level (defense in depth).

Pour toute nouvelle action `@action(detail=True)` qui appelle un service IA
payant (OpenAI / Ollama distant), ajouter le throttle :

```python
from project.api.throttles import AIActionRateThrottle

@action(detail=True, methods=["post"], url_path="ai/...",
        throttle_classes=[AIActionRateThrottle])
def my_ai_action(self, request, pk=None):
    ...
```

Le rate est piloté par `settings.DEVFLOW_AI_RATE_LIMIT` (défaut `"30/min"`).

### 4. Tout `workspace_id` reçu en POST/JSON DOIT être vérifié

`user_can_access_workspace(user, workspace)` est l'helper à utiliser avant
de créer un objet dans un workspace passé en paramètre (voir
`ProjectGenesisAPIView`). Sans ce contrôle, un user peut créer un projet
dans le workspace d'un autre tenant.

### 5. Coquille `AInsight` à conserver telle quelle

Le modèle s'appelle `AInsight` au lieu de `AIInsight` (`related_name="ai_insights"`).
À **ne pas corriger** : la migration de renommage casserait toutes les
références FK et la table `django_migrations` en production. Documenté ici
pour éviter les corrections involontaires.

### 6. Aucun nouvel envoi d'email synchrone

Si l'IA Phase 0 a oublié de migrer un envoi, le passer immédiatement par
Celery (`send_task_assignment_email_task.delay(...)`). Pas de `send_mail`
synchrone dans une vue HTTP — bloque la requête sur SMTP.

### 7. Tests de non-régression obligatoires sur les corrections de sécurité

Voir `project/tests_security.py`. Pour toute nouvelle vue exposant un objet
par PK, ajouter un test : "user A workspace W1 ne peut pas atteindre
l'objet de user B workspace W2 → 404 attendu".

---

## 🤖 Provider IA principal — DeepSeek (Phase 4 — PR17)

À partir de Phase 4, le provider IA par défaut est **DeepSeek** (compatible
100 % API OpenAI Chat Completions). L'architecture provider de DevFlow reste
strictement la même : tous les services métier passent par
`project.services.ai.factory.get_ai_provider()` sans modification.

### Configuration prod

```bash
# .env ou variables systemd
DEEPSEEK_API_KEY=sk-...                          # obligatoire pour activer
AI_DEEPSEEK_MODEL=deepseek-chat                  # default
AI_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1 # default
AI_BACKEND=auto                                  # default : DeepSeek prioritaire
```

### Chaîne de fallback en mode `auto`

1. **DeepSeek** (si `DEEPSEEK_API_KEY` non vide)
2. OpenAI (si `OPENAI_API_KEY` non vide)
3. Local (Ollama / vLLM si `AI_LOCAL_BASE_URL` configuré)
4. NullProvider → tous les services basculent automatiquement sur
   leurs heuristiques déterministes (jamais d'erreur utilisateur)

### Modèles DeepSeek utilisables

- `deepseek-chat` — généraliste (V3), default. Bon compromis pour Genesis,
  résumé, recommandations.
- `deepseek-reasoner` — raisonnement (R1). À privilégier pour `risk-analysis`
  et `forecast` si on veut plus de profondeur (override via
  `AI_DEEPSEEK_MODEL` ou paramètre de service).
- `deepseek-coder` — spécialisé code. Pas utilisé par DevFlow par défaut.

### Forcer un autre backend

```bash
AI_BACKEND=openai    # bascule explicite sur OpenAI
AI_BACKEND=local     # force Ollama / vLLM
AI_BACKEND=none      # désactive l'IA, force heuristiques (tests, audits)
```

