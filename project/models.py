from decimal import Decimal

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

from project.utils.codes import unique_slug, next_sequential_code


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def archive(self):
        self.is_archived = True
        self.archived_at = timezone.now()
        self.save(update_fields=["is_archived", "archived_at", "updated_at"])


class Workspace(TimeStampedModel, SoftDeleteModel):
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="devflow/workspaces/logos/", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_workspaces",
    )
    is_active = models.BooleanField(default=True)
    timezone = models.CharField(max_length=64, default="Africa/Abidjan")
    quarter_label = models.CharField(max_length=30, blank=True, help_text="Ex: Q2 2026")

    # ─── Papier en-tête (utilisé pour les PDF facture, devis, etc.) ───
    legal_name = models.CharField(max_length=200, blank=True,
                                  help_text="Raison sociale complète (ex: SARL DATARIUM)")
    tagline = models.CharField(max_length=120, blank=True,
                               help_text="Slogan affiché en pied de page (ex: DIGITAL & TECHNOLOGIES)")
    legal_rccm = models.CharField(max_length=60, blank=True,
                                  help_text="Numéro RCCM")
    legal_cc = models.CharField(max_length=60, blank=True,
                                help_text="Numéro Compte Contribuable")
    legal_tax_id = models.CharField(max_length=60, blank=True,
                                    help_text="Identifiant fiscal / TVA")
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    bank_details = models.TextField(blank=True,
                                    help_text="IBAN / RIB / coordonnées bancaires affichées sur la facture")
    invoice_footer_text = models.TextField(blank=True,
                                           help_text="Mentions légales additionnelles (TVA non applicable, etc.)")
    accent_color = models.CharField(max_length=20, default="#F4722B",
                                    help_text="Couleur de la barre orange du papier en-tête")

    class Meta:
        ordering = ["name"]
        verbose_name = "Workspace"
        verbose_name_plural = "Workspaces"

    def __str__(self):
        return self.name

    @property
    def logo_url(self):
        if self.logo:
            return self.logo.url
        return None

    @property
    def initials(self):
        return (self.name[:2] if self.name else "WS").upper()

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            index = 1
            while Workspace.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                index += 1
                slug = f"{base_slug}-{index}"
            self.slug = slug
        super().save(*args, **kwargs)


class Team(TimeStampedModel, SoftDeleteModel):
    class TeamType(models.TextChoices):
        BACKEND = "BACKEND", "Backend"
        FRONTEND = "FRONTEND", "Frontend"
        DEVOPS = "DEVOPS", "DevOps"
        QA = "QA", "QA / Test"
        DATA = "DATA", "Data"
        MOBILE = "MOBILE", "Mobile"
        SECURITY = "SECURITY", "Sécurité"
        PRODUCT = "PRODUCT", "Produit"
        DESIGN = "DESIGN", "Design"
        OTHER = "OTHER", "Autre"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    team_type = models.CharField(max_length=20, choices=TeamType.choices, default=TeamType.OTHER)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_teams",
    )
    color = models.CharField(max_length=20, default="#7C6FF7")
    velocity_target = models.PositiveIntegerField(default=0)
    velocity_current = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("workspace", "name")]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} · {self.workspace.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TeamMembership(TimeStampedModel):
    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrateur"
        CTO = "CTO", "CTO"
        PM = "PM", "Project Manager"
        PRODUCT_OWNER = "PO", "Product Owner"
        SCRUM_MASTER = "SM", "Scrum Master"
        TECH_LEAD = "TECH_LEAD", "Tech Lead"
        DEVELOPER = "DEVELOPER", "Développeur"
        QA = "QA", "QA"
        DEVOPS = "DEVOPS", "DevOps"
        DESIGNER = "DESIGNER", "Designer"
        ANALYST = "ANALYST", "Analyste"
        VIEWER = "VIEWER", "Observateur"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Actif"
        ON_LEAVE = "ON_LEAVE", "En congé"
        REMOTE = "REMOTE", "Télétravail"
        INACTIVE = "INACTIVE", "Inactif"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devflow_memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DEVELOPER)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    job_title = models.CharField(max_length=120, blank=True)
    capacity_points = models.PositiveIntegerField(default=0)
    current_load_percent = models.PositiveSmallIntegerField(default=0)
    avatar_color = models.CharField(max_length=32, blank=True)
    joined_at = models.DateField(default=timezone.now)

    class Meta:
        ordering = ["-status", "user__last_name", "user__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user", "team"],
                name="uniq_membership_with_team",
                condition=Q(team__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uniq_membership_no_team",
                condition=Q(team__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} · {self.workspace}"

    def save(self, *args, **kwargs):
        # Couleur d'avatar par défaut basée sur l'ID utilisateur (palette stable)
        if not self.avatar_color and self.user_id:
            palette = [
                "#7C6FF7", "#FF4E00", "#0EA5C9", "#22C55E", "#F59E0B",
                "#EF4444", "#8B5CF6", "#EC4899", "#14B8A6", "#F97316",
            ]
            self.avatar_color = palette[self.user_id % len(palette)]
        super().save(*args, **kwargs)


def compute_risk_score(project):
    score = 0
    today = timezone.now().date()

    # ── retard
    if project.target_date:
        delay = (today - project.target_date).days
        if delay > 0:
            score += min(delay * 2, 40)  # max 40 pts

    # ── progression vs temps
    if project.start_date and project.target_date:
        total_days = (project.target_date - project.start_date).days or 1
        elapsed_days = (today - project.start_date).days
        expected_progress = max(0, min(100, (elapsed_days / total_days) * 100))

        gap = expected_progress - (project.progress_percent or 0)
        if gap > 0:
            score += min(gap, 30)

    # ── progression faible
    if project.progress_percent < 20:
        score += 10

    # ── clamp final
    return min(score, 100)


class UserProfile(TimeStampedModel):
    class Seniority(models.TextChoices):
        INTERN = "INTERN", "Stagiaire"
        JUNIOR = "JUNIOR", "Junior"
        MID = "MID", "Intermédiaire"
        SENIOR = "SENIOR", "Senior"
        LEAD = "LEAD", "Lead"
        EXPERT = "EXPERT", "Expert"

    class ContractType(models.TextChoices):
        FULL_TIME = "FULL_TIME", "Temps plein"
        PART_TIME = "PART_TIME", "Temps partiel"
        FREELANCE = "FREELANCE", "Freelance"
        INTERN = "INTERN", "Stage"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="user_profiles",
    )

    # ───────────── Infos générales ─────────────
    job_title = models.CharField(max_length=120, blank=True)
    seniority = models.CharField(
        max_length=20,
        choices=Seniority.choices,
        default=Seniority.JUNIOR,
    )
    contract_type = models.CharField(
        max_length=20,
        choices=ContractType.choices,
        default=ContractType.FULL_TIME,
    )

    avatar = models.ImageField(
        upload_to="devflow/users/avatars/",
        null=True,
        blank=True,
    )
    phone = models.CharField(max_length=30, blank=True)
    location = models.CharField(max_length=120, blank=True)

    # ───────────── Capacité & workload ─────────────
    capacity_hours_per_day = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8,
        help_text="Capacité théorique par jour",
    )

    capacity_hours_per_week = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=40,
    )

    availability_percent = models.PositiveSmallIntegerField(
        default=100,
        help_text="Disponibilité actuelle (%)",
    )

    # ───────────── Coûts & facturation ─────────────
    cost_per_day = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="Coût interne journalier",
    )

    billable_rate_per_day = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        help_text="Tarif de vente journalier",
    )

    currency = models.CharField(max_length=10, default="XOF")

    # ───────────── Suivi performance ─────────────
    performance_score = models.PositiveSmallIntegerField(default=0)
    velocity_contribution = models.PositiveIntegerField(default=0)

    # ───────────── Flags ─────────────
    is_billable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    # ───────────── Méta ─────────────
    joined_company_at = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("user", "workspace")]
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user} · {self.get_seniority_display()}"


class ProjectCategory(models.Model):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    is_billable = models.BooleanField(default=False)
    budget_type = models.CharField(
        max_length=20,
        choices=[
            ("FIXED", "Forfait"),
            ("TIME", "Temps passé"),
            ("NONE", "Non facturé"),
        ],
        default="TIME"
    )
    is_strategic = models.BooleanField(default=False)
    affects_revenue = models.BooleanField(default=True)
    color = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name


class Project(TimeStampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planifié"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        IN_DELIVERY = "IN_DELIVERY", "Livraison"
        BLOCKED = "BLOCKED", "Bloqué"
        DELAYED = "DELAYED", "Retard"
        DONE = "DONE", "Terminé"
        ON_HOLD = "ON_HOLD", "En pause"
        CANCELLED = "CANCELLED", "Annulé"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critique"

    class HealthStatus(models.TextChoices):
        GREEN = "GREEN", "Vert"
        AMBER = "AMBER", "Orange"
        RED = "RED", "Rouge"
        GRAY = "GRAY", "Neutre"

    category = models.ForeignKey(
        ProjectCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name="projects"
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="projects")
    team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="projects",
        help_text="Équipe principale (référent). Pour plusieurs équipes, utilisez le champ Équipes contributrices.",
    )
    teams = models.ManyToManyField(
        Team, blank=True, related_name="contributing_projects",
        help_text="Toutes les équipes qui contribuent au projet (multi-sélection).",
    )
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, blank=True)
    code = models.CharField(max_length=30, blank=True)
    description = models.TextField(blank=True)
    tech_stack = models.CharField(max_length=255, blank=True, help_text="Ex: Django / React / PostgreSQL")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_projects",
    )
    product_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_projects",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    health_status = models.CharField(max_length=10, choices=HealthStatus.choices, default=HealthStatus.GRAY)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    risk_score = models.PositiveSmallIntegerField(default=0)
    ai_risk_label = models.CharField(max_length=30, blank=True, help_text="Ex: Faible, Moyen, Élevé, Critique")
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    delivered_at = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    is_favorite = models.BooleanField(default=False)
    image = models.ImageField(upload_to="devflow/projects/covers/", null=True, blank=True)

    class Meta:
        unique_together = [("workspace", "name")]
        ordering = ["name"]
        permissions = [
            ("view_financial_data", "Peut voir les données financières des projets"),
        ]

    def __str__(self):
        return self.name

    # ────────────────────────────────────────────────────────────────────
    # Pool d'utilisateurs disponibles pour l'IA d'affectation et les
    # widgets de sélection. Combine :
    #   - les ProjectMember explicites
    #   - les TeamMembership ACTIVE des équipes contributrices (M2M `teams`)
    #     et de l'équipe principale (FK `team`).
    # Retourne un queryset de TeamMembership distinct par utilisateur, avec
    # leur rôle utile pour l'IA.
    # ────────────────────────────────────────────────────────────────────
    def get_assignable_memberships(self):
        from django.db.models import Q
        team_ids = set(self.teams.values_list("id", flat=True))
        if self.team_id:
            team_ids.add(self.team_id)
        if not team_ids:
            return TeamMembership.objects.none()
        return (
            TeamMembership.objects
            .filter(workspace=self.workspace, team_id__in=team_ids,
                    status=TeamMembership.Status.ACTIVE)
            .select_related("user", "user__profile", "team")
            .order_by("team__name", "user__last_name")
        )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name, fallback="project")

        if not self.code:
            self.code = next_sequential_code(
                model_class=Project,
                field_name="code",
                prefix="PRJ",
                padding=3,
            )

        self.progress_percent = max(0, min(100, self.progress_percent or 0))
        self.risk_score = compute_risk_score(self)

        super().save(*args, **kwargs)


