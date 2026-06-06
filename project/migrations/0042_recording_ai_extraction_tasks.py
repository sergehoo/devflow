"""
PR-MEET-AI-ENRICH : ajoute TASK_MENTION et TASK_SUGGESTION à
RecordingAIExtraction.Kind.choices.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0041_meetingagendaitem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="recordingaiextraction",
            name="kind",
            field=models.CharField(
                choices=[
                    ("decision", "Décision"),
                    ("action", "Action"),
                    ("risk", "Risque"),
                    ("note", "Note"),
                    ("project_suggestion", "Suggestion : nouveau projet"),
                    ("sprint_suggestion", "Suggestion : nouveau sprint"),
                    ("milestone_suggestion", "Suggestion : nouveau jalon"),
                    ("project_mention", "Projet mentionné"),
                    ("sprint_mention", "Sprint mentionné"),
                    ("milestone_mention", "Jalon mentionné"),
                    ("task_mention", "Tâche mentionnée"),
                    ("task_suggestion", "Suggestion : nouvelle tâche"),
                ],
                max_length=25,
            ),
        ),
    ]
