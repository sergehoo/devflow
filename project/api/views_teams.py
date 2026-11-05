"""
API Équipes & membres (frontend React, Phase 3).

``GET team-members/`` réutilise ``TeamMembershipListView.get_queryset`` (scoping
workspace, filtres ``team``/``role``/``status``, recherche ``q``) ; les écritures
passent par les ponts ``forms/team``, ``forms/member`` et ``actions/member-*``.
"""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.api.pagination import FlexiblePagination


def _name(user) -> str:
    return (user.get_full_name() or user.get_username()) if user else ""


class TeamMembersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from project.services.password_reset import can_manage_passwords
        from project.services.rbac import RBACService
        from project.views import TeamMembershipListView

        django_request = request._request
        django_request.user = request.user
        view = TeamMembershipListView()
        view.setup(django_request)
        ws = view.get_current_workspace()
        qs = view.get_queryset().select_related("user", "team").order_by("user__first_name", "user__last_name", "user__username")
        paginator = FlexiblePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        profiles = {
            p.user_id: p for p in dm.UserProfile.objects.filter(
                user_id__in=[m.user_id for m in page], workspace=ws,
            ).select_related("manager__user")
        } if ws else {}
        response = paginator.get_paginated_response([
            {
                "id": m.pk,
                "user": {"id": m.user_id, "name": _name(m.user), "email": m.user.email, "is_active": m.user.is_active},
                "team": {"id": m.team_id, "name": m.team.name} if m.team_id else None,
                "role": m.role, "role_label": m.get_role_display(),
                "status": m.status, "status_label": m.get_status_display(),
                "job_title": m.job_title or getattr(profiles.get(m.user_id), "job_title", "") or "",
                "current_load_percent": m.current_load_percent,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                "manager": _name(profiles[m.user_id].manager.user) if profiles.get(m.user_id) and profiles[m.user_id].manager_id else "",
                "capacity_hours_per_week": float(profiles[m.user_id].capacity_hours_per_week)
                if profiles.get(m.user_id) and profiles[m.user_id].capacity_hours_per_week is not None else None,
                "is_owner": bool(ws and ws.owner_id == m.user_id),
            }
            for m in page
        ])
        response.data["permissions"] = {
            "can_manage_passwords": bool(ws and can_manage_passwords(request.user, ws)),
            "can_onboard": bool(ws and (RBACService.can(request.user, "members.invite", workspace=ws)
                                        or RBACService.can(request.user, "team.manage_members", workspace=ws))),
        }
        response.data["filters"] = {
            "teams": [{"value": str(t.pk), "label": t.name} for t in view._teams_qs()],
            "roles": [{"value": v, "label": l} for v, l in dm.TeamMembership.Role.choices],
            "statuses": [{"value": v, "label": l} for v, l in dm.TeamMembership.Status.choices],
        }
        return response
