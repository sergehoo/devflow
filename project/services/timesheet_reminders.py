"""
Relances timesheet & rapport hebdomadaire managers (appelés par Celery beat).

  * send_daily_reminders  — jours ouvrés : membres sans saisie du jour ;
  * send_weekly_checks    — fin de semaine : incomplet → alerte employé + N+1,
                            aucune saisie → alerte critique ;
  * send_weekly_reports   — N+1 : détail de son équipe ; direction : consolidé.

Anti-doublon : TimesheetReminderLog (unique workspace/user/kind/période).
Préférences : NotificationPreference (in-app, email, fréquence, silence).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from project import models as dm
from project.services import timesheet_workflow as tw

logger = logging.getLogger(__name__)
User = get_user_model()
Kind = dm.TimesheetReminderLog.Kind
ACTIVE_STATUSES = [dm.TeamMembership.Status.ACTIVE, dm.TeamMembership.Status.REMOTE]


# ---------------------------------------------------------------------------
# Destinataires & préférences
# ---------------------------------------------------------------------------
def active_workspaces():
    return dm.Workspace.objects.filter(is_active=True, is_archived=False)


def expected_members(workspace, day: date):
    """Membres actifs attendus sur le timesheet à cette date."""
    users = (
        User.objects.filter(
            is_active=True,
            devflow_memberships__workspace=workspace,
            devflow_memberships__status__in=ACTIVE_STATUSES,
        )
        .distinct()
        .order_by("last_name", "first_name", "username")
    )
    arrivals = dict(
        dm.UserProfile.objects.filter(workspace=workspace, user__in=users)
        .values_list("user_id", "joined_company_at")
    )
    return [u for u in users if not arrivals.get(u.pk) or arrivals[u.pk] <= day]


def _email_allowed(user, *, critical=False) -> bool:
    from project.services.smart_notifications import (
        NotificationPreferenceService,
        SmartNotificationDispatcher,
    )

    if not user.email:
        return False
    prefs = NotificationPreferenceService.get_or_create(user)
    if prefs.notify_frequency == dm.NotificationPreference.NotifyFrequency.DISABLED or not prefs.channel_email:
        return False
    if critical:
        return True
    probe = dm.Notification(recipient=user, notification_type=dm.Notification.NotificationType.SYSTEM)
    return SmartNotificationDispatcher.should_send_email_now(probe)


def _in_app_allowed(user) -> bool:
    from project.services.smart_notifications import NotificationPreferenceService

    prefs = NotificationPreferenceService.get_or_create(user)
    return prefs.channel_in_app and prefs.notify_frequency != dm.NotificationPreference.NotifyFrequency.DISABLED


def _notify(user, workspace, *, subject, body, url, critical=False) -> bool:
    """In-app + email selon préférences. Retourne True si un email est parti."""
    from project.services.notifications import create_in_app_notification

    if _in_app_allowed(user):
        create_in_app_notification(
            recipient=user, workspace=workspace,
            notification_type=dm.Notification.NotificationType.SYSTEM,
            title=subject[:180], body=body[:2000], url=url,
            metadata={"source": "timesheet", "critical": critical},
        )
    if not _email_allowed(user, critical=critical):
        return False
    try:
        from project.utils.urls import absolute_url

        send_mail(
            subject=f"[DevFlow] {subject}",
            message=f"{body}\n\nOuvrir dans DevFlow : {absolute_url(url)}",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("timesheet email failed for user %s", user.pk)
        return False


def _claim(workspace, user, kind, period_start):
    """Réserve l'envoi (unique) ; None si déjà fait."""
    try:
        with transaction.atomic():
            return dm.TimesheetReminderLog.objects.create(
                workspace=workspace, user=user, kind=kind, period_start=period_start,
            )
    except IntegrityError:
        return None


def _name(user):
    return user.get_full_name() or user.username


def _fmt_h(value) -> str:
    value = Decimal(value or 0).quantize(Decimal("0.1"))
    return f"{value.normalize():f}h" if value == value.to_integral() else f"{value}h"


# ---------------------------------------------------------------------------
# Relances
# ---------------------------------------------------------------------------
def send_daily_reminders(day: date | None = None) -> dict:
    day = day or timezone.localdate()
    if day.weekday() >= tw.WORKING_DAYS:
        return {"skipped": "weekend"}
    stats = {"notified": 0, "emails": 0}
    for ws in active_workspaces():
        logged = set(
            dm.TimesheetEntry.objects.filter(workspace=ws, entry_date=day, hours__gt=0)
            .values_list("user_id", flat=True)
        )
        for user in expected_members(ws, day):
            if user.pk in logged:
                continue
            log = _claim(ws, user, Kind.DAILY_MISSING, day)
            if log is None:
                continue
            sent = _notify(
                user, ws,
                subject=f"Timesheet du {day:%d/%m/%Y} non renseigné",
                body=(
                    f"Bonjour {user.first_name or _name(user)},\n\n"
                    f"Aucune heure n'est saisie pour le {day:%d/%m/%Y} dans {ws.name}. "
                    "Merci de compléter votre timesheet."
                ),
                url=f"/timesheets/?date={day:%Y-%m-%d}",
            )
            log.email_sent = sent
            log.save(update_fields=["email_sent", "updated_at"])
            stats["notified"] += 1
            stats["emails"] += int(sent)
    return stats


