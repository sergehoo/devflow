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

from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count, DateTimeField, IntegerField, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

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
      * unread_count : nombre de messages postés par d'AUTRES après le
        last_read_at de la membership du current_user (0 si NULL=jamais lu
        ET aucun message ; sinon nb messages d'autres)
      * other_user_id : pour les DM, l'ID de l'autre membre (utile pour
        regarder sa présence côté front)
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

    # ── unread_count : messages d'AUTRES posté après mon last_read_at ──
    unread_count = 0
    if current_user is not None:
        membership = (
            channel.memberships
            .filter(user_id=current_user.pk)
            .only("last_read_at")
            .first()
        )
        if membership:
            qs = channel.messages.exclude(author_id=current_user.pk)
            if membership.last_read_at:
                qs = qs.filter(created_at__gt=membership.last_read_at)
            unread_count = qs.count()
        else:
            # Pas de membership directe (canal public) → tous les messages
            # d'autres sont "non lus" pour l'UI.
            unread_count = channel.messages.exclude(
                author_id=current_user.pk,
            ).count()

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
        "unread_count": unread_count,
        "other_user_id": (other.pk if (is_dm and other) else None),
    }


REACTION_EMOJIS = ("👍", "❤️", "😂", "😮", "😢", "🎉", "🙏", "🔥")
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _reactions_summary(message: dm.Message, current_user=None) -> list[dict]:
    summary: dict[str, dict] = {}
    for reaction in message.reactions.all():
        row = summary.setdefault(reaction.emoji, {"emoji": reaction.emoji, "count": 0, "mine": False})
        row["count"] += 1
        if current_user is not None and reaction.user_id == current_user.pk:
            row["mine"] = True
    return list(summary.values())


def _message_to_dict(message: dm.Message, *, current_user=None) -> dict:
    author_name = _user_display(message.author)
    return {
        "id": message.pk,
        "channel_id": message.channel_id,
        "author_id": message.author_id,
        "author_name": author_name,
        "author": author_name,  # compat ancien front WebSocket
        "author_username": message.author.get_username() if message.author else "",
        "is_self": bool(current_user and message.author_id == current_user.pk),
        "body": message.body,
        "is_edited": message.is_edited,
        "parent_id": message.parent_id,
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "attachments": [
            {
                "id": a.pk,
                "name": a.name or a.file.name.rsplit("/", 1)[-1],
                "url": a.file.url,
                "size": a.size,
                "mime_type": a.mime_type,
                "is_image": (a.mime_type or "").startswith("image/"),
            }
            for a in message.attachments.all()
        ],
        "reactions": _reactions_summary(message, current_user),
    }


