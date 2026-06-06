"""
PR-MEET-RSVP : table MeetingParticipation (RSVP + Présence).

Crée le modèle MeetingParticipation et migre les données existantes :
pour chaque ProjectMeeting × internal_participants, on crée une row
MeetingParticipation avec rsvp_status=INVITED.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def forwards_seed_existing_invitations(apps, schema_editor):
    """Crée une MeetingParticipation pour chaque (meeting, user) déjà invité."""
    ProjectMeeting = apps.get_model("project", "ProjectMeeting")
    MeetingParticipation = apps.get_model("project", "MeetingParticipation")
    to_create = []
    for meeting in ProjectMeeting.objects.all().iterator():
        existing_user_ids = set(
            MeetingParticipation.objects
            .filter(meeting_id=meeting.pk)
            .values_list("user_id", flat=True)
        )
        for user_id in meeting.internal_participants.values_list("pk", flat=True):
            if user_id in existing_user_ids:
                continue
            to_create.append(MeetingParticipation(
                meeting_id=meeting.pk,
                user_id=user_id,
                rsvp_status="INVITED",
                attendance_status="UNKNOWN",
                self_confirmed=False,
            ))
    if to_create:
        MeetingParticipation.objects.bulk_create(to_create, batch_size=500)


def backwards_noop(apps, schema_editor):
    """Le reverse de la seed est implicite : la table sera dropée."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0039_meeting_minutes_versioning"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MeetingParticipation",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("rsvp_status", models.CharField(
                    choices=[
                        ("INVITED", "Invité"),
                        ("ACCEPTED", "Accepté"),
                        ("DECLINED", "Décliné"),
                        ("TENTATIVE", "Peut-être"),
                    ],
                    default="INVITED", db_index=True, max_length=12,
                )),
                ("rsvp_at", models.DateTimeField(blank=True, null=True)),
                ("rsvp_note", models.CharField(blank=True, max_length=300)),
                ("attendance_status", models.CharField(
                    choices=[
                        ("UNKNOWN", "Non renseigné"),
                        ("PRESENT", "Présent"),
                        ("ABSENT", "Absent"),
                        ("LATE", "Retard"),
                        ("LEFT_EARLY", "Parti tôt"),
                    ],
                    default="UNKNOWN", db_index=True, max_length=12,
                )),
                ("attendance_marked_at", models.DateTimeField(blank=True, null=True)),
                ("self_confirmed", models.BooleanField(
                    default=False,
                    help_text="True si le participant lui-même a confirmé sa présence.",
                )),
                ("attendance_marked_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="marked_attendances",
                    to=settings.AUTH_USER_MODEL,
                    help_text="L'utilisateur qui a marqué la présence (souvent l'organisateur).",
                )),
                ("meeting", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="participations",
                    to="project.projectmeeting",
                )),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="meeting_participations",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["meeting", "user__last_name", "user__first_name"],
                "unique_together": {("meeting", "user")},
                "verbose_name": "Participation à une réunion",
                "verbose_name_plural": "Participations aux réunions",
            },
        ),
        migrations.AddIndex(
            model_name="meetingparticipation",
            index=models.Index(
                fields=["meeting", "rsvp_status"],
                name="proj_meet_p_meet_rsvp_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="meetingparticipation",
            index=models.Index(
                fields=["meeting", "attendance_status"],
                name="proj_meet_p_meet_att_idx",
            ),
        ),
        # Seed les rows pour les réunions déjà créées
        migrations.RunPython(
            forwards_seed_existing_invitations,
            reverse_code=backwards_noop,
        ),
    ]