class ProjectMember(TimeStampedModel):
    class Seniority(models.TextChoices):
        INTERN = "INTERN", "Stagiaire"
        JUNIOR = "JUNIOR", "Junior"
        MID = "MID", "Intermédiaire"
        SENIOR = "SENIOR", "Senior"
        LEAD = "LEAD", "Lead"
        EXPERT = "EXPERT", "Expert"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="project_memberships")
    role = models.CharField(max_length=60, blank=True)
    allocation_percent = models.PositiveSmallIntegerField(default=100)
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = [("project", "user")]
        ordering = ["project", "user"]

    def __str__(self):
        return f"{self.user} · {self.project}"


class CostCategory(TimeStampedModel):
    class CategoryType(models.TextChoices):
        HUMAN = "HUMAN", "Ressources humaines"
        SOFTWARE = "SOFTWARE", "Logiciels / Licences"
        INFRA = "INFRA", "Infrastructure / Cloud"
        EQUIPMENT = "EQUIPMENT", "Équipements"
        SUBCONTRACT = "SUBCONTRACT", "Sous-traitance"
        TRAVEL = "TRAVEL", "Déplacements"
        TRAINING = "TRAINING", "Formation"
        OTHER = "OTHER", "Autre"

    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=20, choices=CategoryType.choices, default=CategoryType.OTHER)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=20, default="#7C6FF7")

    @property
    def is_labor_category(self):
        return self.category_type == self.CategoryType.HUMAN

    @property
    def is_direct_cost_category(self):
        return self.category_type in {
            self.CategoryType.SOFTWARE,
            self.CategoryType.INFRA,
            self.CategoryType.EQUIPMENT,
            self.CategoryType.SUBCONTRACT,
            self.CategoryType.TRAVEL,
            self.CategoryType.TRAINING,
        }

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_direct_cost_category(self):
        return self.category_type in {
            self.CategoryType.SOFTWARE,
            self.CategoryType.INFRA,
            self.CategoryType.EQUIPMENT,
            self.CategoryType.SUBCONTRACT,
            self.CategoryType.TRAVEL,
            self.CategoryType.TRAINING,
            self.CategoryType.OTHER,
        }

    @property
    def is_labor_category(self):
        return self.category_type == self.CategoryType.HUMAN


class BillingRate(TimeStampedModel, SoftDeleteModel):
    class RateUnit(models.TextChoices):
        HOURLY = "HOURLY", "Horaire"
        DAILY = "DAILY", "Journalier"
        MONTHLY = "MONTHLY", "Mensuel"

    class WorkerLevel(models.TextChoices):
        INTERN = "INTERN", "Stagiaire"
        JUNIOR = "JUNIOR", "Junior"
        MID = "MID", "Intermédiaire"
        SENIOR = "SENIOR", "Senior"
        LEAD = "LEAD", "Lead"
        EXPERT = "EXPERT", "Expert"
        OTHER = "OTHER", "Autre"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing_rates",
        null=True,
        blank=True,
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="billing_rates",
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=120, blank=True)
    worker_level = models.CharField(max_length=20, choices=WorkerLevel.choices, default=WorkerLevel.OTHER)
    unit = models.CharField(max_length=10, choices=RateUnit.choices, default=RateUnit.DAILY)

    cost_rate_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sale_rate_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default="XOF")
    valid_from = models.DateField(default=timezone.localdate)
    valid_to = models.DateField(null=True, blank=True)

    is_internal_cost = models.BooleanField(default=True)
    is_billable_rate = models.BooleanField(default=True)

    class Meta:
        ordering = ["-valid_from"]
        verbose_name = "Tarif de facturation"
        verbose_name_plural = "Tarifs de facturation"

    def clean(self):
        errors = {}

        if not self.user and not self.team and not self.name:
            errors["name"] = "Veuillez renseigner un utilisateur, une équipe ou un nom de tarif."

        if self.user and self.team:
            errors["team"] = "Choisissez soit un utilisateur, soit une équipe, pas les deux."

        if self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = "La date de fin doit être postérieure à la date de début."

        if self.cost_rate_amount is not None and self.cost_rate_amount < 0:
            errors["cost_rate_amount"] = "Le coût interne ne peut pas être négatif."

        if self.sale_rate_amount is not None and self.sale_rate_amount < 0:
            errors["sale_rate_amount"] = "Le tarif de vente ne peut pas être négatif."

        if (
                self.sale_rate_amount is not None
                and self.cost_rate_amount is not None
                and self.is_billable_rate
                and self.sale_rate_amount < self.cost_rate_amount
        ):
            errors["sale_rate_amount"] = "Le tarif de vente ne peut pas être inférieur au coût interne."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.cost_rate_amount = self.cost_rate_amount or Decimal("0")
        self.sale_rate_amount = self.sale_rate_amount or Decimal("0")
        self.full_clean()
        super().save(*args, **kwargs)

    @staticmethod
    def get_user_daily_cost(user):
        today = timezone.localdate()
        profile = getattr(user, "profile", None)

        rate = (
            BillingRate.objects.filter(
                user=user,
                is_internal_cost=True,
                valid_from__lte=today,
            )
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
            .order_by("-valid_from", "-id")
            .first()
        )

        if rate:
            if rate.unit == BillingRate.RateUnit.DAILY:
                return rate.cost_rate_amount or Decimal("0")

            if rate.unit == BillingRate.RateUnit.HOURLY:
                hours_per_day = Decimal("8")
                if profile and getattr(profile, "capacity_hours_per_day", None):
                    hours_per_day = Decimal(str(profile.capacity_hours_per_day))
                return (rate.cost_rate_amount or Decimal("0")) * hours_per_day

            if rate.unit == BillingRate.RateUnit.MONTHLY:
                return (rate.cost_rate_amount or Decimal("0")) / Decimal("22")

        if profile and getattr(profile, "cost_per_day", None) is not None:
            return profile.cost_per_day or Decimal("0")

        return Decimal("0")

    @staticmethod
    def get_user_sale_daily_rate(user):
        today = timezone.localdate()
        profile = getattr(user, "profile", None)

        rate = (
            BillingRate.objects.filter(
                user=user,
                is_billable_rate=True,
                valid_from__lte=today,
            )
            .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
            .order_by("-valid_from", "-id")
            .first()
        )

        if rate:
            if rate.unit == BillingRate.RateUnit.DAILY:
                return rate.sale_rate_amount or Decimal("0")

            if rate.unit == BillingRate.RateUnit.HOURLY:
                hours_per_day = Decimal("8")
                if profile and getattr(profile, "capacity_hours_per_day", None):
                    hours_per_day = Decimal(str(profile.capacity_hours_per_day))
                return (rate.sale_rate_amount or Decimal("0")) * hours_per_day

            if rate.unit == BillingRate.RateUnit.MONTHLY:
                return (rate.sale_rate_amount or Decimal("0")) / Decimal("22")

        if profile and getattr(profile, "billable_rate_per_day", None) is not None:
            return profile.billable_rate_per_day or Decimal("0")

        return Decimal("0")

    @property
    def target_label(self):
        if self.user:
            return str(self.user)
        if self.team:
            return str(self.team)
        if self.name:
            return self.name
        return "Tarif"

    @property
    def margin_amount(self):
        return (self.sale_rate_amount or Decimal("0")) - (self.cost_rate_amount or Decimal("0"))

    @property
    def margin_percent(self):
        cost = self.cost_rate_amount or Decimal("0")
        if cost <= 0:
            return Decimal("0")
        return (self.margin_amount / cost) * Decimal("100")

    @property
    def is_currently_active(self):
        today = timezone.localdate()
        if self.valid_from and self.valid_from > today:
            return False
        if self.valid_to and self.valid_to < today:
            return False
        return True

    def __str__(self):
        return (
            f"{self.target_label} · {self.get_worker_level_display()} · "
            f"coût={self.cost_rate_amount} · vente={self.sale_rate_amount} {self.currency}"
        )


class ProjectBudget(TimeStampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        ESTIMATED = "ESTIMATED", "Estimatif"
        BASELINE = "BASELINE", "Prévisionnel validé"
        APPROVED = "APPROVED", "Approuvé"
        REVISED = "REVISED", "Révisé"
        CLOSED = "CLOSED", "Clos"

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="budgetestimatif")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    currency = models.CharField(max_length=10, default="XOF")

    estimated_labor_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_software_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_infra_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_subcontract_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_other_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    contingency_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    management_reserve_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    version_number = models.PositiveIntegerField(default=1)

    target_margin_percent = models.PositiveSmallIntegerField(default=20)
    markup_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    planned_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    approved_budget = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    alert_threshold_percent = models.PositiveSmallIntegerField(default=80)

    overhead_cost_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_project_budgets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def total_estimated_cost(self):
        return (
                (self.estimated_labor_cost or Decimal("0"))
                + (self.estimated_software_cost or Decimal("0"))
                + (self.estimated_infra_cost or Decimal("0"))
                + (self.estimated_subcontract_cost or Decimal("0"))
                + (self.estimated_other_cost or Decimal("0"))
                + (self.contingency_amount or Decimal("0"))
                + (self.management_reserve_amount or Decimal("0"))
        )

    @property
    def direct_cost_estimated(self):
        return (
                (self.estimated_software_cost or Decimal("0"))
                + (self.estimated_infra_cost or Decimal("0"))
                + (self.estimated_subcontract_cost or Decimal("0"))
                + (self.estimated_other_cost or Decimal("0"))
        )

    @property
    def labor_cost_estimated(self):
        return self.estimated_labor_cost or Decimal("0")

    @property
    def marked_up_sale_amount(self):
        return self.total_estimated_cost * (
                Decimal("1") + ((self.markup_percent or Decimal("0")) / Decimal("100"))
        )

    @property
    def expected_revenue_amount(self):
        if (self.planned_revenue or Decimal("0")) > 0:
            return self.planned_revenue
        return self.marked_up_sale_amount

    @property
    def estimated_margin_amount(self):
        return self.expected_revenue_amount - self.total_estimated_cost

    @property
    def estimated_margin_percent(self):
        cost = self.total_estimated_cost
        if cost <= 0:
            return Decimal("0")
        return (self.estimated_margin_amount / cost) * Decimal("100")

    @property
    def estimated_gross_margin_amount(self):
        return self.expected_revenue_amount - self.direct_cost_estimated

    @property
    def estimated_operating_margin_amount(self):
        return self.expected_revenue_amount - self.direct_cost_estimated - self.labor_cost_estimated

    @property
    def estimated_net_profit_amount(self):
        return (
                self.estimated_operating_margin_amount
                - (self.overhead_cost_amount or Decimal("0"))
                - (self.tax_amount or Decimal("0"))
        )

    @property
    def estimated_profit_margin_percent(self):
        revenue = self.expected_revenue_amount
        if revenue <= 0:
            return Decimal("0")
        return (self.estimated_net_profit_amount / revenue) * Decimal("100")

    @property
    def budget_consumption_percent(self):
        if not self.approved_budget or self.approved_budget <= 0:
            return Decimal("0")
        return (self.total_estimated_cost / self.approved_budget) * Decimal("100")

    @property
    def is_over_alert_threshold(self):
        return self.budget_consumption_percent >= Decimal(str(self.alert_threshold_percent or 0))

    def __str__(self):
        return f"Budget · {self.project.name}"


