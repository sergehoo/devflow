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


def _apply_profile(profile, *, job_title, weekly_capacity, arrival_date, manager_profile):
    if job_title:
        profile.job_title = job_title
    if weekly_capacity is not None:
        profile.capacity_hours_per_week = weekly_capacity
        profile.capacity_hours_per_day = (Decimal(weekly_capacity) / 5).quantize(Decimal("0.01"))
    if arrival_date:
        profile.joined_company_at = arrival_date
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
