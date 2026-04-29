# Migration corrigée — schéma aligné sur project/models.py
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('project', '0017_aichatsession_aichatmessage'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProjectMeeting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_archived', models.BooleanField(default=False)),
                ('archived_at', models.DateTimeField(blank=True, null=True)),
                ('title', models.CharField(max_length=200)),
                ('meeting_type', models.CharField(choices=[('FRAMING', 'Cadrage'), ('FOLLOW_UP', 'Suivi'), ('SPRINT_REVIEW', 'Sprint review'), ('PROJECT_COMMITTEE', 'Comité projet'), ('STEERING_COMMITTEE', 'Comité de pilotage'), ('RETROSPECTIVE', 'Rétrospective'), ('OTHER', 'Autre')], default='FOLLOW_UP', max_length=25)),
                ('status', models.CharField(choices=[('PLANNED', 'Planifiée'), ('HELD', 'Tenue'), ('CANCELLED', 'Annulée'), ('POSTPONED', 'Reportée')], default='PLANNED', max_length=15)),
                ('scheduled_at', models.DateTimeField()),
                ('duration_minutes', models.PositiveIntegerField(default=60)),
                ('location', models.CharField(blank=True, max_length=200)),
                ('meeting_link', models.URLField(blank=True)),
                ('external_participants', models.TextField(blank=True, help_text='Liste libre, un par ligne (Nom — Société — Email)')),
                ('agenda', models.TextField(blank=True, help_text='Ordre du jour')),
                ('notes', models.TextField(blank=True, help_text='Prise de notes / compte-rendu')),
                ('decisions', models.TextField(blank=True, help_text='Décisions prises')),
                ('blockers', models.TextField(blank=True, help_text='Points bloquants')),
                ('next_steps', models.TextField(blank=True, help_text='Prochaine étape')),
                ('ai_summary', models.TextField(blank=True)),
                ('ai_extracted_at', models.DateTimeField(blank=True, null=True)),
                ('ai_used_provider', models.CharField(blank=True, max_length=50)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_meetings', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_meetings', to=settings.AUTH_USER_MODEL)),
                ('organizer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='organized_meetings', to=settings.AUTH_USER_MODEL)),
                ('internal_participants', models.ManyToManyField(blank=True, related_name='attended_meetings', to=settings.AUTH_USER_MODEL)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='meetings', to='project.project')),
                ('sprint', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='meetings', to='project.sprint')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='meetings', to='project.workspace')),
            ],
            options={
                'verbose_name': 'Réunion projet',
                'verbose_name_plural': 'Réunions projet',
                'ordering': ['-scheduled_at'],
                'permissions': [('ai_process_meeting', "Peut lancer le traitement IA d'une réunion")],
            },
        ),
        migrations.CreateModel(
            name='MeetingAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('file', models.FileField(upload_to='devflow/meetings/')),
                ('label', models.CharField(blank=True, max_length=200)),
                ('meeting', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='project.projectmeeting')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='meeting_uploads', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='MeetingActionItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(max_length=300)),
                ('description', models.TextField(blank=True)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('status', models.CharField(choices=[('OPEN', 'Ouverte'), ('IN_PROGRESS', 'En cours'), ('DONE', 'Terminée'), ('CANCELLED', 'Annulée')], default='OPEN', max_length=15)),
                ('priority', models.CharField(choices=[('LOW', 'Low'), ('MEDIUM', 'Medium'), ('HIGH', 'High'), ('CRITICAL', 'Critique')], default='MEDIUM', max_length=20)),
                ('converted_at', models.DateTimeField(blank=True, null=True)),
                ('converted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='converted_meeting_actions', to=settings.AUTH_USER_MODEL)),
                ('converted_task', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_meeting_actions', to='project.task')),
                ('meeting', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='action_items', to='project.projectmeeting')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='meeting_action_items', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Action de réunion',
                'verbose_name_plural': 'Actions de réunion',
                'ordering': ['due_date', '-created_at'],
            },
        ),
    ]