class ProjectEstimateLine(TimeStampedModel):
    class EstimationSource(models.TextChoices):
        MANUAL = "MANUAL", "Manuel"
        TASK = "TASK", "Tâche"
        SPRINT = "SPRINT", "Sprint"
        MILESTONE = "MILESTONE", "Jalon"

    class BudgetStage(models.TextChoices):
        ESTIMATED = "ESTIMATED", "Estimatif"
        BASELINE = "BASELINE", "Prévisionnel validé"
        FORECAST = "FORECAST", "Forecast"
        RAF = "RAF", "Reste à faire"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="estimate_lines",
    )
    category = models.ForeignKey(
        CostCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimate_lines",
    )
    source_type = models.CharField(
        max_length=20,
        choices=EstimationSource.choices,
        default=EstimationSource.MANUAL,
    )
    budget_stage = models.CharField(
        max_length=20,
        choices=BudgetStage.choices,
        default=BudgetStage.ESTIMATED,
    )

    task = models.ForeignKey(
        "Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimate_lines",
    )
    sprint = models.ForeignKey(
        "Sprint",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimate_lines",
    )
    milestone = models.ForeignKey(
        "Milestone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="estimate_lines",
    )

    label = models.CharField(max_length=180)
    description = models.TextField(blank=True)

    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    cost_unit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cost_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sale_unit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sale_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    markup_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_estimate_lines",
    )

    class Meta:
        ordering = ["project", "budget_stage", "label"]

    def save(self, *args, **kwargs):
        quantity = self.quantity or Decimal("0")
        cost_unit = self.cost_unit_amount or Decimal("0")

        self.cost_amount = quantity * cost_unit

        markup = self.markup_percent or Decimal("0")
        if markup == 0 and self.project_id:
            budget = getattr(self.project, "budgetestimatif", None)
            if budget and getattr(budget, "markup_percent", None):
                markup = budget.markup_percent or Decimal("0")

        self.sale_unit_amount = cost_unit * (
                Decimal("1") + (markup / Decimal("100"))
        )
        self.sale_amount = quantity * self.sale_unit_amount

        super().save(*args, **kwargs)

    @property
    def margin_amount(self):
        return (self.sale_amount or Decimal("0")) - (self.cost_amount or Decimal("0"))

    def __str__(self):
        return f"{self.project.name} · {self.label}"


class ProjectRevenue(TimeStampedModel):
    class RevenueType(models.TextChoices):
        FIXED = "FIXED", "Forfait"
        MILESTONE = "MILESTONE", "Paiement jalon"
        TIME_MATERIAL = "TIME_MATERIAL", "Régie"
        LICENSE = "LICENSE", "Licence"
        OTHER = "OTHER", "Autre"

    class RevenueStatus(models.TextChoices):
        PLANNED = "PLANNED", "Prévu"
        INVOICED = "INVOICED", "Facturé"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partiellement encaissé"
        PAID = "PAID", "Encaissé"
        CANCELLED = "CANCELLED", "Annulé"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="revenues")
    revenue_type = models.CharField(max_length=20, choices=RevenueType.choices, default=RevenueType.FIXED)
    status = models.CharField(max_length=20, choices=RevenueStatus.choices, default=RevenueStatus.PLANNED)

    title = models.CharField(max_length=180)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    invoiced_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default="XOF")
    expected_date = models.DateField(null=True, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_received = models.BooleanField(default=False)

    class Meta:
        ordering = ["expected_date", "title"]

    @property
    def remaining_to_invoice(self):
        return max((self.amount or Decimal("0")) - (self.invoiced_amount or Decimal("0")), Decimal("0"))

    @property
    def remaining_to_collect(self):
        return max((self.invoiced_amount or Decimal("0")) - (self.received_amount or Decimal("0")), Decimal("0"))

    @property
    def is_fully_collected(self):
        return (self.received_amount or Decimal("0")) >= (self.amount or Decimal("0"))

    def __str__(self):
        return f"{self.project.name} · {self.title}"


class TimesheetCostSnapshot(TimeStampedModel):
    timesheet_entry = models.OneToOneField(
        "TimesheetEntry",
        on_delete=models.CASCADE,
        related_name="cost_snapshot",
    )
    billing_rate = models.ForeignKey(
        BillingRate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timesheet_snapshots",
    )
    rate_unit = models.CharField(max_length=10, blank=True)
    rate_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    computed_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="XOF")

    def __str__(self):
        return f"{self.timesheet_entry} · {self.computed_cost}"


class Sprint(TimeStampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planifié"
        ACTIVE = "ACTIVE", "En cours"
        REVIEW = "REVIEW", "Review"
        DONE = "DONE", "Terminé"
        CANCELLED = "CANCELLED", "Annulé"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="sprints")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="sprints")
    name = models.CharField(max_length=120)
    number = models.PositiveIntegerField(default=1)
    goal = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    start_date = models.DateField()
    end_date = models.DateField()
    velocity_target = models.PositiveIntegerField(default=0)
    velocity_completed = models.PositiveIntegerField(default=0)
    total_story_points = models.PositiveIntegerField(default=0)
    completed_story_points = models.PositiveIntegerField(default=0)
    remaining_story_points = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("project", "number")]
        ordering = ["-start_date"]

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.project_id:
            self.workspace = self.project.workspace
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def remaining_days(self):
        return (self.end_date - timezone.localdate()).days

    def clean(self):
        if self.end_date < self.start_date:
            raise ValidationError("La date de fin doit être postérieure à la date de début.")

    def __str__(self):
        return f"{self.project.name} · Sprint {self.number}"


class SprintMetric(TimeStampedModel):
    sprint = models.ForeignKey(Sprint, on_delete=models.CASCADE, related_name="metrics")
    metric_date = models.DateField(default=timezone.localdate)
    planned_remaining_points = models.PositiveIntegerField(default=0)
    actual_remaining_points = models.PositiveIntegerField(default=0)
    completed_tasks = models.PositiveIntegerField(default=0)
    added_scope_points = models.PositiveIntegerField(default=0)
    removed_scope_points = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("sprint", "metric_date")]
        ordering = ["metric_date"]

    def __str__(self):
        return f"{self.sprint} · {self.metric_date}"


class BacklogItem(TimeStampedModel, SoftDeleteModel):
    class ItemType(models.TextChoices):
        EPIC = "EPIC", "Epic"
        STORY = "STORY", "User Story"
        TASK = "TASK", "Task"
        BUG = "BUG", "Bug"
        IMPROVEMENT = "IMPROVEMENT", "Improvement"
        SPIKE = "SPIKE", "Spike"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="backlog_items")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="backlog_items")
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="backlog_items")
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.TASK)
    rank = models.PositiveIntegerField(default=0)
    story_points = models.PositiveIntegerField(default=0)
    acceptance_criteria = models.TextField(blank=True)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_backlog_items",
    )

    class Meta:
        ordering = ["rank", "title"]

    def __str__(self):
        return self.title


class Task(TimeStampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        TODO = "TODO", "À faire"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        REVIEW = "REVIEW", "Review"
        DONE = "DONE", "Terminé"
        BLOCKED = "BLOCKED", "Bloqué"
        CANCELLED = "CANCELLED", "Annulé"
        EXPIRED = "EXPIRED", "Expirée non traitée"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critique"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tasks")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    backlog_item = models.ForeignKey(BacklogItem, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="tasks")
    parent = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="subtasks")
    title = models.CharField(max_length=220)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    risk_score = models.PositiveSmallIntegerField(default=0)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    estimate_hours = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    spent_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    start_date = models.DateField(
        null=True, blank=True,
        help_text="Date à partir de laquelle la tâche est planifiée (borne gauche du calendrier).",
    )
    due_date = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateField(
        null=True, blank=True,
        help_text="Date à laquelle la tâche a été marquée expirée non traitée.",
    )
    pm_overdue_notified_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Dernière fois que le PM a été notifié du dépassement d'échéance.",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_tasks",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
    )
    position = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    attachments_count = models.PositiveIntegerField(default=0)
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["position", "-priority", "title"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.project_id:
            self.workspace = self.project.workspace

        self.progress_percent = max(0, min(100, self.progress_percent))
        self.risk_score = max(0, min(100, self.risk_score))

        if self.status == self.Status.DONE and not self.completed_at:
            self.completed_at = timezone.now()

        self.full_clean()
        super().save(*args, **kwargs)

    # =========================================================================
    # Source unique de vérité pour l'affectation : maintient en cohérence
    # le FK Task.assignee et le modèle TaskAssignment (M2M étendu).
    # Les vues / services DOIVENT passer par ces méthodes.
    # =========================================================================
    def assign(self, user, *, assigned_by=None, allocation_percent=100):
        from django.db import transaction

        if user is None:
            return self.unassign(actor=assigned_by)

        with transaction.atomic():
            previous_id = self.assignee_id
            self._assigned_by = assigned_by  # picked up by signals
            self.assignee = user
            self.save(update_fields=["assignee", "updated_at"])

            TaskAssignment.objects.update_or_create(
                task=self,
                user=user,
                defaults={
                    "assigned_by": assigned_by,
                    "allocation_percent": allocation_percent,
                    "is_active": True,
                },
            )
            # Désactive les autres affectations actives sur cette tâche
            TaskAssignment.objects.filter(
                task=self, is_active=True
            ).exclude(user=user).update(is_active=False)

            # ActivityLog
            try:
                if previous_id != user.pk:
                    ActivityLog.objects.create(
                        workspace=self.workspace,
                        actor=assigned_by,
                        project=self.project,
                        task=self,
                        activity_type=ActivityLog.ActivityType.MEMBER_ASSIGNED,
                        title=f"Tâche assignée à {user}",
                        description=(
                            f"{assigned_by or 'Système'} a assigné la tâche "
                            f"« {self.title} » à {user}."
                        ),
                    )
            except Exception:
                pass

    def unassign(self, *, actor=None):
        from django.db import transaction

        with transaction.atomic():
            TaskAssignment.objects.filter(task=self, is_active=True).update(
                is_active=False
            )
            self._assigned_by = actor
            self.assignee = None
            self.save(update_fields=["assignee", "updated_at"])


class TaskAssignment(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_assignments_created",
    )
    allocation_percent = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("task", "user")]

    def __str__(self):
        return f"{self.task} -> {self.user}"


