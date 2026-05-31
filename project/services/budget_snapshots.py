"""
DevFlow — Services Budget V2 (Phase 3, PR15).

Deux services :

  1. BudgetSnapshotService — capture / compare / list de snapshots budget
     (baseline, forecast, manual, auto). Le snapshot fige un dump JSON
     complet de ``build_budget_overview`` à un instant T, pour pouvoir
     comparer "Baseline V1 vs Forecast actuel" plus tard.

  2. BudgetAlertService — calcule les projets en dépassement de seuil
     (alert_threshold_percent sur ProjectBudget). Renvoie une liste
     structurée prête à servir pour /api/v1/.../alerts/ et pour la tâche
     Celery périodique.

Aucune action IA — purement déterministe et SQL-friendly.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from project import models as dm
from project.services.budget import ProjectBudgetService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers JSON
# ---------------------------------------------------------------------------
def _serialize_for_json(value: Any) -> Any:
    """Convertit récursivement Decimal/date/datetime en types JSON-safe."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_for_json(v) for v in value]
    return value


def _decimal_or_zero(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------
class BudgetSnapshotService:
    """
    Crée et compare des ProjectBudgetSnapshot.

    Pattern d'usage typique :
      1. Lors de la validation initiale du budget (status BASELINE) →
         capture(kind=BASELINE, label="Baseline V1")
      2. Tous les mois ou à chaque modif significative →
         capture(kind=FORECAST, label="Forecast mars 2026")
      3. Pour voir l'écart → compare(baseline, last_forecast)
    """

    @classmethod
    def capture(
        cls,
        project: dm.Project,
        *,
        label: str | None = None,
        kind: str = dm.ProjectBudgetSnapshot.SnapshotKind.MANUAL,
        actor=None,
        notes: str = "",
    ) -> dm.ProjectBudgetSnapshot:
        """
        Fige le budget courant du projet sous forme de snapshot JSON.

        Le payload contient le dump de ``build_budget_overview(project)``
        (tous les montants, marges, %, currency, etc.) prêt à être
        re-consommé par la vue de comparaison.
        """
        overview = ProjectBudgetService.build_budget_overview(project)
        payload = _serialize_for_json(overview)

        snapshot_date = timezone.localdate()
        effective_label = label or (
            f"{kind.title()} {snapshot_date:%Y-%m-%d}"
            if kind else f"Snapshot {snapshot_date:%Y-%m-%d}"
        )

        snapshot = dm.ProjectBudgetSnapshot.objects.create(
            workspace=project.workspace,
            project=project,
            label=effective_label,
            kind=kind,
            snapshot_date=snapshot_date,
            payload=payload,
            created_by=actor,
            notes=notes,
        )
        return snapshot

    @classmethod
    def latest(
        cls,
        project: dm.Project,
        *,
        kind: str | None = None,
    ) -> dm.ProjectBudgetSnapshot | None:
        """Retourne le dernier snapshot (filtré par kind si fourni)."""
        qs = dm.ProjectBudgetSnapshot.objects.filter(project=project)
        if kind:
            qs = qs.filter(kind=kind)
        return qs.order_by("-snapshot_date", "-id").first()

    @classmethod
    def compare(
        cls,
        snapshot_a: dm.ProjectBudgetSnapshot,
        snapshot_b: dm.ProjectBudgetSnapshot,
    ) -> dict:
        """
        Compare deux snapshots et retourne un dict d'écarts numériques.

        Convention : b - a (donc valeurs positives = augmentation entre A et B).
        Seules les clés numériques communes sont diffées ; les clés textes
        sont reportées telles quelles (currency, label).
        """
        a, b = snapshot_a.payload or {}, snapshot_b.payload or {}
        diff: dict[str, Any] = {}

        for key in set(a.keys()) | set(b.keys()):
            va, vb = a.get(key), b.get(key)
            # Comparaison numérique si convertible des deux côtés
            try:
                da = _decimal_or_zero(va)
                db = _decimal_or_zero(vb)
                # On filtre les clés clairement non-numériques pour ne pas
                # polluer le diff avec des "0" de fallback partout.
                if (va is None or isinstance(va, (int, float)) or
                        (isinstance(va, str) and va.replace(".", "", 1).replace("-", "", 1).isdigit())):
                    diff[key] = {
                        "before": str(da),
                        "after": str(db),
                        "delta": str(db - da),
                    }
                    continue
            except Exception:
                pass
            diff[key] = {"before": va, "after": vb}

        return {
            "snapshot_a": {
                "id": snapshot_a.pk,
                "label": snapshot_a.label,
                "snapshot_date": snapshot_a.snapshot_date.isoformat(),
                "kind": snapshot_a.kind,
            },
            "snapshot_b": {
                "id": snapshot_b.pk,
                "label": snapshot_b.label,
                "snapshot_date": snapshot_b.snapshot_date.isoformat(),
                "kind": snapshot_b.kind,
            },
            "diff": diff,
        }


# ---------------------------------------------------------------------------
# Alertes budget
# ---------------------------------------------------------------------------
@dataclass
class BudgetAlert:
    project_id: int
    project_name: str
    workspace_id: int
    severity: str          # "info" | "warning" | "critical"
    consumption_percent: int
    alert_threshold_percent: int
    approved_budget: str   # str(Decimal) pour JSON-safe
    actual_cost: str
    forecast_final_cost: str
    currency: str

    def to_dict(self) -> dict:
        return asdict(self)


class BudgetAlertService:
    """
    Détecte les projets en dépassement de seuil et qualifie l'alerte.

    Stratégie de seuil :
      * consumption >= threshold      → info
      * consumption >= threshold + 10 → warning
      * consumption >= 100            → critical
    """

    INFO_OFFSET = 0
    WARNING_OFFSET = 10
    CRITICAL_THRESHOLD = 100

    @classmethod
    def _classify(cls, consumption: int, threshold: int) -> str | None:
        if consumption >= cls.CRITICAL_THRESHOLD:
            return "critical"
        if consumption >= threshold + cls.WARNING_OFFSET:
            return "warning"
        if consumption >= threshold + cls.INFO_OFFSET:
            return "info"
        return None

    @classmethod
    def for_project(cls, project: dm.Project) -> BudgetAlert | None:
        """
        Calcule l'alerte courante pour un projet précis.
        Retourne None si pas d'alerte (consumption < threshold).
        """
        budget = getattr(project, "budgetestimatif", None)
        if budget is None or not budget.alert_threshold_percent:
            return None

        overview = ProjectBudgetService.build_budget_overview(project)
        consumption = int(overview.get("forecast_consumption_percent") or 0)
        threshold = int(budget.alert_threshold_percent)

        severity = cls._classify(consumption, threshold)
        if severity is None:
            return None

        return BudgetAlert(
            project_id=project.pk,
            project_name=project.name,
            workspace_id=project.workspace_id,
            severity=severity,
            consumption_percent=consumption,
            alert_threshold_percent=threshold,
            approved_budget=str(overview.get("approved_budget") or "0"),
            actual_cost=str(overview.get("actual_cost") or "0"),
            forecast_final_cost=str(overview.get("forecast_final_cost") or "0"),
            currency=overview.get("currency") or "XOF",
        )

    @classmethod
    def for_workspace(
        cls,
        workspace: dm.Workspace,
        *,
        only_active: bool = True,
    ) -> list[BudgetAlert]:
        """Liste les alertes en cours sur tous les projets du workspace."""
        qs = dm.Project.objects.filter(workspace=workspace, is_archived=False)
        if only_active:
            qs = qs.filter(status__in=[
                dm.Project.Status.PLANNED,
                dm.Project.Status.IN_PROGRESS,
                dm.Project.Status.IN_DELIVERY,
                dm.Project.Status.BLOCKED,
                dm.Project.Status.DELAYED,
                dm.Project.Status.ON_HOLD,
            ])

        alerts = []
        for project in qs.select_related("workspace"):
            try:
                alert = cls.for_project(project)
                if alert:
                    alerts.append(alert)
            except Exception as exc:
                logger.warning(
                    "BudgetAlertService failed for project %s: %s",
                    project.pk, exc,
                )

        # Trier par sévérité décroissante puis consommation décroissante
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        alerts.sort(key=lambda a: (
            severity_order.get(a.severity, 99),
            -a.consumption_percent,
        ))
        return alerts


# ---------------------------------------------------------------------------
# EAC + Cost Variance — calcul périodique
# ---------------------------------------------------------------------------
class ProjectEACService:
    """
    Calcule et stocke Project.computed_eac et Project.computed_cost_variance.

    EAC (Estimate at Completion) = actual_cost + RAF_cost
        — coût total prévu à la fin du projet, basé sur ce qu'on a déjà
          dépensé + ce qu'il reste à faire.

    Cost Variance = forecast_final_cost - approved_budget
        — positif = dépassement attendu, négatif = économie attendue.
    """

    @classmethod
    def recompute(cls, project: dm.Project) -> dict:
        """
        Recalcule les 2 indicateurs et persiste sur l'instance Project.
        Retourne un dict de stats pour log.
        """
        overview = ProjectBudgetService.build_budget_overview(project)
        eac = _decimal_or_zero(overview.get("forecast_final_cost"))
        approved = _decimal_or_zero(overview.get("approved_budget"))
        variance = eac - approved

        dm.Project.objects.filter(pk=project.pk).update(
            computed_eac=eac,
            computed_cost_variance=variance,
            eac_computed_at=timezone.now(),
        )
        return {
            "project_id": project.pk,
            "eac": str(eac),
            "variance": str(variance),
            "approved_budget": str(approved),
        }

    @classmethod
    def recompute_workspace(
        cls,
        workspace: dm.Workspace,
        *,
        only_active: bool = True,
    ) -> dict:
        """Recalcule l'EAC pour tous les projets actifs d'un workspace."""
        qs = dm.Project.objects.filter(
            workspace=workspace, is_archived=False,
        )
        if only_active:
            qs = qs.exclude(status__in=[
                dm.Project.Status.DONE,
                dm.Project.Status.CANCELLED,
            ])

        stats = {"recomputed": 0, "errors": 0}
        for project in qs:
            try:
                cls.recompute(project)
                stats["recomputed"] += 1
            except Exception as exc:
                stats["errors"] += 1
                logger.warning(
                    "ProjectEACService.recompute failed for %s: %s",
                    project.pk, exc,
                )
        return stats
