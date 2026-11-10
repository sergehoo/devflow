"""
Ticketing multi-applications (centre de support DevFlow).

Les applications externes (``ExternalApplication``) déclarent des tickets via
l'API d'intégration authentifiée (HMAC ou identifiants dédiés). DevFlow les
classe, les route vers une équipe, suit le SLA et renvoie les changements par
webhook signé. Importé à la fin de ``project/models.py`` (même app ``project``).
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from project.models import Project, Task, Team, TimeStampedModel, Workspace


class ExternalApplication(TimeStampedModel):
    class Environment(models.TextChoices):
        PRODUCTION = "PRODUCTION", "Production"
        STAGING = "STAGING", "Pré-production"
        TEST = "TEST", "Test"
        DEVELOPMENT = "DEVELOPMENT", "Développement"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspendue"
        ARCHIVED = "ARCHIVED", "Archivée"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="external_applications")
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=60, help_text="Identifiant court, unique dans le workspace (ex. « portail-client »).")
    description = models.TextField(blank=True)
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="external_applications")
    environment = models.CharField(max_length=15, choices=Environment.choices, default=Environment.PRODUCTION)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    teams = models.ManyToManyField(Team, blank=True, related_name="supported_applications",
                                   help_text="Équipes responsables du support de l'application.")
    default_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     help_text="Équipe par défaut quand aucune règle de routage ne s'applique.")
    sla_policy = models.ForeignKey("TicketSLAPolicy", on_delete=models.SET_NULL, null=True, blank=True, related_name="applications")
    # Identifiants d'intégration : key_id public, secret chiffré (jamais renvoyé après création).
    key_id = models.CharField(max_length=40, unique=True, editable=False)
    secret_encrypted = models.TextField(editable=False)
    secret_last4 = models.CharField(max_length=4, editable=False)
    secret_rotated_at = models.DateTimeField(null=True, blank=True)
    # Webhooks sortants
    webhook_url = models.URLField(blank=True)
    webhook_events = models.JSONField(default=list, blank=True, help_text="Événements envoyés (vide = tous).")
    # Garde-fous
    rate_limit_per_minute = models.PositiveIntegerField(default=60)
    daily_ticket_quota = models.PositiveIntegerField(default=500)
    max_attachment_mb = models.PositiveSmallIntegerField(default=10)
    retention_days = models.PositiveIntegerField(null=True, blank=True,
                                                 help_text="Purge des données déclarant après N jours (clôturés). Vide = conserver.")
    config = models.JSONField(default=dict, blank=True, help_text="Paramètres d'intégration non sensibles.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["workspace", "code"], name="uniq_external_app_code_per_workspace")]

    def __str__(self):
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class TicketSLAPolicy(TimeStampedModel):
    """Politique SLA : délais par priorité, calendrier de service, escalade."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ticket_sla_policies")
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)
    # Délais en minutes par priorité : {"P1": {"first_response": 30, "resolution": 240}, ...}
    targets = models.JSONField(default=dict)
    business_hours_only = models.BooleanField(default=True)
    business_start = models.TimeField(default="08:00")
    business_end = models.TimeField(default="18:00")
    business_days = models.JSONField(default=list, help_text="Jours ouvrés (0 = lundi … 6 = dimanche).")
    timezone = models.CharField(max_length=60, default="Africa/Abidjan")
    warn_before_percent = models.PositiveSmallIntegerField(default=80, help_text="Alerte quand ce % du délai est consommé.")
    escalation_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    auto_escalate = models.BooleanField(default=True)

    class Meta:
        ordering = ["-is_default", "name"]

    def __str__(self):
        return self.name