class TaskComment(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments")
    body = models.TextField()
    is_internal = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Commentaire {self.pk} · {self.task}"


class TaskAttachment(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    file = models.FileField(upload_to="devflow/tasks/attachments/")
    name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return self.name or self.file.name


class PullRequest(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Ouverte"
        APPROVED = "APPROVED", "Approuvée"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changements demandés"
        MERGED = "MERGED", "Mergée"
        CLOSED = "CLOSED", "Fermée"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="pull_requests")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="pull_requests")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="pull_requests")
    external_id = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=220)
    repository = models.CharField(max_length=180, blank=True)
    branch_name = models.CharField(max_length=160, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="authored_prs")
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.OPEN)
    reviewers_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    opened_at = models.DateTimeField(default=timezone.now)
    merged_at = models.DateTimeField(null=True, blank=True)
    url = models.URLField(blank=True)

    class Meta:
        ordering = ["-opened_at"]

    def __str__(self):
        return self.title


class Risk(TimeStampedModel, SoftDeleteModel):
    class Severity(models.TextChoices):
        LOW = "LOW", "Faible"
        MEDIUM = "MEDIUM", "Moyen"
        HIGH = "HIGH", "Élevé"
        CRITICAL = "CRITICAL", "Critique"

    class Probability(models.TextChoices):
        LOW = "LOW", "Faible"
        MEDIUM = "MEDIUM", "Moyenne"
        HIGH = "HIGH", "Élevée"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Ouvert"
        MITIGATED = "MITIGATED", "Maîtrisé"
        ESCALATED = "ESCALATED", "Escaladé"
        CLOSED = "CLOSED", "Clos"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="risks")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="risks")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="risks")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=12, choices=Severity.choices, default=Severity.MEDIUM)
    probability = models.CharField(max_length=12, choices=Probability.choices, default=Probability.MEDIUM)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    impact_score = models.PositiveSmallIntegerField(default=0)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="owned_risks")
    mitigation_plan = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def priority_score(self):
        severity_map = {
            self.Severity.LOW: 25,
            self.Severity.MEDIUM: 50,
            self.Severity.HIGH: 75,
            self.Severity.CRITICAL: 100,
        }
        probability_map = {
            self.Probability.LOW: 30,
            self.Probability.MEDIUM: 60,
            self.Probability.HIGH: 100,
        }
        severity_value = severity_map.get(self.severity, 0)
        probability_value = probability_map.get(self.probability, 0)
        return int((severity_value + probability_value + (self.impact_score or 0)) / 3)

    def save(self, *args, **kwargs):
        if not self.workspace_id:
            if self.project_id:
                self.workspace = self.project.workspace
            elif self.task_id:
                self.workspace = self.task.workspace

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class AInsight(TimeStampedModel):
    class InsightType(models.TextChoices):
        RISK = "RISK", "Risque"
        VELOCITY = "VELOCITY", "Vélocité"
        WORKLOAD = "WORKLOAD", "Charge"
        DELIVERY = "DELIVERY", "Livraison"
        PRODUCTIVITY = "PRODUCTIVITY", "Productivité"
        ALERT = "ALERT", "Alerte"
        SUGGESTION = "SUGGESTION", "Suggestion"

    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        LOW = "LOW", "Faible"
        MEDIUM = "MEDIUM", "Moyen"
        HIGH = "HIGH", "Élevé"
        CRITICAL = "CRITICAL", "Critique"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="ai_insights")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_insights")
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_insights")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_insights")
    insight_type = models.CharField(max_length=20, choices=InsightType.choices)
    severity = models.CharField(max_length=12, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=200)
    summary = models.TextField()
    recommendation = models.TextField(blank=True)
    score = models.PositiveSmallIntegerField(default=0)
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)
    detected_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-detected_at"]

    @property
    def severity_color(self):
        mapping = {
            self.Severity.INFO: "cyan",
            self.Severity.LOW: "green",
            self.Severity.MEDIUM: "amber",
            self.Severity.HIGH: "red",
            self.Severity.CRITICAL: "red",
        }
        return mapping.get(self.severity, "gray")

    @property
    def priority_rank(self):
        mapping = {
            self.Severity.INFO: 1,
            self.Severity.LOW: 2,
            self.Severity.MEDIUM: 3,
            self.Severity.HIGH: 4,
            self.Severity.CRITICAL: 5,
        }
        return mapping.get(self.severity, 1)

    @property
    def is_actionable(self):
        return bool(self.recommendation and self.recommendation.strip())

    def clean(self):
        errors = {}

        if self.score < 0 or self.score > 100:
            errors["score"] = "Le score doit être compris entre 0 et 100."

        if self.sprint and self.project and self.sprint.project_id != self.project_id:
            errors["sprint"] = "Le sprint sélectionné n'appartient pas au projet choisi."

        if self.task and self.project and self.task.project_id != self.project_id:
            errors["task"] = "La tâche sélectionnée n'appartient pas au projet choisi."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.workspace_id:
            if self.project_id:
                self.workspace = self.project.workspace
            elif self.sprint_id:
                self.workspace = self.sprint.workspace
            elif self.task_id:
                self.workspace = self.task.workspace

        self.score = max(0, min(100, self.score or 0))
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class Notification(TimeStampedModel):
    class NotificationType(models.TextChoices):
        TASK = "TASK", "Tâche"
        PROJECT = "PROJECT", "Projet"
        RISK = "RISK", "Risque"
        PR = "PR", "Pull Request"
        MESSAGE = "MESSAGE", "Message"
        SPRINT = "SPRINT", "Sprint"
        AI = "AI", "IA"
        SYSTEM = "SYSTEM", "Système"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                  related_name="devflow_notifications")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=NotificationType.choices)
    title = models.CharField(max_length=180)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ActivityLog(TimeStampedModel):
    class ActivityType(models.TextChoices):
        PROJECT_CREATED = "PROJECT_CREATED", "Projet créé"
        PROJECT_UPDATED = "PROJECT_UPDATED", "Projet mis à jour"
        TASK_CREATED = "TASK_CREATED", "Tâche créée"
        TASK_MOVED = "TASK_MOVED", "Tâche déplacée"
        TASK_BLOCKED = "TASK_BLOCKED", "Tâche bloquée"
        TASK_COMPLETED = "TASK_COMPLETED", "Tâche terminée"
        PR_OPENED = "PR_OPENED", "PR ouverte"
        PR_MERGED = "PR_MERGED", "PR mergée"
        SPRINT_STARTED = "SPRINT_STARTED", "Sprint démarré"
        SPRINT_REVIEWED = "SPRINT_REVIEWED", "Sprint review validée"
        MEMBER_ASSIGNED = "MEMBER_ASSIGNED", "Membre assigné"
        COMMENT_ADDED = "COMMENT_ADDED", "Commentaire ajouté"
        RISK_CREATED = "RISK_CREATED", "Risque créé"
        AI_GENERATED = "AI_GENERATED", "Insight IA"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="activity_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="devflow_activities")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")
    task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")
    activity_type = models.CharField(max_length=30, choices=ActivityType.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class DirectChannel(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="channels")
    name = models.CharField(max_length=120)
    is_private = models.BooleanField(default=False)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through="ChannelMembership",
                                     related_name="devflow_channels")

    class Meta:
        unique_together = [("workspace", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChannelMembership(TimeStampedModel):
    channel = models.ForeignKey(DirectChannel, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="channel_memberships")
    joined_at = models.DateTimeField(default=timezone.now)
    is_muted = models.BooleanField(default=False)

    class Meta:
        unique_together = [("channel", "user")]


class Message(TimeStampedModel):
    channel = models.ForeignKey(DirectChannel, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devflow_messages")
    body = models.TextField()
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies")

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.author} · {self.channel}"


class TimesheetEntry(TimeStampedModel):
    class ApprovalStatus(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        SUBMITTED = "SUBMITTED", "Soumis"
        APPROVED = "APPROVED", "Approuvé"
        REJECTED = "REJECTED", "Rejeté"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="timesheet_entries")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="timesheet_entries")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="timesheet_entries")
    task = models.ForeignKey("Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="timesheet_entries")

    entry_date = models.DateField(default=timezone.localdate)
    hours = models.DecimalField(max_digits=6, decimal_places=2)
    description = models.TextField(blank=True)

    is_billable = models.BooleanField(default=True)
    approval_status = models.CharField(max_length=15, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_timesheets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-entry_date", "-created_at"]

    def clean(self):
        # Les heures peuvent être 0 (saisie en attente) — on bloque seulement les valeurs négatives
        # ou abusives (> 24h sur une journée).
        if self.hours is not None:
            if self.hours < 0:
                raise ValidationError({"hours": "Le nombre d'heures ne peut pas être négatif."})
            if self.hours > 24:
                raise ValidationError({"hours": "Le nombre d'heures ne peut pas dépasser 24 sur une même journée."})

    def __str__(self):
        return f"{self.user} · {self.hours}h · {self.entry_date}"


class DashboardSnapshot(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="dashboard_snapshots")
    snapshot_date = models.DateField(default=timezone.localdate)
    active_projects = models.PositiveIntegerField(default=0)
    completed_tasks = models.PositiveIntegerField(default=0)
    pending_tasks = models.PositiveIntegerField(default=0)
    blocked_tasks = models.PositiveIntegerField(default=0)
    active_members = models.PositiveIntegerField(default=0)
    remote_members = models.PositiveIntegerField(default=0)
    portfolio_health_percent = models.PositiveSmallIntegerField(default=0)
    delivery_forecast_percent = models.PositiveSmallIntegerField(default=0)
    open_risks = models.PositiveIntegerField(default=0)
    velocity_score = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("workspace", "snapshot_date")]
        ordering = ["-snapshot_date"]

    def __str__(self):
        return f"{self.workspace} · {self.snapshot_date}"


class UserPreference(TimeStampedModel):
    class Theme(models.TextChoices):
        LIGHT = "light", "Clair"
        DARK = "dark", "Sombre"
        SYSTEM = "system", "Système"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devflow_preference")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="user_preferences")
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.LIGHT)
    sidebar_collapsed = models.BooleanField(default=False)
    default_view = models.CharField(max_length=30, default="dashboard")
    show_ai_panel = models.BooleanField(default=True)
    notifications_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"Préférences de {self.user}"


# ══════════════════════════════════════════════════════════════════════════════
# 1. ÉTIQUETTES (Labels / Tags)
#    Manquait : aucun système de tagging pour les tâches et projets.
# ══════════════════════════════════════════════════════════════════════════════

class Label(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=60)
    color = models.CharField(max_length=20, default="#F4722B")
    description = models.CharField(max_length=160, blank=True)

    class Meta:
        unique_together = [("workspace", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class TaskLabel(TimeStampedModel):
    """Table de liaison Task ↔ Label (M2M explicite pour garder la traçabilité)."""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="labels")
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="task_labels")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        unique_together = [("task", "label")]

    def __str__(self):
        return f"{self.label.name} → {self.task}"


