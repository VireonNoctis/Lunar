from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


log = logging.getLogger("lunar.modmail")


# ============================================================
# CONFIG DEFAULTS
# ============================================================

DEFAULT_GUILD_ID = 0
DEFAULT_CATEGORY_ID = 0
DEFAULT_LOG_CHANNEL_ID = 0
DEFAULT_STAFF_ROLE_ID = 0

CONFIG_KEY = "modmail:config"
BLOCKED_KEY = "modmail:blocked"

TOPIC_PREFIX = "modmail:user:"
CLOSED_TOPIC_PREFIX = "modmail:closed:user:"

CHANNEL_PREFIX = "ticket-"
CLOSED_CHANNEL_PREFIX = "closed-"

TRANSCRIPT_LIMIT = 1000
MAX_MESSAGE_LENGTH = 1900
MAX_TICKET_NAME_LENGTH = 90


# ============================================================
# DATA MODELS
# ============================================================

@dataclass(slots=True)
class ModmailConfig:

    guild_id: int = DEFAULT_GUILD_ID
    category_id: int = DEFAULT_CATEGORY_ID
    log_channel_id: int = DEFAULT_LOG_CHANNEL_ID
    staff_role_id: int = DEFAULT_STAFF_ROLE_ID


# ============================================================
# PERSISTENT TICKET VIEW
# ============================================================

class TicketControls(
    discord.ui.View
):

    def __init__(
        self,
        cog: "ModmailIntegration",
    ) -> None:

        super().__init__(
            timeout=None
        )

        self.cog = cog

    # ========================================================
    # CLOSE
    # ========================================================

    @discord.ui.button(
        label="Close",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="modmail:close",
        row=0,
    )
    async def close_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_control_close(
            interaction
        )

    # ========================================================
    # TRANSCRIPT
    # ========================================================

    @discord.ui.button(
        label="Transcript",
        emoji="📄",
        style=discord.ButtonStyle.secondary,
        custom_id="modmail:transcript",
        row=0,
    )
    async def transcript_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_control_transcript(
            interaction
        )

    # ========================================================
    # BLOCK
    # ========================================================

    @discord.ui.button(
        label="Block User",
        emoji="🚫",
        style=discord.ButtonStyle.danger,
        custom_id="modmail:block",
        row=0,
    )
    async def block_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_control_block(
            interaction
        )


# ============================================================
# MODMAIL INTEGRATION
# ============================================================

