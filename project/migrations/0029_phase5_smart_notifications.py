"""
Phase 5 — PR21 : Notifications intelligentes.

Migration ADDITIVE :
  * CreateModel NotificationPreference (1-1 User)
  * CreateModel NotificationDigest (historique des digests envoyés)

ROLLBACK : ``migrate project 0028`` supprime les 2 tables. Aucune perte
de donnée — les Notifications existantes restent intactes.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0028_phase4_ai_v2"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("channel_in_app", models.BooleanField(default=True)),
                ("channel_email", models.BooleanField(default=True)),
                ("channel_digest", models.BooleanField(
                    default=True,
                    help_text="Recevoir un digest récap (cumul des notifs sur la période).",
                )),
                ("notify_frequency", models.CharField(
                    choices=[
                        ("IMMEDIATE", "Immédiat"),
                        ("HOURLY", "Toutes les heures (regroupé)"),
                        ("DAILY", "Quotidien (digest)"),
                        ("DISABLED", "Désactivées"),
                    ],
                    default="IMMEDIATE", max_length=12,
                )),
                ("quiet_hours_start", models.PositiveSmallIntegerField(
                    default=22,
                    help_text="Heure de début du silence (0-23). Aucun email envoyé.",
                )),
                ("quiet_hours_end", models.PositiveSmallIntegerField(
                    default=7,
                    help_text="Heure de fin du silence (0-23).",
                )),
                ("priority_types", models.JSONField(
                    blank=True, default=list,
                    help_text='Notification types qui bypassent le digest. Ex: ["RISK"].',
                )),
                ("user", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="notification_preference",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-updated_at"]},
        ),
        migrations.CreateModel(
            name="NotificationDigest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("frequency", models.CharField(
                    choices=[
                        ("HOURLY", "Horaire"),
                        ("DAILY", "Quotidien"),
                        ("WEEKLY", "Hebdomadaire"),
                    ],
                    default="DAILY", max_length=10,
                )),
                ("period_start", models.DateTimeField()),
                ("period_end", models.DateTimeField()),
                ("notifications_count", models.PositiveIntegerField(default=0)),
                ("payload", models.JSONField(
                    default=dict,
                    help_text="Récap structuré : groupes par type/projet, top 5 actions...",
                )),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("sent_via_email", models.BooleanField(default=False)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="notification_digests",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["-period_end", "-id"]},
        ),
        migrations.AddIndex(
            model_name="notificationdigest",
            index=models.Index(
                fields=["user", "-period_end"],
                name="digest_user_period_idx",
            ),
        ),
    ]