class ProjectLabel(TimeStampedModel):
    """Même principe pour les projets."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="labels")
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="project_labels")

    class Meta:
        unique_together = [("project", "label")]

    def __str__(self):
        return f"{self.label.name} → {self.project}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. DÉPENDANCES DE TÂCHES
#    Manquait : relation "bloque / est bloquée par" entre tâches.
# ══════════════════════════════════════════════════════════════════════════════

class TaskDependency(TimeStampedModel):
    class DependencyType(models.TextChoices):
        BLOCKS = "BLOCKS", "Bloque"
        IS_BLOCKED_BY = "IS_BLOCKED_BY", "Est bloquée par"
        RELATES_TO = "RELATES_TO", "Liée à"
        DUPLICATES = "DUPLICATES", "Duplique"
        CLONED_FROM = "CLONED_FROM", "Clonée depuis"

    from_task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="outgoing_dependencies")
    to_task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="incoming_dependencies")
    dependency_type = models.CharField(max_length=20, choices=DependencyType.choices, default=DependencyType.BLOCKS)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        unique_together = [("from_task", "to_task", "dependency_type")]
        ordering = ["-created_at"]

    def clean(self):
        if self.from_task == self.to_task:
            raise ValidationError("Une tâche ne peut pas dépendre d'elle-même.")

    def __str__(self):
        return f"{self.from_task} {self.get_dependency_type_display()} {self.to_task}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. CHECKLISTS DE TÂCHES
#    Manquait : sous-éléments de type checklist (différent des sous-tâches).
# ══════════════════════════════════════════════════════════════════════════════

class TaskChecklist(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklists")
    title = models.CharField(max_length=160, default="Checklist")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"{self.title} · {self.task}"


class ChecklistItem(TimeStampedModel):
    checklist = models.ForeignKey(TaskChecklist, on_delete=models.CASCADE, related_name="items")
    text = models.CharField(max_length=220)
    is_checked = models.BooleanField(default=False)
    checked_at = models.DateTimeField(null=True, blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="checked_items",
    )
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]

    def save(self, *args, **kwargs):
        if self.is_checked and not self.checked_at:
            self.checked_at = timezone.now()
        elif not self.is_checked:
            self.checked_at = None
            self.checked_by = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.text


# ══════════════════════════════════════════════════════════════════════════════
# 4. JALONS (Milestones)
#    Manquait : aucun concept de jalons projet (go-live, beta, release…).
# ══════════════════════════════════════════════════════════════════════════════

class Milestone(TimeStampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planifié"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        AT_RISK = "AT_RISK", "À risque"
        DONE = "DONE", "Atteint"
        MISSED = "MISSED", "Manqué"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="milestones")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PLANNED)
    due_date = models.DateField()
    completed_at = models.DateField(null=True, blank=True)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="owned_milestones",
    )

    class Meta:
        ordering = ["due_date"]

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.project_id:
            self.workspace = self.project.workspace
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} · {self.name}"


class MilestoneTask(TimeStampedModel):
    """Association d'une tâche à un jalon."""
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name="milestone_tasks")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="milestones")

    class Meta:
        unique_together = [("milestone", "task")]

    def __str__(self):
        return f"{self.task} → {self.milestone}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. RELEASES / VERSIONS
#    Manquait : gestion des versions livrées (v1.0, v2.3-beta…).
# ══════════════════════════════════════════════════════════════════════════════

class Release(TimeStampedModel, SoftDeleteModel):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planifiée"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        RELEASED = "RELEASED", "Publiée"
        CANCELLED = "CANCELLED", "Annulée"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="releases")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="releases")
    name = models.CharField(max_length=100)  # ex: "v2.4.0"
    tag = models.CharField(max_length=60, blank=True)  # ex: "stable", "beta"
    description = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PLANNED)
    release_date = models.DateField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    changelog = models.TextField(blank=True)
    release_url = models.URLField(blank=True)
    tasks = models.ManyToManyField(Task, blank=True, related_name="releases")
    sprints = models.ManyToManyField(Sprint, blank=True, related_name="releases")

    class Meta:
        unique_together = [("project", "name")]
        ordering = ["-release_date"]

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.project_id:
            self.workspace = self.project.workspace
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.project.name} · {self.name}"


# ══════════════════════════════════════════════════════════════════════════════
# 6. ROADMAP
#    Manquait : feuille de route temporelle avec items positionnés.
# ══════════════════════════════════════════════════════════════════════════════

class Roadmap(TimeStampedModel, SoftDeleteModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="roadmaps")
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_public = models.BooleanField(default=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="owned_roadmaps",
    )

    class Meta:
        unique_together = [("workspace", "name")]
        ordering = ["-start_date"]

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    def __str__(self):
        return self.name


class RoadmapItem(TimeStampedModel):
    class ItemStatus(models.TextChoices):
        PLANNED = "PLANNED", "Planifié"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        DONE = "DONE", "Terminé"
        AT_RISK = "AT_RISK", "À risque"

    roadmap = models.ForeignKey(Roadmap, on_delete=models.CASCADE, related_name="items")
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roadmap_items",
    )
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roadmap_items",
    )
    title = models.CharField(max_length=160)
    color = models.CharField(max_length=20, default="#F4722B")
    status = models.CharField(max_length=15, choices=ItemStatus.choices, default=ItemStatus.PLANNED)
    start_date = models.DateField()
    end_date = models.DateField()
    row = models.PositiveIntegerField(default=0, help_text="Ligne d'affichage sur la roadmap")

    class Meta:
        ordering = ["start_date", "row"]

    def clean(self):
        errors = {}

        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = "La date de fin doit être postérieure ou égale à la date de début."

        if self.roadmap_id and self.start_date and self.start_date < self.roadmap.start_date:
            errors["start_date"] = "La date de début doit être comprise dans la période de la roadmap."

        if self.roadmap_id and self.end_date and self.end_date > self.roadmap.end_date:
            errors["end_date"] = "La date de fin doit être comprise dans la période de la roadmap."

        if self.project_id and self.milestone_id and self.milestone.project_id != self.project_id:
            errors["milestone"] = "Le jalon ne correspond pas au projet sélectionné."

        if errors:
            raise ValidationError(errors)

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    def __str__(self):
        return f"{self.roadmap.name} · {self.title}"


# ══════════════════════════════════════════════════════════════════════════════
# 7. COLONNES KANBAN PERSONNALISÉES
#    Manquait : les colonnes du board sont codées en dur dans le frontend.
#    Chaque projet devrait pouvoir définir ses propres colonnes.
# ══════════════════════════════════════════════════════════════════════════════

