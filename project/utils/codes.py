import re
from django.db.models import Max
from django.utils.text import slugify


def build_slug(value: str, fallback: str = "item") -> str:
    value = (value or "").strip()
    slug = slugify(value)
    return slug or fallback


def build_prefix(value: str, max_length: int = 4, fallback: str = "ITEM") -> str:
    """
    Ex:
    'Plateforme Bestepargne' -> 'PB'
    'DevFlow Project' -> 'DP'
    'API' -> 'API'
    """
    value = re.sub(r"[^A-Za-z0-9\s\-]", " ", value or "").strip()
    parts = [p for p in re.split(r"[\s\-_]+", value) if p]

    if not parts:
        return fallback[:max_length].upper()

    if len(parts) == 1:
        word = parts[0][:max_length]
        return word.upper()

    prefix = "".join(p[0] for p in parts[:max_length])
    return prefix.upper()


def next_sequential_code(model_class, field_name: str = "code", prefix: str = "ITEM", padding: int = 3) -> str:
    """
    Génère un code du type:
    PRJ-001
    TSK-014
    etc.

    Cherche les codes existants commençant par le préfixe.
    """
    pattern_prefix = f"{prefix}-"
    qs = model_class.objects.filter(**{f"{field_name}__startswith": pattern_prefix})

    max_num = 0
    for value in qs.values_list(field_name, flat=True):
        if not value:
            continue
        try:
            num = int(str(value).replace(pattern_prefix, ""))
            max_num = max(max_num, num)
        except (TypeError, ValueError):
            continue

    next_num = max_num + 1
    return f"{prefix}-{str(next_num).zfill(padding)}"


def unique_slug(instance, value: str, slug_field: str = "slug", fallback: str = "item") -> str:
    """
    Génère un slug unique pour le modèle de l'instance.
    """
    base_slug = build_slug(value, fallback=fallback)
    model_class = instance.__class__

    slug = base_slug
    index = 2

    qs = model_class.objects.all()
    if instance.pk:
        qs = qs.exclude(pk=instance.pk)

    while qs.filter(**{slug_field: slug}).exists():
        slug = f"{base_slug}-{index}"
        index += 1

    return slug
