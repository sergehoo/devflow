from django.contrib.auth import get_user_model
from project import models as dm


def get_or_create_direct_channel(workspace, users, name=None, is_private=True):
    users = list(set(users))
    if len(users) < 2:
        raise ValueError("Un channel direct nécessite au moins deux utilisateurs.")

    if not name:
        name = " · ".join(sorted([
            u.get_full_name() or u.username
            for u in users
        ]))

    channel = dm.DirectChannel.objects.create(
        workspace=workspace,
        name=name,
        is_private=is_private,
    )

    for user in users:
        dm.ChannelMembership.objects.get_or_create(
            channel=channel,
            user=user,
        )

    return channel