class BoardColumn(TimeStampedModel):
    """Colonne Kanban configurable par projet."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="board_columns")
    name = models.CharField(max_length=80)
    mapped_status = models.CharField(
        max_length=20,
        choices=Task.Status.choices,
        blank=True,
        help_text="Statut Task auquel cette colonne correspond.",
    )
    position = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=20, blank=True)
    wip_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Limite Work-In-Progress (0 = illimitée).",
    )
    is_done_column = models.BooleanField(default=False)

    class Meta:
        unique_together = [("project", "name")]
        ordering = ["position"]

    def __str__(self):
        return f"{self.project.name} · {self.name}"


# ══════════════════════════════════════════════════════════════════════════════
# 8. INVITATIONS AU WORKSPACE
#    Manquait : aucun workflow d'invitation par e-mail.
# ══════════════════════════════════════════════════════════════════════════════

class WorkspaceInvitation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        ACCEPTED = "ACCEPTED", "Acceptée"
        DECLINED = "DECLINED", "Refusée"
        EXPIRED = "EXPIRED", "Expirée"
        REVOKED = "REVOKED", "Révoquée"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_invitations",
    )
    role = models.CharField(
        max_length=20,
        choices=TeamMembership.Role.choices,
        default=TeamMembership.Role.DEVELOPER,
    )
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="invitations")
    token = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("workspace", "email")]
        ordering = ["-created_at"]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"Invitation {self.email} → {self.workspace.name}"


# ══════════════════════════════════════════════════════════════════════════════
# 9. INTÉGRATIONS EXTERNES
#    Manquait : connexion à GitHub, GitLab, Jira, Slack, etc.
# ══════════════════════════════════════════════════════════════════════════════

class Integration(TimeStampedModel):
    class Provider(models.TextChoices):
        GITHUB = "GITHUB", "GitHub"
        GITLAB = "GITLAB", "GitLab"
        BITBUCKET = "BITBUCKET", "Bitbucket"
        JIRA = "JIRA", "Jira"
        SLACK = "SLACK", "Slack"
        TEAMS = "TEAMS", "Microsoft Teams"
        FIGMA = "FIGMA", "Figma"
        SENTRY = "SENTRY", "Sentry"
        DATADOG = "DATADOG", "Datadog"
        LINEAR = "LINEAR", "Linear"
        OTHER = "OTHER", "Autre"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        ERROR = "ERROR", "Erreur"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="integrations")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    config = models.JSONField(default=dict, blank=True,
                              help_text="Paramètres propres au provider (org, repo, channel…)")
    # Les tokens sensibles doivent être chiffrés (ex: django-fernet-fields)
    access_token_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    installed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="installed_integrations",
    )

    class Meta:
        unique_together = [("workspace", "provider")]
        ordering = ["provider"]

    def __str__(self):
        return f"{self.get_provider_display()} · {self.workspace.name}"


class Webhook(TimeStampedModel):
    """Webhooks sortants (DevFlow → service externe)."""

    class Event(models.TextChoices):
        TASK_CREATED = "task.created", "Tâche créée"
        TASK_UPDATED = "task.updated", "Tâche mise à jour"
        TASK_COMPLETED = "task.completed", "Tâche terminée"
        SPRINT_STARTED = "sprint.started", "Sprint démarré"
        SPRINT_DONE = "sprint.done", "Sprint terminé"
        PR_MERGED = "pr.merged", "PR mergée"
        RISK_ESCALATED = "risk.escalated", "Risque escaladé"
        AI_INSIGHT = "ai.insight", "Insight IA"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="webhooks")
    url = models.URLField()
    secret = models.CharField(max_length=128, blank=True)
    events = models.JSONField(default=list, help_text="Liste des événements abonnés.")
    is_active = models.BooleanField(default=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Webhook {self.url} · {self.workspace.name}"


# ══════════════════════════════════════════════════════════════════════════════
# 10. RÉACTIONS EMOJI
#     Manquait : réactions sur commentaires et messages (type Slack/GitHub).
# ══════════════════════════════════════════════════════════════════════════════

class Reaction(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reactions")
    emoji = models.CharField(max_length=10)
    # Relations génériques vers TaskComment ou Message (on garde deux FK nullable)
    task_comment = models.ForeignKey(
        TaskComment, on_delete=models.CASCADE,
        null=True, blank=True, related_name="reactions",
    )
    message = models.ForeignKey(
        Message, on_delete=models.CASCADE,
        null=True, blank=True, related_name="reactions",
    )

    class Meta:
        ordering = ["emoji"]

    def clean(self):
        if not self.task_comment and not self.message:
            raise ValidationError("Une réaction doit être liée à un commentaire ou à un message.")
        if self.task_comment and self.message:
            raise ValidationError("Une réaction ne peut pas être liée aux deux à la fois.")

    def __str__(self):
        return f"{self.emoji} · {self.user}"


# ══════════════════════════════════════════════════════════════════════════════
# 11. PIÈCES JOINTES AUX MESSAGES
#     Manquait : les Message n'avaient pas de système de fichiers joints.
# ══════════════════════════════════════════════════════════════════════════════

class MessageAttachment(TimeStampedModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="devflow/messages/attachments/")
    name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return self.name or self.file.name


# ══════════════════════════════════════════════════════════════════════════════
# 12. SPRINT REVIEW & RETROSPECTIVE
#     Manquait : compte-rendus des cérémonies Scrum.
# ══════════════════════════════════════════════════════════════════════════════

class SprintReview(TimeStampedModel):
    sprint = models.OneToOneField(Sprint, on_delete=models.CASCADE, related_name="review")
    held_at = models.DateTimeField(null=True, blank=True)
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="facilitated_reviews",
    )
    demo_notes = models.TextField(blank=True)
    accepted_stories = models.ManyToManyField(BacklogItem, blank=True, related_name="reviewed_in")
    stakeholder_feedback = models.TextField(blank=True)
    velocity_actual = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Review · {self.sprint}"


class SprintRetrospective(TimeStampedModel):
    sprint = models.OneToOneField(Sprint, on_delete=models.CASCADE, related_name="retrospective")
    held_at = models.DateTimeField(null=True, blank=True)
    facilitator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="facilitated_retros",
    )
    went_well = models.TextField(blank=True, help_text="Ce qui a bien fonctionné")
    to_improve = models.TextField(blank=True, help_text="Ce qui doit être amélioré")
    action_items = models.TextField(blank=True, help_text="Actions décidées")
    mood_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Score d'humeur d'équipe 1-5",
    )

    def __str__(self):
        return f"Rétro · {self.sprint}"


# ══════════════════════════════════════════════════════════════════════════════
# 13. CLÉS API WORKSPACE
#     Manquait : accès programmatique à l'API DevFlow par workspace.
# ══════════════════════════════════════════════════════════════════════════════

class APIKey(TimeStampedModel):
    class Scope(models.TextChoices):
        READ_ONLY = "READ_ONLY", "Lecture seule"
        READ_WRITE = "READ_WRITE", "Lecture / Écriture"
        ADMIN = "ADMIN", "Admin"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="api_keys")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_api_keys",
    )
    name = models.CharField(max_length=100)
    key_hash = models.CharField(max_length=128, unique=True, help_text="SHA-256 de la clé en clair.")
    key_prefix = models.CharField(max_length=10, help_text="Préfixe visible (ex: df_live_…)")
    scope = models.CharField(max_length=15, choices=Scope.choices, default=Scope.READ_ONLY)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.key_prefix}… · {self.workspace.name}"


# ══════════════════════════════════════════════════════════════════════════════
# 14. PARAMÈTRES DU WORKSPACE
#     Manquait : configuration fine du workspace (au-delà du modèle Workspace).
# ══════════════════════════════════════════════════════════════════════════════

class WorkspaceSettings(TimeStampedModel):
    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="settings")
    # Sprints
    default_sprint_duration_days = models.PositiveSmallIntegerField(default=14)
    story_points_scale = models.JSONField(
        default=list,
        help_text="Séquence de points ex: [1,2,3,5,8,13,21]",
    )
    # Notifications
    notify_task_assigned = models.BooleanField(default=True)
    notify_task_due_soon = models.BooleanField(default=True)
    notify_blocked_task = models.BooleanField(default=True)
    notify_pr_review = models.BooleanField(default=True)
    due_soon_threshold_days = models.PositiveSmallIntegerField(default=3)
    # IA
    ai_insights_enabled = models.BooleanField(default=True)
    ai_risk_auto_detect = models.BooleanField(default=True)
    ai_workload_suggestions = models.BooleanField(default=True)
    # Accès
    allow_guest_access = models.BooleanField(default=False)
    require_2fa = models.BooleanField(default=False)
    # Apparence
    primary_color = models.CharField(max_length=20, default="#F4722B")
    logo_url = models.URLField(blank=True)

    def __str__(self):
        return f"Settings · {self.workspace.name}"


# ══════════════════════════════════════════════════════════════════════════════
# 15. OKR — OBJECTIFS ET RÉSULTATS CLÉS
#     Manquait : alignement stratégique des équipes sur des objectifs mesurables.
# ══════════════════════════════════════════════════════════════════════════════

class Objective(TimeStampedModel, SoftDeleteModel):
    class Level(models.TextChoices):
        COMPANY = "COMPANY", "Entreprise"
        TEAM = "TEAM", "Équipe"
        INDIVIDUAL = "INDIVIDUAL", "Individuel"

    class Status(models.TextChoices):
        ON_TRACK = "ON_TRACK", "En bonne voie"
        AT_RISK = "AT_RISK", "À risque"
        BEHIND = "BEHIND", "En retard"
        DONE = "DONE", "Atteint"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="objectives")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, related_name="objectives")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="owned_objectives",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    level = models.CharField(max_length=15, choices=Level.choices, default=Level.TEAM)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ON_TRACK)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    start_date = models.DateField()
    end_date = models.DateField()
    quarter_label = models.CharField(max_length=20, blank=True, help_text="Ex: Q2 2026")

    class Meta:
        ordering = ["-start_date", "title"]

    def __str__(self):
        return self.title


class KeyResult(TimeStampedModel):
    class ResultType(models.TextChoices):
        PERCENTAGE = "PERCENTAGE", "Pourcentage"
        NUMBER = "NUMBER", "Nombre"
        BOOLEAN = "BOOLEAN", "Oui / Non"
        CURRENCY = "CURRENCY", "Montant"

    objective = models.ForeignKey(Objective, on_delete=models.CASCADE, related_name="key_results")
    title = models.CharField(max_length=200)
    result_type = models.CharField(max_length=15, choices=ResultType.choices, default=ResultType.PERCENTAGE)
    target_value = models.DecimalField(max_digits=14, decimal_places=2, default=100)
    current_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    unit = models.CharField(max_length=30, blank=True, help_text="Ex: %, €, tickets")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="key_results",
    )

    class Meta:
        ordering = ["objective", "title"]

    @property
    def progress_percent(self):
        if self.target_value == 0:
            return 0
        value = int((self.current_value / self.target_value) * 100)
        return max(0, min(value, 100))

    def __str__(self):
        return f"{self.objective.title} · {self.title}"


class ProjectExpense(TimeStampedModel):
    class ExpenseStatus(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        ESTIMATED = "ESTIMATED", "Estimatif"
        FORECAST = "FORECAST", "Prévisionnel"
        COMMITTED = "COMMITTED", "Engagé"
        ACCRUED = "ACCRUED", "Constaté"
        PAID = "PAID", "Décaissé"
        REJECTED = "REJECTED", "Rejeté"
        VALIDATED = "VALIDATED", "Validé"

    class ApprovalState(models.TextChoices):
        PENDING = "PENDING", "En attente"
        LEVEL1_APPROVED = "LEVEL1_APPROVED", "Validé niveau 1"
        LEVEL2_APPROVED = "LEVEL2_APPROVED", "Validé niveau 2"
        REJECTED = "REJECTED", "Rejeté"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="expenses")
    category = models.ForeignKey(
        CostCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
    )
    task = models.ForeignKey("Task", on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    sprint = models.ForeignKey("Sprint", on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    milestone = models.ForeignKey("Milestone", on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="expenses")

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.DRAFT,
    )

    approval_state = models.CharField(
        max_length=25,
        choices=ApprovalState.choices,
        default=ApprovalState.PENDING,
    )

    expense_date = models.DateField(default=timezone.localdate)
    committed_date = models.DateField(null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=10, default="XOF")
    vendor = models.CharField(max_length=150, blank=True)
    reference = models.CharField(max_length=120, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_project_expenses",
    )

    level1_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="level1_approved_project_expenses",
    )
    level1_approved_at = models.DateTimeField(null=True, blank=True)

    level2_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="level2_approved_project_expenses",
    )
    level2_approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_project_expenses",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="validated_project_expenses",
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    is_direct_cost = models.BooleanField(default=True)
    is_labor_cost = models.BooleanField(default=False)

    class Meta:
        ordering = ["-expense_date", "-created_at"]
        permissions = [
            ("approve_projectexpense_level1", "Peut valider une dépense au niveau 1"),
            ("approve_projectexpense_level2", "Peut valider une dépense au niveau 2"),
            ("view_projectexpense_financial", "Peut voir les dépenses projet"),
        ]

    def clean(self):
        errors = {}

        if self.amount is not None and self.amount < 0:
            errors["amount"] = "Le montant ne peut pas être négatif."

        if self.paid_date and self.committed_date and self.paid_date < self.committed_date:
            errors["paid_date"] = "La date de paiement ne peut pas être antérieure à la date d'engagement."

        if self.category:
            if getattr(self.category, "is_labor_category", False):
                self.is_labor_cost = True
                self.is_direct_cost = False
            elif getattr(self.category, "is_direct_cost_category", False):
                self.is_direct_cost = True

        if errors:
            raise ValidationError(errors)

    def approve_level1(self, user):
        if self.approval_state not in [self.ApprovalState.PENDING]:
            raise ValidationError("Cette dépense ne peut plus être validée au niveau 1.")

        self.approval_state = self.ApprovalState.LEVEL1_APPROVED
        self.level1_approved_by = user
        self.level1_approved_at = timezone.now()
        self.status = self.ExpenseStatus.COMMITTED
        self.save(update_fields=[
            "approval_state",
            "level1_approved_by",
            "level1_approved_at",
            "status",
            "updated_at",
        ])

    @property
    def can_be_edited(self):
        return self.approval_state == self.ApprovalState.PENDING

    def approve_level2(self, user):
        if self.approval_state not in [self.ApprovalState.LEVEL1_APPROVED]:
            raise ValidationError("La validation niveau 2 nécessite une validation niveau 1.")

        now = timezone.now()
        self.approval_state = self.ApprovalState.LEVEL2_APPROVED
        self.level2_approved_by = user
        self.level2_approved_at = now
        self.validated_by = user
        self.validated_at = now
        self.status = self.ExpenseStatus.VALIDATED
        self.save(update_fields=[
            "approval_state",
            "level2_approved_by",
            "level2_approved_at",
            "validated_by",
            "validated_at",
            "status",
            "updated_at",
        ])

    def reject(self, user, reason=""):
        now = timezone.now()
        self.approval_state = self.ApprovalState.REJECTED
        self.rejected_by = user
        self.rejected_at = now
        self.rejection_reason = reason or ""
        self.status = self.ExpenseStatus.REJECTED
        self.save(update_fields=[
            "approval_state",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "status",
            "updated_at",
        ])

    @property
    def is_paid(self):
        return self.status == self.ExpenseStatus.PAID

    @property
    def is_committed(self):
        return self.status == self.ExpenseStatus.COMMITTED

    @property
    def is_fully_approved(self):
        return self.approval_state == self.ApprovalState.LEVEL2_APPROVED

    def __str__(self):
        return f"{self.project.name} · {self.title} · {self.amount}"


class ProjectDocumentImport(TimeStampedModel):
    class ImportStatus(models.TextChoices):
        UPLOADED = "UPLOADED", "Uploadé"
        PROCESSING = "PROCESSING", "En traitement"
        COMPLETED = "COMPLETED", "Terminé"
        FAILED = "FAILED", "Échec"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="project_imports")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file = models.FileField(upload_to="devflow/project_imports/")
    status = models.CharField(max_length=20, choices=ImportStatus.choices, default=ImportStatus.UPLOADED)

    extracted_text = models.TextField(blank=True)
    ai_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_imports",
    )

    def __str__(self):
        return f"Import {self.pk} · {self.workspace.name}"


class ProjectKPI(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="kpis")
    name = models.CharField(max_length=120)
    value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    value_text = models.CharField(max_length=120, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    module_name = models.CharField(max_length=160, blank=True)


class ProjectModuleROI(TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="module_rois")
    module_name = models.CharField(max_length=160)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    roi_percent = models.DecimalField(max_digits=8, decimal_places=2, default=0)


class SprintFinancialSnapshot(TimeStampedModel):
    sprint = models.ForeignKey(Sprint, on_delete=models.CASCADE, related_name="financial_snapshots")
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)


class FeatureFinancialSnapshot(TimeStampedModel):
    backlog_item = models.ForeignKey(BacklogItem, on_delete=models.CASCADE, related_name="financial_snapshots")
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    roi_percent = models.DecimalField(max_digits=8, decimal_places=2, default=0)


# =========================================================================
# AI PROJECT STRUCTURING — Proposals
# =========================================================================
class ProjectAIProposal(TimeStampedModel):
    """
    Proposition IA générée à la création d'un projet (ou à la demande).
    Stocke la roadmap, milestones, sprints, backlog, tasks, dependencies,
    assignments suggérés. L'utilisateur valide ou rejette avant application.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente de génération"
        GENERATING = "GENERATING", "Génération en cours"
        READY = "READY", "Prête à validation"
        PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED", "Partiellement validée"
        VALIDATED = "VALIDATED", "Validée"
        APPLIED = "APPLIED", "Appliquée au projet"
        REJECTED = "REJECTED", "Rejetée"
        FAILED = "FAILED", "Échec de génération"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="ai_proposals",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="ai_proposals",
    )
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.PENDING)

    # Méta-données IA
    used_provider = models.CharField(max_length=50, blank=True)
    used_model = models.CharField(max_length=120, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    raw_payload = models.JSONField(default=dict, blank=True)
    prompt_snapshot = models.TextField(blank=True)
    error_message = models.TextField(blank=True)

    # Synthèse pour la prévisualisation
    summary = models.TextField(blank=True)
    risks_summary = models.TextField(blank=True)
    recommendations = models.JSONField(default=list, blank=True)

    # Workflow
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="triggered_ai_proposals",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="validated_ai_proposals",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Proposition IA projet"
        verbose_name_plural = "Propositions IA projet"

    def __str__(self):
        return f"Proposition IA · {self.project.name} · {self.get_status_display()}"

    # Helpers d'agrégation utilisés par les vues
    def items_by_kind(self, kind):
        return self.items.filter(kind=kind).order_by("order_index", "id")

    @property
    def task_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.TASK)

    @property
    def sprint_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.SPRINT)

    @property
    def milestone_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.MILESTONE)

    @property
    def roadmap_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.ROADMAP_ITEM)

    @property
    def backlog_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.BACKLOG)

    @property
    def dependency_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.DEPENDENCY)

    @property
    def assignment_items(self):
        return self.items_by_kind(ProjectAIProposalItem.Kind.ASSIGNMENT)

    @property
    def total_items_count(self):
        return self.items.count()

    @property
    def validated_items_count(self):
        return self.items.filter(item_status=ProjectAIProposalItem.ItemStatus.VALIDATED).count()

    @property
    def is_editable(self):
        return self.status in {
            self.Status.READY,
            self.Status.PARTIALLY_VALIDATED,
            self.Status.VALIDATED,
        }


