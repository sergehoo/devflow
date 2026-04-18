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