"""
PR-CHAT-2 : ajout de ChannelMembership.last_read_at.

Champ utilisé pour calculer le compteur de messages non lus par canal :
    unread_count(user, channel) = nb messages dans channel.messages
                                  où created_at > membership.last_read_at
                                  ET author_id != user.id

Migration purement ADDITIVE :
  * nouveau champ DateTimeField nullable + blank (NULL = jamais lu / canal neuf
    → tous les messages sont considérés comme non lus pour la première
    visite, comportement attendu côté UI)
  * aucun impact sur les données existantes
  * réversible sans perte

ROLLBACK : ``migrate project 0033`` supprime la colonne.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # Avant : dépendait directement de 0033_merge_20260601_1038, mais
        # un merge intermédiaire 0034_merge_20260601_1049 a été généré
        # côté repo (par makemigrations --merge). On enchaîne dessus pour
        # ne laisser qu'un seul leaf migration.
        ("project", "0034_merge_20260601_1049"),
    ]

    operations = [
        migrations.AddField(
            model_name="channelmembership",
            name="last_read_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text=(
                    "Horodatage du dernier message lu par l'utilisateur sur "
                    "ce canal. NULL = jamais lu (tous les messages sont "
                    "non lus). Mis à jour via POST "
                    "/api/v1/me/chat/channels/{id}/mark-read/."
                ),
            ),
        ),
        migrations.AddIndex(
            model_name="channelmembership",
            index=models.Index(
                fields=["user", "channel", "last_read_at"],
                name="chan_memb_unread_idx",
            ),
        ),
    ]