class ModmailIntegration(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        self.config = ModmailConfig()

        self.config_loaded = False

        self.blocked_users: set[int] = set()

        self.loaded_tickets: dict[
            int,
            int,
        ] = {}

        self.ticket_locks: dict[
            int,
            asyncio.Lock,
        ] = {}

    # ========================================================
    # LIFECYCLE
    # ========================================================

    async def cog_load(
        self,
    ) -> None:

        await self.load_state()

        self.register_persistent_view()

        self.rebuild_ticket_cache()

    async def cog_unload(
        self,
    ) -> None:

        self.loaded_tickets.clear()

        self.ticket_locks.clear()

    def register_persistent_view(
        self,
    ) -> None:

        try:

            self.bot.add_view(
                TicketControls(self)
            )

        except Exception:

            log.exception(
                "Failed to register persistent Modmail view."
            )

    # ========================================================
    # DATABASE STATE
    # ========================================================

    async def load_state(
        self,
    ) -> None:

        self.config = ModmailConfig()

        self.blocked_users = set()

        if db.variables is None:

            self.config_loaded = True

            return

        try:

            config_row = await db.variables.get(
                CONFIG_KEY
            )

            if config_row is not None:

                raw = getattr(
                    config_row,
                    "string_value",
                    None,
                )

                if raw:

                    data = json.loads(raw)

                    self.config = ModmailConfig(
                        guild_id=int(
                            data.get(
                                "guild_id",
                                0,
                            )
                        ),
                        category_id=int(
                            data.get(
                                "category_id",
                                0,
                            )
                        ),
                        log_channel_id=int(
                            data.get(
                                "log_channel_id",
                                0,
                            )
                        ),
                        staff_role_id=int(
                            data.get(
                                "staff_role_id",
                                0,
                            )
                        ),
                    )

            blocked_row = await db.variables.get(
                BLOCKED_KEY
            )

            if blocked_row is not None:

                raw_blocked = getattr(
                    blocked_row,
                    "string_value",
                    None,
                )

                if raw_blocked:

                    values = json.loads(
                        raw_blocked
                    )

                    self.blocked_users = {
                        int(value)
                        for value in values
                    }

        except Exception:

            log.exception(
                "Failed to load Modmail state."
            )

        self.config_loaded = True

    async def save_config(
        self,
        config: ModmailConfig,
    ) -> None:

        self.config = config

        if db.variables is None:
            return

        await db.variables.set(
            CONFIG_KEY,
            string_value=json.dumps(
                {
                    "guild_id": config.guild_id,
                    "category_id": config.category_id,
                    "log_channel_id": config.log_channel_id,
                    "staff_role_id": config.staff_role_id,
                },
                separators=(
                    ",",
                    ":",
                ),
            ),
            metadata={
                "system": "modmail",
                "updated_at": self.utcnow().isoformat(),
            },
        )

    async def save_blocked_users(
        self,
    ) -> None:

        if db.variables is None:
            return

        await db.variables.set(
            BLOCKED_KEY,
            string_value=json.dumps(
                sorted(
                    self.blocked_users
                ),
                separators=(
                    ",",
                    ":",
                ),
            ),
            metadata={
                "system": "modmail",
                "updated_at": self.utcnow().isoformat(),
            },
        )

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def utcnow() -> datetime:

        return datetime.now(
            timezone.utc
        )

    def configured(
        self,
    ) -> bool:

        return all(
            (
                self.config.guild_id,
                self.config.category_id,
                self.config.log_channel_id,
                self.config.staff_role_id,
            )
        )

    def get_ticket_lock(
        self,
        user_id: int,
    ) -> asyncio.Lock:

        lock = self.ticket_locks.get(
            user_id
        )

        if lock is None:

            lock = asyncio.Lock()

            self.ticket_locks[
                user_id
            ] = lock

        return lock

    def normalize_channel_name(
        self,
        user: discord.abc.User,
        closed: bool = False,
    ) -> str:

        base = user.name.lower()

        base = re.sub(
            r"[^a-z0-9-]+",
            "-",
            base,
        ).strip("-")

        if not base:

            base = "user"

        base = base[:60]

        name = (
            f"{base}-{user.id}"
        )

        if closed:

            name = (
                f"{CLOSED_CHANNEL_PREFIX}"
                f"{name}"
            )

        else:

            name = (
                f"{CHANNEL_PREFIX}"
                f"{name}"
            )

        return name[
            :MAX_TICKET_NAME_LENGTH
        ]

    @staticmethod
    def parse_user_id_from_topic(
        topic: Optional[str],
    ) -> Optional[int]:

        if not topic:
            return None

        for prefix in (
            TOPIC_PREFIX,
            CLOSED_TOPIC_PREFIX,
        ):

            if topic.startswith(
                prefix
            ):

                raw = topic[
                    len(prefix):
                ].strip()

                try:

                    return int(raw)

                except ValueError:

                    return None

        return None

    @staticmethod
    def is_closed_topic(
        topic: Optional[str],
    ) -> bool:

        return bool(
            topic
            and topic.startswith(
                CLOSED_TOPIC_PREFIX
            )
        )

    def rebuild_ticket_cache(
        self,
    ) -> None:

        self.loaded_tickets.clear()

        if (
            not self.config.guild_id
            or not self.config.category_id
        ):

            return

        guild = self.bot.get_guild(
            self.config.guild_id
        )

        if guild is None:
            return

        category = guild.get_channel(
            self.config.category_id
        )

        if not isinstance(
            category,
            discord.CategoryChannel,
        ):

            return

        for channel in category.channels:

            if not isinstance(
                channel,
                discord.TextChannel,
            ):

                continue

            user_id = (
                self.parse_user_id_from_topic(
                    channel.topic
                )
            )

            if user_id is None:
                continue

            if self.is_closed_topic(
                channel.topic
            ):

                continue

            self.loaded_tickets[
                user_id
            ] = channel.id

    def get_active_ticket(
        self,
        user_id: int,
    ) -> Optional[
        discord.TextChannel
    ]:

        channel_id = (
            self.loaded_tickets.get(
                user_id
            )
        )

        if channel_id:

            channel = self.bot.get_channel(
                channel_id
            )

            if isinstance(
                channel,
                discord.TextChannel,
            ):

                return channel

        guild = self.bot.get_guild(
            self.config.guild_id
        )

        if guild is None:
            return None

        category = guild.get_channel(
            self.config.category_id
        )

        if not isinstance(
            category,
            discord.CategoryChannel,
        ):

            return None

        for channel in category.channels:

            if not isinstance(
                channel,
                discord.TextChannel,
            ):

                continue

            if self.is_closed_topic(
                channel.topic
            ):

                continue

            if (
                self.parse_user_id_from_topic(
                    channel.topic
                )
                == user_id
            ):

                self.loaded_tickets[
                    user_id
                ] = channel.id

                return channel

        return None

    async def get_guild(
        self,
    ) -> Optional[discord.Guild]:

        if not self.config.guild_id:
            return None

        guild = self.bot.get_guild(
            self.config.guild_id
        )

        if guild is not None:
            return guild

        try:

            return await self.bot.fetch_guild(
                self.config.guild_id
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):

            return None

    async def get_log_channel(
        self,
    ) -> Optional[
        discord.TextChannel
    ]:

        if not self.config.log_channel_id:
            return None

        channel = self.bot.get_channel(
            self.config.log_channel_id
        )

        if isinstance(
            channel,
            discord.TextChannel,
        ):

            return channel

        try:

            channel = await self.bot.fetch_channel(
                self.config.log_channel_id
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):

            return None

        return (
            channel
            if isinstance(
                channel,
                discord.TextChannel,
            )
            else None
        )

    def member_is_staff(
        self,
        member: discord.Member,
    ) -> bool:

        if member.guild_permissions.manage_guild:

            return True

        if not self.config.staff_role_id:

            return False

        return (
            member.get_role(
                self.config.staff_role_id
            )
            is not None
        )

    async def ensure_staff(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if not isinstance(
            interaction.user,
            discord.Member,
        ):

            await self.safe_interaction_error(
                interaction,
                (
                    f"{EMOJI['denied']} "
                    "This can only be used in a server."
                ),
            )

            return False

        if not self.member_is_staff(
            interaction.user
        ):

            await self.safe_interaction_error(
                interaction,
                (
                    f"{EMOJI['denied']} "
                    "You are not authorized to manage Modmail."
                ),
            )

            return False

        return True

    async def safe_interaction_error(
        self,
        interaction: discord.Interaction,
        content: str,
    ) -> None:

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    content,
                    ephemeral=True,
                )

            else:

                await interaction.response.send_message(
                    content,
                    ephemeral=True,
                )

        except discord.HTTPException:

            pass

    # ========================================================
    # CHANNEL PERMISSIONS
    # ========================================================

    async def build_overwrites(
        self,
        guild: discord.Guild,
    ) -> dict[
        discord.abc.Snowflake,
        discord.PermissionOverwrite,
    ]:

        overwrites: dict[
            discord.abc.Snowflake,
            discord.PermissionOverwrite,
        ] = {}

        overwrites[
            guild.default_role
        ] = discord.PermissionOverwrite(
            view_channel=False,
        )

        me = guild.me

        if me is not None:

            overwrites[
                me
            ] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                manage_channels=True,
                manage_messages=True,
            )

        role = guild.get_role(
            self.config.staff_role_id
        )

        if role is not None:

            overwrites[
                role
            ] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
            )

        return overwrites

    # ========================================================
    # TICKET CREATION
    # ========================================================

    async def create_ticket(
        self,
        user: discord.User,
    ) -> Optional[
        discord.TextChannel
    ]:

        if user.id in self.blocked_users:

            try:

                await user.send(
                    embed=discord.Embed(
                        title="Modmail Unavailable",
                        description=(
                            f"{EMOJI['denied']} "
                            "You are currently blocked from using Modmail."
                        ),
                        color=discord.Color.red(),
                    )
                )

            except discord.HTTPException:

                pass

            return None

        if not self.configured():

            try:

                await user.send(
                    "Modmail is not configured yet. "
                    "Please try again later."
                )

            except discord.HTTPException:

                pass

            return None

        existing = self.get_active_ticket(
            user.id
        )

        if existing is not None:

            return existing

        guild = await self.get_guild()

        if guild is None:

            return None

        category = guild.get_channel(
            self.config.category_id
        )

        if not isinstance(
            category,
            discord.CategoryChannel,
        ):

            log.error(
                "Configured Modmail category %s is invalid.",
                self.config.category_id,
            )

            return None

        overwrites = await self.build_overwrites(
            guild
        )

        try:

            channel = (
                await guild.create_text_channel(
                    name=self.normalize_channel_name(
                        user
                    ),
                    category=category,
                    topic=(
                        f"{TOPIC_PREFIX}"
                        f"{user.id}"
                    ),
                    overwrites=overwrites,
                    reason=(
                        f"Modmail ticket for "
                        f"{user} ({user.id})"
                    ),
                )
            )

        except (
            discord.Forbidden,
            discord.HTTPException,
        ):

            log.exception(
                "Failed to create Modmail ticket for %s.",
                user.id,
            )

            return None

        self.loaded_tickets[
            user.id
        ] = channel.id

        embed = discord.Embed(
            title=(
                f"{EMOJI['moon']} "
                "Modmail Ticket"
            ),
            description=(
                f"A new Modmail conversation was opened for "
                f"**{user}** ({user.mention}).\n\n"
                "Messages sent by the user in DMs will appear here. "
                "Staff replies sent in this channel are forwarded to the user.\n\n"
                f"{EMOJI['staff']} "
                "Keep all replies relevant to the ticket."
            ),
            color=0x7C5CFF,
            timestamp=self.utcnow(),
        )

        embed.set_thumbnail(
            url=user.display_avatar.url
        )

        embed.set_footer(
            text=f"User ID: {user.id}"
        )

        try:

            await channel.send(
                embed=embed,
                view=TicketControls(self),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        except discord.HTTPException:

            log.exception(
                "Failed to send Modmail ticket header in %s.",
                channel.id,
            )

        log_channel = await self.get_log_channel()

        if log_channel is not None:

            try:

                await log_channel.send(
                    embed=discord.Embed(
                        title="Modmail Ticket Opened",
                        description=(
                            f"**User:** {user.mention}\n"
                            f"**Channel:** {channel.mention}\n"
                            f"**User ID:** `{user.id}`"
                        ),
                        color=discord.Color.green(),
                        timestamp=self.utcnow(),
                    ),
                    allowed_mentions=(
                        discord.AllowedMentions.none()
                    ),
                )

            except discord.HTTPException:

                pass

        try:

            await user.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['approved']} "
                        "Modmail Opened"
                    ),
                    description=(
                        "Your message has been sent to the "
                        "Lunar staff team.\n\n"
                        "Keep replying to this DM to continue "
                        "the conversation."
                    ),
                    color=0x7C5CFF,
                )
            )

        except discord.HTTPException:

            pass

        return channel

    # ========================================================
    # FORWARD DM TO STAFF
    # ========================================================

    async def forward_dm(
        self,
        message: discord.Message,
    ) -> None:

        user = message.author

        async with self.get_ticket_lock(
            user.id
        ):

            channel = self.get_active_ticket(
                user.id
            )

            if channel is None:

                channel = await self.create_ticket(
                    user  # type: ignore[arg-type]
                )

            if channel is None:

                return

            embed = discord.Embed(
                title="New Modmail Message",
                description=(
                    message.content[
                        :MAX_MESSAGE_LENGTH
                    ]
                    if message.content
                    else "*(No text content)*"
                ),
                color=0x7C5CFF,
                timestamp=message.created_at,
            )

            embed.set_author(
                name=str(user),
                icon_url=user.display_avatar.url,
            )

            embed.set_footer(
                text=(
                    f"User ID: {user.id} • DM"
                )
            )

            files: list[
                discord.File
            ] = []

            attachment_urls: list[
                str
            ] = []

            for attachment in message.attachments:

                try:

                    files.append(
                        await attachment.to_file(
                            use_cached=True
                        )
                    )

                except (
                    discord.HTTPException,
                    OSError,
                ):

                    attachment_urls.append(
                        attachment.url
                    )

            if attachment_urls:

                embed.add_field(
                    name="Attachments",
                    value=(
                        "\n".join(
                            attachment_urls
                        )[:1024]
                    ),
                    inline=False,
                )

            if message.stickers:

                embed.add_field(
                    name="Stickers",
                    value=(
                        "\n".join(
                            sticker.name
                            for sticker
                            in message.stickers
                        )[:1024]
                    ),
                    inline=False,
                )

            try:

                await channel.send(
                    embed=embed,
                    files=files,
                    allowed_mentions=(
                        discord.AllowedMentions.none()
                    ),
                )

            except (
                discord.Forbidden,
                discord.HTTPException,
            ):

                log.exception(
                    "Failed forwarding DM %s to ticket %s.",
                    message.id,
                    channel.id,
                )

    # ========================================================
    # FORWARD STAFF MESSAGE TO USER
    # ========================================================

    async def forward_staff_message(
        self,
        message: discord.Message,
    ) -> None:

        if not isinstance(
            message.channel,
            discord.TextChannel,
        ):

            return

        user_id = (
            self.parse_user_id_from_topic(
                message.channel.topic
            )
        )

        if user_id is None:

            return

        if self.is_closed_topic(
            message.channel.topic
        ):

            return

        if not isinstance(
            message.author,
            discord.Member,
        ):

            return

        if not self.member_is_staff(
            message.author
        ):

            return

        try:

            user = await self.bot.fetch_user(
                user_id
            )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):

            await message.channel.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['error']} "
                        "Delivery Failed"
                    ),
                    description=(
                        "I could not retrieve the Modmail user. "
                        "The ticket remains open."
                    ),
                    color=discord.Color.red(),
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

            return

        embed = discord.Embed(
            title="Lunar Staff",
            description=(
                message.content[
                    :MAX_MESSAGE_LENGTH
                ]
                if message.content
                else "*(Attachment / file)*"
            ),
            color=0x7C5CFF,
            timestamp=message.created_at,
        )

        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url,
        )

        embed.set_footer(
            text=(
                "Reply to this DM to continue "
                "the Modmail conversation."
            )
        )

        files: list[
            discord.File
        ] = []

        attachment_urls: list[
            str
        ] = []

        for attachment in message.attachments:

            try:

                files.append(
                    await attachment.to_file(
                        use_cached=True
                    )
                )

            except (
                discord.HTTPException,
                OSError,
            ):

                attachment_urls.append(
                    attachment.url
                )

        if attachment_urls:

            embed.add_field(
                name="Attachments",
                value=(
                    "\n".join(
                        attachment_urls
                    )[:1024]
                ),
                inline=False,
            )

        try:

            await user.send(
                embed=embed,
                files=files,
            )

        except discord.Forbidden:

            await message.channel.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['error']} "
                        "DMs Closed"
                    ),
                    description=(
                        "The user currently "
                        "cannot receive DMs."
                    ),
                    color=discord.Color.red(),
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        except discord.HTTPException:

            log.exception(
                "Failed delivering staff message "
                "to user %s.",
                user_id,
            )

    # ========================================================
    # CLOSE TICKET
    # ========================================================

    async def close_ticket(
        self,
        channel: discord.TextChannel,
        moderator: discord.Member,
        *,
        reason: str = "No reason provided.",
        notify_user: bool = True,
    ) -> Optional[int]:

        user_id = (
            self.parse_user_id_from_topic(
                channel.topic
            )
        )

        if user_id is None:

            return None

        async with self.get_ticket_lock(
            user_id
        ):

            topic = (
                f"{CLOSED_TOPIC_PREFIX}"
                f"{user_id}"
            )

            closed_name = channel.name

            if closed_name.startswith(
                CHANNEL_PREFIX
            ):

                closed_name = (
                    f"{CLOSED_CHANNEL_PREFIX}"
                    f"{closed_name[len(CHANNEL_PREFIX):]}"
                )

            try:

                await channel.edit(
                    name=closed_name[
                        :MAX_TICKET_NAME_LENGTH
                    ],
                    topic=topic,
                    reason=(
                        f"Modmail closed by "
                        f"{moderator}"
                    ),
                )

            except discord.HTTPException:

                try:

                    await channel.edit(
                        topic=topic,
                        reason=(
                            f"Modmail closed by "
                            f"{moderator}"
                        ),
                    )

                except discord.HTTPException:

                    pass

            guild = channel.guild

            role = guild.get_role(
                self.config.staff_role_id
            )

            if role is not None:

                try:

                    await channel.set_permissions(
                        role,
                        send_messages=False,
                    )

                except discord.HTTPException:

                    pass

            self.loaded_tickets.pop(
                user_id,
                None,
            )

            await channel.send(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['approved']} "
                        "Modmail Closed"
                    ),
                    description=(
                        f"This ticket was closed by "
                        f"{moderator.mention}.\n\n"
                        f"**Reason:** {reason[:1000]}"
                    ),
                    color=discord.Color.red(),
                    timestamp=self.utcnow(),
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

            if notify_user:

                try:

                    user = await self.bot.fetch_user(
                        user_id
                    )

                    await user.send(
                        embed=discord.Embed(
                            title=(
                                f"{EMOJI['approved']} "
                                "Modmail Closed"
                            ),
                            description=(
                                "Your Modmail ticket has been "
                                "closed by the Lunar staff team.\n\n"
                                "You can start a new ticket at "
                                "any time by sending another DM."
                            ),
                            color=discord.Color.red(),
                        )
                    )

                except (
                    discord.Forbidden,
                    discord.NotFound,
                    discord.HTTPException,
                ):

                    pass

            await self.log_action(
                title="Modmail Ticket Closed",
                description=(
                    f"**User ID:** `{user_id}`\n"
                    f"**Ticket:** {channel.mention}\n"
                    f"**Moderator:** {moderator.mention}\n"
                    f"**Reason:** {reason[:700]}"
                ),
                color=discord.Color.red(),
            )

            return user_id

    # ========================================================
    # REOPEN TICKET
    # ========================================================

    async def reopen_ticket(
        self,
        channel: discord.TextChannel,
        moderator: discord.Member,
    ) -> Optional[int]:

        user_id = (
            self.parse_user_id_from_topic(
                channel.topic
            )
        )

        if user_id is None:

            return None

        if not self.is_closed_topic(
            channel.topic
        ):

            return user_id

        try:

            user = await self.bot.fetch_user(
                user_id
            )

            new_name = (
                self.normalize_channel_name(
                    user,
                    closed=False,
                )
            )

        except discord.HTTPException:

            current_name = channel.name

            if current_name.startswith(
                CLOSED_CHANNEL_PREFIX
            ):

                new_name = (
                    current_name[
                        len(CLOSED_CHANNEL_PREFIX):
                    ]
                )

                new_name = (
                    f"{CHANNEL_PREFIX}"
                    f"{new_name}"
                )

            else:

                new_name = current_name

        try:

            await channel.edit(
                name=new_name,
                topic=(
                    f"{TOPIC_PREFIX}"
                    f"{user_id}"
                ),
                reason=(
                    f"Modmail reopened by "
                    f"{moderator}"
                ),
            )

        except discord.HTTPException:

            return user_id

        role = channel.guild.get_role(
            self.config.staff_role_id
        )

        if role is not None:

            try:

                await channel.set_permissions(
                    role,
                    send_messages=True,
                )

            except discord.HTTPException:

                pass

        self.loaded_tickets[
            user_id
        ] = channel.id

        await channel.send(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Modmail Reopened"
                ),
                description=(
                    f"This ticket was reopened by "
                    f"{moderator.mention}."
                ),
                color=discord.Color.green(),
                timestamp=self.utcnow(),
            ),
            view=TicketControls(
                self
            ),
            allowed_mentions=(
                discord.AllowedMentions.none()
            ),
        )

        await self.log_action(
            title="Modmail Ticket Reopened",
            description=(
                f"**User ID:** `{user_id}`\n"
                f"**Ticket:** {channel.mention}\n"
                f"**Moderator:** {moderator.mention}"
            ),
            color=discord.Color.green(),
        )

        return user_id

    # ========================================================
    # BLOCK USER
    # ========================================================

    async def block_user(
        self,
        user_id: int,
        moderator: discord.Member,
    ) -> bool:

        already = (
            user_id
            in self.blocked_users
        )

        self.blocked_users.add(
            user_id
        )

        await self.save_blocked_users()

        channel = self.get_active_ticket(
            user_id
        )

        if channel is not None:

            await self.close_ticket(
                channel,
                moderator,
                reason=(
                    "User blocked from Modmail."
                ),
                notify_user=False,
            )

        if not already:

            await self.log_action(
                title="Modmail User Blocked",
                description=(
                    f"**User ID:** `{user_id}`\n"
                    f"**Moderator:** {moderator.mention}"
                ),
                color=discord.Color.red(),
            )

        return not already

    # ========================================================
    # UNBLOCK USER
    # ========================================================

    async def unblock_user(
        self,
        user_id: int,
        moderator: discord.Member,
    ) -> bool:

        if user_id not in self.blocked_users:

            return False

        self.blocked_users.discard(
            user_id
        )

        await self.save_blocked_users()

        await self.log_action(
            title="Modmail User Unblocked",
            description=(
                f"**User ID:** `{user_id}`\n"
                f"**Moderator:** {moderator.mention}"
            ),
            color=discord.Color.green(),
        )

        return True

    # ========================================================
    # TRANSCRIPT BUILDING
    # ========================================================

    async def build_transcript(
        self,
        channel: discord.TextChannel,
    ) -> tuple[str, bytes]:

        lines = [
            "LUNAR MODMAIL TRANSCRIPT",
            "=" * 72,
            (
                f"Guild: "
                f"{channel.guild.name} "
                f"({channel.guild.id})"
            ),
            (
                f"Channel: "
                f"{channel.name} "
                f"({channel.id})"
            ),
            (
                f"Generated: "
                f"{self.utcnow().isoformat()}"
            ),
            "=" * 72,
            "",
        ]

        try:

            messages = [
                message
                async for message
                in channel.history(
                    limit=TRANSCRIPT_LIMIT,
                    oldest_first=True,
                )
            ]

        except discord.HTTPException as exc:

            lines.append(
                f"FAILED TO FETCH HISTORY: {exc}"
            )

            data = "\n".join(
                lines
            ).encode(
                "utf-8",
                errors="replace",
            )

            return (
                "error.txt",
                data,
            )

        for message in messages:

            timestamp = (
                message.created_at.isoformat()
            )

            author = str(
                message.author
            )

            content = (
                message.clean_content
                or "[no text]"
            )

            lines.append(
                (
                    f"[{timestamp}] "
                    f"{author} "
                    f"({message.author.id})"
                )
            )

            lines.append(
                content
            )

            if message.attachments:

                lines.append(
                    "Attachments: "
                    + ", ".join(
                        attachment.url
                        for attachment
                        in message.attachments
                    )
                )

            if message.embeds:

                lines.append(
                    f"Embeds: "
                    f"{len(message.embeds)}"
                )

            lines.append(
                "-" * 72
            )

        data = "\n".join(
            lines
        ).encode(
            "utf-8",
            errors="replace",
        )

        filename = (
            f"modmail-{channel.id}"
            f"-transcript.txt"
        )

        return (
            filename,
            data,
        )

    async def send_transcript(
        self,
        channel: discord.TextChannel,
        moderator: Optional[
            discord.Member
        ] = None,
    ) -> bool:

        filename, data = (
            await self.build_transcript(
                channel
            )
        )

        log_channel = (
            await self.get_log_channel()
        )

        if log_channel is None:

            return False

        user_id = (
            self.parse_user_id_from_topic(
                channel.topic
            )
        )

        embed = discord.Embed(
            title="Modmail Transcript",
            description=(
                f"**Ticket:** {channel.mention}\n"
                f"**User ID:** "
                f"`{user_id or 'Unknown'}`\n"
                f"**Generated by:** "
                f"{moderator.mention if moderator else 'System'}"
            ),
            color=0x7C5CFF,
            timestamp=self.utcnow(),
        )

        try:

            await log_channel.send(
                embed=embed,
                file=discord.File(
                    io.BytesIO(
                        data
                    ),
                    filename=filename,
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        except discord.HTTPException:

            log.exception(
                "Failed to send transcript for %s.",
                channel.id,
            )

            return False

        return True

    # ========================================================
    # LOGGING
    # ========================================================

    async def log_action(
        self,
        *,
        title: str,
        description: str,
        color: discord.Color,
    ) -> None:

        channel = (
            await self.get_log_channel()
        )

        if channel is None:

            return

        try:

            await channel.send(
                embed=discord.Embed(
                    title=title,
                    description=description,
                    color=color,
                    timestamp=self.utcnow(),
                ),
                allowed_mentions=(
                    discord.AllowedMentions.none()
                ),
            )

        except discord.HTTPException:

            log.exception(
                "Failed to log Modmail action: %s",
                title,
            )

    # ========================================================
    # VALIDATE TICKET CONTROLS
    # ========================================================

    async def validate_control(
        self,
        interaction: discord.Interaction,
    ) -> Optional[
        discord.TextChannel
    ]:

        if not await self.ensure_staff(
            interaction
        ):

            return None

        if not isinstance(
            interaction.channel,
            discord.TextChannel,
        ):

            await self.safe_interaction_error(
                interaction,
                (
                    f"{EMOJI['denied']} "
                    "This is not a Modmail ticket."
                ),
            )

            return None

        user_id = (
            self.parse_user_id_from_topic(
                interaction.channel.topic
            )
        )

        if user_id is None:

            await self.safe_interaction_error(
                interaction,
                (
                    f"{EMOJI['denied']} "
                    "This is not a Modmail ticket."
                ),
            )

            return None

        return interaction.channel

    # ========================================================
    # CLOSE BUTTON
    # ========================================================

    async def handle_control_close(
        self,
        interaction: discord.Interaction,
    ) -> None:

        channel = (
            await self.validate_control(
                interaction
            )
        )

        if channel is None:

            return

        await interaction.response.defer(
            ephemeral=True
        )

        await self.close_ticket(
            channel,
            interaction.user,  # type: ignore[arg-type]
            reason=(
                "Closed from ticket controls."
            ),
        )

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                "Ticket closed successfully."
            )
        )

    # ========================================================
    # TRANSCRIPT BUTTON
    # ========================================================

    async def handle_control_transcript(
        self,
        interaction: discord.Interaction,
    ) -> None:

        channel = (
            await self.validate_control(
                interaction
            )
        )

        if channel is None:

            return

        await interaction.response.defer(
            ephemeral=True
        )

        success = (
            await self.send_transcript(
                channel,
                interaction.user,  # type: ignore[arg-type]
            )
        )

        await interaction.edit_original_response(
            content=(
                (
                    f"{EMOJI['approved']} "
                    "Transcript sent to the Modmail log channel."
                )
                if success
                else
                (
                    f"{EMOJI['error']} "
                    "I couldn't send the transcript."
                )
            )
        )

    # ========================================================
    # BLOCK BUTTON
    # ========================================================

    async def handle_control_block(
        self,
        interaction: discord.Interaction,
    ) -> None:

        channel = (
            await self.validate_control(
                interaction
            )
        )

        if channel is None:

            return

        user_id = (
            self.parse_user_id_from_topic(
                channel.topic
            )
        )

        if user_id is None:

            return

        await interaction.response.defer(
            ephemeral=True
        )

        await self.block_user(
            user_id,
            interaction.user,  # type: ignore[arg-type]
        )

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                f"User `{user_id}` has been blocked "
                "and the ticket was closed."
            )
        )

    # ========================================================
    # READY EVENT
    # ========================================================

    @commands.Cog.listener()
    async def on_ready(
        self,
    ) -> None:

        if not self.config_loaded:

            await self.load_state()

        self.rebuild_ticket_cache()

        self.rebuild_ticket_cache()

    # ========================================================
    # MESSAGE EVENT
    # ========================================================

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:

        if message.author.bot:

            return

        # ----------------------------------------------------
        # USER DM
        # ----------------------------------------------------

        if message.guild is None:

            await self.forward_dm(
                message
            )

            return

        # ----------------------------------------------------
        # STAFF MESSAGE
        # ----------------------------------------------------

        if not isinstance(
            message.channel,
            discord.TextChannel,
        ):

            return

        if (
            message.guild.id
            != self.config.guild_id
        ):

            return

        if (
            message.channel.category_id
            != self.config.category_id
        ):

            return

        if (
            self.parse_user_id_from_topic(
                message.channel.topic
            )
            is None
        ):

            return

        await self.forward_staff_message(
            message
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        ModmailIntegration(bot)
    )