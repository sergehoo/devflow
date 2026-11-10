"""
Ticketing multi-applications — API.

* Intégration (applications externes, ``/api/v1/integrations/tickets/``) :
  authentification par signature HMAC (recommandée) ou identifiants dédiés,
  jamais par session ; Idempotency-Key, quotas, rate limit, validation stricte.
* Interne (DevFlow, session + CSRF) : tickets, applications, routage, SLA,
  livraisons de webhooks, tableau de bord. Scoping workspace + RBAC + droits objet.
"""

from __future__ import annotations

import hmac
import logging
import re
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db.models import Avg, Count, F, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from project import models as dm
from project.api.pagination import FlexiblePagination
from project.api.permissions import IsWorkspaceMember, WorkspaceScopedViewSetMixin
from project.services import ticketing as svc
from project.services import ticketing_webhooks as hooks
from project.utils.workspaces import user_can_access_workspace

logger = logging.getLogger("devflow.ticketing")
T = dm.Ticket
MAX_SKEW_SECONDS = 300
MAX_FILES = 5


def _err(exc: svc.TicketError) -> Response:
    return Response({"detail": str(exc)}, status=exc.status)


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


# ═══ Authentification des applications ═══════════════════════════════════════

class ApplicationAuthentication(BaseAuthentication):
    """
    Signature HMAC (en-têtes ``X-DevFlow-App``, ``X-DevFlow-Timestamp``,
    ``X-DevFlow-Signature``) ou identifiants dédiés (``Authorization:
    DevFlowApp <key_id>:<secret>``) — serveur à serveur uniquement.
    """

    def authenticate(self, request):
        key_id = request.headers.get("X-DevFlow-App", "")
        secret_given = None
        auth = request.headers.get("Authorization", "")
        if not key_id and auth.startswith("DevFlowApp "):
            key_id, _, secret_given = auth[len("DevFlowApp "):].partition(":")
        if not key_id:
            return None
        app = dm.ExternalApplication.objects.select_related("workspace").filter(key_id=key_id.strip()).first()
        if app is None:
            logger.warning("integration auth: unknown key %s", key_id[:20])
            raise AuthenticationFailed("Identifiants d'application invalides.")
        secret = svc.get_secret(app)
        if secret_given is not None:
            if not hmac.compare_digest(secret_given.strip(), secret):
                logger.warning("integration auth: bad secret for %s", app.key_id)
                raise AuthenticationFailed("Identifiants d'application invalides.")
        else:
            ts = request.headers.get("X-DevFlow-Timestamp", "")
            sig = request.headers.get("X-DevFlow-Signature", "").removeprefix("sha256=")
            if not ts.isdigit() or abs(time.time() - int(ts)) > MAX_SKEW_SECONDS:
                raise AuthenticationFailed("Horodatage absent ou hors fenêtre (5 min).")
            expected = svc.signature(secret, ts, request.method, request.path, request._request.body)
            if not hmac.compare_digest(sig, expected):
                logger.warning("integration auth: bad signature for %s", app.key_id)
                raise AuthenticationFailed("Signature invalide.")
            if not cache.add(f"ticketing:sig:{expected}", 1, MAX_SKEW_SECONDS * 2):
                raise AuthenticationFailed("Requête rejouée.")
        if not app.is_active:
            raise AuthenticationFailed("Application suspendue ou archivée.")
        return AnonymousUser(), app

    def authenticate_header(self, request):
        return 'DevFlowApp realm="integrations"'


class HasApplication(permissions.BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, dm.ExternalApplication)


class ApplicationRateThrottle(SimpleRateThrottle):
    """Débit par application (``rate_limit_per_minute``)."""

    scope = "ticketing_app"

    def get_rate(self):
        return "60/min"

    def allow_request(self, request, view):
        app = request.auth
        if isinstance(app, dm.ExternalApplication):
            self.num_requests, self.duration = app.rate_limit_per_minute, 60
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        app = request.auth
        return f"throttle_ticketing_app_{app.pk}" if isinstance(app, dm.ExternalApplication) else None


