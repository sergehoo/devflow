# Migration : module Facturation + UniqueConstraint TeamMembership
# Generated manually on 2026-04-29

from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('project', '0018_projectmeeting_meetingattachment_meetingactionitem'),
    ]

    operations = [
        # ────────────────────────────────────────────────────────────────
        # 1. TeamMembership — remplacer unique_together par UniqueConstraint
        # ────────────────────────────────────────────────────────────────
        migrations.AlterUniqueTogether(
            name='teammembership',
            unique_together=set(),
        ),
        migrations.AlterModelOptions(
            name='teammembership',
            options={'ordering': ['-status', 'user__last_name', 'user__first_name']},
        ),
        migrations.AddConstraint(
            model_name='teammembership',
            constraint=models.UniqueConstraint(
                condition=models.Q(('team__isnull', False)),
                fields=('workspace', 'user', 'team'),
                name='uniq_membership_with_team',
            ),
        ),
        migrations.AddConstraint(
            model_name='teammembership',
            constraint=models.UniqueConstraint(
                condition=models.Q(('team__isnull', True)),
                fields=('workspace', 'user'),
                name='uniq_membership_no_team',
            ),
        ),

        # ────────────────────────────────────────────────────────────────
        # 2. InvoiceClient
        # ────────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='InvoiceClient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_archived', models.BooleanField(default=False)),
                ('archived_at', models.DateTimeField(blank=True, null=True)),
                ('name', models.CharField(max_length=180)),
                ('legal_name', models.CharField(blank=True, max_length=200)),
                ('tax_id', models.CharField(blank=True, max_length=60)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('phone', models.CharField(blank=True, max_length=40)),
                ('address_line1', models.CharField(blank=True, max_length=200)),
                ('address_line2', models.CharField(blank=True, max_length=200)),
                ('postal_code', models.CharField(blank=True, max_length=20)),
                ('city', models.CharField(blank=True, max_length=120)),
                ('country', models.CharField(blank=True, max_length=80)),
                ('contact_name', models.CharField(blank=True, max_length=180)),
                ('notes', models.TextField(blank=True)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                related_name='invoice_clients',
                                                to='project.workspace')),
            ],
            options={
                'ordering': ['name'],
                'unique_together': {('workspace', 'name')},
            },
        ),

        # ────────────────────────────────────────────────────────────────
        # 3. Invoice
        # ────────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='Invoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_archived', models.BooleanField(default=False)),
                ('archived_at', models.DateTimeField(blank=True, null=True)),
                ('number', models.CharField(blank=True, max_length=40)),
                ('title', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('issue_date', models.DateField(default=django.utils.timezone.localdate)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('period_start', models.DateField(blank=True, null=True)),
                ('period_end', models.DateField(blank=True, null=True)),
                ('paid_at', models.DateField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('subtotal_ht', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('discount_amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('tax_rate', models.DecimalField(decimal_places=2, default=Decimal('18.00'), max_digits=5)),
                ('tax_amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('total_ttc', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('paid_amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('currency', models.CharField(default='XOF', max_length=10)),
                ('status', models.CharField(
                    choices=[
                        ('DRAFT', 'Brouillon'), ('ISSUED', 'Émise'), ('SENT', 'Envoyée'),
                        ('PARTIALLY_PAID', 'Partiellement payée'), ('PAID', 'Payée'),
                        ('OVERDUE', 'En retard'), ('CANCELLED', 'Annulée')],
                    default='DRAFT', max_length=20)),
                ('billing_mode', models.CharField(
                    choices=[
                        ('FIXED', 'Forfait (Estimate Lines)'),
                        ('TIME_AND_MATERIALS', 'Régie (Timesheets)'),
                        ('MILESTONE', 'Sur jalon'),
                        ('MANUAL', 'Manuel')],
                    default='MANUAL', max_length=25)),
                ('pdf_file', models.FileField(blank=True, null=True, upload_to='devflow/invoices/')),
                ('client', models.ForeignKey(blank=True, null=True,
                                             on_delete=django.db.models.deletion.PROTECT,
                                             related_name='invoices',
                                             to='project.invoiceclient')),
                ('issued_by', models.ForeignKey(blank=True, null=True,
                                                on_delete=django.db.models.deletion.SET_NULL,
                                                related_name='issued_invoices',
                                                to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                              related_name='invoices',
                                              to='project.project')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                related_name='invoices',
                                                to='project.workspace')),
            ],
            options={
                'ordering': ['-issue_date', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='invoice',
            index=models.Index(fields=['workspace', 'status'], name='proj_inv_ws_status_idx'),
        ),
        migrations.AddIndex(
            model_name='invoice',
            index=models.Index(fields=['project', 'status'], name='proj_inv_proj_status_idx'),
        ),
        migrations.AddIndex(
            model_name='invoice',
            index=models.Index(fields=['due_date'], name='proj_inv_due_idx'),
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(
                condition=~models.Q(('number', '')),
                fields=('workspace', 'number'),
                name='uniq_invoice_number_per_workspace',
            ),
        ),

        # ────────────────────────────────────────────────────────────────
        # 4. InvoiceLine
        # ────────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='InvoiceLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('line_type', models.CharField(
                    choices=[('SERVICE', 'Prestation'), ('TIME', 'Régie / Heures'),
                             ('EXPENSE', 'Frais refacturé'), ('MILESTONE', 'Jalon'),
                             ('DISCOUNT', 'Remise'), ('OTHER', 'Autre')],
                    default='SERVICE', max_length=15)),
                ('label', models.CharField(max_length=240)),
                ('description', models.TextField(blank=True)),
                ('quantity', models.DecimalField(decimal_places=2, default=1, max_digits=12)),
                ('unit_price', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('position', models.PositiveIntegerField(default=0)),
                ('estimate_line', models.ForeignKey(blank=True, null=True,
                                                    on_delete=django.db.models.deletion.SET_NULL,
                                                    related_name='invoice_lines',
                                                    to='project.projectestimateline')),
                ('milestone', models.ForeignKey(blank=True, null=True,
                                                on_delete=django.db.models.deletion.SET_NULL,
                                                related_name='invoice_lines',
                                                to='project.milestone')),
                ('user', models.ForeignKey(blank=True, null=True,
                                           on_delete=django.db.models.deletion.SET_NULL,
                                           related_name='invoice_lines',
                                           to=settings.AUTH_USER_MODEL)),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='lines',
                                              to='project.invoice')),
            ],
            options={
                'ordering': ['position', 'id'],
            },
        ),

        # ────────────────────────────────────────────────────────────────
        # 5. InvoicePayment
        # ────────────────────────────────────────────────────────────────
        migrations.CreateModel(
            name='InvoicePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('received_at', models.DateField(default=django.utils.timezone.localdate)),
                ('method', models.CharField(
                    choices=[('BANK_TRANSFER', 'Virement bancaire'),
                             ('CARD', 'Carte bancaire'), ('CASH', 'Espèces'),
                             ('CHECK', 'Chèque'), ('MOBILE_MONEY', 'Mobile Money'),
                             ('OTHER', 'Autre')],
                    default='BANK_TRANSFER', max_length=20)),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('status', models.CharField(
                    choices=[('PENDING', 'En attente'), ('CONFIRMED', 'Confirmé'),
                             ('REFUNDED', 'Remboursé'), ('FAILED', 'Échoué')],
                    default='CONFIRMED', max_length=12)),
                ('note', models.TextField(blank=True)),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='payments',
                                              to='project.invoice')),
                ('recorded_by', models.ForeignKey(blank=True, null=True,
                                                  on_delete=django.db.models.deletion.SET_NULL,
                                                  related_name='recorded_payments',
                                                  to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-received_at', '-id'],
            },
        ),
    ]
