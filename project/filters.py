from __future__ import annotations

from typing import Type

import django_filters
from django.db import models
from django.db.models import Model

from .registry import MODEL_REGISTRY


def get_filter_fields(model: Type[Model]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for field in model._meta.fields:
        if isinstance(field, (models.CharField, models.TextField, models.SlugField, models.EmailField, models.URLField)):
            result[field.name] = ["exact", "icontains"]
        elif isinstance(field, (models.DateField, models.DateTimeField, models.TimeField)):
            result[field.name] = ["exact", "gte", "lte"]
        elif isinstance(field, (models.IntegerField, models.PositiveIntegerField, models.PositiveSmallIntegerField, models.DecimalField, models.FloatField)):
            result[field.name] = ["exact", "gte", "lte"]
        elif isinstance(field, models.BooleanField):
            result[field.name] = ["exact"]
        elif isinstance(field, (models.ForeignKey, models.OneToOneField)):
            result[field.name] = ["exact"]
    return result


def build_filterset_class(model: Type[Model]) -> Type[django_filters.FilterSet]:
    meta = type("Meta", (), {"model": model, "fields": get_filter_fields(model)})
    filterset_class = type(f"{model.__name__}FilterSet", (django_filters.FilterSet,), {"Meta": meta})
    return filterset_class


FILTERSET_REGISTRY = {
    key: build_filterset_class(model)
    for key, model in MODEL_REGISTRY.items()
}

WorkspaceFilterSet = FILTERSET_REGISTRY["workspace"]
ProjectFilterSet = FILTERSET_REGISTRY["project"]
SprintFilterSet = FILTERSET_REGISTRY["sprint"]
TaskFilterSet = FILTERSET_REGISTRY["task"]
RiskFilterSet = FILTERSET_REGISTRY["risk"]
ObjectiveFilterSet = FILTERSET_REGISTRY["objective"]