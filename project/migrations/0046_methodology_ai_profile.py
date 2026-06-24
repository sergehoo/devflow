"""PR9-METHODO : MethodologyAIProfile (persona IA par méthodologie)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0045_seed_methodologies"),
    ]

    operations = [
        migrations.CreateModel(
            name="MethodologyAIProfile",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("persona", models.CharField(max_length=200)),
                ("system_prompt", models.TextField()),
                ("capabilities", models.JSONField(default=list, blank=True)),
                ("tone", models.CharField(max_length=30, blank=True)),
                ("examples", models.JSONField(default=list, blank=True)),
                ("methodology", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="ai_profile", to="project.methodology",
                )),
            ],
            options={
                "verbose_name": "Profil IA méthodologie",
                "verbose_name_plural": "Profils IA méthodologie",
            },
        ),
    ]
