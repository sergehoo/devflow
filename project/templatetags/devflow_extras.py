from django import template

register = template.Library()


@register.filter
def attr(obj, name):
    return getattr(obj, name, "")


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