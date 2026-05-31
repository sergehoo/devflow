"""PR24 — Security Audit Log."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0031_phase6_rbac"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("event_type", models.CharField(
                    choices=[
                        ("LOGIN", "Connexion"),
                        ("LOGOUT", "Déconnexion"),
                        ("LOGIN_FAILED", "Connexion échouée"),
                        ("CREATE", "Création"),
                        ("UPDATE", "Modification"),
                        ("DELETE", "Suppression"),
                        ("ACCESS_DENIED", "Accès refusé"),
                        ("PERMISSION_CHANGE", "Permissions modifiées"),
                        ("ROLE_CHANGE", "Rôle modifié"),
                        ("EXPORT", "Export de données"),
                        ("OTHER", "Autre"),
                    ],
                    db_index=True, max_length=20,
                )),
                ("severity", models.CharField(
                    choices=[
                        ("INFO", "Info"),
                        ("WARNING", "Avertissement"),
                        ("CRITICAL", "Critique"),
                    ],
                    db_index=True, default="INFO", max_length=10,
                )),
                ("action", models.CharField(max_length=80,
                    help_text="Code action métier (ex: project.delete, budget.export).")),
                ("target_type", models.CharField(blank=True, max_length=80,
                    help_text="Nom du modèle ciblé (ex: Project, Workspace).")),
                ("target_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("target_repr", models.CharField(blank=True, max_length=200)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=500)),
                ("request_path", models.CharField(blank=True, max_length=500)),
                ("request_method", models.CharField(blank=True, max_length=10)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("success", models.BooleanField(default=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="security_audit_logs",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="security_audit_logs",
                    to="project.workspace",
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="securityauditlog",
            index=models.Index(fields=["workspace", "-created_at"], name="audit_ws_date_idx"),
        ),
        migrations.AddIndex(
            model_name="securityauditlog",
            index=models.Index(fields=["user", "-created_at"], name="audit_user_date_idx"),
        ),
        migrations.AddIndex(
            model_name="securityauditlog",
            index=models.Index(fields=["event_type", "-created_at"], name="audit_event_date_idx"),
        ),
    ]
