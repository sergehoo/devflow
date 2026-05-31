"""
PR23 — RBAC central : WorkspaceRoleAssignment.

Migration ADDITIVE :
  * CreateModel WorkspaceRoleAssignment
  * UniqueConstraint(workspace, user)
  * 2 indexes pour le lookup rapide

ROLLBACK : ``migrate project 0030`` supprime la table. Aucune perte de
donnée (les Workspace.owner restent la source primaire des rôles Owner).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0030_phase5_ai_reports"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkspaceRoleAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role", models.CharField(
                    choices=[
                        ("WORKSPACE_OWNER", "Propriétaire workspace"),
                        ("PROJECT_MANAGER", "Chef de projet"),
                        ("TEAM_LEAD", "Lead équipe"),
                        ("MEMBER", "Membre"),
                        ("CLIENT", "Client"),
                    ],
                    default="MEMBER", max_length=20,
                )),
                ("notes", models.TextField(blank=True)),
                ("assigned_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="rbac_assignments_made",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="rbac_assignments",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="rbac_assignments",
                    to="project.workspace",
                )),
            ],
            options={"ordering": ["workspace", "user"]},
        ),
        migrations.AddConstraint(
            model_name="workspaceroleassignment",
            constraint=models.UniqueConstraint(
                fields=("workspace", "user"),
                name="uniq_workspace_role_per_user",
            ),
        ),
        migrations.AddIndex(
            model_name="workspaceroleassignment",
            index=models.Index(
                fields=["workspace", "role"],
                name="rbac_ws_role_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="workspaceroleassignment",
            index=models.Index(
                fields=["user", "workspace"],
                name="rbac_user_ws_idx",
            ),
        ),
    ]
