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