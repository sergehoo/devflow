import re
from decimal import Decimal, InvalidOperation

import bleach
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def attr(obj, name):
    return getattr(obj, name, "")


# ─── PR23 — RBAC : templatetag user_can ───────────────────────────────────
@register.simple_tag(takes_context=True)
def user_can(context, action, target=None):
    """
    Vérifie une permission RBAC dans un template Django :

        {% load devflow_extras %}
        {% user_can "project.edit" project as can_edit %}
        {% if can_edit %}
            <button>Modifier</button>
        {% endif %}

    Ou simplement :

        {% if request.user.is_superuser or rbac_permissions|has_perm:"project.edit" %}

    Préférer ``user_can`` car il sait dériver le workspace depuis ``target``.
    """
    request = context.get("request")
    if request is None or not getattr(request, "user", None):
        return False
    from project.services.rbac import RBACService
    workspace = context.get("rbac_workspace") or context.get("current_workspace")
    return RBACService.can(request.user, action, target=target, workspace=workspace)


@register.filter
def has_perm(perms_set, action):
    """
    Filtre rapide pour vérifier une permission depuis le set exposé par
    le context processor ``devflow_rbac`` :

        {% if rbac_permissions|has_perm:"workspace.manage" %}
    """
    if not perms_set:
        return False
    if "*" in perms_set:
        return True
    if action in perms_set:
        return True
    # Wildcard domaine
    domain = action.split(".", 1)[0] if "." in action else action
    return f"{domain}.*" in perms_set


@register.filter
def get_item(d, key):
    """Accès dictionnaire depuis un template : {{ mydict|get_item:"key" }}."""
    if d is None:
        return ""
    try:
        return d.get(key, "")
    except (AttributeError, TypeError):
        try:
            return d[key]
        except (KeyError, TypeError, IndexError):
            return ""


def _to_decimal(value):
    """Convertit n'importe quelle valeur numérique en Decimal sans lever d'exception."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _format_decimal(value: Decimal, decimals: int) -> str:
    """Formate un Decimal avec N décimales, en supprimant les zéros inutiles."""
    quant = Decimal(10) ** -decimals
    rounded = value.quantize(quant)
    # Supprime les zéros à droite (60.00 → 60, 1.50 → 1.5)
    text = format(rounded.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@register.filter
def short_amount(value):
    """
    Formate un montant en version courte :
        60000      → "60 K"
        1_500_000  → "1.5 M"
        2_300_000_000 → "2.3 Md"
        950        → "950"
    Les valeurs négatives gardent leur signe. Les bornes prennent en compte
    l'arrondi : 999 500 → "1 M" (et pas "1000 K").
    """
    dec = _to_decimal(value)
    if dec is None:
        return ""

    sign = "-" if dec < 0 else ""
    n = abs(dec)

    # Seuils ajustés pour éviter "1000 K" après arrondi à 1 décimale.
    if n >= Decimal("999500000"):
        return f"{sign}{_format_decimal(n / Decimal('1000000000'), 1)} Md"
    if n >= Decimal("999500"):
        return f"{sign}{_format_decimal(n / Decimal('1000000'), 1)} M"
    if n >= Decimal("1000"):
        return f"{sign}{_format_decimal(n / Decimal('1000'), 1)} K"
    # < 1000 : on garde tel quel, sans décimales superflues
    return f"{sign}{_format_decimal(n, 2)}"


# ─── PR-MEET-FIX-HTML : rendu sécurisé du HTML utilisateur ───────────────
# Whitelist large pour autoriser le rich-text saisi dans les notes meeting,
# CR, décisions, etc. — assez permissif pour les usages métier mais
# nettoyé contre les XSS (script, on*=, javascript:).
_SAFE_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "div", "em",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "li", "ol", "p", "pre", "q", "s", "small",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "u", "ul",
}
_SAFE_ATTRS = {
    "*": ["class", "id", "title"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan", "align"],
    "th": ["colspan", "rowspan", "align", "scope"],
}
# Note : on retire `style` volontairement — le rendu est piloté par les
# classes Tailwind du wrapper (.devflow-prose) côté template, ce qui évite
# les soucis CSS-injection et le warning NoCssSanitizerWarning de bleach.
_SAFE_PROTOCOLS = ["http", "https", "mailto", "tel"]

# Détection grossière : le contenu contient-il au moins une balise HTML ?
_HTML_TAG_RE = re.compile(r"<\s*[a-zA-Z][^>]*>")


@register.filter(name="safe_html")
def safe_html(value):
    """
    Rend du HTML utilisateur en le nettoyant via bleach (XSS-safe).

    Usage dans un template :

        {{ meeting.notes|safe_html }}

    Comportement :
    - Si le texte contient des balises HTML → nettoyage avec whitelist
      (ul, li, p, strong, em, a, table, etc.) et linkification des URLs.
    - Si le texte est en clair → conversion naïve des sauts de ligne en
      <br> pour préserver la mise en forme visuelle.

    XSS bloqué : <script>, on*= (onerror, onclick...), javascript:, data:,
    iframes, embeds, etc.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""

    if _HTML_TAG_RE.search(text):
        # Cas "rich text" : on autorise les balises whitelisted
        cleaned = bleach.clean(
            text,
            tags=_SAFE_TAGS,
            attributes=_SAFE_ATTRS,
            protocols=_SAFE_PROTOCOLS,
            strip=True,
            strip_comments=True,
        )
        cleaned = bleach.linkify(cleaned, parse_email=False)
    else:
        # Cas "texte plain" : escape + linebreaks → <br>
        escaped = bleach.clean(text, tags=set(), attributes={}, strip=True)
        cleaned = escaped.replace("\r\n", "\n").replace("\n", "<br>")
        cleaned = bleach.linkify(cleaned, parse_email=False)

    return mark_safe(cleaned)


@register.filter
def full_amount(value):
    """
    Retourne le montant exact, séparateurs de milliers par espace insécable.
    Utilisé pour le tooltip (popover) au survol.
        60000   → "60 000"
        1234.5  → "1 234.5"
    """
    dec = _to_decimal(value)
    if dec is None:
        return ""

    sign = "-" if dec < 0 else ""
    n = abs(dec)

    # Sépare partie entière / décimale
    text = format(n, "f")
    if "." in text:
        int_part, dec_part = text.split(".", 1)
        dec_part = dec_part.rstrip("0")
    else:
        int_part, dec_part = text, ""

    # Sépare les milliers avec une espace insécable fine
    grouped = "{:,}".format(int(int_part)).replace(",", " ")
    if dec_part:
        return f"{sign}{grouped}.{dec_part}"
    return f"{sign}{grouped}"