EXTERNAL_ID = re.compile(r"^[A-Za-z0-9._:\-]{1,120}$")


class ReporterSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=120, required=False, allow_blank=True)
    name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


class IntegrationTicketSerializer(serializers.Serializer):
    external_id = serializers.RegexField(EXTERNAL_ID, error_messages={"invalid": "Identifiant externe invalide (lettres, chiffres, . _ : -)."})
    title = serializers.CharField(min_length=3, max_length=200)
    description = serializers.CharField(max_length=20_000, required=False, allow_blank=True)
    category = serializers.ChoiceField(choices=T.Category.choices, required=False)
    severity = serializers.ChoiceField(choices=T.Severity.choices, required=False)
    reporter = ReporterSerializer(required=False)
    environment = serializers.CharField(max_length=40, required=False, allow_blank=True)
    app_version = serializers.CharField(max_length=40, required=False, allow_blank=True)
    url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    metadata = serializers.DictField(required=False)

    def to_internal_value(self, data):
        if hasattr(data, "getlist"):  # multipart : champs JSON sérialisés en texte
            import json

            plain = {k: data.get(k) for k in data.keys() if k != "attachments"}
            for key in ("reporter", "metadata"):
                if isinstance(plain.get(key), str) and plain[key]:
                    try:
                        plain[key] = json.loads(plain[key])
                    except ValueError:
                        raise ValidationError({key: "JSON invalide."})
            data = plain
        return super().to_internal_value(data)


class IntegrationCommentSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=10_000)
    author = ReporterSerializer(required=False)


def _files(request):
    files = request.FILES.getlist("attachments")
    if len(files) > MAX_FILES:
        raise ValidationError({"attachments": f"{MAX_FILES} fichiers maximum par requête."})
    return files


class IntegrationBase(APIView):
    authentication_classes = [ApplicationAuthentication]
    permission_classes = [HasApplication]
    throttle_classes = [ApplicationRateThrottle]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def ticket(self, request, external_id):
        ticket = dm.Ticket.objects.filter(application=request.auth, external_id=external_id).first()
        if ticket is None:
            raise Http404
        return ticket


class IntegrationTicketListCreateView(IntegrationBase):
    """``GET`` (tickets de l'application, paginés) / ``POST`` (création idempotente)."""

    def get(self, request):
        qs = dm.Ticket.objects.filter(application=request.auth).order_by("-created_at")
        if request.query_params.get("reporter_id"):
            qs = qs.filter(reporter_external_id=request.query_params["reporter_id"])
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        paginator = FlexiblePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response([svc.public_ticket(t) for t in page])

    def post(self, request):
        key = request.headers.get("Idempotency-Key", "").strip()
        if len(key) > 120:
            return Response({"detail": "Idempotency-Key trop longue (120 caractères maximum)."}, status=400)
        serializer = IntegrationTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket, created = svc.create_from_integration(request.auth, serializer.validated_data, _files(request), key)
        except svc.TicketError as exc:
            return _err(exc)
        logger.info("integration ticket %s %s by %s", ticket.reference, "created" if created else "replayed", request.auth.key_id)
        body = {**svc.public_ticket(ticket), "duplicate": not created}
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class IntegrationTicketDetailView(IntegrationBase):
    def get(self, request, external_id):
        return Response(svc.public_ticket(self.ticket(request, external_id), history=True))


class IntegrationTicketCommentView(IntegrationBase):
    def post(self, request, external_id):
        ticket = self.ticket(request, external_id)
        if ticket.status in (T.Status.CLOSED, T.Status.CANCELLED):
            return Response({"detail": "Ticket clôturé : créez un nouveau ticket."}, status=409)
        data = request.data
        if hasattr(data, "getlist"):
            import json

            data = {"body": data.get("body", ""), "author": json.loads(data["author"]) if data.get("author") else {}}
        serializer = IntegrationCommentSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            comment = svc.add_comment(ticket, body=serializer.validated_data["body"], visibility="PUBLIC",
                                      external=serializer.validated_data.get("author") or {}, files=_files(request))
        except svc.TicketError as exc:
            return _err(exc)
        return Response(svc.public_comment(comment), status=status.HTTP_201_CREATED)