def _broadcast(channel_id: int, event: dict) -> None:
    """Diffuse un événement aux WebSocket ouverts sur la conversation (best effort)."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(f"chat_channel_{channel_id}", event)
    except Exception:  # Redis indisponible : le polling REST prend le relais
        logger.debug("chat broadcast failed for channel %s", channel_id, exc_info=True)


def dm_key_for(user_a, user_b) -> str:
    low, high = sorted((user_a.pk, user_b.pk))
    return f"{low}:{high}"


def _unique_channel_name(workspace, base: str) -> str:
    base = base[:110]
    name, suffix = base, 1
    while dm.DirectChannel.objects.filter(workspace=workspace, name=name).exists():
        suffix += 1
        name = f"{base} #{suffix}"
    return name


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
    def find_or_create_direct(
        cls, *, user_a, user_b, workspace,
    ) -> dm.DirectChannel:
        """
        Conversation privée unique par paire d'utilisateurs et workspace
        (contrainte DB ``uniq_chat_dm_pair``). Idempotent, sûr en concurrence.
        """
        from project.utils.workspaces import users_in_workspaces

        if user_a is None or user_b is None:
            raise ValueError("Les deux utilisateurs sont requis.")
        if user_a.pk == user_b.pk:
            raise ValueError("Impossible de créer un DM avec soi-même.")
        allowed = set(users_in_workspaces([workspace.pk]).filter(pk__in=[user_a.pk, user_b.pk])
                      .values_list("pk", flat=True))
        if allowed != {user_a.pk, user_b.pk}:
            raise ValueError("Les deux utilisateurs doivent appartenir au workspace.")

        key = dm_key_for(user_a, user_b)
        channel = dm.DirectChannel.objects.filter(workspace=workspace, dm_key=key).first()
        if channel is None:
            names = sorted([user_a.get_username(), user_b.get_username()])
            try:
                with transaction.atomic():
                    channel = dm.DirectChannel.objects.create(
                        workspace=workspace, is_private=True,
                        kind=dm.DirectChannel.Kind.DM, dm_key=key,
                        name=_unique_channel_name(workspace, f"DM @{names[0]} / @{names[1]}"),
                    )
            except IntegrityError:
                channel = dm.DirectChannel.objects.get(workspace=workspace, dm_key=key)
        dm.ChannelMembership.objects.bulk_create(
            [dm.ChannelMembership(channel=channel, user=u) for u in (user_a, user_b)],
            ignore_conflicts=True,
        )
        return channel

    # ─── Conversations automatiques Équipe / Projet ──────────────────────
    @classmethod
    def _sync_group_channel(cls, *, workspace, kind, title, member_ids, team=None, project=None):
        lookup = {"team": team} if team is not None else {"project": project}
        channel = dm.DirectChannel.objects.filter(**lookup).first()
        if channel is None:
            try:
                with transaction.atomic():
                    channel = dm.DirectChannel.objects.create(
                        workspace=workspace, kind=kind, is_private=True,
                        name=_unique_channel_name(workspace, title), **lookup,
                    )
            except IntegrityError:
                channel = dm.DirectChannel.objects.get(**lookup)
        member_ids = set(
            User.objects.filter(pk__in=member_ids, is_active=True).values_list("pk", flat=True)
        )
        current = set(channel.memberships.values_list("user_id", flat=True))
        if member_ids - current:
            dm.ChannelMembership.objects.bulk_create(
                [dm.ChannelMembership(channel=channel, user_id=uid) for uid in member_ids - current],
                ignore_conflicts=True,
            )
        if current - member_ids:
            channel.memberships.filter(user_id__in=current - member_ids).delete()
        return channel

    @classmethod
    def sync_team_channel(cls, team) -> dm.DirectChannel:
        member_ids = set(
            dm.TeamMembership.objects.filter(team=team)
            .exclude(status=dm.TeamMembership.Status.INACTIVE)
            .values_list("user_id", flat=True)
        )
        if team.lead_id:
            member_ids.add(team.lead_id)
        return cls._sync_group_channel(
            workspace=team.workspace, kind=dm.DirectChannel.Kind.TEAM,
            title=f"Équipe · {team.name}", member_ids=member_ids, team=team,
        )

    @classmethod
    def sync_project_channel(cls, project) -> dm.DirectChannel:
        member_ids = set(dm.ProjectMember.objects.filter(project=project).values_list("user_id", flat=True))
        member_ids.update(uid for uid in (project.owner_id, project.product_manager_id) if uid)
        return cls._sync_group_channel(
            workspace=project.workspace, kind=dm.DirectChannel.Kind.PROJECT,
            title=f"Projet · {project.name}", member_ids=member_ids, project=project,
        )

    @classmethod
    def ensure_group_channels_for(cls, user, workspace, *, force=False) -> None:
        """Rattrapage idempotent (équipes/projets antérieurs), au plus toutes les 10 min."""
        if not force and not cache.add(f"chat:group-sync:{workspace.pk}:{user.pk}", 1, 600):
            return
        teams = dm.Team.objects.filter(
            Q(memberships__user=user) | Q(lead=user), workspace=workspace,
        ).distinct()
        for team in teams:
            cls.sync_team_channel(team)
        projects = dm.Project.objects.filter(
            Q(members__user=user) | Q(owner=user) | Q(product_manager=user), workspace=workspace,
        ).distinct()
        for project in projects:
            cls.sync_project_channel(project)

    @classmethod
    def conversation_dict(cls, user, channel) -> dict | None:
        return next(
            (c for c in cls.conversations_for(user, channel.workspace) if c["id"] == channel.pk), None,
        )

    # ─── Liste Messenger ─────────────────────────────────────────────────
    @classmethod
    def conversations_for(cls, user, workspace, query: str = "") -> list[dict]:
        """Conversations dont l'utilisateur est participant, triées par activité."""
        unread = cls.unread_counts_for(user)["by_channel"]
        last = dm.Message.objects.filter(channel=OuterRef("pk")).order_by("-created_at")
        mine = dm.ChannelMembership.objects.filter(channel=OuterRef("pk"), user=user)
        channels = list(
            dm.DirectChannel.objects.filter(workspace=workspace, memberships__user=user)
            .select_related("team", "project")
            .annotate(
                last_body=Subquery(last.values("body")[:1]),
                last_at=Subquery(last.values("created_at")[:1]),
                last_author_id=Subquery(last.values("author_id")[:1]),
                is_muted=Subquery(mine.values("is_muted")[:1]),
                member_count=Count("memberships", distinct=True),
            )
        )
        dm_ids = [c.pk for c in channels if c.kind == dm.DirectChannel.Kind.DM]
        others = {
            m.channel_id: m.user
            for m in dm.ChannelMembership.objects.filter(channel_id__in=dm_ids)
            .exclude(user=user).select_related("user")
        }
        result = []
        for c in channels:
            other = others.get(c.pk)
            if c.kind == dm.DirectChannel.Kind.DM:
                title, section = (_user_display(other) if other else c.name), "direct"
            elif c.kind == dm.DirectChannel.Kind.TEAM:
                title, section = (c.team.name if c.team_id else c.name), "teams"
            elif c.kind == dm.DirectChannel.Kind.PROJECT:
                title, section = (c.project.name if c.project_id else c.name), "projects"
            else:
                title, section = c.name, "groups"
            result.append({
                "id": c.pk,
                "kind": c.kind,
                "section": section,
                "title": title,
                "other_user_id": other.pk if other else None,
                "member_count": c.member_count,
                "last_message_preview": (c.last_body or "")[:120],
                "last_message_at": c.last_at.isoformat() if c.last_at else None,
                "last_author_is_me": c.last_author_id == user.pk,
                "unread_count": unread.get(c.pk, 0),
                "is_muted": bool(c.is_muted),
            })
        query = (query or "").strip().lower()
        if query:
            result = [r for r in result if query in r["title"].lower()]
        result.sort(key=lambda r: r["last_message_at"] or "", reverse=True)
        return result

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
    def post_message(
        cls, *, channel: dm.DirectChannel, author, body: str,
        parent: dm.Message | None = None, files=(), client_id=None,
    ) -> PostMessageResult:
        body = (body or "").strip()
        files = list(files or [])
        if not body and not files:
            raise ValueError("Le message ne peut pas être vide.")
        if len(body) > 5000:
            raise ValueError("Le message dépasse 5000 caractères.")
        if len(files) > MAX_ATTACHMENTS:
            raise ValueError(f"{MAX_ATTACHMENTS} pièces jointes maximum par message.")
        for f in files:
            if f.size > MAX_ATTACHMENT_BYTES:
                raise ValueError(f"« {f.name} » dépasse {MAX_ATTACHMENT_BYTES // (1024 * 1024)} Mo.")

        # Participant obligatoire pour les conversations privées
        is_member = dm.ChannelMembership.objects.filter(channel=channel, user=author).exists()
        if not is_member and channel.is_private:
            raise PermissionError("Vous n'êtes pas membre de ce canal.")
        if parent is not None and parent.channel_id != channel.pk:
            parent = None

        with transaction.atomic():
            message = dm.Message.objects.create(
                channel=channel, author=author, body=body or "📎", parent=parent,
            )
            for f in files:
                dm.MessageAttachment.objects.create(
                    message=message, file=f, name=f.name[:255],
                    mime_type=(getattr(f, "content_type", "") or "")[:120], size=f.size,
                )
            dm.ChannelMembership.objects.filter(channel=channel, user=author).update(
                last_read_at=message.created_at,
            )
            recipients = (
                channel.memberships.exclude(user=author).filter(is_muted=False)
                .values_list("user_id", flat=True)
            )
            title = (
                f"{_user_display(author)}" if channel.kind == dm.DirectChannel.Kind.DM
                else f"{_user_display(author)} · {channel.team.name if channel.team_id else channel.project.name if channel.project_id else channel.name}"
            )
            dm.Notification.objects.bulk_create([
                dm.Notification(
                    recipient_id=uid, workspace=channel.workspace,
                    notification_type=dm.Notification.NotificationType.MESSAGE,
                    title=title[:180], body=(body or "Pièce jointe")[:180],
                    url=f"/chat/?channel={channel.pk}",
                    metadata={"channel_id": channel.pk, "message_id": message.pk},
                )
                for uid in recipients
            ])

        message = (
            dm.Message.objects.select_related("author")
            .prefetch_related("attachments", "reactions").get(pk=message.pk)
        )
        payload = _message_to_dict(message)
        payload["client_id"] = client_id
        _broadcast(channel.pk, {"type": "chat.message", "message": payload})
        return PostMessageResult(message=message, channel=channel)

    # ─── Réactions ──────────────────────────────────────────────────────
    @classmethod
    def toggle_reaction(cls, *, user, message: dm.Message, emoji: str) -> list[dict]:
        if emoji not in REACTION_EMOJIS:
            raise ValueError("Réaction non supportée.")
        channel = message.channel
        if not dm.ChannelMembership.objects.filter(channel=channel, user=user).exists():
            raise PermissionError("Vous n'êtes pas participant de cette conversation.")
        existing = dm.Reaction.objects.filter(message=message, user=user, emoji=emoji)
        if existing.exists():
            existing.delete()
        else:
            dm.Reaction.objects.create(message=message, user=user, emoji=emoji)
        summary = _reactions_summary(dm.Message.objects.prefetch_related("reactions").get(pk=message.pk))
        _broadcast(channel.pk, {
            "type": "chat.event", "event": "reaction",
            "data": {"message_id": message.pk, "reactions": summary},
        })
        return _reactions_summary(
            dm.Message.objects.prefetch_related("reactions").get(pk=message.pk), current_user=user,
        )

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
                .prefetch_related("attachments", "reactions")
                .filter(pk__gt=after_id)
                .order_by("created_at")
            )
            return [_message_to_dict(m, current_user=user) for m in qs[:limit]]

        qs = (
            channel.messages.select_related("author")
            .prefetch_related("attachments", "reactions").order_by("-created_at")
        )
        if before_id:
            qs = qs.filter(pk__lt=before_id)
        messages = list(qs[:limit])
        messages.reverse()  # plus récents en bas dans l'UI
        return [_message_to_dict(m, current_user=user) for m in messages]

    # ─── Annuaire contacts ──────────────────────────────────────────────
    @classmethod
    def contacts_for(cls, user, query: str = "", limit: int = 30, workspace=None) -> list[dict]:
        """
        Liste les utilisateurs assignables comme contact (mêmes workspaces que
        l'utilisateur courant). Filtrable par nom/username.

        Enrichit chaque contact avec son statut de présence (online/idle/offline)
        et son ``inactive_minutes`` — calculés via ``PresenceService`` (cache Redis).
        """
        from project.utils.workspaces import get_user_workspace_ids
        workspace_ids = get_user_workspace_ids(user)
        if workspace is not None:
            workspace_ids = {workspace.pk} & set(workspace_ids)

        contacts_qs = (
            User.objects
            .filter(
                Q(profile__workspace_id__in=workspace_ids)
                | Q(devflow_memberships__workspace_id__in=workspace_ids)
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
        users = list(contacts_qs)

        # Lookup batch de la présence (1 round-trip Redis).
        from project.services.presence import PresenceService
        presence = PresenceService.get_many([u.pk for u in users])

        return [
            {
                "id": u.pk,
                "username": u.get_username(),
                "display_name": _user_display(u),
                "email": u.email or "",
                "presence": (
                    presence.get(u.pk).to_dict()
                    if presence.get(u.pk) else
                    {"status": "offline", "inactive_minutes": None}
                ),
            }
            for u in users
        ]

    # ─── Mark-as-read ───────────────────────────────────────────────────
    @classmethod
    def mark_read(cls, *, user, channel: dm.DirectChannel) -> dict:
        """
        Met à jour ``ChannelMembership.last_read_at`` à maintenant pour ce
        user sur ce canal. Idempotent.

        Retourne dict avec le nouvel unread_count (0 après mark-read).

        Si pas de membership (canal public), on en crée une — l'user
        a "rejoint" implicitement le canal en y entrant.
        """
        now = timezone.now()
        membership, _created = dm.ChannelMembership.objects.get_or_create(
            channel=channel, user=user,
            defaults={"last_read_at": now},
        )
        membership.last_read_at = now
        membership.save(update_fields=["last_read_at", "updated_at"])
        _broadcast(channel.pk, {
            "type": "chat.event", "event": "read",
            "data": {"user_id": user.pk, "last_read_at": now.isoformat()},
        })
        return {
            "channel_id": channel.pk,
            "last_read_at": now.isoformat(),
            "unread_count": 0,
        }

    # ─── Unread counts ──────────────────────────────────────────────────
    @classmethod
    def unread_counts_for(cls, user) -> dict:
        """
        ``{"total": int, "by_channel": {channel_id: count}}`` — en une requête :
        messages d'autres auteurs postérieurs au last_read_at, sur les
        conversations dont l'utilisateur est participant (tenants autorisés).
        """
        from project.utils.workspaces import get_user_workspace_ids

        epoch = Value(datetime(1970, 1, 1, tzinfo=dt_timezone.utc), output_field=DateTimeField())
        unread_sq = (
            dm.Message.objects.filter(
                channel_id=OuterRef("channel_id"), created_at__gt=OuterRef("read_mark"),
            )
            .exclude(author_id=user.pk)
            .order_by().values("channel_id").annotate(c=Count("id")).values("c")
        )
        rows = (
            dm.ChannelMembership.objects.filter(
                user=user, channel__workspace_id__in=get_user_workspace_ids(user),
            )
            .annotate(read_mark=Coalesce("last_read_at", epoch))
            .annotate(unread=Coalesce(Subquery(unread_sq, output_field=IntegerField()), 0))
            .filter(unread__gt=0)
            .values_list("channel_id", "unread")
        )
        by_channel = dict(rows)
        return {"total": sum(by_channel.values()), "by_channel": by_channel}

    # ─── Membres canal (avec présence) ──────────────────────────────────
    @classmethod
    def members_for_channel(
        cls, *, user, channel: dm.DirectChannel,
    ) -> list[dict]:
        """
        Liste les membres d'un canal, enrichis de leur présence.

        Vérifie l'accès du caller au canal (sinon PermissionError).
        """
        if not cls.channels_qs_for(user).filter(pk=channel.pk).exists():
            raise PermissionError("Canal inaccessible.")

        memberships = (
            channel.memberships
            .select_related("user")
            .order_by("user__first_name", "user__username")
        )
        members = [m for m in memberships if m.user_id]

        from project.services.presence import PresenceService
        presence = PresenceService.get_many([m.user_id for m in members])

        return [
            {
                "user_id": m.user_id,
                "username": m.user.get_username(),
                "display_name": _user_display(m.user),
                "email": m.user.email or "",
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                "is_self": m.user_id == user.pk,
                "presence": (
                    presence.get(m.user_id).to_dict()
                    if presence.get(m.user_id) else
                    {"status": "offline", "inactive_minutes": None}
                ),
            }
            for m in members
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
