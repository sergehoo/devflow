"""
TJM des collaborateurs (``BillingRate``) : consultation par espace de travail,
périodes tarifaires et revalorisation des heures saisies.

* Un tarif sans projet est le TJM général du collaborateur ; un tarif avec projet
  ne s'applique qu'à ce projet (prioritaire, cf. ``BillingRate._daily_amount_for_user``).
* Une nouvelle période (« à partir du … ») clôt automatiquement la précédente la
  veille, pour qu'un seul tarif soit en vigueur à une date donnée.
* Le coût d'une saisie de temps est figé dans ``TimesheetCostSnapshot`` au TJM du
  jour de la saisie : changer un TJM ne modifie pas le passé, sauf revalorisation
  explicite (``revalue``) sur une période.

``BillingRate`` n'a pas de lien direct avec un espace de travail. Un TJM général vaut
pour le collaborateur partout : il appartient à son espace PRINCIPAL (``profile.workspace``,
même règle que l'API ``billing-rates``). Ailleurs, on ne voit ni ne modifie que les tarifs
propres aux projets de l'espace courant.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from project import models as dm
from project.utils.workspaces import users_in_workspaces

ZERO = Decimal("0")
HOURS_WINDOW = 30
BR = dm.BillingRate


class RateError(ValueError):
    """Saisie de TJM invalide (message affichable)."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def _name(user) -> str:
    return user.get_full_name() or user.get_username()


def _hours_per_day(user) -> Decimal:
    profile = getattr(user, "profile", None)
    try:
        value = Decimal(str(profile.capacity_hours_per_day)) if profile and profile.capacity_hours_per_day else ZERO
    except (InvalidOperation, TypeError, ValueError):
        value = ZERO
    return value if value > 0 else Decimal("8")


def per_day(rate, amount, user) -> Decimal:
    """Montant ramené à la journée (unité horaire × heures/jour, mensuelle ÷ jours ouvrés)."""
    amount = Decimal(amount or 0)
    if rate.unit == BR.RateUnit.HOURLY:
        return amount * _hours_per_day(user)
    if rate.unit == BR.RateUnit.MONTHLY:
        divisor = BR._working_days_per_month()
        return (amount / divisor).quantize(Decimal("0.01")) if divisor > 0 else ZERO
    return amount


def _status(rate, today) -> str:
    if rate.valid_from > today:
        return "future"
    if rate.valid_to and rate.valid_to < today:
        return "past"
    return "current"


def serialize_rate(rate, user, today) -> dict:
    cost, sale = per_day(rate, rate.cost_rate_amount, user), per_day(rate, rate.sale_rate_amount, user)
    return {
        "id": rate.pk,
        "worker_level": rate.worker_level, "worker_level_label": rate.get_worker_level_display(),
        "unit": rate.unit, "unit_label": rate.get_unit_display(),
        "cost_rate_amount": str(rate.cost_rate_amount), "sale_rate_amount": str(rate.sale_rate_amount),
        "daily_cost": str(cost), "daily_sale": str(sale),
        # Taux de marge sur coût (même définition que BillingRate.margin_percent).
        "margin_percent": float(round((sale - cost) / cost * 100, 1)) if cost > 0 and sale > 0 else None,
        "currency": rate.currency,
        "valid_from": rate.valid_from.isoformat(), "valid_to": rate.valid_to.isoformat() if rate.valid_to else None,
        "project": {"id": rate.project_id, "name": rate.project.name} if rate.project_id else None,
        "status": _status(rate, today),
    }


def workspace_rates(workspace, rate_ids=None):
    """Tarifs actifs (non archivés) des membres : généraux + propres aux projets de cet espace."""
    members = list(users_in_workspaces([workspace.pk]))
    qs = (BR.objects.filter(is_archived=False, user_id__in=[u.pk for u in members])
          .filter(Q(project__isnull=True, user__profile__workspace=workspace) | Q(project__workspace=workspace))
          .select_related("project").order_by("-valid_from", "-id"))
    if rate_ids is not None:
        qs = qs.filter(pk__in=rate_ids)
    return members, qs


