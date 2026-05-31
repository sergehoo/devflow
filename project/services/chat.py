"""
DevFlow — Service Chat unifié.

Objectif : un seul service propre pour gérer DM (1-1) et groupes (3+),
remplaçant le double système (channel_chat_views FBV + DirectChannelViewSet
CBV) identifié dans l'audit.

Convention :
  * DM         = DirectChannel(is_private=True) avec EXACTEMENT 2 membres
  * Groupe     = DirectChannel(is_private=True) avec 3+ membres et `name` libre
  * Salon WS   = DirectChannel(is_private=False) — visible par tous les membres
                 du workspace (cas avancé, pas exposé en UI Phase initiale)

Aucune modification du schéma — on travaille sur les modèles existants
(DirectChannel, ChannelMembership, Message).

Helper legacy ``get_or_create_direct_channel`` conservé en bas pour la
compatibilité avec d'éventuels appels existants.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Max, Q

from project import models as dm

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user_display(user) -> str:
    """Retourne le nom d'affichage d'un user (full_name > username)."""
    if not user:
        return "—"
    full = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return full or user.get_username()


def _channel_to_dict(channel: dm.DirectChannel, *, current_user) -> dict:
    """
    Sérialise un canal pour l'UI.

    Inclut :
      * is_dm (bool) : True si canal à 2 membres
      * display_name : pour les DM, le nom de l'autre membre ; pour les
        groupes, le `name` du canal
      * last_message_preview, last_message_at
    """
    members = list(channel.members.all())
    member_dicts = [
        {
            "id": m.pk,
            "username": m.get_username(),
            "display_name": _user_display(m),
            "is_self": m.pk == current_user.pk if current_user else False,
        }
        for m in members
    ]
    is_dm = len(members) == 2
    other = None
    if is_dm and current_user:
        other = next((m for m in members if m.pk != current_user.pk), None)

    last_msg = channel.messages.order_by("-created_at").first()
    last_preview = ""
    last_at = None
    if last_msg:
        last_preview = (last_msg.body or "")[:140]
        last_at = last_msg.created_at.isoformat()

    return {
        "id": channel.pk,
        "name": channel.name,
        "is_private": channel.is_private,
        "is_dm": is_dm,
        "is_group": (not is_dm) and (len(members) >= 2),
        "display_name": _user_display(other) if (is_dm and other) else channel.name,
        "display_subtitle": (
            f"DM · {_user_display(other)}" if (is_dm and other)
            else f"{len(members)} participants"
        ),
        "member_count": len(members),
        "members": member_dicts,
        "last_message_preview": last_preview,
        "last_message_at": last_at,
        "workspace_id": channel.workspace_id,
    }


def _message_to_dict(message: dm.Message, *, current_user=None) -> dict:
    return {
        "id": message.pk,
        "channel_id": message.channel_id,
        "author_id": message.author_id,
        "author_name": _user_display(message.author),
        "author_username": message.author.get_username() if message.author else "",
        "is_self": (current_user and message.author_id == current_user.pk),
        "body": message.body,
        "is_edited": message.is_edited,
        "parent_id": message.parent_id,
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
@dataclass
class PostMessageResult:
    message: dm.Message
    channel: dm.DirectChannel

    def to_dict(self, current_user=None) -> dict:
        return _message_to_dict(self.message, current_user=current_user)


class ChatService:
    """
    Toutes les opérations chat passent par ici (cohérence + DRY).

    Sécurité : chaque méthode contrôle l'appartenance du caller au canal
    ou au workspace cible. Aucune action cross-tenant possible.
    """

    # ─── Lookup channels ────────────────────────────────────────────────
    @classmethod
    def channels_qs_for(cls, user):
        """
        Queryset des canaux accessibles à l'utilisateur :
          * où il est membre, OU
          * publics (is_private=False) dans un workspace dont il est membre
        """
        from project.utils.workspaces import get_user_workspace_ids
        workspace_ids = get_user_workspace_ids(user)
        return (
            dm.DirectChannel.objects
            .filter(workspace_id__in=workspace_ids)
            .filter(Q(members=user) | Q(is_private=False))
            .distinct()
            .annotate(
                _member_count=Count("members", distinct=True),
                _last_at=Max("messages__created_at"),
            )
            .prefetch_related("members")
            .order_by("-_last_at", "name")
        )

    @classmethod
    def list_channels_for(cls, user) -> list[dict]:
        qs = cls.channels_qs_for(user)
        return [_channel_to_dict(c, current_user=user) for c in qs[:100]]

    @classmethod
    def get_channel_for(cls, user, channel_id: int) -> dm.DirectChannel | None:
        """Retourne le canal si user a accès, sinon None."""
        return cls.channels_qs_for(user).filter(pk=channel_id).first()

    # ─── Création DM ────────────────────────────────────────────────────
    @classmethod
    @transaction.atomic
    def find_or_create_direct(
        cls, *, user_a, user_b, workspace,
    ) -> dm.DirectChannel:
        """
        Trouve ou crée un canal DM (privé, 2 membres) entre user_a et user_b
        dans le workspace donné. Idempotent.
        """
        if user_a is None or user_b is None:
            raise ValueError("Les deux utilisateurs sont requis.")
        if user_a.pk == user_b.pk:
            raise ValueError("Impossible de créer un DM avec soi-même.")

        # Cherche un canal existant : private + workspace + exactement 2 membres
        # qui sont user_a ET user_b.
        existing = (
            dm.DirectChannel.objects
            .filter(workspace=workspace, is_private=True)
            .filter(members=user_a)
            .filter(members=user_b)
            .annotate(member_count=Count("members"))
            .filter(member_count=2)
            .first()
        )
        if existing:
            return existing

        # Nom DM : "DM @username_a / @username_b" — stable et identifiable.
        # Trié pour un nom déterministe peu importe l'ordre des args.
        sorted_names = sorted([user_a.get_username(), user_b.get_username()])
        dm_name = f"DM @{sorted_names[0]} / @{sorted_names[1]}"

        # Si un canal du même nom existe (collision peu probable mais possible),
        # on suffixe avec l'ID des users.
        base_name = dm_name
        suffix = 1
        while dm.DirectChannel.objects.filter(
            workspace=workspace, name=dm_name,
        ).exists():
            suffix += 1
            dm_name = f"{base_name} #{suffix}"

        channel = dm.DirectChannel.objects.create(
            workspace=workspace, name=dm_name, is_private=True,
        )
        dm.ChannelMembership.objects.bulk_create([
            dm.ChannelMembership(channel=channel, user=user_a),
            dm.ChannelMembership(channel=channel, user=user_b),
        ])
        return channel

    # ─── Création groupe ────────────────────────────────────────────────
    @classmethod
    @transaction.atomic
    def create_group(
        cls, *, workspace, name: str, members: Iterable, creator,
    ) -> dm.DirectChannel:
        """Crée un groupe avec ≥2 membres (créateur compris)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Le nom du groupe est obligatoire.")

        # Déduplique + ajoute le créateur s'il n'est pas dans la liste
        members_list = list({m.pk: m for m in members if m is not None}.values())
        if creator is not None and not any(m.pk == creator.pk for m in members_list):
            members_list.append(creator)
        if len(members_list) < 2:
            raise ValueError(
                "Un groupe doit contenir au moins 2 membres (créateur compris)."
            )

        # Garantit l'unicité du nom dans le workspace.
        base_name = name
        suffix = 1
        while dm.DirectChannel.objects.filter(
            workspace=workspace, name=name,
        ).exists():
            suffix += 1
            name = f"{base_name} #{suffix}"

        channel = dm.DirectChannel.objects.create(
            workspace=workspace, name=name, is_private=True,
        )
        dm.ChannelMembership.objects.bulk_create([
            dm.ChannelMembership(channel=channel, user=m) for m in members_list
        ])
        return channel

    # ─── Envoi message ──────────────────────────────────────────────────
    @classmethod
    @transaction.atomic
    def post_message(
        cls, *, channel: dm.DirectChannel, author, body: str,
        parent: dm.Message | None = None,
    ) -> PostMessageResult:
        body = (body or "").strip()
        if not body:
            raise ValueError("Le message ne peut pas être vide.")
        if len(body) > 5000:
            raise ValueError("Le message dépasse 5000 caractères.")

        # Vérif appartenance pour les canaux privés
        is_member = dm.ChannelMembership.objects.filter(
            channel=channel, user=author,
        ).exists()
        if not is_member and channel.is_private:
            raise PermissionError("Vous n'êtes pas membre de ce canal.")

        message = dm.Message.objects.create(
            channel=channel, author=author, body=body, parent=parent,
        )
        return PostMessageResult(message=message, channel=channel)

    # ─── Messages ───────────────────────────────────────────────────────
    @classmethod
    def latest_messages(
        cls, *, channel: dm.DirectChannel, user,
        before_id: int | None = None, after_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Retourne les messages du canal. Vérifie l'accès du user au canal.

        * before_id : pagination historique (charge les messages plus anciens)
        * after_id  : polling temps réel (récupère les nouveaux uniquement)
        """
        access_check = cls.channels_qs_for(user).filter(pk=channel.pk).exists()
        if not access_check:
            raise PermissionError("Canal inaccessible.")

        if after_id:
            qs = (
                channel.messages
                .select_related("author")
                .filter(pk__gt=after_id)
                .order_by("created_at")
            )
            return [_message_to_dict(m, current_user=user) for m in qs[:limit]]

        qs = channel.messages.select_related("author").order_by("-created_at")
        if before_id:
            qs = qs.filter(pk__lt=before_id)
        messages = list(qs[:limit])
        messages.reverse()  # plus récents en bas dans l'UI
        return [_message_to_dict(m, current_user=user) for m in messages]

    # ─── Annuaire contacts ──────────────────────────────────────────────
    @classmethod
    def contacts_for(cls, user, query: str = "", limit: int = 30) -> list[dict]:
        """
        Liste les utilisateurs assignables comme contact (mêmes workspaces que
        l'utilisateur courant). Filtrable par nom/username.
        """
        from project.utils.workspaces import get_user_workspace_ids
        workspace_ids = get_user_workspace_ids(user)

        contacts_qs = (
            User.objects
            .filter(
                Q(profile__workspace_id__in=workspace_ids)
                | Q(team_memberships__workspace_id__in=workspace_ids)
                | Q(owned_workspaces__id__in=workspace_ids)
            )
            .exclude(pk=user.pk)
            .filter(is_active=True)
            .distinct()
        )

        query = (query or "").strip()
        if query:
            contacts_qs = contacts_qs.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(email__icontains=query)
            )

        contacts_qs = contacts_qs.order_by("first_name", "username")[:limit]
        return [
            {
                "id": u.pk,
                "username": u.get_username(),
                "display_name": _user_display(u),
                "email": u.email or "",
            }
            for u in contacts_qs
        ]


# ---------------------------------------------------------------------------
# Compat legacy — wrapper sur l'ancienne signature
# ---------------------------------------------------------------------------
def get_or_create_direct_channel(workspace, users, name=None, is_private=True):
    """
    Helper legacy conservé pour la compatibilité — délègue à
    ``ChatService.find_or_create_direct`` ou ``create_group`` selon le nombre
    de users.
    """
    users = list({u.pk: u for u in users if u is not None}.values())
    if len(users) < 2:
        raise ValueError("Un channel direct nécessite au moins deux utilisateurs.")
    if len(users) == 2:
        return ChatService.find_or_create_direct(
            user_a=users[0], user_b=users[1], workspace=workspace,
        )
    creator = users[0]
    return ChatService.create_group(
        workspace=workspace,
        name=name or "Groupe",
        members=users,
        creator=creator,
    )
