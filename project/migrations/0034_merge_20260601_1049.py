"""
Merge 0034_merge_20260601_1049 — restauré.

Référencé par 0034_channelmembership_last_read_at (commit ebf894a) mais jamais
versionné : le graphe de migrations était cassé (NodeNotFoundError) sur tout
clone neuf. Migration vide : les bases où il est déjà enregistré dans
django_migrations ne voient aucun changement.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0033_merge_20260601_1038"),
    ]

    operations = []
