"""
Points d'entrée PUBLICS du ticketing (aucune session, aucun secret) :

* ``GET  /api/v1/public/apps/<clé>/?mode=form|widget|hosted`` → libellés + jeton de formulaire ;
* ``POST /api/v1/public/apps/<clé>/tickets/`` → signalement (multipart) ;
* ``POST /api/v1/public/apps/<clé>/track/`` → suivi (référence + code de suivi) ;
* ``GET  /support/app/<slug>/`` → formulaire public hébergé (``?embed=1`` : widget).

CORS : en-têtes renvoyés uniquement aux origines autorisées de l'application, et
contrôle serveur de l'origine pour le mode « formulaire existant » (le navigateur
n'est pas la seule barrière). Requêtes « simples » côté SDK : pas de pré-vol.
"""

from __future__ import annotations

import secrets

from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from project import models as dm
from project.api.views_ticketing import client_ip
from project.services import ticketing_public as tp

T = dm.Ticket
SELF = "'self'"


def _json(request, app, payload, status=200):
    response = JsonResponse(payload, status=status)
    origin = request.headers.get("Origin", "")
    if app is not None and tp.origin_allowed(app, origin):
        response["Access-Control-Allow-Origin"] = tp.normalize_origin(origin)
    response["Vary"] = "Origin"
    response["Cache-Control"] = "no-store"
    return response


def _error(request, app, mode, exc: tp.PublicIntakeError):
    if app is not None and exc.record:
        tp.record_error(app, mode if mode in tp.MODES else "form", exc.record)
    return _json(request, app, {"detail": exc.message}, status=exc.status)


def _options():
    return {
        "categories": [{"value": v, "label": label} for v, label in T.Category.choices],
        "impacts": [{"value": v, "label": label} for v, label in T.Severity.choices],
    }


@csrf_exempt
@require_http_methods(["GET"])
def public_app(request, key):
    app = tp.app_for_key(key)
    mode = request.GET.get("mode", "form")
    if app is None:
        return _json(request, None, {"detail": "Application inconnue."}, status=404)
    try:
        tp.check_mode(app, mode, request.headers.get("Origin", ""))
    except tp.PublicIntakeError as exc:
        return _error(request, app, mode, exc)
    return _json(request, app, {
        "application": app.name, "mode": mode, "form_token": tp.issue_form_token(app, mode),
        "max_files": tp.MAX_FILES, "max_attachment_mb": app.max_attachment_mb, "email_required": mode == "hosted", **_options(),
    })


@csrf_exempt
@require_http_methods(["POST"])
def public_submit(request, key):
    app = tp.app_for_key(key)
    mode = request.POST.get("mode", "")
    if app is None:
        return _json(request, None, {"detail": "Application inconnue."}, status=404)
    try:
        result = tp.submit(app, mode, request.POST, request.FILES.getlist("attachments"),
                           ip=client_ip(request), origin=request.headers.get("Origin", ""))
    except tp.PublicIntakeError as exc:
        return _error(request, app, mode, exc)
    return _json(request, app, result, status=201 if result["created"] else 200)


@csrf_exempt
@require_http_methods(["POST"])
def public_track(request, key):
    app = tp.app_for_key(key)
    if app is None or not any(tp.modes(app)[m] for m in tp.BROWSER_MODES):
        return _json(request, None, {"detail": "Application inconnue."}, status=404)
    try:
        data = tp.track(app, request.POST.get("reference", ""), request.POST.get("code", ""), ip=client_ip(request))
    except tp.PublicIntakeError as exc:
        return _json(request, app, {"detail": exc.message}, status=exc.status)
    return _json(request, app, data)


@xframe_options_exempt
@require_http_methods(["GET"])
def support_public_form(request, slug):
    """Formulaire public hébergé ; ``?embed=1`` = contenu du widget (intégrable par les domaines autorisés)."""
    app = dm.ExternalApplication.objects.filter(public_slug=slug).first()
    embed = request.GET.get("embed") == "1"
    mode = "widget" if embed else "hosted"
    if app is None or not app.is_active or not tp.modes(app)[mode] or not app.public_key:
        raise Http404("Formulaire indisponible.")
    parent = tp.normalize_origin(request.GET.get("origin", "")) if embed else None
    nonce = secrets.token_urlsafe(16)
    display_name = (request.GET.get("name") or "").strip()[:80] if embed else ""
    response = render(request, "support/public_form.html", {
        "app": app, "app_name": display_name or app.name, "mode": mode, "embed": embed, "nonce": nonce,
        "public_key": app.public_key, "form_token": tp.issue_form_token(app, mode),
        "parent_origin": parent if parent and tp.origin_allowed(app, parent) else "",
        "page_url": (request.GET.get("page") or "")[:500] if embed else "", **_options(),
        "max_files": tp.MAX_FILES, "max_mb": app.max_attachment_mb,
    })
    ancestors = " ".join(tp.normalize_origin(o) for o in (app.allowed_origins or []) if tp.normalize_origin(o)) if embed else ""
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src 'self' data: blob:; "
        f"connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors {ancestors or SELF}"
    )
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    return response
