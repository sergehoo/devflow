"""
Workflow hebdomadaire des timesheets.

    Employé saisit (DRAFT) → Soumet (SUBMITTED) → N+1 valide (APPROVED, verrouillé)
                                                 ↘ N+1 rejette (REJECTED) → correction (DRAFT) → re-soumission

Règles :
  * seul le manager direct (UserProfile.manager, N+1) valide / rejette ;
  * une semaine SUBMITTED ou APPROVED n'est plus modifiable par l'employé ;
  * chaque transition est tracée dans TimesheetApprovalLog ;
  * le quota hebdomadaire vient de UserProfile.capacity_hours_per_week,
    proratisé sur les jours ouvrés (et la date d'arrivée).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from project import models as dm

Status = dm.TimesheetEntry.ApprovalStatus

DEFAULT_WEEKLY_HOURS = Decimal("40")
WORKING_DAYS = 5
LOCKED_STATUSES = {Status.SUBMITTED, Status.APPROVED}


class TimesheetWorkflowError(Exception):
    """Transition refusée (droits, état, verrou)."""


# ---------------------------------------------------------------------------
# Calendrier & quota
# ---------------------------------------------------------------------------
def week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def get_profile(user, workspace):
    """Profil de l'utilisateur dans ce workspace (None si rattaché ailleurs)."""
    profile = dm.UserProfile.objects.filter(user=user, workspace=workspace).first()
    return profile


def weekly_capacity(user, workspace) -> Decimal:
    profile = get_profile(user, workspace)
    if profile and profile.capacity_hours_per_week is not None:
        return Decimal(profile.capacity_hours_per_week)
    return DEFAULT_WEEKLY_HOURS


def expected_hours(user, workspace, monday: date, upto: date | None = None) -> Decimal:
    """
    Heures attendues sur la semaine (jours ouvrés lun→ven), proratisées :
      * à partir de la date d'arrivée (joined_company_at) ;
      * jusqu'à ``upto`` inclus (ex. aujourd'hui pour une semaine en cours).
    """
    profile = get_profile(user, workspace)
    capacity = (
        Decimal(profile.capacity_hours_per_week)
        if profile and profile.capacity_hours_per_week is not None
        else DEFAULT_WEEKLY_HOURS
    )
    start = monday
    if profile and profile.joined_company_at and profile.joined_company_at > start:
        start = profile.joined_company_at
    end = monday + timedelta(days=WORKING_DAYS - 1)
    if upto is not None and upto < end:
        end = upto
    days = sum(
        1 for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() < WORKING_DAYS
    ) if end >= start else 0
    return (capacity / WORKING_DAYS * days).quantize(Decimal("0.01"))


def week_entries(user, workspace, monday: date):
    return dm.TimesheetEntry.objects.filter(
        user=user, workspace=workspace,
        entry_date__gte=monday, entry_date__lte=monday + timedelta(days=6),
    )


def consolidated_status(statuses) -> str:
    statuses = set(statuses)
    if not statuses:
        return ""
    if statuses == {Status.APPROVED}:
        return Status.APPROVED
    if Status.REJECTED in statuses:
        return Status.REJECTED
    if Status.SUBMITTED in statuses:
        return Status.SUBMITTED
    return Status.DRAFT


@dataclass
class WeekSummary:
    monday: date
    status: str
    is_locked: bool
    total_hours: Decimal
    planned_hours: Decimal
    capacity: Decimal
    expected: Decimal
    day_totals: dict = field(default_factory=dict)
    last_log: object = None

    @property
    def status_label(self) -> str:
        return dict(Status.choices).get(self.status, "Aucune saisie")

    @property
    def completion_percent(self) -> int:
        if not self.expected:
            return 100 if self.total_hours else 0
        return int(round(self.total_hours / self.expected * 100))

    @property
    def missing_hours(self) -> Decimal:
        return max(Decimal("0"), self.expected - self.total_hours)


def week_summary(user, workspace, monday: date, upto: date | None = None) -> WeekSummary:
    qs = week_entries(user, workspace, monday)
    status = consolidated_status(qs.values_list("approval_status", flat=True))
    agg = qs.aggregate(total=Sum("hours"), planned=Sum("planned_hours"))
    day_totals = {
        row["entry_date"]: row["total"] or Decimal("0")
        for row in qs.values("entry_date").annotate(total=Sum("hours"))
    }
    return WeekSummary(
        monday=monday,
        status=status,
        is_locked=status in LOCKED_STATUSES or bool(
            qs.filter(approval_status__in=LOCKED_STATUSES).exists()
        ),
        total_hours=agg["total"] or Decimal("0"),
        planned_hours=agg["planned"] or Decimal("0"),
        capacity=weekly_capacity(user, workspace),
        expected=expected_hours(user, workspace, monday, upto=upto),
        day_totals=day_totals,
        last_log=dm.TimesheetApprovalLog.objects.filter(
            workspace=workspace, employee=user, week_start=monday,
        ).select_related("actor").first(),
    )


# ---------------------------------------------------------------------------
# Hiérarchie
# ---------------------------------------------------------------------------
def is_direct_manager(manager_user, employee_user, workspace) -> bool:
    profile = get_profile(employee_user, workspace)
    return bool(
        profile and profile.manager_id
        and profile.manager.user_id == manager_user.pk
        and profile.manager.workspace_id == workspace.pk
    )