def board(workspace, today=None) -> dict:
    """Écran « TJM des collaborateurs » : un collaborateur par ligne, tarif en vigueur et historique."""
    today = today or timezone.localdate()
    members, rates = workspace_rates(workspace)
    by_user = defaultdict(list)
    for rate in rates:
        by_user[rate.user_id].append(rate)

    since = today - timedelta(days=HOURS_WINDOW - 1)
    entries = dm.TimesheetEntry.objects.filter(workspace=workspace, user_id__in=[u.pk for u in members], hours__gt=0)
    hours = dict(entries.filter(entry_date__gte=since).order_by().values("user_id")
                 .annotate(h=Sum("hours")).values_list("user_id", "h"))
    unvalued = dict(entries.filter(Q(cost_snapshot__isnull=True) | Q(cost_snapshot__computed_cost=0))
                    .exclude(approval_status=dm.TimesheetEntry.ApprovalStatus.REJECTED)
                    .order_by().values("user_id").annotate(n=Count("id")).values_list("user_id", "n"))
    jobs = {}
    for uid, job, team in (dm.TeamMembership.objects.filter(workspace=workspace, user_id__in=[u.pk for u in members])
                           .order_by("-job_title", "id").values_list("user_id", "job_title", "team__name")):
        if uid not in jobs or (job and not jobs[uid][0]):
            jobs[uid] = (job or "", team or "")

    rows = []
    for user in sorted(members, key=lambda u: _name(u).lower()):
        own = by_user.get(user.pk, [])
        current = next((r for r in own if r.project_id is None and _status(r, today) == "current"), None)
        profile = getattr(user, "profile", None)
        home = bool(profile and profile.workspace_id == workspace.pk)
        rows.append({
            "user_id": user.pk, "name": _name(user),
            "job_title": jobs.get(user.pk, ("", ""))[0], "team": jobs.get(user.pk, ("", ""))[1],
            # Espace principal : seul à gérer le TJM général (sinon : tarifs par projet uniquement).
            "home": home,
            "current": serialize_rate(current, user, today) if current else None,
            "rates": [serialize_rate(r, user, today) for r in own],
            "profile_cost_per_day": str(profile.cost_per_day) if home and profile.cost_per_day else None,
            "hours_30d": float(hours.get(user.pk) or 0),
            "unvalued_entries": int(unvalued.get(user.pk) or 0),
        })
    return {
        "workspace": {"id": workspace.pk, "name": workspace.name},
        "today": today.isoformat(), "hours_window": HOURS_WINDOW, "currency": "XOF",
        "levels": [{"value": v, "label": str(label)} for v, label in BR.WorkerLevel.choices],
        "units": [{"value": v, "label": str(label)} for v, label in BR.RateUnit.choices],
        "projects": [{"id": pk, "name": name} for pk, name in
                     dm.Project.objects.filter(workspace=workspace, is_archived=False).order_by("name").values_list("id", "name")],
        "summary": {
            "members": len(rows),
            "with_rate": sum(1 for r in rows if r["current"]),
            "without_rate": sum(1 for r in rows if not r["current"]),
            "unvalued_entries": sum(r["unvalued_entries"] for r in rows),
        },
        "members": rows,
    }


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------
def _decimal(value, field, label) -> Decimal:
    try:
        number = Decimal(str(value).replace(" ", "").replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        raise RateError(f"{label} : montant invalide.", field) from None
    if not number.is_finite():
        raise RateError(f"{label} : montant invalide.", field)
    if number < 0 or number >= Decimal("1e12"):
        raise RateError(f"{label} : montant hors limites.", field)
    return number.quantize(Decimal("0.01"))


def _day(value, field, label, required=False):
    if value in (None, ""):
        if required:
            raise RateError(f"{label} : date requise.", field)
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise RateError(f"{label} : date invalide (AAAA-MM-JJ).", field) from None


def clean(workspace, data, *, rate=None) -> dict:
    """Valide une saisie de l'écran ; les relations doivent appartenir à l'espace de travail."""
    member_ids = set(users_in_workspaces([workspace.pk]).values_list("pk", flat=True))
    if rate is None:
        try:
            user_id = int(data.get("user"))
        except (TypeError, ValueError):
            raise RateError("Collaborateur requis.", "user") from None
        if user_id not in member_ids:
            raise RateError("Ce collaborateur n'est pas membre de l'espace de travail.", "user")
    else:
        user_id = rate.user_id
    project = None
    if data.get("project") not in (None, "", 0, "0"):
        try:
            project = dm.Project.objects.get(pk=int(data["project"]), workspace=workspace)
        except (dm.Project.DoesNotExist, TypeError, ValueError):
            raise RateError("Projet introuvable dans cet espace de travail.", "project") from None
    level = data.get("worker_level") or BR.WorkerLevel.OTHER
    if level not in BR.WorkerLevel.values:
        raise RateError("Niveau inconnu.", "worker_level")
    unit = data.get("unit") or BR.RateUnit.DAILY
    if unit not in BR.RateUnit.values:
        raise RateError("Unité inconnue.", "unit")
    if project is None and not dm.UserProfile.objects.filter(user_id=user_id, workspace=workspace).exists():
        raise RateError("Le TJM général de ce collaborateur est géré par son espace de travail principal : "
                        "choisissez un projet de cet espace.", "project")
    currency = str(data.get("currency") or "XOF").strip().upper()[:10] or "XOF"
    valid_from = _day(data.get("valid_from"), "valid_from", "Début", required=True)
    valid_to = _day(data.get("valid_to"), "valid_to", "Fin")
    if valid_to and valid_to < valid_from:
        raise RateError("La fin précède le début.", "valid_to")
    cost = _decimal(data.get("cost_rate_amount"), "cost_rate_amount", "Coût")
    sale = _decimal(data.get("sale_rate_amount", 0) or 0, "sale_rate_amount", "Vente")
    return {"user_id": user_id, "project": project, "worker_level": level, "unit": unit, "currency": currency,
            "valid_from": valid_from, "valid_to": valid_to, "cost_rate_amount": cost, "sale_rate_amount": sale}


def _same_scope(values, exclude_pk=None):
    qs = BR.objects.filter(is_archived=False, user_id=values["user_id"], project=values["project"])
    return qs.exclude(pk=exclude_pk) if exclude_pk else qs


def _close(rate_id, valid_to):
    BR.objects.filter(pk=rate_id).update(valid_to=valid_to, updated_at=timezone.now())


@transaction.atomic
def save_rate(workspace, data, *, rate=None) -> BR:
    """
    Nouvelle période (``rate`` absent) ou correction d'un tarif existant.

    * Nouvelle période : la période en cours est close la veille ; si la nouvelle est
      bornée, la suite de l'ancienne reprend le lendemain de sa fin ; un même début
      remplace le tarif existant ; une période qui commence après borne celle-ci.
    * Correction : le périmètre (collaborateur, projet) ne change pas ; le début reste
      entre les périodes voisines et la précédente suit le nouveau début (pas de trou).
    """
    values = clean(workspace, data, rate=rate)
    start = values["valid_from"]
    day = timedelta(days=1)

    if rate is not None and rate.pk:
        values["project"] = rate.project  # périmètre figé à la correction
        others = _same_scope(values, rate.pk)
        prev = others.filter(valid_from__lt=rate.valid_from).order_by("-valid_from").first()
        nxt = others.filter(valid_from__gt=rate.valid_from).order_by("valid_from").first()
        if (prev and start <= prev.valid_from) or (nxt and start >= nxt.valid_from):
            raise RateError("La date de début doit rester entre la période précédente et la suivante.", "valid_from")
        if nxt and (values["valid_to"] is None or values["valid_to"] >= nxt.valid_from):
            values["valid_to"] = nxt.valid_from - day
        if prev and (prev.valid_to is None or prev.valid_to >= start or prev.valid_to == rate.valid_from - day):
            _close(prev.pk, start - day)
    else:
        rate = _same_scope(values).filter(valid_from=start).first() or BR(user_id=values["user_id"],
                                                                           project=values["project"])
        others = _same_scope(values, rate.pk)
        later = others.filter(valid_from__gt=start).order_by("valid_from").first()
        if later and (values["valid_to"] is None or values["valid_to"] >= later.valid_from):
            values["valid_to"] = later.valid_from - day
        end = values["valid_to"]
        for prev in others.filter(valid_from__lt=start).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=start)):
            if end is not None and (prev.valid_to is None or prev.valid_to > end):
                # Période temporaire au milieu d'une autre : la suite de l'ancienne reprend après.
                BR.objects.create(
                    user_id=prev.user_id, project=prev.project, name=prev.name, worker_level=prev.worker_level,
                    unit=prev.unit, cost_rate_amount=prev.cost_rate_amount, sale_rate_amount=prev.sale_rate_amount,
                    currency=prev.currency, valid_from=end + day, valid_to=prev.valid_to,
                    is_internal_cost=prev.is_internal_cost, is_billable_rate=prev.is_billable_rate)
            _close(prev.pk, start - day)

    for field, value in values.items():
        setattr(rate, field, value)
    name = f"TJM {rate.get_worker_level_display()}" + (f" · {rate.project.name}" if rate.project_id else "")
    rate.name = name[: BR._meta.get_field("name").max_length]
    rate.is_internal_cost = True
    # Sans tarif de vente : coût interne seulement (non facturable).
    rate.is_billable_rate = rate.sale_rate_amount > 0
    try:
        rate.save()
    except DjangoValidationError as exc:  # règles du modèle (ex. vente < coût)
        field, messages = next(iter(getattr(exc, "message_dict", {"detail": exc.messages}).items()))
        raise RateError(" ".join(messages), field if field != "__all__" else None) from exc
    return rate


