"""
PR2-METHODO : Workflow Engine — transitions de statuts contrôlées par rôle.

Ajoute :
  * MethodologyWorkflow (un workflow nommé par catégorie d'objet)
  * WorkflowTransition (transitions entre 2 statuts, avec rôles et triggers)
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0043_methodology_engine"),
    ]

    operations = [
        # ─── MethodologyWorkflow ───────────────────────────────────────
        migrations.CreateModel(
            name="MethodologyWorkflow",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("code", models.SlugField(max_length=50)),
                ("name", models.CharField(max_length=80)),
                ("description", models.TextField(blank=True)),
                ("applies_to", models.CharField(
                    max_length=20, default="task", db_index=True,
                    choices=[
                        ("task", "Tâche"),
                        ("story", "User Story"),
                        ("epic", "Epic"),
                        ("feature", "Feature"),
                        ("bug", "Bug"),
                        ("deliverable", "Livrable"),
                        ("phase", "Phase"),
                        ("milestone", "Jalon"),
                        ("risk", "Risque"),
                        ("any", "Tout objet"),
                    ],
                )),
                ("is_default", models.BooleanField(default=False)),
                ("methodology", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="workflows", to="project.methodology",
                )),
            ],
            options={
                "ordering": ["methodology", "applies_to", "name"],
                "verbose_name": "Workflow méthodologie",
                "verbose_name_plural": "Workflows méthodologie",
            },
        ),
        migrations.AddConstraint(
            model_name="methodologyworkflow",
            constraint=models.UniqueConstraint(
                fields=("methodology", "code"),
                name="uniq_workflow_per_methodology",
            ),
        ),
        migrations.AddIndex(
            model_name="methodologyworkflow",
            index=models.Index(
                fields=["methodology", "applies_to"],
                name="proj_workflow_meth_at_idx",
            ),
        ),

        # ─── WorkflowTransition ───────────────────────────────────────
        migrations.CreateModel(
            name="WorkflowTransition",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("label", models.CharField(max_length=80, blank=True)),
                ("required_role_codes", models.JSONField(default=list, blank=True)),
                ("requires_comment", models.BooleanField(default=False)),
                ("auto_trigger", models.CharField(
                    max_length=30, default="none", db_index=True,
                    choices=[
                        ("none", "—"),
                        ("on_pr_merged", "PR mergée"),
                        ("on_pr_opened", "PR ouverte"),
                        ("on_all_subtasks_done", "Toutes sous-tâches DONE"),
                        ("on_review_approved", "Revue approuvée"),
                        ("on_deadline_passed", "Échéance dépassée"),
                        ("on_blocked_resolved", "Bloqueur résolu"),
                        ("on_budget_exceeded", "Budget dépassé"),
                    ],
                )),
                ("conditions_json", models.JSONField(default=dict, blank=True)),
                ("workflow", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="transitions",
                    to="project.methodologyworkflow",
                )),
                ("from_status", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="outgoing_transitions",
                    to="project.methodologystatus",
                )),
                ("to_status", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="incoming_transitions",
                    to="project.methodologystatus",
                )),
            ],
            options={
                "ordering": ["workflow", "from_status", "to_status"],
                "verbose_name": "Transition workflow",
                "verbose_name_plural": "Transitions workflow",
            },
        ),
        migrations.AddConstraint(
            model_name="workflowtransition",
            constraint=models.UniqueConstraint(
                fields=("workflow", "from_status", "to_status"),
                name="uniq_transition_per_workflow",
            ),
        ),
        migrations.AddIndex(
            model_name="workflowtransition",
            index=models.Index(
                fields=["workflow", "auto_trigger"],
                name="proj_trans_wf_auto_idx",
            ),
        ),
    ]
