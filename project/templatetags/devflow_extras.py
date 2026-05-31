from decimal import Decimal, InvalidOperation

from django import template

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