@transaction.atomic
def archive_rate(rate) -> None:
    """Archive un tarif ; la période précédente (close par lui) reprend sa plage : pas de trou."""
    (BR.objects.select_for_update()
     .filter(is_archived=False, user_id=rate.user_id, project_id=rate.project_id,
             valid_to=rate.valid_from - timedelta(days=1))
     .exclude(pk=rate.pk)
     .update(valid_to=rate.valid_to, updated_at=timezone.now()))
    rate.is_archived = True
    rate.archived_at = timezone.now()
    rate.save(update_fields=["is_archived", "archived_at", "updated_at"])


def revalue(workspace, user_ids, since, until=None, project_id=None) -> dict:
    """
    Recalcule le coût figé des saisies de temps (TJM du jour de chaque saisie) sur la période ;
    ``project_id`` : uniquement les saisies de ce projet (tarif propre à un projet).
    """
    from project.signals import create_or_update_timesheet_snapshot

    entries = (dm.TimesheetEntry.objects.filter(workspace=workspace, user_id__in=list(user_ids), hours__gt=0,
                                                entry_date__gte=since)
               .select_related("user", "user__profile"))
    if until:
        entries = entries.filter(entry_date__lte=until)
    if project_id:
        entries = entries.filter(project_id=project_id)
    entries = list(entries)
    snapshots = dm.TimesheetCostSnapshot.objects.filter(timesheet_entry__in=entries)
    before = snapshots.aggregate(total=Sum("computed_cost"))["total"] or ZERO
    for entry in entries:
        create_or_update_timesheet_snapshot(dm.TimesheetEntry, entry, created=False)
    after = snapshots.aggregate(total=Sum("computed_cost"))["total"] or ZERO
    return {"entries": len(entries), "before": str(before), "after": str(after), "since": since.isoformat(),
            "until": until.isoformat() if until else None}
