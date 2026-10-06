"""
SECURITY — service des fichiers MEDIA avec contrôle d'accès.

Remplace l'exposition publique de /media/ : un fichier n'est servi que si
l'utilisateur connecté appartient au workspace de l'objet qui le référence
(pièce jointe, enregistrement, document importé, facture…).

En production derrière nginx : MEDIA_X_ACCEL_REDIRECT=True délègue l'envoi
à nginx (location interne /protected-media/) après autorisation Django.
"""

from __future__ import annotations

import mimetypes
import posixpath
from functools import lru_cache
from urllib.parse import quote

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import FileResponse, Http404, HttpResponse
from django.utils._os import safe_join

from project.utils.workspaces import get_user_workspace_ids, workspace_lookup_for_model

# Identité visuelle uniquement (utilisée dans les emails / PDF) : publique.
PUBLIC_MEDIA_PREFIXES = ("devflow/workspaces/logos/",)


@lru_cache(maxsize=1)
def _file_fields():
    return [
        (model, field.name)
        for model in apps.get_app_config("project").get_models()
        for field in model._meta.fields
        if isinstance(field, models.FileField)
    ]


def user_can_access_media(user, path: str) -> bool:
    if path.startswith(PUBLIC_MEDIA_PREFIXES):
        return True
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if path.startswith(f"exports/u{user.pk}/"):
        return True
    workspace_ids = get_user_workspace_ids(user)
    if not workspace_ids:
        return False
    for model, field_name in _file_fields():
        owners = model._default_manager.filter(**{field_name: path})
        if not owners.exists():
            continue
        if model._meta.label == "project.MessageAttachment":
            # Messagerie : réservé aux participants de la conversation.
            from project.services.chat import ChatService
            return owners.filter(message__channel__in=ChatService.channels_qs_for(user)).exists()
        lookup = workspace_lookup_for_model(model)
        if lookup and owners.filter(**{f"{lookup}__in": workspace_ids}).exists():
            return True
    return False


def _serve(path: str):
    if getattr(settings, "MEDIA_X_ACCEL_REDIRECT", False):
        response = HttpResponse()
        response["X-Accel-Redirect"] = f"/protected-media/{quote(path)}"
        response["Content-Type"] = mimetypes.guess_type(path)[0] or "application/octet-stream"
        return response
    try:
        full_path = safe_join(str(settings.MEDIA_ROOT), path)
        return FileResponse(open(full_path, "rb"))
    except (OSError, ValueError):
        raise Http404("Fichier introuvable.")


def protected_media(request, path):
    path = posixpath.normpath(path).lstrip("/")
    if path.startswith("..") or path in ("", "."):
        raise Http404("Fichier introuvable.")
    if not path.startswith(PUBLIC_MEDIA_PREFIXES):
        return _protected(request, path)
    return _serve(path)


@login_required
def _protected(request, path):
    if not user_can_access_media(request.user, path):
        raise Http404("Fichier introuvable.")
    response = _serve(path)
    response["Cache-Control"] = "private, no-store"
    return response
