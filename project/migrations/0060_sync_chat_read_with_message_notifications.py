"""
Messagerie : état « lu » aligné entre les conversations et leurs notifications.

Jusqu'ici, marquer une notification « message » comme lue (cloche, « Tout
marquer comme lu ») ne lisait pas la conversation, et lire une conversation ne
lisait pas ses notifications : le badge de la messagerie restait affiché alors
que l'utilisateur avait tout lu. Le code synchronise désormais les deux ; ce
rattrapage applique la même règle à l'existant, sans jamais faire reculer un
repère de lecture :

1. notification « message » lue → conversation lue jusqu'à ce message ;
2. notification « message » non lue d'un message déjà lu dans la conversation
   → notification lue.

Seules les notifications de messagerie (métadonnées ``channel_id`` +
``message_id``) sont concernées ; les notifications « message » des
enregistrements de réunion n'ont pas de fil et sont ignorées.
"""
from django.db import migrations
from django.db.models import Q
from django.utils import timezone

CHUNK = 1000


def _chat_rows(Notification, is_read):
    """(pk, recipient_id, channel_id, message_id) des notifications de messagerie."""
    rows = (
        Notification.objects.filter(notification_type="MESSAGE", is_read=is_read)
        .values_list("pk", "recipient_id", "metadata")
        .iterator(chunk_size=2000)
    )
    for pk, recipient_id, meta in rows:
        if not isinstance(meta, dict):
            continue
        channel_id, message_id = meta.get("channel_id"), meta.get("message_id")
        if type(channel_id) is int and type(message_id) is int:
            yield pk, recipient_id, channel_id, message_id


def _messages(Message, ids):
    """{message_id: (channel_id, created_at)} par paquets."""
    ids, found = list(ids), {}
    for start in range(0, len(ids), CHUNK):
        for pk, channel_id, created_at in Message.objects.filter(pk__in=ids[start:start + CHUNK]).values_list(
            "pk", "channel_id", "created_at",
        ):
            found[pk] = (channel_id, created_at)
    return found


def sync(apps, schema_editor):
    Notification = apps.get_model("project", "Notification")
    Message = apps.get_model("project", "Message")
    ChannelMembership = apps.get_model("project", "ChannelMembership")
    now = timezone.now()

    # 1. Notifications lues → repère de lecture avancé jusqu'au dernier message notifié.
    read = list(_chat_rows(Notification, True))
    messages = _messages(Message, {row[3] for row in read})
    marks = {}
    for _pk, user_id, _channel_id, message_id in read:
        if message_id not in messages:
            continue
        channel_id, created_at = messages[message_id]
        key = (user_id, channel_id)
        if key not in marks or marks[key] < created_at:
            marks[key] = created_at
    for (user_id, channel_id), created_at in marks.items():
        ChannelMembership.objects.filter(user_id=user_id, channel_id=channel_id).filter(
            Q(last_read_at__isnull=True) | Q(last_read_at__lt=created_at),
        ).update(last_read_at=created_at, updated_at=now)

    # 2. Notifications non lues dont le message est déjà lu dans la conversation → lues.
    unread = list(_chat_rows(Notification, False))
    messages = _messages(Message, {row[3] for row in unread})
    read_marks = {}
    for user_id, channel_id, last_read_at in ChannelMembership.objects.filter(
        user_id__in=sorted({row[1] for row in unread}), last_read_at__isnull=False,
    ).values_list("user_id", "channel_id", "last_read_at").iterator(chunk_size=2000):
        read_marks[(user_id, channel_id)] = last_read_at
    to_read = []
    for pk, user_id, _channel_id, message_id in unread:
        if message_id not in messages:
            continue
        channel_id, created_at = messages[message_id]
        last_read_at = read_marks.get((user_id, channel_id))
        if last_read_at is not None and created_at <= last_read_at:
            to_read.append(pk)
    for start in range(0, len(to_read), CHUNK):
        Notification.objects.filter(pk__in=to_read[start:start + CHUNK]).update(is_read=True, read_at=now)


class Migration(migrations.Migration):

    dependencies = [
        ("project", "0059_normalize_project_methodology"),
    ]

    operations = [
        migrations.RunPython(sync, migrations.RunPython.noop),
    ]
