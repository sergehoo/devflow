from django.core.exceptions import ValidationError

from project import models as dm


def get_default_workspace_for_user(user):
    """
    Retourne le workspace par défaut d'un utilisateur.
    Priorité :
    1. workspace possédé
    2. premier workspace actif de membership
    3. premier workspace actif disponible
    """
    if not user or not user.is_authenticated:
        return None

    owned = dm.Workspace.objects.filter(
        owner=user,
        is_archived=False,
        is_active=True,
    ).first()
    if owned:
        return owned

    membership = (
        dm.TeamMembership.objects.select_related("workspace")
        .filter(
            user=user,
            workspace__is_archived=False,
            workspace__is_active=True,
        )
        .order_by("workspace__name")
        .first()
    )
    if membership:
        return membership.workspace

    return (
        dm.Workspace.objects.filter(is_archived=False, is_active=True)
        .order_by("name")
        .first()
    )


def get_user_workspace_ids(user):
    """
    SECURITY (Phase 0) — Retourne l'ensemble des IDs de workspaces accessibles
    à l'utilisateur connecté, pour les vues FBV et les helpers qui n'héritent
    pas de WorkspaceSecurityMixin.

    Inclut :
    1. workspace du profil utilisateur (s'il est non archivé)
    2. workspaces possédés (Workspace.owner)
    3. workspaces liés à ses memberships (TeamMembership)

    Utilisé pour scoper les `get_object_or_404` cross-tenant et empêcher
    qu'un user A puisse modifier un objet du workspace de user B.
    """
    if not user or not user.is_authenticated:
        return set()

    workspace_ids = set()

    profile = getattr(user, "profile", None)
    if profile and profile.workspace_id:
        profile_ws = profile.workspace
        if profile_ws and not profile_ws.is_archived:
            workspace_ids.add(profile_ws.id)

    workspace_ids.update(
        dm.Workspace.objects.filter(
            owner=user,
            is_archived=False,
        ).values_list("id", flat=True)
    )

    workspace_ids.update(
        dm.Workspace.objects.filter(
            memberships__user=user,
            is_archived=False,
        ).values_list("id", flat=True)
    )

    return workspace_ids


def user_can_access_workspace(user, workspace) -> bool:
    """SECURITY (Phase 0) — Helper booléen pour vérifier l'accès d'un user à un workspace."""
    if workspace is None:
        return False
    workspace_id = getattr(workspace, "id", None) or getattr(workspace, "pk", None)
    if workspace_id is None:
        return False
    return workspace_id in get_user_workspace_ids(user)


def users_in_workspaces(workspace_ids):
    """
    SECURITY — Queryset des users qui ont accès à AU MOINS UN des
    workspaces donnés (via profile, team membership ou ownership).

    Garantit qu'on ne renvoie JAMAIS un user d'un autre workspace.
    Utilisé partout où on doit afficher une liste de "personnes" :
      * autocomplete assignee tâche
      * select user dans les forms
      * annuaire chat / mentions
      * liste membres équipe
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    User = get_user_model()
    if not workspace_ids:
        return User.objects.none()
    return (
        User.objects.filter(
            Q(profile__workspace_id__in=workspace_ids)
            | Q(devflow_memberships__workspace_id__in=workspace_ids)
            | Q(owned_workspaces__id__in=workspace_ids)
        )
        .filter(is_active=True)
        .distinct()
    )


def users_for_user(user):
    """
    SECURITY — Queryset des users que ``user`` peut voir (= membres de
    ses workspaces). Exclut l'user lui-même n'est PAS effectué ici (à la
    discrétion du caller selon le contexte : autocomplete = oui, annuaire
    membre équipe = non).

    Cas SuperAdmin : retourne tous les users actifs (accès global).
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if not user or not getattr(user, "is_authenticated", False):
        return User.objects.none()
    if getattr(user, "is_superuser", False):
        return User.objects.filter(is_active=True)
    return users_in_workspaces(get_user_workspace_ids(user))


def resolve_workspace(instance):
    """
    Tente de déduire le workspace à partir des relations déjà présentes.
    """
    if getattr(instance, "workspace_id", None):
        return instance.workspace

    for attr in ("project", "team", "sprint", "milestone", "roadmap"):
        related = getattr(instance, attr, None)
        if related and getattr(related, "workspace_id", None):
            return related.workspace

    return None


def ensure_workspace(instance, user=None):
    """
    Affecte un workspace si absent.
    """
    workspace = resolve_workspace(instance)

    if not workspace and user:
        workspace = get_default_workspace_for_user(user)

    if workspace and hasattr(instance, "workspace_id") and not instance.workspace_id:
        instance.workspace = workspace

    if hasattr(instance, "workspace_id") and not instance.workspace_id:
        raise ValidationError("Impossible de déterminer automatiquement le workspace.")

    return instance