"""
Onboarding d'un employé depuis /team-memberships/create/ — sans Django Admin.

Deux modes :
  * utilisateur existant du workspace → rattachement équipe + rôle + hiérarchie ;
  * nouvel employé → création d'un compte inactif (mot de passe inutilisable),
    profil + appartenance immédiats, puis invitation sécurisée (token, expiration)
    pour activer le compte et choisir son mot de passe.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from project import models as dm

User = get_user_model()

INVITATION_TTL_DAYS = 7


def workspace_users(workspace):
    """Utilisateurs rattachés au workspace (appartenance ou profil)."""
    if workspace is None:
        return User.objects.none()
    return (
        User.objects.filter(
            Q(devflow_memberships__workspace=workspace) | Q(profile__workspace=workspace)
        )
        .distinct()
        .order_by("last_name", "first_name", "username")
    )


def _unique_username(email: str) -> str:
    base = (email.split("@")[0] or "user")[:30]
    username, idx = base, 1
    while User.objects.filter(username=username).exists():
        username = f"{base[:26]}{idx}"
        idx += 1
    return username


def _apply_profile(profile, *, job_title, weekly_capacity, arrival_date, manager_profile, keep_existing=False):
    """
    ``keep_existing`` (rattachement d'un collaborateur déjà en place à une autre équipe) :
    le formulaire préremplit capacité (40 h) et date d'arrivée (aujourd'hui) et laisse le N+1
    vide ; ces valeurs par défaut ne doivent pas écraser son profil. On ne renseigne alors
    que ce qui manque (N+1 choisi, date d'entrée encore vide).
    """
    if job_title:
        profile.job_title = job_title
    if weekly_capacity is not None:
        profile.capacity_hours_per_week = weekly_capacity
        profile.capacity_hours_per_day = (Decimal(weekly_capacity) / 5).quantize(Decimal("0.01"))
    if arrival_date and not (keep_existing and profile.joined_company_at):
        profile.joined_company_at = arrival_date
    if manager_profile is not None or not keep_existing:
        profile.manager = manager_profile
    profile.full_clean(exclude=["avatar"])
    profile.save()
    return profile


@transaction.atomic
def onboard_employee(
    *,
    workspace,
    actor,
    team=None,
    role=dm.TeamMembership.Role.DEVELOPER,
    weekly_capacity=None,
    arrival_date=None,
    manager_user=None,
    job_title="",
    existing_user=None,
    first_name="",
    last_name="",
    email="",
    request=None,
):
    """Retourne (membership, invitation|None)."""
    manager_profile = None
    if manager_user is not None:
        manager_profile, _ = dm.UserProfile.objects.get_or_create(
            user=manager_user, defaults={"workspace": workspace},
        )
        if manager_profile.workspace_id != workspace.pk:
            raise ValueError("Le manager doit appartenir au workspace courant.")

    invitation = None
    if existing_user is not None:
        user = existing_user
    else:
        user = User(
            username=_unique_username(email),
            email=email.lower(),
            first_name=first_name,
            last_name=last_name,
            is_active=False,
        )
        user.set_unusable_password()
        user._invited_workspace = workspace  # lu par le signal create_user_profile
        user.save()

    profile, _ = dm.UserProfile.objects.get_or_create(user=user, defaults={"workspace": workspace})
    if profile.workspace_id == workspace.pk:
        _apply_profile(
            profile, job_title=job_title, weekly_capacity=weekly_capacity,
            arrival_date=arrival_date, manager_profile=manager_profile,
            keep_existing=existing_user is not None,
        )

    membership, _ = dm.TeamMembership.objects.update_or_create(
        workspace=workspace, user=user, team=team,
        defaults={
            "role": role,
            "status": dm.TeamMembership.Status.ACTIVE,
            "job_title": job_title or "",
            "joined_at": arrival_date or timezone.localdate(),
        },
    )

    if existing_user is None:
        invitation, _ = dm.WorkspaceInvitation.objects.update_or_create(
            workspace=workspace, email=user.email,
            defaults={
                "invited_by": actor,
                "role": role,
                "team": team,
                "token": secrets.token_urlsafe(48),
                "status": dm.WorkspaceInvitation.Status.PENDING,
                "expires_at": timezone.now() + timedelta(days=INVITATION_TTL_DAYS),
                "accepted_at": None,
            },
        )

        def _send():
            from project.services.invitations import send_invitation_email
            send_invitation_email(invitation, request=request)

        transaction.on_commit(_send)

    return membership, invitation


def set_manager(user, workspace, manager_user):
    """Change le N+1 d'un collaborateur (validation cycle/workspace incluse)."""
    profile = dm.UserProfile.objects.get(user=user, workspace=workspace)
    profile.manager = (
        dm.UserProfile.objects.get(user=manager_user, workspace=workspace)
        if manager_user else None
    )
    profile.full_clean(exclude=["avatar"])
    profile.save(update_fields=["manager", "updated_at"])
    return profile


# ---------------------------------------------------------------------------
# Droits sur les appartenances (création, modification, retrait)
# ---------------------------------------------------------------------------
# ``TeamMembership.role`` ouvre encore des accès hérités : lecture finance
# (views_budget.can_view_financials, views.can_view_financial_data : ADMIN, CTO, PM, PO,
# TECH_LEAD) et validation des dépenses (niveau 1 : PM, PO ; niveau 2 : ADMIN, CTO,
# TECH_LEAD). Ces rôles sont réservés aux détenteurs de ``members.manage``.
ELEVATED_ROLES = frozenset({
    dm.TeamMembership.Role.ADMIN, dm.TeamMembership.Role.CTO, dm.TeamMembership.Role.PM,
    dm.TeamMembership.Role.PRODUCT_OWNER, dm.TeamMembership.Role.TECH_LEAD,
})


def can_manage_members(user, workspace) -> bool:
    """Gestion complète (propriétaire, admin) ou gestion des membres d'équipe (team lead)."""
    from project.services.rbac import RBACService

    return bool(workspace) and (
        RBACService.can(user, "members.manage", workspace=workspace)
        or RBACService.can(user, "team.manage_members", workspace=workspace)
    )


def _protected_target(member_user, workspace) -> bool:
    """Cible hors de portée d'un team lead : encadrement RBAC ou rôle d'équipe élevé."""
    from project.services import rbac

    if member_user.is_superuser or workspace.owner_id == member_user.pk:
        return True
    if rbac.RBACService.get_role_for(member_user, workspace) in (
        rbac.SUPER_ADMIN, rbac.WORKSPACE_OWNER, rbac.PROJECT_MANAGER, rbac.TEAM_LEAD,
    ):
        return True
    return dm.TeamMembership.objects.filter(
        workspace=workspace, user=member_user, role__in=ELEVATED_ROLES,
    ).exists()


def membership_change_error(actor, workspace, *, member_user, role=None, previous_role=None) -> str | None:
    """
    Refus d'une création / modification / suppression d'appartenance, ou ``None``.
    Un team lead (``team.manage_members`` sans ``members.manage``) ne touche ni à son propre
    rattachement, ni à l'encadrement (propriétaire, admins, chefs de projet, autres team leads,
    titulaires d'un rôle d'équipe élevé), et n'attribue ni ne retire de rôle élevé.
    """
    from project.services.rbac import RBACService

    if not can_manage_members(actor, workspace):
        return "Vous n'avez pas le droit de gérer les membres de ce workspace."
    if RBACService.can(actor, "members.manage", workspace=workspace):
        return None
    if member_user is not None and member_user.pk == actor.pk:
        return "Vous ne pouvez pas modifier votre propre rattachement."
    if role in ELEVATED_ROLES or previous_role in ELEVATED_ROLES:
        return "Seul un administrateur du workspace peut attribuer ou retirer ce rôle."
    if member_user is not None and _protected_target(member_user, workspace):
        return "Seul un administrateur du workspace peut modifier le rattachement de ce collaborateur."
    return None


def manageable_membership_ids(actor, workspace, memberships) -> set:
    """Appartenances que ``actor`` peut modifier / retirer (affichage des actions par ligne)."""
    from project.services.rbac import RBACService

    if not can_manage_members(actor, workspace):
        return set()
    memberships = list(memberships)
    if RBACService.can(actor, "members.manage", workspace=workspace):
        return {m.pk for m in memberships}
    return {
        m.pk for m in memberships
        if m.user_id != actor.pk and m.role not in ELEVATED_ROLES and not _protected_target(m.user, workspace)
    }


def removable_membership_ids(actor, workspace, memberships) -> set:
    """
    Appartenances que ``actor`` peut retirer : celles qu'il gère, sauf le DERNIER rattachement
    du propriétaire (il peut quitter une équipe secondaire ; seul un superadmin retire le dernier).
    """
    memberships = list(memberships)
    allowed = manageable_membership_ids(actor, workspace, memberships)
    if not allowed or workspace is None or actor.is_superuser:
        return allowed
    owner_rows = dm.TeamMembership.objects.filter(workspace=workspace, user_id=workspace.owner_id).count()
    return {
        m.pk for m in memberships
        if m.pk in allowed and not (m.user_id == workspace.owner_id and owner_rows <= 1)
    }