def direct_report_users(manager_user, workspace):
    profile = get_profile(manager_user, workspace)
    if not profile:
        return []
    return [p.user for p in profile.direct_reports.select_related("user").filter(workspace=workspace)]


def visible_user_ids(user, workspace) -> set[int]:
    """Soi-même + tous ses subordonnés (directs et indirects)."""
    ids = {user.pk}
    profile = get_profile(user, workspace)
    if profile:
        ids.update(p.user_id for p in profile.all_reports() if p.workspace_id == workspace.pk)
    return ids


# ---------------------------------------------------------------------------
# Verrou & transitions
# ---------------------------------------------------------------------------
def assert_week_editable(user, workspace, day: date) -> None:
    monday, sunday = week_bounds(day)
    if dm.TimesheetEntry.objects.filter(
        user=user, workspace=workspace, entry_date__gte=monday, entry_date__lte=sunday,
        approval_status__in=LOCKED_STATUSES,
    ).exists():
        raise TimesheetWorkflowError(
            "Cette semaine est soumise ou validée : elle n'est plus modifiable."
        )


def reopen_rejected_for_correction(user, workspace, day: date) -> int:
    """Correction après rejet : les lignes REJECTED de la semaine repassent en DRAFT."""
    monday, sunday = week_bounds(day)
    return dm.TimesheetEntry.objects.filter(
        user=user, workspace=workspace, entry_date__gte=monday, entry_date__lte=sunday,
        approval_status=Status.REJECTED,
    ).update(approval_status=Status.DRAFT)


def _log(workspace, employee, monday, action, actor, comment, qs):
    agg = qs.aggregate(total=Sum("hours"))
    return dm.TimesheetApprovalLog.objects.create(
        workspace=workspace, employee=employee, week_start=monday,
        action=action, actor=actor, comment=comment or "",
        total_hours=agg["total"] or 0, entry_count=qs.count(),
    )


def _notify(recipient, workspace, title, body, url="/timesheets/list/"):
    from project.services.notifications import create_in_app_notification

    return create_in_app_notification(
        recipient=recipient, workspace=workspace,
        notification_type=dm.Notification.NotificationType.SYSTEM,
        title=title[:180], body=body, url=url,
    )


@transaction.atomic
def submit_week(user, workspace, monday: date) -> int:
    monday, _ = week_bounds(monday)
    qs = week_entries(user, workspace, monday)
    if not qs.exists():
        raise TimesheetWorkflowError("Aucune saisie à soumettre pour cette semaine.")
    if qs.filter(approval_status__in=LOCKED_STATUSES).exists():
        raise TimesheetWorkflowError("Cette semaine est déjà soumise ou validée.")
    count = qs.update(approval_status=Status.SUBMITTED, approved_by=None, approved_at=None)
    _log(workspace, user, monday, dm.TimesheetApprovalLog.Action.SUBMITTED, user, "", qs)

    profile = get_profile(user, workspace)
    if profile and profile.manager_id:
        _notify(
            profile.manager.user, workspace,
            f"Timesheet à valider : {user.get_full_name() or user.username}",
            f"Semaine du {monday:%d/%m/%Y} soumise pour validation.",
        )
    return count


@transaction.atomic
def review_week(reviewer, employee, workspace, monday: date, *, approve: bool, comment: str = "") -> int:
    monday, _ = week_bounds(monday)
    if reviewer.pk == employee.pk:
        raise TimesheetWorkflowError("Vous ne pouvez pas valider votre propre timesheet.")
    if not is_direct_manager(reviewer, employee, workspace):
        raise TimesheetWorkflowError("Seul le manager direct (N+1) peut valider ce timesheet.")
    comment = (comment or "").strip()
    if not approve and not comment:
        raise TimesheetWorkflowError("Un commentaire est obligatoire pour rejeter.")

    qs = week_entries(employee, workspace, monday)
    if not qs.filter(approval_status=Status.SUBMITTED).exists():
        raise TimesheetWorkflowError("Aucune saisie soumise à valider pour cette semaine.")

    new_status = Status.APPROVED if approve else Status.REJECTED
    count = qs.update(
        approval_status=new_status, approved_by=reviewer, approved_at=timezone.now(),
    )
    action = dm.TimesheetApprovalLog.Action.APPROVED if approve else dm.TimesheetApprovalLog.Action.REJECTED
    _log(workspace, employee, monday, action, reviewer, comment, qs)
    _notify(
        employee, workspace,
        f"Timesheet {'validé' if approve else 'rejeté'} — semaine du {monday:%d/%m/%Y}",
        comment or "Votre semaine est validée et verrouillée.",
        url=f"/timesheets/?date={monday:%Y-%m-%d}",
    )
    return count


@transaction.atomic
def reopen_week(reviewer, employee, workspace, monday: date, comment: str = "") -> int:
    """Déverrouillage exceptionnel d'une semaine validée, réservé au N+1."""
    monday, _ = week_bounds(monday)
    if not is_direct_manager(reviewer, employee, workspace):
        raise TimesheetWorkflowError("Seul le manager direct (N+1) peut rouvrir ce timesheet.")
    qs = week_entries(employee, workspace, monday)
    count = qs.update(approval_status=Status.DRAFT, approved_by=None, approved_at=None)
    if not count:
        raise TimesheetWorkflowError("Aucune saisie pour cette semaine.")
    _log(workspace, employee, monday, dm.TimesheetApprovalLog.Action.REOPENED, reviewer, comment, qs)
    return count