class ProjectAIProposalItem(TimeStampedModel):
    """
    Item individuel d'une proposition IA. Le payload est volontairement
    flexible (JSONField) pour accueillir les attributs propres à chaque
    type sans multiplier les colonnes inutilisées.
    """

    class Kind(models.TextChoices):
        ROADMAP_ITEM = "ROADMAP_ITEM", "Phase roadmap"
        MILESTONE = "MILESTONE", "Jalon"
        SPRINT = "SPRINT", "Sprint"
        BACKLOG = "BACKLOG", "Élément de backlog"
        TASK = "TASK", "Tâche"
        DEPENDENCY = "DEPENDENCY", "Dépendance"
        ASSIGNMENT = "ASSIGNMENT", "Affectation"

    class ItemStatus(models.TextChoices):
        PROPOSED = "PROPOSED", "Proposé"
        EDITED = "EDITED", "Modifié"
        VALIDATED = "VALIDATED", "Validé"
        REJECTED = "REJECTED", "Rejeté"
        APPLIED = "APPLIED", "Appliqué"

    proposal = models.ForeignKey(
        ProjectAIProposal,
        on_delete=models.CASCADE,
        related_name="items",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    item_status = models.CharField(
        max_length=15,
        choices=ItemStatus.choices,
        default=ItemStatus.PROPOSED,
    )

    # Identifiant logique pour les références internes (ex. pour relier
    # une dépendance à une tâche par son `local_ref`)
    local_ref = models.CharField(max_length=80, blank=True)

    # Champs courants (suffisants pour 90% des cas)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    order_index = models.PositiveIntegerField(default=0)

    # Tâche-spécifique (les autres types peuvent réutiliser ce qui leur sert)
    priority = models.CharField(max_length=20, blank=True)
    complexity = models.CharField(max_length=20, blank=True)
    estimate_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    recommended_profile = models.CharField(max_length=120, blank=True)
    recommended_assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposed_assignments",
    )
    sprint_ref = models.CharField(max_length=80, blank=True)
    milestone_ref = models.CharField(max_length=80, blank=True)
    depends_on_refs = models.JSONField(default=list, blank=True)
    acceptance_criteria = models.JSONField(default=list, blank=True)

    # Sprint-spécifique
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    velocity_target = models.PositiveIntegerField(default=0)

    # Free-form payload (extensions futures sans migration)
    extra_payload = models.JSONField(default=dict, blank=True)

    # Workflow
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_ai_proposal_items",
    )
    edited_at = models.DateTimeField(null=True, blank=True)
    applied_object_id = models.PositiveIntegerField(null=True, blank=True)
    applied_object_model = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["proposal", "kind", "order_index"]
        indexes = [
            models.Index(fields=["proposal", "kind"]),
            models.Index(fields=["proposal", "item_status"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.title or self.local_ref}"


class ProjectMeeting(TimeStampedModel, SoftDeleteModel):
    """Réunion projet (cadrage, suivi, sprint review, comité, etc.)."""

    class MeetingType(models.TextChoices):
        FRAMING = "FRAMING", "Cadrage"
        FOLLOW_UP = "FOLLOW_UP", "Suivi"
        SPRINT_REVIEW = "SPRINT_REVIEW", "Sprint review"
        PROJECT_COMMITTEE = "PROJECT_COMMITTEE", "Comité projet"
        STEERING_COMMITTEE = "STEERING_COMMITTEE", "Comité de pilotage"
        RETROSPECTIVE = "RETROSPECTIVE", "Rétrospective"
        OTHER = "OTHER", "Autre"

    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planifiée"
        HELD = "HELD", "Tenue"
        CANCELLED = "CANCELLED", "Annulée"
        POSTPONED = "POSTPONED", "Reportée"

    workspace = models.ForeignKey(
        "Workspace", on_delete=models.CASCADE, related_name="meetings"
    )
    project = models.ForeignKey(
        "Project", on_delete=models.CASCADE, related_name="meetings"
    )
    sprint = models.ForeignKey(
        "Sprint", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="meetings",
    )
    title = models.CharField(max_length=200)
    meeting_type = models.CharField(
        max_length=25, choices=MeetingType.choices, default=MeetingType.FOLLOW_UP,
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PLANNED,
    )

    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    location = models.CharField(max_length=200, blank=True)
    meeting_link = models.URLField(blank=True)

    organizer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="organized_meetings",
    )
    internal_participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="attended_meetings",
        blank=True,
    )
    external_participants = models.TextField(
        blank=True,
        help_text="Liste libre, un par ligne (Nom — Société — Email)",
    )

    agenda = models.TextField(blank=True, help_text="Ordre du jour")
    notes = models.TextField(blank=True, help_text="Prise de notes / compte-rendu")
    decisions = models.TextField(blank=True, help_text="Décisions prises")
    blockers = models.TextField(blank=True, help_text="Points bloquants")
    next_steps = models.TextField(blank=True, help_text="Prochaine étape")

    # Synthèse IA (générée à la demande)
    ai_summary = models.TextField(blank=True)
    ai_extracted_at = models.DateTimeField(null=True, blank=True)
    ai_used_provider = models.CharField(max_length=50, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_meetings",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="updated_meetings",
    )

    class Meta:
        ordering = ["-scheduled_at"]
        verbose_name = "Réunion projet"
        verbose_name_plural = "Réunions projet"
        permissions = [
            ("ai_process_meeting", "Peut lancer le traitement IA d'une réunion"),
        ]

    def __str__(self):
        return f"{self.title} · {self.project.name}"

    def save(self, *args, **kwargs):
        if not self.workspace_id and self.project_id:
            self.workspace = self.project.workspace
        super().save(*args, **kwargs)

    @property
    def duration_label(self):
        h, m = divmod(self.duration_minutes or 0, 60)
        if h and m:
            return f"{h}h {m:02d}"
        if h:
            return f"{h}h"
        return f"{m} min"

    @property
    def participants_count(self):
        external = sum(1 for line in (self.external_participants or "").splitlines() if line.strip())
        return self.internal_participants.count() + external

    @property
    def status_color(self):
        return {
            self.Status.PLANNED: "cyan",
            self.Status.HELD: "green",
            self.Status.CANCELLED: "red",
            self.Status.POSTPONED: "amber",
        }.get(self.status, "cyan")


class MeetingActionItem(TimeStampedModel):
    """Action décidée pendant une réunion. Convertible en Task."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Ouverte"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        DONE = "DONE", "Terminée"
        CANCELLED = "CANCELLED", "Annulée"

    meeting = models.ForeignKey(
        ProjectMeeting, on_delete=models.CASCADE, related_name="action_items",
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="meeting_action_items",
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.OPEN,
    )
    priority = models.CharField(
        max_length=20,
        choices=[
            ("LOW", "Low"), ("MEDIUM", "Medium"),
            ("HIGH", "High"), ("CRITICAL", "Critique"),
        ],
        default="MEDIUM",
    )

    # Lien optionnel vers la Task créée à partir de cette action
    converted_task = models.ForeignKey(
        "Task",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="source_meeting_actions",
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="converted_meeting_actions",
    )

    class Meta:
        ordering = ["due_date", "-created_at"]
        verbose_name = "Action de réunion"
        verbose_name_plural = "Actions de réunion"

    def __str__(self):
        return f"{self.title} · {self.meeting.title}"


class MeetingAttachment(TimeStampedModel):
    meeting = models.ForeignKey(
        ProjectMeeting, on_delete=models.CASCADE, related_name="attachments",
    )
    file = models.FileField(upload_to="devflow/meetings/")
    label = models.CharField(max_length=200, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="meeting_uploads",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.label or self.file.name


class AIChatSession(TimeStampedModel):
    """
    Session conversationnelle DevFlow AI. Permet de garder l'historique
    multi-tours, le contexte projet/sprint actif, et les statistiques
    d'usage.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_chat_sessions",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="ai_chat_sessions",
        null=True,
        blank=True,
    )
    project = models.ForeignKey(
        "Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_chat_sessions",
    )
    title = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Session chat IA"
        verbose_name_plural = "Sessions chat IA"

    def __str__(self):
        return self.title or f"Chat #{self.pk} · {self.user}"