def send_weekly_checks(day: date | None = None) -> dict:
    day = day or timezone.localdate()
    monday, _ = tw.week_bounds(day)
    friday = monday + timedelta(days=tw.WORKING_DAYS - 1)
    stats = {"incomplete": 0, "missing": 0, "emails": 0}
    for ws in active_workspaces():
        for user in expected_members(ws, friday):
            summary = tw.week_summary(user, ws, monday)
            if summary.expected <= 0 or summary.total_hours >= summary.expected:
                continue
            missing = summary.total_hours == 0
            kind = Kind.WEEKLY_MISSING if missing else Kind.WEEKLY_INCOMPLETE
            log = _claim(ws, user, kind, monday)
            if log is None:
                continue
            ratio = f"{_fmt_h(summary.total_hours)}/{_fmt_h(summary.expected)}"
            if missing:
                subject = f"ALERTE CRITIQUE — aucun timesheet semaine du {monday:%d/%m/%Y}"
                body = (
                    f"Bonjour {user.first_name or _name(user)},\n\n"
                    f"Aucune heure n'a été saisie cette semaine ({ratio}). "
                    "Votre timesheet doit être complété et soumis sans délai."
                )
            else:
                subject = f"Timesheet incomplet — semaine du {monday:%d/%m/%Y} ({ratio})"
                body = (
                    f"Bonjour {user.first_name or _name(user)},\n\n"
                    f"Votre timesheet de la semaine est incomplet : {ratio} "
                    f"(il manque {_fmt_h(summary.missing_hours)}). Merci de le compléter puis de le soumettre."
                )
            url = f"/timesheets/?date={monday:%Y-%m-%d}"
            sent = _notify(user, ws, subject=subject, body=body, url=url, critical=missing)

            profile = tw.get_profile(user, ws)
            if profile and profile.manager_id:
                manager = profile.manager.user
                sent_m = _notify(
                    manager, ws,
                    subject=(
                        f"{'ALERTE CRITIQUE' if missing else 'Timesheet incomplet'} — "
                        f"{_name(user)} ({ratio})"
                    ),
                    body=(
                        f"{_name(user)} : {ratio} saisies pour la semaine du {monday:%d/%m/%Y}"
                        f"{' — aucun timesheet.' if missing else '.'}"
                    ),
                    url="/timesheets/list/",
                    critical=missing,
                )
                stats["emails"] += int(sent_m)
            log.email_sent = sent
            log.save(update_fields=["email_sent", "updated_at"])
            stats["missing" if missing else "incomplete"] += 1
            stats["emails"] += int(sent)
    return stats


# ---------------------------------------------------------------------------
# Rapport hebdomadaire
# ---------------------------------------------------------------------------
@dataclass
class MemberRow:
    user: object
    teams: list
    hours: Decimal
    expected: Decimal
    status: str
    manager_user_id: int | None

    @property
    def percent(self) -> int:
        return int(round(self.hours / self.expected * 100)) if self.expected else 0


def build_weekly_report(workspace, monday: date) -> dict:
    monday, sunday = tw.week_bounds(monday)
    friday = monday + timedelta(days=tw.WORKING_DAYS - 1)
    members = expected_members(workspace, friday)
    team_names = {}
    for user_id, name in dm.TeamMembership.objects.filter(
        workspace=workspace, user__in=members, team__isnull=False, team__is_archived=False,
    ).values_list("user_id", "team__name"):
        team_names.setdefault(user_id, []).append(name)
    managers = dict(
        dm.UserProfile.objects.filter(workspace=workspace, user__in=members, manager__isnull=False)
        .values_list("user_id", "manager__user_id")
    )

    rows = []
    for user in members:
        summary = tw.week_summary(user, workspace, monday)
        rows.append(MemberRow(
            user=user,
            teams=sorted(team_names.get(user.pk, [])) or ["Sans équipe"],
            hours=summary.total_hours,
            expected=summary.expected,
            status=summary.status,
            manager_user_id=managers.get(user.pk),
        ))

    tasks = list(
        dm.Task.objects.filter(
            workspace=workspace, is_archived=False,
            due_date__gte=monday, due_date__lte=sunday,
        )
        .exclude(status__in=[dm.Task.Status.DONE, dm.Task.Status.CANCELLED])
        .select_related("project", "assignee")
        .order_by("due_date", "title")
    )
    return {"workspace": workspace, "monday": monday, "sunday": sunday, "rows": rows, "tasks": tasks}


