"""
Vue HTML "Mes actions du jour" — Phase 1 (PR7).

Cockpit personnel pour l'utilisateur connecté : tâches dues aujourd'hui,
en retard, en cours, suivis de réunions, insights IA pertinents,
notifications non lues.

La vue HTML et l'endpoint DRF /api/v1/me/today/ partagent le même
service ``project.services.my_day.MyDayService`` (DRY).
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from project.services.my_day import MyDayService
from project.utils.workspaces import get_default_workspace_for_user


# Petits messages d'ambiance roulés sur la date du jour (déterministe).
QUOTES = [
    "Une bonne tâche terminée vaut mieux que dix en attente.",
    "Faites le moins, mais faites le mieux.",
    "Avancer un peu chaque jour finit par mener loin.",
    "La clarté précède l'action.",
    "Mieux vaut viser juste que viser fort.",
    "Une journée maîtrisée commence par une action concrète.",
    "Décidez. Faites. Ajustez.",
]


def _greeting_for(now) -> str:
    hour = now.hour
    if hour < 6:
        return "Bonne nuit"
    if hour < 12:
        return "Bonjour"
    if hour < 18:
        return "Bon après-midi"
    return "Bonsoir"


class MyDayView(LoginRequiredMixin, TemplateView):
    template_name = "devflow/my_day.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        payload = MyDayService.build(self.request.user)

        now = timezone.localtime()
        ctx.update({
            "section": "my_day",
            "page_title": "Mes actions du jour",
            # Expose current_workspace pour le branding topbar
            "current_workspace": get_default_workspace_for_user(self.request.user),
            "today": payload.today,
            "stats": payload.stats,
            "tasks_today": payload.tasks_today,
            "tasks_overdue": payload.tasks_overdue,
            "tasks_in_progress": payload.tasks_in_progress,
            "meeting_action_items": payload.meeting_action_items,
            "ai_insights": payload.ai_insights,
            "unread_notifications": payload.unread_notifications,
            "greeting": _greeting_for(now),
            "quote_of_day": QUOTES[payload.today.toordinal() % len(QUOTES)],
        })
        return ctx
