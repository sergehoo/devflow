"""
PR-INV : permet l'émission de factures hors projet.

Avant : ``Invoice.project`` était NOT NULL (FK PROTECT), donc impossible
d'émettre une facture libre (consulting flat-fee, vente de licence, frais
divers, etc.).

Après : ``Invoice.project`` devient nullable. La facture reste TOUJOURS
rattachée à un workspace (FK CASCADE inchangé) — l'isolation multi-tenant
est préservée.

Migration ADDITIVE / non destructive :
  * AlterField uniquement (passage à null=True, blank=True)
  * Aucune donnée existante touchée (toutes les factures actuelles ont
    déjà un project, elles restent valides)
  * Réversible — sauf si une facture libre a été créée entretemps, auquel
    cas le ``migrate project 0035`` doit d'abord supprimer/réassigner ces
    enregistrements à un project.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0034_channelmembership_last_read_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invoice",
            name="project",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invoices",
                to="project.project",
                help_text=(
                    "Projet associé. Facultatif : une facture peut être "
                    "libre (consulting flat-fee, licence, frais divers…). "
                    "Dans tous les cas, la facture reste rattachée à un "
                    "workspace via le champ ``workspace``."
                ),
            ),
        ),
    ]
