"""
Frontend React (coexistence) : sert frontend/dist/index.html sous /app/…
L'ancien frontend Django reste inchangé sur ses routes.
"""

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import ensure_csrf_cookie

_INDEX = settings.FRONTEND_DIST_DIR / "index.html"


@ensure_csrf_cookie
def spa_index(request, path=""):
    try:
        html = _INDEX.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HttpResponse(
            "Frontend React non construit : exécutez « cd frontend && npm run build ».",
            status=503, content_type="text/plain; charset=utf-8",
        )
    response = HttpResponse(html)
    response["Cache-Control"] = "no-cache"
    return response