def _team_totals(rows):
    totals = {}
    for row in rows:
        for team in row.teams:
            hours, expected = totals.get(team, (Decimal("0"), Decimal("0")))
            totals[team] = (hours + row.hours, expected + row.expected)
    return {
        team: int(round(h / e * 100)) if e else 0
        for team, (h, e) in sorted(totals.items())
    }


def render_report(report: dict, rows=None, tasks=None, title="Rapport hebdomadaire") -> str:
    rows = report["rows"] if rows is None else rows
    tasks = report["tasks"] if tasks is None else tasks
    lines = [
        f"{title} — {report['workspace'].name}",
        f"Semaine du {report['monday']:%d/%m/%Y} au {report['sunday']:%d/%m/%Y}",
        "",
        "Occupation par équipe",
    ]
    lines += [f"  {team} : {pct}%" for team, pct in _team_totals(rows).items()] or ["  —"]
    lines += ["", "Heures saisies / attendues"]
    lines += [f"  {_name(r.user)} : {_fmt_h(r.hours)}/{_fmt_h(r.expected)}" for r in rows] or ["  —"]

    under = [r for r in rows if r.hours < r.expected]
    absent = [r for r in rows if r.hours == 0]
    pending = [r for r in rows if r.hours > 0 and r.status != dm.TimesheetEntry.ApprovalStatus.APPROVED]
    lines += ["", f"Collaborateurs sous quota ({len(under)})"]
    lines += [f"  {_name(r.user)} : {r.percent}%" for r in under] or ["  —"]
    lines += ["", f"Timesheets absents ({len(absent)})"]
    lines += [f"  {_name(r.user)}" for r in absent] or ["  —"]
    lines += ["", f"Timesheets non validés ({len(pending)})"]
    lines += [
        f"  {_name(r.user)} : {dict(dm.TimesheetEntry.ApprovalStatus.choices).get(r.status, r.status)}"
        for r in pending
    ] or ["  —"]
    lines += ["", f"Tâches prévues non finalisées ({len(tasks)})"]
    lines += [
        f"  - {t.title}"
        f"{f' [{t.project.name}]' if t.project_id else ''}"
        f" — {_name(t.assignee) if t.assignee_id else 'non assignée'}"
        f" — échéance {t.due_date:%d/%m}"
        for t in tasks
    ] or ["  —"]
    return "\n".join(lines)


def top_managers(workspace):
    """Direction : owner du workspace + sommets de la hiérarchie ayant des subordonnés."""
    users = {workspace.owner_id: workspace.owner} if workspace.owner_id else {}
    for profile in dm.UserProfile.objects.filter(
        workspace=workspace, manager__isnull=True, direct_reports__isnull=False,
    ).select_related("user").distinct():
        users[profile.user_id] = profile.user
    return [u for u in users.values() if u.is_active]


def send_weekly_reports(day: date | None = None) -> dict:
    day = day or timezone.localdate()
    monday, _ = tw.week_bounds(day)
    stats = {"manager_reports": 0, "top_reports": 0, "emails": 0}
    for ws in active_workspaces():
        report = build_weekly_report(ws, monday)
        tops = top_managers(ws)
        top_ids = {u.pk for u in tops}

        for top in tops:
            log = _claim(ws, top, Kind.WEEKLY_REPORT_TOP, monday)
            if log is None:
                continue
            body = render_report(report, title="Rapport hebdomadaire consolidé")
            sent = _notify(
                top, ws, subject=f"Rapport hebdomadaire consolidé — {ws.name}",
                body=body, url="/timesheets/list/", critical=True,
            )
            log.email_sent = sent
            log.save(update_fields=["email_sent", "updated_at"])
            stats["top_reports"] += 1
            stats["emails"] += int(sent)

        manager_ids = {r.manager_user_id for r in report["rows"] if r.manager_user_id}
        for manager in User.objects.filter(pk__in=manager_ids - top_ids, is_active=True):
            rows = [r for r in report["rows"] if r.manager_user_id == manager.pk]
            report_ids = {r.user.pk for r in rows}
            tasks = [t for t in report["tasks"] if t.assignee_id in report_ids]
            log = _claim(ws, manager, Kind.WEEKLY_REPORT_MANAGER, monday)
            if log is None:
                continue
            body = render_report(report, rows=rows, tasks=tasks, title="Rapport hebdomadaire de votre équipe")
            sent = _notify(
                manager, ws, subject=f"Rapport hebdomadaire de votre équipe — {ws.name}",
                body=body, url="/timesheets/list/", critical=True,
            )
            log.email_sent = sent
            log.save(update_fields=["email_sent", "updated_at"])
            stats["manager_reports"] += 1
            stats["emails"] += int(sent)
    return stats