class TicketRoutingRule(TimeStampedModel):
    """Application + catégorie + gravité → équipe (premier match par position)."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ticket_routing_rules")
    name = models.CharField(max_length=120)
    application = models.ForeignKey(ExternalApplication, on_delete=models.CASCADE, null=True, blank=True, related_name="routing_rules")
    category = models.CharField(max_length=20, blank=True)
    severity = models.CharField(max_length=10, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="ticket_routing_rules")
    auto_assign = models.BooleanField(default=False, help_text="Affecter à l'agent disponible le moins chargé de l'équipe.")
    priority_override = models.CharField(max_length=2, blank=True)
    position = models.PositiveIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.name


class Ticket(TimeStampedModel):
    class Category(models.TextChoices):
        BUG = "BUG", "Anomalie"
        INCIDENT = "INCIDENT", "Incident"
        QUESTION = "QUESTION", "Question"
        FEATURE = "FEATURE", "Demande d'évolution"
        ACCESS = "ACCESS", "Accès / compte"
        OTHER = "OTHER", "Autre"

    class Severity(models.TextChoices):  # gravité technique (déclarée / qualifiée)
        CRITICAL = "CRITICAL", "Critique"
        MAJOR = "MAJOR", "Majeure"
        MINOR = "MINOR", "Mineure"
        TRIVIAL = "TRIVIAL", "Triviale"

    class Priority(models.TextChoices):  # priorité opérationnelle (DevFlow)
        P1 = "P1", "P1 — Urgente"
        P2 = "P2", "P2 — Haute"
        P3 = "P3", "P3 — Normale"
        P4 = "P4", "P4 — Basse"

    class Status(models.TextChoices):
        NEW = "NEW", "Nouveau"
        QUALIFIED = "QUALIFIED", "Qualifié"
        ASSIGNED = "ASSIGNED", "Assigné"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        WAITING = "WAITING", "En attente"
        RESOLVED = "RESOLVED", "Résolu"
        CLOSED = "CLOSED", "Clôturé"
        CANCELLED = "CANCELLED", "Annulé"

    class Source(models.TextChoices):
        API = "API", "API"
        MANUAL = "MANUAL", "Manuel"
        EMAIL = "EMAIL", "E-mail"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tickets")
    application = models.ForeignKey(ExternalApplication, on_delete=models.PROTECT, related_name="tickets")
    number = models.PositiveIntegerField()
    reference = models.CharField(max_length=20)
    external_id = models.CharField(max_length=120)
    idempotency_key = models.CharField(max_length=120, blank=True)
    reporter_external_id = models.CharField(max_length=120, blank=True)
    reporter_name = models.CharField(max_length=150, blank=True)
    reporter_email = models.EmailField(blank=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.BUG)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MINOR)
    priority = models.CharField(max_length=2, choices=Priority.choices, default=Priority.P3)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    environment = models.CharField(max_length=40, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    url = models.URLField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True, help_text="Contexte technique assaini (aucune donnée sensible).")
    # Jalons
    qualified_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    reopened_count = models.PositiveSmallIntegerField(default=0)
    # SLA
    sla_policy = models.ForeignKey(TicketSLAPolicy, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    first_response_due = models.DateTimeField(null=True, blank=True)
    resolution_due = models.DateTimeField(null=True, blank=True)
    sla_paused_at = models.DateTimeField(null=True, blank=True)
    sla_paused_seconds = models.PositiveIntegerField(default=0)
    sla_warning_sent = models.BooleanField(default=False)
    first_response_breached = models.BooleanField(default=False)
    resolution_breached = models.BooleanField(default=False)
    escalation_level = models.PositiveSmallIntegerField(default=0)
    escalated_at = models.DateTimeField(null=True, blank=True)
    # Canal d'origine (API d'intégration, saisie DevFlow, e-mail entrant)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.API)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="created_tickets", help_text="Auteur d'une création manuelle.")
    mailbox = models.ForeignKey("TicketMailbox", on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets",
                                help_text="Boîte de support utilisée pour les échanges par e-mail.")

    OPEN_STATUSES = (Status.NEW, Status.QUALIFIED, Status.ASSIGNED, Status.IN_PROGRESS, Status.WAITING)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "number"], name="uniq_ticket_number_per_workspace"),
            models.UniqueConstraint(fields=["workspace", "reference"], name="uniq_ticket_reference_per_workspace"),
            models.UniqueConstraint(fields=["application", "external_id"], name="uniq_ticket_external_id_per_app"),
            models.UniqueConstraint(fields=["application", "idempotency_key"], condition=~models.Q(idempotency_key=""),
                                    name="uniq_ticket_idempotency_per_app"),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["workspace", "team", "status"]),
            models.Index(fields=["workspace", "assignee", "status"]),
            models.Index(fields=["status", "resolution_due"]),
            models.Index(fields=["application", "reporter_external_id"]),
        ]

    def __str__(self):
        return f"{self.reference} · {self.title}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES


class TicketComment(TimeStampedModel):
    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Public"
        INTERNAL = "INTERNAL", "Interne"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    author_external_id = models.CharField(max_length=120, blank=True)
    author_external_name = models.CharField(max_length=150, blank=True)
    body = models.TextField()
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)

    class Meta:
        ordering = ["created_at"]

    @property
    def is_external(self) -> bool:
        return self.author_id is None


def _ticket_attachment_path(instance, filename):
    import os
    ext = os.path.splitext(filename)[1].lower()[:10]
    return f"tickets/{instance.ticket.workspace_id}/{instance.ticket_id}/{uuid.uuid4().hex}{ext}"


class TicketAttachment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(TicketComment, on_delete=models.SET_NULL, null=True, blank=True, related_name="attachments")
    file = models.FileField(upload_to=_ticket_attachment_path, max_length=300)
    original_name = models.CharField(max_length=200)
    mime_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField(default=0)
    visibility = models.CharField(max_length=10, choices=TicketComment.Visibility.choices, default=TicketComment.Visibility.PUBLIC)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    uploaded_by_external = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["created_at"]


class TicketEvent(models.Model):
    class Origin(models.TextChoices):
        API = "API", "Application externe"
        UI = "UI", "DevFlow"
        EMAIL = "EMAIL", "E-mail"
        SYSTEM = "SYSTEM", "Système"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor_label = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=40)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    origin = models.CharField(max_length=10, choices=Origin.choices, default=Origin.UI)
    is_public = models.BooleanField(default=False, help_text="Visible par l'application d'origine.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["ticket", "created_at"])]


class TicketWebhookDelivery(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        SUCCESS = "SUCCESS", "Livré"
        FAILED = "FAILED", "Échec (nouvel essai prévu)"
        DEAD = "DEAD", "Abandonné"

    application = models.ForeignKey(ExternalApplication, on_delete=models.CASCADE, related_name="webhook_deliveries")
    ticket = models.ForeignKey(Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhook_deliveries")
    event = models.CharField(max_length=40)
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    destination = models.URLField()
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempt = models.PositiveSmallIntegerField(default=0)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_excerpt = models.CharField(max_length=300, blank=True)
    error = models.CharField(max_length=300, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]


# ─── Canal e-mail ────────────────────────────────────────────────────────────

class TicketMailbox(TimeStampedModel):
    """
    Boîte de support (réception IMAP ou webhook fournisseur, envoi SMTP).
    Identifiants chiffrés (Fernet, même clé que les secrets d'intégration),
    jamais renvoyés au frontend.
    """

    class Inbound(models.TextChoices):
        IMAP = "IMAP", "IMAP (relève périodique)"
        WEBHOOK = "WEBHOOK", "Webhook du fournisseur"

    class Security(models.TextChoices):
        SSL = "SSL", "SSL/TLS implicite"
        STARTTLS = "STARTTLS", "STARTTLS"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ticket_mailboxes")
    application = models.ForeignKey(ExternalApplication, on_delete=models.PROTECT, related_name="mailboxes")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    name = models.CharField(max_length=120)
    address = models.EmailField(help_text="Adresse de support (destinataire des e-mails clients).")
    from_name = models.CharField(max_length=120, blank=True, help_text="Nom d'expéditeur des réponses.")
    is_active = models.BooleanField(default=True)
    inbound = models.CharField(max_length=10, choices=Inbound.choices, default=Inbound.IMAP)
    # IMAP
    imap_host = models.CharField(max_length=255, blank=True)
    imap_port = models.PositiveIntegerField(default=993)
    imap_security = models.CharField(max_length=10, choices=Security.choices, default=Security.SSL)
    imap_username = models.CharField(max_length=255, blank=True)
    imap_password_encrypted = models.TextField(blank=True, editable=False)
    imap_folder = models.CharField(max_length=120, default="INBOX")
    # SMTP (vide = connexion e-mail par défaut de DevFlow, Reply-To = adresse de la boîte)
    smtp_host = models.CharField(max_length=255, blank=True)
    smtp_port = models.PositiveIntegerField(default=465)
    smtp_security = models.CharField(max_length=10, choices=Security.choices, default=Security.SSL)
    smtp_username = models.CharField(max_length=255, blank=True)
    smtp_password_encrypted = models.TextField(blank=True, editable=False)
    # Webhook entrant (fournisseur) : clé publique d'URL + secret de signature chiffré
    inbound_key = models.CharField(max_length=40, unique=True, editable=False)
    webhook_secret_encrypted = models.TextField(blank=True, editable=False)
    # Règles de réception
    auto_acknowledge = models.BooleanField(default=True, help_text="Accusé de réception avec la référence du ticket.")
    default_category = models.CharField(max_length=10, default="QUESTION")
    allowed_domains = models.JSONField(default=list, blank=True, help_text="Domaines autorisés à créer des tickets (vide = tous).")
    blocked_senders = models.JSONField(default=list, blank=True, help_text="Adresses ou domaines refusés.")
    max_attachment_mb = models.PositiveSmallIntegerField(default=10)
    # Supervision
    last_uid = models.PositiveBigIntegerField(default=0)
    uid_validity = models.PositiveBigIntegerField(default=0)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    next_poll_at = models.DateTimeField(null=True, blank=True)
    alert_sent_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["workspace", "address"], name="uniq_ticket_mailbox_address_per_workspace")]

    def __str__(self):
        return f"{self.name} <{self.address}>"


def _ticket_mail_path(instance, filename):
    return f"ticket-mail/{instance.mailbox.workspace_id}/{instance.mailbox_id}/{uuid.uuid4().hex}.eml"


class TicketEmailMessage(TimeStampedModel):
    """Journal des e-mails entrants et sortants d'une boîte (déduplication, file de rejet, livraison)."""

    class Direction(models.TextChoices):
        INBOUND = "IN", "Entrant"
        OUTBOUND = "OUT", "Sortant"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Reçu (à traiter)"
        PROCESSED = "PROCESSED", "Traité"
        IGNORED = "IGNORED", "Ignoré (réponse automatique)"
        REJECTED = "REJECTED", "Rejeté"
        FAILED = "FAILED", "Échec (nouvel essai prévu)"
        PENDING = "PENDING", "En attente d'envoi"
        SENT = "SENT", "Envoyé"
        DEAD = "DEAD", "Abandonné"

    class Kind(models.TextChoices):
        NEW_TICKET = "NEW_TICKET", "Nouveau ticket"
        REPLY = "REPLY", "Réponse"
        ACK = "ACK", "Accusé de réception"
        AGENT_REPLY = "AGENT_REPLY", "Réponse de l'équipe"
        UNKNOWN = "UNKNOWN", "Non reconnu"

    mailbox = models.ForeignKey(TicketMailbox, on_delete=models.CASCADE, related_name="messages")
    ticket = models.ForeignKey(Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="email_messages")
    comment = models.ForeignKey(TicketComment, on_delete=models.SET_NULL, null=True, blank=True, related_name="email_messages")
    direction = models.CharField(max_length=3, choices=Direction.choices)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.UNKNOWN)
    status = models.CharField(max_length=10, choices=Status.choices)
    message_id = models.CharField(max_length=255)
    in_reply_to = models.CharField(max_length=255, blank=True)
    references = models.TextField(blank=True)
    from_address = models.EmailField(blank=True)
    from_name = models.CharField(max_length=150, blank=True)
    to_addresses = models.TextField(blank=True)
    subject = models.CharField(max_length=255, blank=True)
    body_text = models.TextField(blank=True, help_text="Corps texte nettoyé (sortant : contenu envoyé).")
    raw = models.FileField(upload_to=_ticket_mail_path, max_length=300, blank=True)
    size = models.PositiveIntegerField(default=0)
    reason = models.CharField(max_length=300, blank=True, help_text="Motif de rejet / erreur (sans secret).")
    attempt = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["mailbox", "direction", "message_id"], name="uniq_ticket_email_per_mailbox")]
        indexes = [
            models.Index(fields=["mailbox", "status"]),
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["message_id"]),
        ]

    def __str__(self):
        return f"{self.get_direction_display()} {self.subject[:60]}"
