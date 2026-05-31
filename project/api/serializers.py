"""
DevFlow REST API — Serializers.

Couvre les modèles métier clés : Workspace, Project, Sprint, Task,
ProjectBudget, ProjectEstimateLine, ProjectRevenue, ProjectExpense,
TimesheetEntry, AInsight.
"""

from __future__ import annotations

from rest_framework import serializers

from project import models as dm


# =========================================================================
# Workspace / Team
# =========================================================================
class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = dm.Workspace
        fields = ["id", "name", "slug", "currency", "is_archived", "created_at", "updated_at"]
        read_only_fields = ["slug", "created_at", "updated_at"]


class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = dm.Team
        fields = ["id", "name", "team_type", "workspace", "created_at"]
        read_only_fields = ["created_at"]


# =========================================================================
# Project
# =========================================================================
class ProjectSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True)
    members_count = serializers.IntegerField(source="members.count", read_only=True)

    class Meta:
        model = dm.Project
        fields = [
            "id",
            "workspace",
            "team",
            "name",
            "slug",
            "code",
            "description",
            "tech_stack",
            "owner",
            "owner_name",
            "product_manager",
            "status",
            "priority",
            "health_status",
            "progress_percent",
            "risk_score",
            "ai_risk_label",
            "start_date",
            "target_date",
            "delivered_at",
            "budget",
            "members_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "slug",
            "code",
            "risk_score",
            "ai_risk_label",
            "created_at",
            "updated_at",
        ]


class ProjectMemberSerializer(serializers.ModelSerializer):
    user_label = serializers.CharField(source="user.__str__", read_only=True)

    class Meta:
        model = dm.ProjectMember
        fields = [
            "id",
            "project",
            "user",
            "user_label",
            "team",
            "role",
            "allocation_percent",
            "is_primary",
            "created_at",
        ]
        read_only_fields = ["created_at"]


