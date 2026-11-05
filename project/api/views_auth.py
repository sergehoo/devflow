"""
API d'authentification du frontend React (session Django + CSRF).

  GET  /api/v1/auth/csrf/       — pose le cookie csrftoken
  GET  /api/v1/auth/me/         — utilisateur, workspace courant, workspaces, rôle, permissions
  POST /api/v1/auth/login/      — {login, password} via le formulaire allauth (mêmes règles)
  POST /api/v1/auth/logout/
  POST /api/v1/auth/workspace/  — {workspace_id} : change le workspace courant (membre uniquement)

Aucun jeton n'est remis au navigateur : la session reste dans un cookie HttpOnly.
"""

from __future__ import annotations

from django.contrib.auth import logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from project import models as dm
from project.services.rbac import RBACService
from project.utils.workspaces import get_default_workspace_for_user, get_user_workspace_ids


def _current_workspace(user):
    profile = getattr(user, "profile", None)
    allowed = get_user_workspace_ids(user)
    if profile and profile.workspace_id in allowed:
        return profile.workspace
    return get_default_workspace_for_user(user)


def serialize_me(user) -> dict:
    current = _current_workspace(user)
    workspaces = dm.Workspace.objects.filter(
        id__in=get_user_workspace_ids(user), is_archived=False,
    ).order_by("name")
    profile = getattr(user, "profile", None)
    avatar = profile.avatar.url if profile and profile.avatar else None
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name() or user.get_username(),
        "is_superuser": user.is_superuser,
        "avatar": avatar,
        "job_title": getattr(profile, "job_title", "") or "",
        "workspace": (
            {"id": current.pk, "name": current.name,
             "role": RBACService.get_role_for(user, current),
             "role_label": RBACService.role_label(RBACService.get_role_for(user, current) or "")}
            if current else None
        ),
        "workspaces": [{"id": w.pk, "name": w.name} for w in workspaces],
        "permissions": sorted(RBACService.user_permissions(user, current)) if current else [],
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"ok": True})


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(serialize_me(request.user))


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from allauth.account.forms import LoginForm
        from rest_framework.authentication import SessionAuthentication
        from rest_framework.exceptions import PermissionDenied

        try:  # DRF n'impose pas le CSRF aux anonymes : on le fait (anti « login CSRF »)
            SessionAuthentication().enforce_csrf(request)
        except PermissionDenied:
            return Response({"detail": "Jeton CSRF manquant ou invalide."}, status=status.HTTP_403_FORBIDDEN)

        data = request.data or {}
        form = LoginForm(
            data={"login": (data.get("login") or "").strip(), "password": data.get("password") or ""},
            request=request._request,
        )
        if not form.is_valid():
            errors = [str(e) for e in form.non_field_errors()] or [
                str(e) for errs in form.errors.values() for e in errs
            ]
            return Response(
                {"detail": errors[0] if errors else "Identifiants invalides."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        form.login(request._request)  # flux allauth complet (vérification email, rate limit…)
        user = request._request.user
        if not user.is_authenticated:
            return Response(
                {"detail": "Connexion impossible : vérifiez votre adresse email (un lien vient de vous être envoyé)."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(serialize_me(user))


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request._request)
        return Response({"ok": True})


class WorkspaceSwitchView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            workspace_id = int((request.data or {}).get("workspace_id"))
        except (TypeError, ValueError):
            return Response({"detail": "workspace_id invalide."}, status=status.HTTP_400_BAD_REQUEST)
        if workspace_id not in get_user_workspace_ids(request.user):
            return Response({"detail": "Workspace introuvable."}, status=status.HTTP_404_NOT_FOUND)
        profile = getattr(request.user, "profile", None)
        if profile is None:
            dm.UserProfile.objects.create(user=request.user, workspace_id=workspace_id)
        else:
            profile.workspace_id = workspace_id
            profile.save(update_fields=["workspace", "updated_at"])
        request.user.refresh_from_db()
        return Response(serialize_me(request.user))
