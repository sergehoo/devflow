"""
Vue HTML chat unifié — DM + groupes.

Tout se joue dans un composant Alpine.js (templates/devflow/chat.html) qui
consomme les endpoints DRF /api/v1/me/chat/*. La vue Django sert juste la
coquille (auth + workspace courant).
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from project.utils.workspaces import get_default_workspace_for_user


class ChatView(LoginRequiredMixin, TemplateView):
    template_name = "devflow/chat.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["section"] = "chat"
        ctx["page_title"] = "Discussions"
        ctx["current_workspace"] = get_default_workspace_for_user(self.request.user)
        return ctx