# =========================================================================
# Finance
# =========================================================================
class BillingRateSerializer(serializers.ModelSerializer):
    margin_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    margin_percent = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    target_label = serializers.CharField(read_only=True)

    class Meta:
        model = dm.BillingRate
        fields = [
            "id",
            "user",
            "team",
            "name",
            "worker_level",
            "unit",
            "cost_rate_amount",
            "sale_rate_amount",
            "margin_amount",
            "margin_percent",
            "currency",
            "valid_from",
            "valid_to",
            "is_internal_cost",
            "is_billable_rate",
            "target_label",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class ProjectBudgetSerializer(serializers.ModelSerializer):
    total_estimated_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    estimated_margin_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    estimated_margin_percent = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    estimated_net_profit_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = dm.ProjectBudget
        fields = [
            "id",
            "project",
            "status",
            "currency",
            "estimated_labor_cost",
            "estimated_software_cost",
            "estimated_infra_cost",
            "estimated_subcontract_cost",
            "estimated_other_cost",
            "contingency_amount",
            "management_reserve_amount",
            "version_number",
            "target_margin_percent",
            "markup_percent",
            "planned_revenue",
            "approved_budget",
            "alert_threshold_percent",
            "overhead_cost_amount",
            "tax_amount",
            "approved_by",
            "approved_at",
            "notes",
            "total_estimated_cost",
            "estimated_margin_amount",
            "estimated_margin_percent",
            "estimated_net_profit_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at", "approved_by", "approved_at"]


class ProjectEstimateLineSerializer(serializers.ModelSerializer):
    margin_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = dm.ProjectEstimateLine
        fields = [
            "id",
            "project",
            "category",
            "source_type",
            "budget_stage",
            "task",
            "sprint",
            "milestone",
            "label",
            "description",
            "quantity",
            "cost_unit_amount",
            "cost_amount",
            "sale_unit_amount",
            "sale_amount",
            "markup_percent",
            "margin_amount",
            "created_at",
        ]
        read_only_fields = ["cost_amount", "sale_amount", "sale_unit_amount", "created_at"]


class ProjectRevenueSerializer(serializers.ModelSerializer):
    remaining_to_invoice = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    remaining_to_collect = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = dm.ProjectRevenue
        fields = [
            "id",
            "project",
            "revenue_type",
            "status",
            "title",
            "amount",
            "invoiced_amount",
            "received_amount",
            "currency",
            "expected_date",
            "invoice_date",
            "received_date",
            "is_received",
            "remaining_to_invoice",
            "remaining_to_collect",
            "notes",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class ProjectExpenseSerializer(serializers.ModelSerializer):
    is_fully_approved = serializers.BooleanField(read_only=True)

    class Meta:
        model = dm.ProjectExpense
        fields = [
            "id",
            "project",
            "category",
            "task",
            "sprint",
            "milestone",
            "title",
            "description",
            "status",
            "approval_state",
            "expense_date",
            "committed_date",
            "paid_date",
            "amount",
            "currency",
            "vendor",
            "reference",
            "is_direct_cost",
            "is_labor_cost",
            "is_fully_approved",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "approval_state",
            "is_fully_approved",
            "created_by",
            "created_at",
            "updated_at",
        ]


# =========================================================================
# Sprint / Task
# =========================================================================
class SprintSerializer(serializers.ModelSerializer):
    class Meta:
        model = dm.Sprint
        fields = [
            "id",
            "workspace",
            "project",
            "team",
            "name",
            "number",
            "goal",
            "status",
            "start_date",
            "end_date",
            "velocity_target",
            "velocity_completed",
            "total_story_points",
            "completed_story_points",
            "remaining_story_points",
        ]


class TaskSerializer(serializers.ModelSerializer):
    assignee_label = serializers.CharField(source="assignee.__str__", read_only=True, default="")

    class Meta:
        model = dm.Task
        fields = [
            "id",
            "workspace",
            "project",
            "sprint",
            "backlog_item",
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "assignee_label",
            "reporter",
            "estimate_hours",
            "spent_hours",
            "story_points",
            "due_date",
            "is_archived",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class TimesheetEntrySerializer(serializers.ModelSerializer):
    computed_cost = serializers.SerializerMethodField()

    class Meta:
        model = dm.TimesheetEntry
        fields = [
            "id",
            "user",
            "workspace",
            "project",
            "task",
            "entry_date",
            "hours",
            "description",
            "is_billable",
            "approval_status",
            "approved_by",
            "approved_at",
            "computed_cost",
        ]
        read_only_fields = ["approved_by", "approved_at", "computed_cost"]

    def get_computed_cost(self, obj):
        snap = getattr(obj, "cost_snapshot", None)
        return str(snap.computed_cost) if snap else None


# =========================================================================
# AInsight
# =========================================================================
class AInsightSerializer(serializers.ModelSerializer):
    severity_color = serializers.CharField(read_only=True)
    is_actionable = serializers.BooleanField(read_only=True)

    class Meta:
        model = dm.AInsight
        fields = [
            "id",
            "workspace",
            "project",
            "sprint",
            "task",
            "insight_type",
            "severity",
            "severity_color",
            "title",
            "summary",
            "recommendation",
            "score",
            "is_read",
            "is_dismissed",
            "is_actionable",
            "detected_at",
            "created_at",
        ]
        read_only_fields = ["created_at", "severity_color", "is_actionable"]


# =========================================================================
# Aggregations / Read-only
# =========================================================================
class BudgetOverviewSerializer(serializers.Serializer):
    """Sérialiseur read-only pour le résultat de build_budget_overview."""

    approved_budget = serializers.DecimalField(max_digits=14, decimal_places=2)
    estimated_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    actual_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    committed_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    raf_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    forecast_final_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    planned_revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    invoiced_revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    received_revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    gross_margin = serializers.DecimalField(max_digits=14, decimal_places=2)
    operating_margin = serializers.DecimalField(max_digits=14, decimal_places=2)
    net_profit = serializers.DecimalField(max_digits=14, decimal_places=2)
    profit_margin_percent = serializers.IntegerField()
    expense_ratio_percent = serializers.IntegerField()
    forecast_consumption_percent = serializers.IntegerField()
    forecast_margin = serializers.DecimalField(max_digits=14, decimal_places=2)
    real_margin = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.CharField()


# =========================================================================
# Phase 2 — Multi-modes projet (PR12)
# =========================================================================
class ProjectPhaseSerializer(serializers.ModelSerializer):
    """Phase d'un projet Waterfall — voir Project.Methodology.WATERFALL."""

    class Meta:
        model = dm.ProjectPhase
        fields = [
            "id", "workspace", "project", "name", "description",
            "position", "status", "start_date", "end_date",
            "gate_required", "progress_percent", "owner",
            "is_archived", "created_at", "updated_at",
        ]
        # workspace est dérivé automatiquement du project côté save() — on
        # le rend read-only pour éviter qu'un client ne tente de bypass.
        read_only_fields = ["workspace", "is_archived", "created_at", "updated_at"]


class ProjectViewPreferenceSerializer(serializers.ModelSerializer):
    """Préférence de vue par (user, project)."""

    class Meta:
        model = dm.ProjectViewPreference
        fields = ["id", "user", "project", "view_mode",
                  "created_at", "updated_at"]
        read_only_fields = ["user", "created_at", "updated_at"]


class FieldReportPhotoSerializer(serializers.ModelSerializer):
    """Photo rattachée à un FieldReport."""

    class Meta:
        model = dm.FieldReportPhoto
        fields = ["id", "report", "image", "caption", "uploaded_by",
                  "created_at"]
        read_only_fields = ["uploaded_by", "created_at"]


class FieldReportSerializer(serializers.ModelSerializer):
    """
    Rapport de chantier — voir Project.Methodology.FIELD.

    Inclut les photos en read-only (utiliser l'endpoint dédié pour upload).
    """
    photos = FieldReportPhotoSerializer(many=True, read_only=True)

    class Meta:
        model = dm.FieldReport
        fields = [
            "id", "workspace", "project", "reporter", "report_date",
            "location_name", "location_lat", "location_lng",
            "weather", "workforce_count", "incidents", "notes",
            "photos", "is_archived", "created_at", "updated_at",
        ]
        read_only_fields = ["workspace", "is_archived", "created_at", "updated_at"]


class RealEstateLotSerializer(serializers.ModelSerializer):
    """Lot d'un projet immobilier — voir Project.Methodology.REAL_ESTATE."""

    class Meta:
        model = dm.RealEstateLot
        fields = [
            "id", "workspace", "project", "lot_number", "floor",
            "surface_m2", "bedrooms", "price", "currency", "status",
            "buyer_name", "buyer_email", "buyer_phone",
            "reserved_at", "sold_at", "notes",
            "is_archived", "created_at", "updated_at",
        ]
        read_only_fields = ["workspace", "is_archived", "created_at", "updated_at"]


class AdminCaseSerializer(serializers.ModelSerializer):
    """Dossier administratif — voir Project.Methodology.ADMINISTRATIVE."""

    class Meta:
        model = dm.AdminCase
        fields = [
            "id", "workspace", "project", "reference", "title",
            "applicant", "document_type", "status",
            "requested_at", "sla_days", "deadline", "decided_at",
            "assignee", "notes",
            "is_archived", "created_at", "updated_at",
        ]
        # deadline est auto-calculée dans Model.save() si non fournie.
        read_only_fields = ["workspace", "is_archived",
                            "created_at", "updated_at"]


# =========================================================================
# Phase 3 — Budget V2 (PR15)
# =========================================================================
class ProjectBudgetSnapshotSerializer(serializers.ModelSerializer):
    """Snapshot d'un budget projet à un instant T."""

    class Meta:
        model = dm.ProjectBudgetSnapshot
        fields = [
            "id", "workspace", "project", "label", "kind", "snapshot_date",
            "payload", "notes", "created_by",
            "created_at", "updated_at",
        ]
        # workspace dérivé du project ; snapshot_date par défaut auto.
        read_only_fields = ["workspace", "payload", "created_by",
                            "created_at", "updated_at"]


class ProjectBudgetForecastRunSerializer(serializers.ModelSerializer):
    """Run IA de BudgetForecastService — read-only via API."""

    class Meta:
        model = dm.ProjectBudgetForecastRun
        fields = [
            "id", "workspace", "project", "horizon_end",
            "base_cost", "optimistic_cost", "pessimistic_cost",
            "expected_margin", "expected_margin_percent",
            "overrun_risk_percent", "confidence",
            "used_provider", "used_model", "tokens_used",
            "ai_summary", "payload", "triggered_by",
            "created_at", "updated_at",
        ]
        read_only_fields = fields  # full read-only (créé via le service IA)


class BudgetAlertSerializer(serializers.Serializer):
    """Sérialiseur read-only pour BudgetAlert (dataclass, pas un modèle)."""

    project_id = serializers.IntegerField()
    project_name = serializers.CharField()
    workspace_id = serializers.IntegerField()
    severity = serializers.CharField()
    consumption_percent = serializers.IntegerField()
    alert_threshold_percent = serializers.IntegerField()
    approved_budget = serializers.CharField()
    actual_cost = serializers.CharField()
    forecast_final_cost = serializers.CharField()
    currency = serializers.CharField()


# =========================================================================
# Phase 5 — Rapports IA hebdomadaires (PR22)
# =========================================================================
class ProjectAIReportSerializer(serializers.ModelSerializer):
    """Rapport projet IA — créé via service, exposé en lecture par l'API."""

    class Meta:
        model = dm.ProjectAIReport
        fields = [
            "id", "workspace", "project", "period",
            "period_start", "period_end", "title", "status",
            "content_markdown", "summary", "payload",
            "used_provider", "used_model", "tokens_used",
            "generated_at", "generated_by",
            "is_archived", "created_at", "updated_at",
        ]
        read_only_fields = fields  # entièrement créé via service
