from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import ListView, View

from project import models as dm


class NotificationListView(LoginRequiredMixin, ListView):
    model = dm.Notification
    template_name = "project/notification/list.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        return (
            dm.Notification.objects
            .filter(recipient=self.request.user)
            .select_related("workspace")
            .order_by("-created_at")
        )


class NotificationMarkReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        notification = get_object_or_404(
            dm.Notification,
            pk=pk,
            recipient=request.user,
        )
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at", "updated_at"])

        if notification.url:
            return redirect(notification.url)
        return redirect("notification_list")