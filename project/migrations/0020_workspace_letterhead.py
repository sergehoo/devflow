# Migration : champs papier en-tête sur Workspace
# Generated manually on 2026-04-29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0019_invoicing_and_team_constraints'),
    ]

    operations = [
        migrations.AddField(
            model_name='workspace',
            name='legal_name',
            field=models.CharField(blank=True, max_length=200,
                                   help_text='Raison sociale complète (ex: SARL DATARIUM)'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='tagline',
            field=models.CharField(blank=True, max_length=120,
                                   help_text='Slogan affiché en pied de page (ex: DIGITAL & TECHNOLOGIES)'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='legal_rccm',
            field=models.CharField(blank=True, max_length=60, help_text='Numéro RCCM'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='legal_cc',
            field=models.CharField(blank=True, max_length=60, help_text='Numéro Compte Contribuable'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='legal_tax_id',
            field=models.CharField(blank=True, max_length=60, help_text='Identifiant fiscal / TVA'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='address_line1',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='workspace',
            name='address_line2',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='workspace',
            name='postal_code',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='workspace',
            name='city',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='workspace',
            name='country',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='workspace',
            name='phone',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='workspace',
            name='website',
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name='workspace',
            name='email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='workspace',
            name='bank_details',
            field=models.TextField(blank=True,
                                   help_text='IBAN / RIB / coordonnées bancaires affichées sur la facture'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='invoice_footer_text',
            field=models.TextField(blank=True,
                                   help_text='Mentions légales additionnelles (TVA non applicable, etc.)'),
        ),
        migrations.AddField(
            model_name='workspace',
            name='accent_color',
            field=models.CharField(default='#F4722B', max_length=20,
                                   help_text='Couleur de la barre orange du papier en-tête'),
        ),
    ]
