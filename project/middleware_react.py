"""
Redirection des anciennes pages HTML migrées vers leurs équivalents React (/app/…).

Uniquement pour une navigation de page : GET / HEAD, ``Accept: text/html``,
hors requêtes AJAX / htmx, hors API, fichiers, administration et pages
d'authentification. Redirections TEMPORAIRES (302) tant que la bascule n'est
pas définitive ; désactivées avec ``DEVFLOW_REACT_DEFAULT=False`` ; une page
historique reste accessible ponctuellement avec ``?classic=1``.

Les ponts React exécutent les vues Django directement (sans passer par les
URL) : ils ne sont pas concernés.
"""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect

STATIC_RULES: list[tuple[str, object]] = [
    (r"^/(tasks|projects|teams|workspaces)/(\d+)/$", lambda m, q: f"/{m[1]}/{m[2]}"),
    (r"^/(tasks|projects|teams|workspaces)/$", lambda m, q: f"/{m[1]}"),
    (r"^/chat/$", lambda m, q: f"/messenger?channel={q['channel']}" if q.get("channel", "").isdigit() else "/messenger"),
    (r"^/channels/(\d+)/$", lambda m, q: f"/messenger?channel={m[1]}"),
    (r"^/timesheets/$", lambda m, q: "/timesheets"),
    (r"^/notifications/$", lambda m, q: "/notifications"),
    (r"^/my-day/$", lambda m, q: "/my-day"),
    (r"^/team-memberships/$", lambda m, q: "/members"),
    (r"^/profile/(?:update/|password/)?$", lambda m, q: "/profile"),
    (r"^/billing/branding/$", lambda m, q: "/branding"),
    # Réunions
    (r"^/meetings/$", lambda m, q: "/meetings"),
    (r"^/meetings/dashboard/$", lambda m, q: "/meetings/dashboard"),
    (r"^/meetings/decisions/$", lambda m, q: "/meetings/decisions"),
    (r"^/meetings/series/$", lambda m, q: "/meetings/series"),
    (r"^/meetings/series/(\d+)/$", lambda m, q: f"/meetings/series/{m[1]}"),
    (r"^/meetings/(\d+)/$", lambda m, q: f"/meetings/{m[1]}"),
    (r"^/meetings/(\d+)/recordings/(\d+)/(?:summary|speakers)/$", lambda m, q: f"/meetings/{m[1]}/recordings/{m[2]}"),
    # Finance / facturation
    (r"^/workspaces/\d+/financial-ai/portfolio/$", lambda m, q: "/finance/portfolio"),
    (r"^/workspaces/\d+/financial-ai/allocation/view/$", lambda m, q: "/finance/allocation"),
    (r"^/billing/invoices/(\d+)/$", lambda m, q: f"/invoices/{m[1]}"),
    # IA de structuration
    (r"^/ai/genesis/$", lambda m, q: "/projects/genesis"),
    (r"^/ai-proposals/(\d+)/$", lambda m, q: f"/ai-proposals/{m[1]}"),
    (r"^/projects/(\d+)/ai-proposals/$", lambda m, q: f"/projects/{m[1]}/ai-proposals"),
    (r"^/project-imports/(\d+)/$", lambda m, q: f"/imports/{m[1]}"),
    (r"^/project-imports/$", lambda m, q: "/imports"),
]
SKIP = re.compile(r"^/(api|app|static|media|accounts|ws|devflo|admin|preview|invitations)/")


@lru_cache(maxsize=1)
def _rules():
    rules = [(re.compile(rx), fn) for rx, fn in STATIC_RULES]
    # Modules du pont générique : liste et fiche → /m/<nom>[/<id>].
    from django.urls import NoReverseMatch, reverse

    from project.api.resources import RESOURCES

    for name, res in RESOURCES.items():
        for suffix, kwargs in (("list", {}), ("detail", {"pk": 987654321})):
            try:
                path = reverse(f"{res.base}_{suffix}", kwargs=kwargs)
            except NoReverseMatch:
                continue
            rx = "^" + re.escape(path).replace("987654321", r"(\d+)") + "$"
            rules.append((re.compile(rx), (lambda n: lambda m, q: f"/m/{n}/{m[1]}" if m.groups() else f"/m/{n}")(name)))
    return rules


def react_target(path: str, query) -> str | None:
    for rx, fn in _rules():
        m = rx.match(path)
        if m:
            return fn(m, query)
    return None


class LegacyToReactRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        target = self._target(request)
        if target:
            return HttpResponseRedirect(f"/app{target}")
        return self.get_response(request)

    @staticmethod
    def _target(request):
        if not getattr(settings, "DEVFLOW_REACT_DEFAULT", False) or request.method not in ("GET", "HEAD"):
            return None
        if request.GET.get("classic") == "1" or SKIP.match(request.path):
            return None
        if request.headers.get("HX-Request") or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return None
        if "text/html" not in request.headers.get("Accept", ""):
            return None
        target = react_target(request.path, request.GET)
        if target and "?" not in target:
            keep = {k: v for k, v in request.GET.items() if k in ("tab", "project", "status", "q", "page")}
            target = f"{target}?{urlencode(keep)}" if keep else target
        return target