# ═══ API interne ══════════════════════════════════════════════════════════════

def _require_admin(user, workspace_id):
    if not svc.can_admin(user, workspace_id):
        raise PermissionDenied("Réservé aux administrateurs du support (ticket.admin).")


class _SameWorkspaceMixin:
    """Valide que les relations pointent vers le workspace de l'objet."""

    same_workspace_fields: tuple[str, ...] = ()

    def validate(self, attrs):
        ws = attrs.get("workspace") or getattr(self.instance, "workspace", None)
        if ws is None:
            raise ValidationError({"workspace": "Workspace requis."})
        for field in self.same_workspace_fields:
            value = attrs.get(field)
            values = value if isinstance(value, (list, tuple)) else [value]
            for obj in values:
                if obj is not None and getattr(obj, "workspace_id", ws.pk) != ws.pk:
                    raise ValidationError({field: "Doit appartenir au même workspace."})
        return attrs


class ExternalApplicationSerializer(_SameWorkspaceMixin, serializers.ModelSerializer):
    same_workspace_fields = ("project", "teams", "default_team", "sla_policy")
    open_tickets = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = dm.ExternalApplication
        fields = ["id", "workspace", "name", "code", "description", "project", "environment", "status", "teams", "default_team",
                  "sla_policy", "key_id", "secret_last4", "secret_rotated_at", "webhook_url", "webhook_events",
                  "rate_limit_per_minute", "daily_ticket_quota", "max_attachment_mb", "retention_days", "config",
                  "created_at", "open_tickets"]
        read_only_fields = ["key_id", "secret_last4", "secret_rotated_at", "created_at"]

    def validate_webhook_url(self, value):
        if value:
            try:
                hooks.check_destination(value)
            except hooks.UnsafeDestination as exc:
                raise ValidationError(str(exc))
        return value

    def validate_webhook_events(self, value):
        unknown = set(value or []) - set(hooks.EVENTS)
        if unknown:
            raise ValidationError(f"Événements inconnus : {', '.join(sorted(unknown))}.")
        return value

    def validate_rate_limit_per_minute(self, value):
        if not 1 <= value <= 600:
            raise ValidationError("Entre 1 et 600 requêtes par minute.")
        return value

    def validate_max_attachment_mb(self, value):
        if not 1 <= value <= 50:
            raise ValidationError("Entre 1 et 50 Mo.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        ws = attrs.get("workspace") or self.instance.workspace
        code = attrs.get("code")
        if code and dm.ExternalApplication.objects.filter(workspace=ws, code=code).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise ValidationError({"code": "Ce code est déjà utilisé dans le workspace."})
        return attrs


class ExternalApplicationViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = dm.ExternalApplication.objects.select_related("workspace", "project", "default_team").prefetch_related("teams")
    serializer_class = ExternalApplicationSerializer
    permission_classes = [permissions.IsAuthenticated, IsWorkspaceMember]

    def get_queryset(self):
        from project.services.rbac import rbac_workspace_ids

        qs = super().get_queryset().annotate(open_tickets=Count("tickets", filter=Q(tickets__status__in=T.OPEN_STATUSES)))
        if not self.request.user.is_superuser:
            qs = qs.filter(workspace_id__in=rbac_workspace_ids(self.request.user, "ticket.view"))
        if self.request.query_params.get("workspace"):
            qs = qs.filter(workspace_id=self.request.query_params["workspace"])
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ws = serializer.validated_data["workspace"]
        if not user_can_access_workspace(request.user, ws):
            raise PermissionDenied("Workspace inaccessible.")
        _require_admin(request.user, ws.pk)
        key_id, secret = svc.new_credentials()
        app = dm.ExternalApplication(key_id=key_id, created_by=request.user)
        svc.set_secret(app, secret)
        teams = serializer.validated_data.pop("teams", [])
        for k, v in serializer.validated_data.items():
            setattr(app, k, v)
        app.save()
        app.teams.set(teams)
        data = self.get_serializer(app).data
        return Response({**data, "secret": secret}, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        _require_admin(self.request.user, serializer.instance.workspace_id)
        if "workspace" in serializer.validated_data and serializer.validated_data["workspace"] != serializer.instance.workspace:
            raise ValidationError({"workspace": "Le workspace d'une application ne peut pas changer."})
        serializer.save()

    def perform_destroy(self, instance):
        _require_admin(self.request.user, instance.workspace_id)
        if instance.tickets.exists():
            raise ValidationError({"detail": "Des tickets sont rattachés : archivez l'application plutôt que de la supprimer."})
        instance.delete()

    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        app = self.get_object()
        _require_admin(request.user, app.workspace_id)
        secret = svc.rotate_secret(app)
        return Response({"key_id": app.key_id, "secret": secret, "secret_last4": app.secret_last4})

    @action(detail=True, methods=["get"])
    def deliveries(self, request, pk=None):
        app = self.get_object()
        rows = app.webhook_deliveries.select_related("ticket")[:50]
        return Response([{
            "id": d.pk, "event": d.event, "event_id": str(d.event_id), "status": d.status, "status_label": d.get_status_display(),
            "attempt": d.attempt, "response_status": d.response_status, "error": d.error, "ticket": d.ticket.reference if d.ticket_id else "",
            "next_attempt_at": d.next_attempt_at, "delivered_at": d.delivered_at, "created_at": d.created_at,
        } for d in rows])

    @action(detail=True, methods=["post"], url_path=r"deliveries/(?P<delivery_id>\d+)/retry")
    def retry_delivery(self, request, pk=None, delivery_id=None):
        app = self.get_object()
        _require_admin(request.user, app.workspace_id)
        delivery = app.webhook_deliveries.filter(pk=delivery_id).first()
        if delivery is None:
            raise Http404
        hooks.retry_now(delivery)
        return Response({"status": delivery.status})


class RoutingRuleSerializer(_SameWorkspaceMixin, serializers.ModelSerializer):
    same_workspace_fields = ("application", "team")

    class Meta:
        model = dm.TicketRoutingRule
        fields = ["id", "workspace", "name", "application", "category", "severity", "team", "auto_assign",
                  "priority_override", "position", "is_active"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get("application") and attrs["application"].workspace_id != (attrs.get("workspace") or self.instance.workspace).pk:
            raise ValidationError({"application": "Doit appartenir au même workspace."})
        for field, choices in (("category", T.Category), ("severity", T.Severity), ("priority_override", T.Priority)):
            if attrs.get(field) and attrs[field] not in choices.values:
                raise ValidationError({field: "Valeur invalide."})
        return attrs


class SLAPolicySerializer(_SameWorkspaceMixin, serializers.ModelSerializer):
    same_workspace_fields = ("escalation_team",)

    class Meta:
        model = dm.TicketSLAPolicy
        fields = ["id", "workspace", "name", "is_default", "targets", "business_hours_only", "business_start", "business_end",
                  "business_days", "timezone", "warn_before_percent", "escalation_team", "auto_escalate"]

    def validate_targets(self, value):
        if not isinstance(value, dict):
            raise ValidationError("Objet attendu : {\"P1\": {\"first_response\": 30, \"resolution\": 240}, …}.")
        for prio, target in value.items():
            if prio not in T.Priority.values or not isinstance(target, dict):
                raise ValidationError(f"Priorité invalide : {prio}.")
            for key in ("first_response", "resolution"):
                if not isinstance(target.get(key), int) or not 1 <= target[key] <= 525_600:
                    raise ValidationError(f"{prio}.{key} : nombre de minutes entre 1 et 525 600.")
        return value

    def validate_business_days(self, value):
        if not isinstance(value, list) or not value or any(d not in range(7) for d in value):
            raise ValidationError("Liste de jours 0 (lundi) à 6 (dimanche).")
        return sorted(set(value))

    def validate_timezone(self, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValidationError("Fuseau horaire inconnu.")
        return value

    def validate_warn_before_percent(self, value):
        if not 10 <= value <= 99:
            raise ValidationError("Entre 10 et 99 %.")
        return value


class _AdminConfigViewSet(WorkspaceScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsWorkspaceMember]

    def get_queryset(self):
        from project.services.rbac import rbac_workspace_ids

        qs = super().get_queryset()
        if not self.request.user.is_superuser:
            qs = qs.filter(workspace_id__in=rbac_workspace_ids(self.request.user, "ticket.view"))
        if self.request.query_params.get("workspace"):
            qs = qs.filter(workspace_id=self.request.query_params["workspace"])
        return qs

    def _check(self, workspace):
        if not user_can_access_workspace(self.request.user, workspace):
            raise PermissionDenied("Workspace inaccessible.")
        _require_admin(self.request.user, workspace.pk)

    def perform_create(self, serializer):
        self._check(serializer.validated_data["workspace"])
        self._save(serializer)

    def perform_update(self, serializer):
        self._check(serializer.instance.workspace)
        if serializer.validated_data.get("workspace", serializer.instance.workspace) != serializer.instance.workspace:
            raise ValidationError({"workspace": "Non modifiable."})
        self._save(serializer)

    def perform_destroy(self, instance):
        self._check(instance.workspace)
        instance.delete()

    def _save(self, serializer):
        serializer.save()


class TicketRoutingRuleViewSet(_AdminConfigViewSet):
    queryset = dm.TicketRoutingRule.objects.select_related("application", "team")
    serializer_class = RoutingRuleSerializer


class TicketSLAPolicyViewSet(_AdminConfigViewSet):
    queryset = dm.TicketSLAPolicy.objects.select_related("escalation_team")
    serializer_class = SLAPolicySerializer

    def _save(self, serializer):
        policy = serializer.save()
        if policy.is_default:  # une seule politique par défaut par workspace
            dm.TicketSLAPolicy.objects.filter(workspace=policy.workspace, is_default=True).exclude(pk=policy.pk).update(is_default=False)


# ─── Tickets (interne) ───────────────────────────────────────────────────────

def _ref(obj, label="name"):
    return {"id": obj.pk, "name": getattr(obj, label)} if obj else None


def ticket_row(t: dm.Ticket) -> dict:
    return {
        "id": t.pk, "reference": t.reference, "title": t.title, "status": t.status, "status_label": t.get_status_display(),
        "priority": t.priority, "priority_label": t.get_priority_display(), "severity": t.severity,
        "severity_label": t.get_severity_display(), "category": t.category, "category_label": t.get_category_display(),
        "application": _ref(t.application), "team": _ref(t.team), "workspace": t.workspace_id,
        "assignee": {"id": t.assignee_id, "name": _name(t.assignee)} if t.assignee_id else None,
        "project": _ref(t.project), "task_id": t.task_id, "reporter_name": t.reporter_name,
        "created_at": t.created_at, "updated_at": t.updated_at, "first_response_due": t.first_response_due,
        "resolution_due": t.resolution_due, "first_response_breached": t.first_response_breached,
        "resolution_breached": t.resolution_breached, "escalation_level": t.escalation_level,
        "sla_paused": t.sla_paused_at is not None,
    }


def ticket_detail(t: dm.Ticket, user) -> dict:
    manage = svc.can_manage(user, t)
    return {
        **ticket_row(t),
        "description": t.description, "environment": t.environment, "app_version": t.app_version, "url": t.url,
        "metadata": t.metadata, "external_id": t.external_id, "reporter_email": t.reporter_email,
        "reporter_external_id": t.reporter_external_id, "task": _ref(t.task, "title"),
        "qualified_at": t.qualified_at, "assigned_at": t.assigned_at, "first_response_at": t.first_response_at,
        "resolved_at": t.resolved_at, "closed_at": t.closed_at, "reopened_count": t.reopened_count,
        "sla": svc.sla_state(t),
        "comments": [{
            "id": c.pk, "body": c.body, "visibility": c.visibility, "created_at": c.created_at,
            "author": _name(c.author) if c.author_id else (c.author_external_name or t.reporter_name or t.application.name),
            "external": c.author_id is None,
        } for c in t.comments.select_related("author")],
        "attachments": [{
            "id": a.pk, "name": a.original_name, "mime_type": a.mime_type, "size": a.size, "visibility": a.visibility,
            "created_at": a.created_at, "uploaded_by": _name(a.uploaded_by) if a.uploaded_by_id else a.uploaded_by_external,
            "download_url": f"/api/v1/tickets/{t.pk}/attachments/{a.pk}/",
        } for a in t.attachments.select_related("uploaded_by")],
        "events": [{
            "id": e.pk, "action": e.action, "actor": _name(e.actor) if e.actor_id else e.actor_label, "origin": e.origin,
            "old": e.old_value, "new": e.new_value, "public": e.is_public, "created_at": e.created_at,
        } for e in t.events.select_related("actor")],
        "allowed_transitions": [{"value": s, "label": T.Status(s).label} for s in svc.allowed_transitions(t, user)],
        "rights": {"manage": manage, "assign": svc.can_assign(user, t), "work": svc.can_work(user, t)},
    }


ORDERINGS = {"created": "-created_at", "updated": "-updated_at", "due": F("resolution_due").asc(nulls_last=True),
             "priority": "priority", "reference": "-number"}


class TicketViewSet(WorkspaceScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Tickets visibles par l'utilisateur (RBAC + équipes + affectations)."""

    queryset = dm.Ticket.objects.select_related("application", "team", "assignee", "project", "task", "workspace", "sla_policy")
    permission_classes = [permissions.IsAuthenticated, IsWorkspaceMember]
    pagination_class = FlexiblePagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = svc.visible_tickets(self.request.user, super().get_queryset())
        p = self.request.query_params
        if p.get("workspace"):
            qs = qs.filter(workspace_id=p["workspace"])
        for param, field in (("status", "status"), ("priority", "priority"), ("severity", "severity"), ("category", "category")):
            if p.get(param):
                qs = qs.filter(**{f"{field}__in": p[param].split(",")})
        for param in ("application", "team", "project"):
            if p.get(param, "").isdigit():
                qs = qs.filter(**{f"{param}_id": p[param]})
        assignee = p.get("assignee", "")
        if assignee == "me":
            qs = qs.filter(assignee=self.request.user)
        elif assignee == "none":
            qs = qs.filter(assignee__isnull=True)
        elif assignee.isdigit():
            qs = qs.filter(assignee_id=assignee)
        if p.get("open") == "1":
            qs = qs.filter(status__in=T.OPEN_STATUSES)
        if p.get("breached") == "1":
            qs = qs.filter(Q(first_response_breached=True) | Q(resolution_breached=True), status__in=T.OPEN_STATUSES)
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(Q(title__icontains=q) | Q(reference__icontains=q) | Q(description__icontains=q)
                           | Q(reporter_name__icontains=q) | Q(external_id__icontains=q))
        return qs.order_by(ORDERINGS.get(p.get("ordering", ""), "-created_at"), "-id")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response([ticket_row(t) for t in page])

    def retrieve(self, request, *args, **kwargs):
        return Response(ticket_detail(self.get_object(), request.user))

    def _do(self, fn):
        ticket = self.get_object()
        try:
            fn(ticket)
        except svc.TicketError as exc:
            return _err(exc)
        ticket.refresh_from_db()
        return Response(ticket_detail(ticket, self.request.user))

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        return self._do(lambda t: svc.transition(t, request.data.get("status", ""), actor=request.user,
                                                 note=str(request.data.get("note") or "")[:2000]))

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        return self._do(lambda t: svc.assign(t, actor=request.user, team_id=request.data.get("team") or None,
                                             assignee_id=request.data.get("assignee") or None))

    @action(detail=True, methods=["post"])
    def qualify(self, request, pk=None):
        return self._do(lambda t: svc.update_fields(t, actor=request.user, data=request.data))

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        return self._do(lambda t: svc.escalate(t, actor=request.user, reason=str(request.data.get("reason") or "")[:300]))

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        files = request.FILES.getlist("attachments")
        if len(files) > MAX_FILES:
            return Response({"detail": f"{MAX_FILES} fichiers maximum."}, status=400)
        return self._do(lambda t: svc.add_comment(t, body=request.data.get("body", ""), user=request.user,
                                                  visibility=request.data.get("visibility", "PUBLIC"), files=files))

    @action(detail=True, methods=["post"], url_path="create-task")
    def create_task(self, request, pk=None):
        return self._do(lambda t: svc.create_task(t, actor=request.user, project_id=request.data.get("project") or None))

    @action(detail=True, methods=["get"])
    def assignable(self, request, pk=None):
        ticket = self.get_object()
        teams = dm.Team.objects.filter(workspace_id=ticket.workspace_id, is_archived=False).order_by("name")
        team_id = request.query_params.get("team") or ticket.team_id
        team = teams.filter(pk=team_id).first() if team_id else None
        agents = []
        if team:
            members = dm.TeamMembership.objects.filter(team=team).select_related("user")
            agents = [{"id": m.user_id, "name": _name(m.user)} for m in members if svc.is_eligible_agent(m.user, team)]
        return Response({"teams": [{"id": x.pk, "name": x.name} for x in teams], "team": team.pk if team else None, "agents": agents})

    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<attachment_id>\d+)")
    def attachment(self, request, pk=None, attachment_id=None):
        ticket = self.get_object()
        att = ticket.attachments.filter(pk=attachment_id).first()
        if att is None or not svc.can_download(request.user, att):
            raise Http404
        response = FileResponse(att.file.open("rb"), as_attachment=not att.mime_type.startswith("image/"),
                                filename=att.original_name, content_type=att.mime_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox"
        return response

    @action(detail=False, methods=["get"])
    def dashboard(self, request):
        qs = self.get_queryset().order_by()
        now = timezone.now()
        open_qs = qs.filter(status__in=T.OPEN_STATUSES)
        resolved_30 = qs.filter(resolved_at__gte=now - timedelta(days=30))
        resolved_count = resolved_30.count()
        responded = qs.filter(first_response_at__isnull=False, created_at__gte=now - timedelta(days=30))
        avg_first = responded.aggregate(v=Avg(F("first_response_at") - F("created_at")))["v"]
        return Response({
            "open": open_qs.count(), "unassigned": open_qs.filter(assignee__isnull=True).count(),
            "mine": open_qs.filter(assignee=request.user).count(),
            "breached": open_qs.filter(Q(first_response_breached=True) | Q(resolution_breached=True)).count(),
            "due_24h": open_qs.filter(resolution_breached=False, resolution_due__lte=now + timedelta(hours=24)).count(),
            "created_7d": qs.filter(created_at__gte=now - timedelta(days=7)).count(),
            "resolved_7d": qs.filter(resolved_at__gte=now - timedelta(days=7)).count(),
            "sla_compliance": round(resolved_30.filter(resolution_breached=False).count() * 100 / resolved_count) if resolved_count else None,
            "avg_first_response_minutes": round(avg_first.total_seconds() / 60) if avg_first else None,
            "by_status": {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))},
            "by_priority": {r["priority"]: r["n"] for r in open_qs.values("priority").annotate(n=Count("id"))},
            "by_application": [{"id": r["application_id"], "name": r["application__name"], "open": r["n"]}
                               for r in open_qs.values("application_id", "application__name").annotate(n=Count("id")).order_by("-n")[:6]],
            "at_risk": [ticket_row(t) for t in open_qs.filter(resolution_due__isnull=False).select_related(
                "application", "team", "assignee", "project").order_by("resolution_due")[:6]],
        })
