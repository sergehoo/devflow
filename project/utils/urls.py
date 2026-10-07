"""
URLs absolues pour les emails et notifications envoyés hors requête HTTP
(Celery, commandes). Un lien relatif (« /tasks/42/ ») est inutilisable dans
un client mail : tout lien d'email doit passer par ``absolute_url``.
"""

from django.conf import settings

_LOCAL_HOSTS = {"*", "localhost", "127.0.0.1", "[::1]", "0.0.0.0"}


def site_base_url() -> str:
    """
    Base publique de l'application, par ordre de priorité :
      1. ``SITE_URL`` (ex. https://flow.datarium-dev.com) ;
      2. première origine https de ``CSRF_TRUSTED_ORIGINS`` ;
      3. premier hôte public de ``ALLOWED_HOSTS`` (https) ;
      4. http://localhost:8000 (développement).
    """
    base = (getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if base:
        return base
    origins = list(getattr(settings, "CSRF_TRUSTED_ORIGINS", None) or [])
    for origin in sorted(origins, key=lambda o: not o.startswith("https://")):
        if origin.startswith(("https://", "http://")) and "*" not in origin:
            return origin.rstrip("/")
    for host in getattr(settings, "ALLOWED_HOSTS", None) or []:
        host = host.strip()
        if host and host not in _LOCAL_HOSTS and not host.startswith("."):
            return f"https://{host}"
    return "http://localhost:8000"


def absolute_url(path: str, request=None) -> str:
    if not path or path.startswith(("http://", "https://")):
        return path
    if request is not None:
        return request.build_absolute_uri(path)
    return f"{site_base_url()}/{path.lstrip('/')}"