class AIChatMessage(TimeStampedModel):
    class Role(models.TextChoices):
        USER = "USER", "Utilisateur"
        ASSISTANT = "ASSISTANT", "Assistant"
        SYSTEM = "SYSTEM", "Système"

    session = models.ForeignKey(
        AIChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    content = models.TextField()
    intent = models.CharField(max_length=80, blank=True)
    used_provider = models.CharField(max_length=50, blank=True)
    used_model = models.CharField(max_length=120, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    context_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["session", "created_at"])]

    def __str__(self):
        return f"[{self.role}] {self.content[:60]}"


class TaskReminder(TimeStampedModel):
    """
    Trace des rappels envoyés sur une tâche : permet d'éviter le spam,
    de mesurer la réactivité et de produire un historique exploitable.
    """

    class Reason(models.TextChoices):
        OVERDUE = "OVERDUE", "Tâche en retard"
        STALE = "STALE", "Tâche stagnante"
        DUE_SOON = "DUE_SOON", "Échéance proche"
        BLOCKED = "BLOCKED", "Tâche bloquée"

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        IN_APP = "IN_APP", "Notification in-app"
        BOTH = "BOTH", "Email + in-app"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reminders")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_reminders",
    )
    reason = models.CharField(max_length=20, choices=Reason.choices, default=Reason.STALE)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.BOTH)

    # Snapshot au moment de l'envoi (pour audit même si la tâche change)
    task_status_at_send = models.CharField(max_length=20, blank=True)
    task_due_date_at_send = models.DateField(null=True, blank=True)
    days_overdue = models.IntegerField(default=0)

    # Métriques de suivi
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    triggered_status_change = models.BooleanField(
        default=False,
        help_text="Vrai si l'assignee a mis à jour la tâche après ce rappel.",
    )

    sent_at = models.DateTimeField(default=timezone.now)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-sent_at"]
        indexes = [
            models.Index(fields=["task", "-sent_at"]),
            models.Index(fields=["recipient", "-sent_at"]),
        ]
        verbose_name = "Rappel tâche"
        verbose_name_plural = "Rappels tâches"

    def __str__(self):
        return f"Rappel {self.task} → {self.recipient} ({self.get_reason_display()})"


class ProjectAIProposalLog(TimeStampedModel):
    """Journal des actions sur une proposition IA (audit & traçabilité)."""

    class Action(models.TextChoices):
        TRIGGERED = "TRIGGERED", "Déclenchée"
        GENERATED = "GENERATED", "Générée"
        ITEM_EDITED = "ITEM_EDITED", "Item modifié"
        ITEM_VALIDATED = "ITEM_VALIDATED", "Item validé"
        ITEM_REJECTED = "ITEM_REJECTED", "Item rejeté"
        VALIDATED = "VALIDATED", "Proposition validée"
        APPLIED = "APPLIED", "Proposition appliquée"
        REJECTED = "REJECTED", "Proposition rejetée"
        FAILED = "FAILED", "Échec"

    proposal = models.ForeignKey(
        ProjectAIProposal,
        on_delete=models.CASCADE,
        related_name="logs",
    )
    action = models.CharField(max_length=25, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_proposal_actions",
    )
    message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.action}] {self.proposal_id}"



# ══════════════════════════════════════════════════════════════════════════════
# 14. FACTURATION CLIENT
#     Invoice → InvoiceLine → InvoicePayment.
#     Une facture est rattachée à un projet (et donc à un workspace).
#     Elle peut être générée automatiquement depuis :
#       - les ProjectEstimateLine (mode forfait)
#       - les TimesheetEntry × BillingRate (mode régie)
#       - les Milestones (jalons facturables)
# ══════════════════════════════════════════════════════════════════════════════

class InvoiceClient(TimeStampedModel, SoftDeleteModel):
    """
    Client final destinataire des factures. Distinct du Workspace pour
    permettre à un même workspace d'émettre vers plusieurs clients.
    """
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invoice_clients"
    )
    name = models.CharField(max_length=180)
    legal_name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(
        max_length=60, blank=True,
        help_text="N° TVA / NIF / SIRET / autre identifiant fiscal."
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)
    contact_name = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("workspace", "name")]

    def __str__(self):
        return self.name


class Invoice(TimeStampedModel, SoftDeleteModel):
    """Facture client liée à un projet."""
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Brouillon"
        ISSUED = "ISSUED", "Émise"
        SENT = "SENT", "Envoyée"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partiellement payée"
        PAID = "PAID", "Payée"
        OVERDUE = "OVERDUE", "En retard"
        CANCELLED = "CANCELLED", "Annulée"
    class BillingMode(models.TextChoices):
        FIXED = "FIXED", "Forfait (Estimate Lines)"
        TIME_AND_MATERIALS = "TIME_AND_MATERIALS", "Régie (Timesheets)"
        MILESTONE = "MILESTONE", "Sur jalon"
        MANUAL = "MANUAL", "Manuel"

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invoices"
    )
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="invoices"
    )
    client = models.ForeignKey(
        InvoiceClient, on_delete=models.PROTECT,
        related_name="invoices", null=True, blank=True,
    )

    # Identification
    number = models.CharField(
        max_length=40, blank=True,
        help_text="Auto-généré si non renseigné (FAC-AAAA-NNNN)."
    )
    title = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    # Dates
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    paid_at = models.DateField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Montants (calculés depuis les InvoiceLine au save)
    subtotal_ht = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("18.00"),
        help_text="Taux de TVA en % appliqué globalement (par défaut 18%)."
    )
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_ttc = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="XOF")

    # Statut & métadonnées
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    billing_mode = models.CharField(
        max_length=25, choices=BillingMode.choices, default=BillingMode.MANUAL
    )

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="issued_invoices",
    )
    pdf_file = models.FileField(
        upload_to="devflow/invoices/", null=True, blank=True
    )

    class Meta:
        ordering = ["-issue_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "number"],
                name="uniq_invoice_number_per_workspace",
                condition=~Q(number=""),
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "status"]),
            models.Index(fields=["project", "status"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"{self.number or 'Brouillon'} · {self.project.name}"

    # ────────────────────────────────────────────────────────────────────
    # Numérotation
    # ────────────────────────────────────────────────────────────────────
    @classmethod
    def generate_number(cls, workspace):
        """Génère un numéro FAC-AAAA-NNNN unique par workspace + année."""
        year = timezone.localdate().year
        prefix = f"FAC-{year}-"
        last = (
            cls.objects.filter(workspace=workspace, number__startswith=prefix)
            .order_by("-number").first()
        )
        next_seq = 1
        if last and last.number:
            try:
                next_seq = int(last.number.rsplit("-", 1)[-1]) + 1
            except (ValueError, IndexError):
                next_seq = cls.objects.filter(
                    workspace=workspace, number__startswith=prefix
                ).count() + 1
        return f"{prefix}{next_seq:04d}"

    # ────────────────────────────────────────────────────────────────────
    # Calculs
    # ────────────────────────────────────────────────────────────────────
    def recompute_totals(self, save=True):
        from django.db.models import Sum

        lines_total = self.lines.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        discount = self.discount_amount or Decimal("0")
        subtotal = (lines_total - discount).quantize(Decimal("0.01"))
        if subtotal < 0:
            subtotal = Decimal("0")

        rate = self.tax_rate or Decimal("0")
        tax = (subtotal * rate / Decimal("100")).quantize(Decimal("0.01"))
        ttc = (subtotal + tax).quantize(Decimal("0.01"))

        paid = self.payments.filter(
            status=InvoicePayment.Status.CONFIRMED
        ).aggregate(s=Sum("amount"))["s"] or Decimal("0")

        self.subtotal_ht = subtotal
        self.tax_amount = tax
        self.total_ttc = ttc
        self.paid_amount = paid

        # Statut auto
        if self.status not in {self.Status.CANCELLED, self.Status.DRAFT}:
            if paid >= ttc and ttc > 0:
                self.status = self.Status.PAID
                if not self.paid_at:
                    self.paid_at = timezone.localdate()
            elif paid > 0:
                self.status = self.Status.PARTIALLY_PAID
            elif self.due_date and self.due_date < timezone.localdate():
                self.status = self.Status.OVERDUE

        if save:
            self.save(update_fields=[
                "subtotal_ht", "tax_amount", "total_ttc",
                "paid_amount", "status", "paid_at", "updated_at",
            ])

    @property
    def remaining_due(self):
        return (self.total_ttc or Decimal("0")) - (self.paid_amount or Decimal("0"))

    def save(self, *args, **kwargs):
        if self.project_id and not self.workspace_id:
            self.workspace = self.project.workspace
        if not self.number and self.workspace_id and self.status != self.Status.DRAFT:
            self.number = self.generate_number(self.workspace)
        if not self.due_date and self.issue_date:
            from datetime import timedelta
            self.due_date = self.issue_date + timedelta(days=30)
        super().save(*args, **kwargs)


class InvoiceLine(TimeStampedModel):
    """Ligne d'une facture."""

    class LineType(models.TextChoices):
        SERVICE = "SERVICE", "Prestation"
        TIME = "TIME", "Régie / Heures"
        EXPENSE = "EXPENSE", "Frais refacturé"
        MILESTONE = "MILESTONE", "Jalon"
        DISCOUNT = "DISCOUNT", "Remise"
        OTHER = "OTHER", "Autre"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="lines"
    )
    line_type = models.CharField(
        max_length=15, choices=LineType.choices, default=LineType.SERVICE
    )
    label = models.CharField(max_length=240)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    position = models.PositiveIntegerField(default=0)

    # Liens optionnels vers les sources qui ont engendré la ligne
    estimate_line = models.ForeignKey(
        ProjectEstimateLine, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="invoice_lines",
    )
    milestone = models.ForeignKey(
        "Milestone", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="invoice_lines",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="invoice_lines",
    )

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.label} ({self.total_amount})"

    def save(self, *args, **kwargs):
        qty = self.quantity or Decimal("0")
        price = self.unit_price or Decimal("0")
        self.total_amount = (qty * price).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class InvoicePayment(TimeStampedModel):
    """Paiement enregistré sur une facture."""

    class Method(models.TextChoices):
        BANK_TRANSFER = "BANK_TRANSFER", "Virement bancaire"
        CARD = "CARD", "Carte bancaire"
        CASH = "CASH", "Espèces"
        CHECK = "CHECK", "Chèque"
        MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"
        OTHER = "OTHER", "Autre"

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        CONFIRMED = "CONFIRMED", "Confirmé"
        REFUNDED = "REFUNDED", "Remboursé"
        FAILED = "FAILED", "Échoué"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="payments"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    received_at = models.DateField(default=timezone.localdate)
    method = models.CharField(
        max_length=20, choices=Method.choices, default=Method.BANK_TRANSFER
    )
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.CONFIRMED
    )
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="recorded_payments",
    )

    class Meta:
        ordering = ["-received_at", "-id"]

    def __str__(self):
        return f"{self.amount} · {self.invoice.number} ({self.get_method_display()})"
