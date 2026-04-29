"""
Service de facturation : génération automatique d'une facture client à
partir d'un projet, selon trois modes :

  - FIXED : forfait, basé sur les ProjectEstimateLine du projet.
  - TIME_AND_MATERIALS : régie, basé sur les TimesheetEntry approuvées
    × le BillingRate de vente actif de chaque utilisateur.
  - MILESTONE : facturation par jalons (Milestones livrés).
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Optional, Iterable

from django.db import transaction
from django.utils import timezone

from project import models as dm


# =============================================================================
# Helpers
# =============================================================================
def _q2(value) -> Decimal:
    """Quantize à 2 décimales."""
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _resolve_or_create_default_client(project) -> dm.InvoiceClient:
    """
    Si le projet n'a pas encore de client de facturation rattaché, on crée
    un client générique « <Nom du projet> – Client par défaut » dans le
    workspace pour permettre l'émission immédiate. Le PM peut le renommer.
    """
    workspace = project.workspace
    name = f"{project.name} – Client"
    client, _ = dm.InvoiceClient.objects.get_or_create(
        workspace=workspace,
        name=name,
        defaults={"contact_name": "À renseigner"},
    )
    return client


# =============================================================================
# Génération
# =============================================================================
class InvoiceGenerator:
    """
    Constructeur :
        gen = InvoiceGenerator(project, issued_by=request.user)
        invoice = gen.from_estimate_lines()
    """

    def __init__(
        self,
        project: dm.Project,
        *,
        client: Optional[dm.InvoiceClient] = None,
        issued_by=None,
        tax_rate: Optional[Decimal] = None,
        currency: Optional[str] = None,
        title: Optional[str] = None,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        notes: str = "",
    ):
        self.project = project
        self.client = client or _resolve_or_create_default_client(project)
        self.issued_by = issued_by
        self.tax_rate = (
            tax_rate if tax_rate is not None else Decimal("18.00")
        )
        self.currency = currency or "XOF"
        self.title = title
        self.period_start = period_start
        self.period_end = period_end
        self.notes = notes

    # -------------------------------------------------------------------
    # Mode FORFAIT
    # -------------------------------------------------------------------
    def from_estimate_lines(
        self,
        budget_stage: str = dm.ProjectEstimateLine.BudgetStage.BASELINE,
    ) -> dm.Invoice:
        """
        Crée une facture forfait depuis les ProjectEstimateLine du projet.
        Par défaut on utilise le `BASELINE` (estimation validée).
        """
        with transaction.atomic():
            invoice = self._create_invoice_shell(
                billing_mode=dm.Invoice.BillingMode.FIXED,
                title=self.title or f"Facture forfait — {self.project.name}",
            )
            lines_qs = self.project.estimate_lines.filter(
                budget_stage=budget_stage
            ).order_by("category__name", "label")

            position = 0
            for line in lines_qs:
                if (line.sale_amount or 0) <= 0:
                    continue
                position += 10
                dm.InvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=dm.InvoiceLine.LineType.SERVICE,
                    label=line.label,
                    description=line.description or (
                        line.category.name if line.category_id else ""
                    ),
                    quantity=line.quantity or Decimal("1"),
                    unit_price=line.sale_unit_amount or Decimal("0"),
                    estimate_line=line,
                    position=position,
                )

            invoice.recompute_totals()
            return invoice

    # -------------------------------------------------------------------
    # Mode RÉGIE
    # -------------------------------------------------------------------
    def from_timesheets(
        self,
        *,
        only_approved: bool = True,
        only_billable: bool = True,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        group_by_user: bool = True,
    ) -> dm.Invoice:
        """
        Crée une facture régie depuis les TimesheetEntry du projet.
        On somme les heures par user (par défaut) puis on multiplie par
        leur tarif de vente journalier (BillingRate de vente actif).
        """
        period_start = period_start or self.period_start
        period_end = period_end or self.period_end

        with transaction.atomic():
            invoice = self._create_invoice_shell(
                billing_mode=dm.Invoice.BillingMode.TIME_AND_MATERIALS,
                title=self.title or f"Facture régie — {self.project.name}",
                period_start=period_start,
                period_end=period_end,
            )

            qs = dm.TimesheetEntry.objects.filter(
                project=self.project,
            ).select_related("user")

            if only_approved:
                qs = qs.filter(
                    approval_status=dm.TimesheetEntry.ApprovalStatus.APPROVED
                )
            if only_billable:
                qs = qs.filter(is_billable=True)
            if period_start:
                qs = qs.filter(entry_date__gte=period_start)
            if period_end:
                qs = qs.filter(entry_date__lte=period_end)

            if group_by_user:
                self._build_lines_grouped_by_user(invoice, qs)
            else:
                self._build_lines_per_entry(invoice, qs)

            invoice.recompute_totals()
            return invoice

    def _build_lines_grouped_by_user(self, invoice, qs):
        """Une ligne par utilisateur : Σ heures × tarif vente jour / heures_jour."""
        users = {}
        for entry in qs:
            users.setdefault(entry.user_id, {"user": entry.user, "hours": Decimal("0")})
            users[entry.user_id]["hours"] += Decimal(str(entry.hours or 0))

        position = 0
        for user_id, data in users.items():
            user = data["user"]
            hours = data["hours"]
            if hours <= 0:
                continue

            sale_daily = dm.BillingRate.get_user_sale_daily_rate(user)
            profile = getattr(user, "profile", None)
            hpd = Decimal("8")
            if profile and getattr(profile, "capacity_hours_per_day", None):
                try:
                    val = Decimal(str(profile.capacity_hours_per_day))
                    if val > 0:
                        hpd = val
                except Exception:
                    pass

            sale_hourly = (sale_daily / hpd) if hpd > 0 else Decimal("0")

            position += 10
            dm.InvoiceLine.objects.create(
                invoice=invoice,
                line_type=dm.InvoiceLine.LineType.TIME,
                label=f"Prestation — {user.get_full_name() or user.username}",
                description=f"Heures facturables sur la période.",
                quantity=hours.quantize(Decimal("0.01")),
                unit_price=sale_hourly.quantize(Decimal("0.01")),
                user=user,
                position=position,
            )

    def _build_lines_per_entry(self, invoice, qs):
        """Une ligne par entrée timesheet (mode détaillé)."""
        position = 0
        for entry in qs.order_by("entry_date", "user__last_name"):
            sale_daily = dm.BillingRate.get_user_sale_daily_rate(entry.user)
            profile = getattr(entry.user, "profile", None)
            hpd = Decimal("8")
            if profile and getattr(profile, "capacity_hours_per_day", None):
                try:
                    val = Decimal(str(profile.capacity_hours_per_day))
                    if val > 0:
                        hpd = val
                except Exception:
                    pass
            hourly = (sale_daily / hpd) if hpd > 0 else Decimal("0")

            position += 1
            dm.InvoiceLine.objects.create(
                invoice=invoice,
                line_type=dm.InvoiceLine.LineType.TIME,
                label=f"{entry.user} · {entry.entry_date}",
                description=entry.description or "",
                quantity=Decimal(str(entry.hours or 0)),
                unit_price=hourly.quantize(Decimal("0.01")),
                user=entry.user,
                position=position,
            )

    # -------------------------------------------------------------------
    # Mode JALON
    # -------------------------------------------------------------------
    def from_milestones(
        self,
        milestones: Optional[Iterable[dm.Milestone]] = None,
    ) -> dm.Invoice:
        """
        Facture une liste de jalons. Si `milestones` est None, on prend tous
        les jalons livrés et non encore facturés (pas de InvoiceLine liée).
        Le montant utilisé est `milestone.payment_amount` si présent, sinon 0.
        """
        with transaction.atomic():
            invoice = self._create_invoice_shell(
                billing_mode=dm.Invoice.BillingMode.MILESTONE,
                title=self.title or f"Facture jalons — {self.project.name}",
            )

            if milestones is None:
                milestones_qs = self.project.milestones.filter(
                    is_archived=False,
                ).exclude(invoice_lines__isnull=False)
                # filtre statut "livré" si dispo
                if hasattr(dm.Milestone, "Status"):
                    delivered_values = [
                        getattr(dm.Milestone.Status, "DONE", None),
                        getattr(dm.Milestone.Status, "DELIVERED", None),
                    ]
                    delivered_values = [v for v in delivered_values if v]
                    if delivered_values:
                        milestones_qs = milestones_qs.filter(
                            status__in=delivered_values
                        )
                milestones = list(milestones_qs)

            position = 0
            for ms in milestones:
                amount = (
                    getattr(ms, "payment_amount", None)
                    or getattr(ms, "amount", None)
                    or Decimal("0")
                )
                if amount <= 0:
                    continue
                position += 10
                dm.InvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=dm.InvoiceLine.LineType.MILESTONE,
                    label=f"Jalon : {ms.name}",
                    description=getattr(ms, "description", "") or "",
                    quantity=Decimal("1"),
                    unit_price=Decimal(amount),
                    milestone=ms,
                    position=position,
                )

            invoice.recompute_totals()
            return invoice

    # -------------------------------------------------------------------
    # Helpers privés
    # -------------------------------------------------------------------
    def _create_invoice_shell(
        self,
        *,
        billing_mode: str,
        title: str,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
    ) -> dm.Invoice:
        """Crée la coquille de facture (status=DRAFT, sans numéro)."""
        invoice = dm.Invoice.objects.create(
            workspace=self.project.workspace,
            project=self.project,
            client=self.client,
            title=title,
            status=dm.Invoice.Status.DRAFT,
            billing_mode=billing_mode,
            tax_rate=self.tax_rate,
            currency=self.currency,
            issued_by=self.issued_by,
            issue_date=timezone.localdate(),
            period_start=period_start or self.period_start,
            period_end=period_end or self.period_end,
            notes=self.notes,
        )
        return invoice


# =============================================================================
# API publique simple
# =============================================================================
def generate_invoice_for_project(
    project,
    *,
    mode: str = "FIXED",
    issued_by=None,
    **kwargs,
):
    """
    Façade simple :
        invoice = generate_invoice_for_project(project, mode="FIXED", issued_by=request.user)
    """
    gen = InvoiceGenerator(project, issued_by=issued_by, **{
        k: v for k, v in kwargs.items()
        if k in {"client", "tax_rate", "currency", "title", "period_start",
                 "period_end", "notes"}
    })
    if mode == "FIXED":
        return gen.from_estimate_lines(
            budget_stage=kwargs.get(
                "budget_stage",
                dm.ProjectEstimateLine.BudgetStage.BASELINE,
            )
        )
    if mode == "TIME_AND_MATERIALS":
        return gen.from_timesheets(
            only_approved=kwargs.get("only_approved", True),
            only_billable=kwargs.get("only_billable", True),
            period_start=kwargs.get("period_start"),
            period_end=kwargs.get("period_end"),
            group_by_user=kwargs.get("group_by_user", True),
        )
    if mode == "MILESTONE":
        return gen.from_milestones(
            milestones=kwargs.get("milestones"),
        )
    raise ValueError(f"Mode de facturation inconnu : {mode}")
