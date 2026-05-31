from project import models as dm


def devflow_notifications(request):
    if not request.user.is_authenticated:
        return {
            "unread_notifications_count": 0,
            "recent_notifications": [],
        }

    notifications_qs = (
        dm.Notification.objects
        .filter(recipient=request.user)
        .select_related("workspace")
        .order_by("-created_at")
    )

    return {
        "unread_notifications_count": notifications_qs.filter(is_read=False).count(),
        "recent_notifications": notifications_qs[:6],
    }


def devflow_rbac(request):
    """
    PR23 — Expose le rôle RBAC + permissions du user dans le workspace courant
    à tous les templates. Utilisé par la sidebar dynamique et le tag
    {% if user_can "x.y" %} ... {% endif %}.
    """
    if not request.user.is_authenticated:
        return {
            "rbac_role": None,
            "rbac_is_super_admin": False,
            "rbac_permissions": set(),
        }

    # Import local pour éviter cycle module
    from project.services.rbac import RBACService
    from project.utils.workspaces import get_default_workspace_for_user

    workspace = get_default_workspace_for_user(request.user)
    role = RBACService.get_role_for(request.user, workspace) if workspace else None
    if request.user.is_superuser:
        role = "SUPER_ADMIN"

    return {
        "rbac_role": role,
        "rbac_role_label": RBACService.role_label(role) if role else "",
        "rbac_is_super_admin": bool(request.user.is_superuser),
        "rbac_permissions": (
            {"*"} if request.user.is_superuser
            else RBACService.user_permissions(request.user, workspace)
        ),
        "rbac_workspace": workspace,
    }