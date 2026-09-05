from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


log = logging.getLogger(__name__)


# ============================================================
# Configuration
# ============================================================

CHANNEL_CATEGORY_NAME = "Private Channels"

# Keep these as normal Discord channel categories.
CHANNEL_TYPES = {
    "roleplay": {
        "label": "Role Play",
        "emoji": "🎭",
        "description": "Create a private role-play channel.",
        "prefix": "roleplay",
    },
    "trade": {
        "label": "Trade",
        "emoji": "💰",
        "description": "Create a private trading channel.",
        "prefix": "trade",
    },
    "chat": {
        "label": "Chat",
        "emoji": "💬",
        "description": "Create a private conversation channel.",
        "prefix": "chat",
    },
}

MAX_USERS = 15
MAX_LOADING_STAGES = 14


# ============================================================
# Helpers
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def unix_timestamp(dt: datetime) -> int:
    return int(dt.timestamp())


def sanitize_channel_name(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s_-]", "", value)
    value = re.sub(r"[\s_-]+", "-", value)
    value = value.strip("-")

    if not value:
        value = "private"

    return value[:70]


def make_channel_suffix() -> str:
    return secrets.token_hex(3)


def progress_bar(percent: int, length: int = 20) -> str:
    percent = max(0, min(100, percent))

    filled = round((percent / 100) * length)
    empty = length - filled

    return f"`{'━' * filled}{'░' * empty}` {percent}%"


def provider_icon(channel_type: str) -> str:
    return CHANNEL_TYPES[channel_type]["emoji"]


# ============================================================
# Persistent model
# ============================================================

@dataclass
class PrivateChannelRecord:
    channel_id: int
    guild_id: int
    owner_id: int
    channel_type: str
    user_ids: list[int]
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PrivateChannelRecord":
        return cls(
            channel_id=int(data["channel_id"]),
            guild_id=int(data["guild_id"]),
            owner_id=int(data["owner_id"]),
            channel_type=str(data["channel_type"]),
            user_ids=[int(x) for x in data.get("user_ids", [])],
            created_at=str(data.get("created_at", utc_now().isoformat())),
        )


# ============================================================
# Database storage
# ============================================================

class PrivateChannelStorage:
    """
    Stores private-channel configuration using the existing
    generic settings repository.

    No additional database schema is required.
    """

    @staticmethod
    def scope(guild_id: int) -> str:
        return f"private_channels:guild:{guild_id}"

    async def load(self, guild_id: int) -> list[PrivateChannelRecord]:
        raw = db.settings.get(
            self.scope(guild_id),
            "channels",
            default=[],
        )

        if not isinstance(raw, list):
            return []

        records: list[PrivateChannelRecord] = []

        for item in raw:
            if not isinstance(item, dict):
                continue

            try:
                records.append(
                    PrivateChannelRecord.from_dict(item)
                )
            except (KeyError, TypeError, ValueError):
                continue

        return records

    async def save(
        self,
        guild_id: int,
        records: list[PrivateChannelRecord],
    ) -> None:
        db.settings.set(
            self.scope(guild_id),
            "channels",
            [record.to_dict() for record in records],
        )

    async def add(
        self,
        record: PrivateChannelRecord,
    ) -> None:
        records = await self.load(record.guild_id)

        records = [
            existing
            for existing in records
            if existing.channel_id != record.channel_id
        ]

        records.append(record)

        await self.save(record.guild_id, records)

    async def remove(
        self,
        guild_id: int,
        channel_id: int,
    ) -> None:
        records = await self.load(guild_id)

        records = [
            record
            for record in records
            if record.channel_id != channel_id
        ]

        await self.save(guild_id, records)

    async def get(
        self,
        guild_id: int,
        channel_id: int,
    ) -> Optional[PrivateChannelRecord]:
        records = await self.load(guild_id)

        for record in records:
            if record.channel_id == channel_id:
                return record

        return None


storage = PrivateChannelStorage()


# ============================================================
# Fake loading
# ============================================================

@dataclass
class LoadingStage:
    title: str
    description: str
    delay: float


LOADING_STAGES = [
    LoadingStage(
        "Initializing private-channel manager",
        "Booting the secure channel provisioning layer.",
        0.85,
    ),
    LoadingStage(
        "Validating your permissions",
        "Checking whether you can create private channels.",
        0.90,
    ),
    LoadingStage(
        "Reading channel configuration",
        "Loading the selected channel template.",
        0.80,
    ),
    LoadingStage(
        "Inspecting selected users",
        "Verifying every selected member can be granted access.",
        0.95,
    ),
    LoadingStage(
        "Building permission matrix",
        "Constructing the private overwrite set.",
        1.05,
    ),
    LoadingStage(
        "Preparing category routing",
        "Resolving the destination category for the new channel.",
        0.90,
    ),
    LoadingStage(
        "Generating secure channel identity",
        "Creating a unique channel name and internal record.",
        0.85,
    ),
    LoadingStage(
        "Applying @everyone restrictions",
        "Removing inherited access from the private workspace.",
        1.00,
    ),
    LoadingStage(
        "Granting selected-user access",
        "Adding the selected members to the permission matrix.",
        1.10,
    ),
    LoadingStage(
        "Configuring moderation access",
        "Keeping server moderators and the bot operational.",
        0.95,
    ),
    LoadingStage(
        "Creating Discord channel",
        "Provisioning the private channel on Discord.",
        1.20,
    ),
    LoadingStage(
        "Verifying permissions",
        "Running a final access-control consistency check.",
        0.95,
    ),
    LoadingStage(
        "Registering channel in database",
        "Saving the private-channel configuration.",
        0.90,
    ),
    LoadingStage(
        "Finalizing workspace",
        "Completing channel provisioning and notification setup.",
        0.80,
    ),
]


async def render_loading(
    interaction: discord.Interaction,
    *,
    channel_type: str,
    users: list[discord.Member],
    stage_index: int,
) -> None:
    stage = LOADING_STAGES[stage_index]

    percent = int(
        ((stage_index + 1) / len(LOADING_STAGES)) * 100
    )

    selected_users = ", ".join(
        member.mention for member in users[:6]
    )

    if len(users) > 6:
        selected_users += f" +{len(users) - 6} more"

    embed = discord.Embed(
        title=f"{EMOJI['loading']} Private Channel Provisioning",
        description=(
            f"### {stage.title}\n"
            f"{stage.description}\n\n"
            f"{progress_bar(percent)}"
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="Channel Type",
        value=(
            f"{provider_icon(channel_type)} "
            f"**{CHANNEL_TYPES[channel_type]['label']}**"
        ),
        inline=True,
    )

    embed.add_field(
        name="Selected Users",
        value=str(len(users)),
        inline=True,
    )

    embed.add_field(
        name="System Layer",
        value=f"`{stage_index + 1}/{len(LOADING_STAGES)}`",
        inline=True,
    )

    embed.add_field(
        name="Access Matrix",
        value=selected_users or "No users selected",
        inline=False,
    )

    embed.set_footer(
        text="Lunar Private Channel Manager"
    )

    try:
        await interaction.edit_original_response(
            embed=embed,
            view=None,
        )
    except discord.HTTPException:
        pass


# ============================================================
# User selector
# ============================================================

class PrivateUserSelect(discord.ui.UserSelect):
    def __init__(self, parent_view: "ChannelSetupView"):
        self.parent_view = parent_view

        super().__init__(
            placeholder="Select the users who should have access...",
            min_values=1,
            max_values=MAX_USERS,
            custom_id="private_channel_user_select",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        members: list[discord.Member] = []

        if interaction.guild is None:
            await interaction.response.send_message(
                "This setup can only be used inside a server.",
                ephemeral=True,
            )
            return

        for selected_user in self.values:
            member = interaction.guild.get_member(selected_user.id)

            if member is not None:
                members.append(member)

        self.parent_view.selected_user_ids = [
            member.id for member in members
        ]

        self.parent_view.selected_members = members

        await interaction.response.edit_message(
            embed=self.parent_view.build_setup_embed(),
            view=self.parent_view,
        )


# ============================================================
# Channel type selector
# ============================================================

class ChannelTypeSelect(discord.ui.Select):
    def __init__(self, parent_view: "ChannelSetupView"):
        self.parent_view = parent_view

        options = [
            discord.SelectOption(
                label="Role Play",
                value="roleplay",
                emoji="🎭",
                description="Private role-play workspace.",
            ),
            discord.SelectOption(
                label="Trade",
                value="trade",
                emoji="💰",
                description="Private trading workspace.",
            ),
            discord.SelectOption(
                label="Chat",
                value="chat",
                emoji="💬",
                description="Private conversation workspace.",
            ),
        ]

        super().__init__(
            placeholder="Choose a channel type...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="private_channel_type_select",
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        selected = self.values[0]

        self.parent_view.channel_type = selected

        await interaction.response.edit_message(
            embed=self.parent_view.build_setup_embed(),
            view=self.parent_view,
        )


# ============================================================
# Confirmation view
# ============================================================

class ConfirmationView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        channel_type: str,
        selected_members: list[discord.Member],
        channel_name: str,
    ):
        super().__init__(timeout=180)

        self.owner_id = owner_id
        self.channel_type = channel_type
        self.selected_members = selected_members
        self.channel_name = channel_name

        self.confirmed = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who started this setup can confirm it.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="Create Channel",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="private_channel_confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.confirmed = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                f"{EMOJI['loading']} **Provision request accepted.**\n"
                "The private channel manager is starting."
            ),
            view=self,
        )

    @discord.ui.button(
        label="Cancel",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        custom_id="private_channel_cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.confirmed = False

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                f"{EMOJI['denied']} **Channel creation cancelled.**"
            ),
            view=self,
        )


# ============================================================
# Main setup view
# ============================================================

class ChannelSetupView(discord.ui.View):
    def __init__(
        self,
        *,
        author: discord.Member,
    ):
        super().__init__(timeout=300)

        self.author = author

        self.channel_type: str = "chat"

        self.selected_user_ids: list[int] = []
        self.selected_members: list[discord.Member] = []

        self.add_item(
            ChannelTypeSelect(self)
        )

        self.add_item(
            PrivateUserSelect(self)
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "This private-channel setup belongs to another user.",
                ephemeral=True,
            )
            return False

        return True

    def build_setup_embed(self) -> discord.Embed:
        channel_info = CHANNEL_TYPES[self.channel_type]

        selected_users = (
            "\n".join(
                f"{index}. {member.mention}"
                for index, member in enumerate(
                    self.selected_members,
                    start=1,
                )
            )
            if self.selected_members
            else f"{EMOJI['question']} No users selected yet."
        )

        embed = discord.Embed(
            title=f"{EMOJI['lunar']} Private Channel Builder",
            description=(
                "Configure the private workspace below.\n\n"
                f"{channel_info['emoji']} **Type:** "
                f"{channel_info['label']}\n"
                f"👥 **Users:** "
                f"{len(self.selected_members)}/{MAX_USERS}\n\n"
                "Select a channel type and then choose the "
                "members who should have access."
            ),
            color=discord.Color.blurple(),
        )

        embed.add_field(
            name="Selected Members",
            value=selected_users,
            inline=False,
        )

        embed.add_field(
            name="Access Model",
            value=(
                "🔒 `@everyone` — denied\n"
                "👤 Selected users — allowed\n"
                "🛡️ Moderation — governed by server permissions"
            ),
            inline=False,
        )

        embed.set_footer(
            text="No channel will be created until you confirm the final preview."
        )

        return embed

    @discord.ui.button(
        label="Preview",
        emoji="👁️",
        style=discord.ButtonStyle.primary,
        row=2,
        custom_id="private_channel_preview",
    )
    async def preview(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not self.selected_members:
            await interaction.response.send_message(
                f"{EMOJI['error']} Select at least one user first.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=build_preview_embed(
                channel_type=self.channel_type,
                members=self.selected_members,
            ),
            view=ConfirmationView(
                owner_id=self.author.id,
                channel_type=self.channel_type,
                selected_members=self.selected_members,
                channel_name=build_channel_name(
                    self.channel_type,
                    self.author.display_name,
                ),
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Reset",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        row=2,
        custom_id="private_channel_reset",
    )
    async def reset(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        self.channel_type = "chat"
        self.selected_user_ids.clear()
        self.selected_members.clear()

        await interaction.response.edit_message(
            embed=self.build_setup_embed(),
            view=self,
        )

    @discord.ui.button(
        label="Close",
        emoji="✖️",
        style=discord.ButtonStyle.danger,
        row=2,
        custom_id="private_channel_close",
    )
    async def close(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=(
                f"{EMOJI['denied']} "
                "Private-channel setup closed."
            ),
            embed=None,
            view=self,
        )


# ============================================================
# Preview / naming
# ============================================================

def build_channel_name(
    channel_type: str,
    owner_name: str,
) -> str:
    prefix = CHANNEL_TYPES[channel_type]["prefix"]

    owner_part = sanitize_channel_name(owner_name)

    suffix = make_channel_suffix()

    return sanitize_channel_name(
        f"{prefix}-{owner_part}-{suffix}"
    )


def build_preview_embed(
    *,
    channel_type: str,
    members: list[discord.Member],
) -> discord.Embed:
    info = CHANNEL_TYPES[channel_type]

    mentions = "\n".join(
        f"• {member.mention}"
        for member in members
    )

    embed = discord.Embed(
        title=f"{EMOJI['verify']} Final Channel Preview",
        description=(
            "Review the private workspace before it is created."
        ),
        color=discord.Color.green(),
    )

    embed.add_field(
        name="Channel Type",
        value=f"{info['emoji']} **{info['label']}**",
        inline=True,
    )

    embed.add_field(
        name="Users",
        value=f"`{len(members)}` selected",
        inline=True,
    )

    embed.add_field(
        name="Privacy",
        value="🔒 Private",
        inline=True,
    )

    embed.add_field(
        name="Members With Access",
        value=mentions,
        inline=False,
    )

    embed.add_field(
        name="Permission Rules",
        value=(
            "• `@everyone` → denied\n"
            "• Selected users → view/send access\n"
            "• Channel creator → full channel access\n"
            "• Server moderation → follows server hierarchy\n"
            "• Bot → channel management access"
        ),
        inline=False,
    )

    return embed


# ============================================================
# Cog
# ============================================================

class PrivateChannel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    async def get_or_create_category(
        self,
        guild: discord.Guild,
    ) -> discord.CategoryChannel:
        existing = discord.utils.get(
            guild.categories,
            name=CHANNEL_CATEGORY_NAME,
        )

        if existing is not None:
            return existing

        category = await guild.create_category(
            name=CHANNEL_CATEGORY_NAME,
            reason="Lunar Private Channel Manager",
        )

        return category

    # --------------------------------------------------------
    # Permission builder
    # --------------------------------------------------------

    def build_overwrites(
        self,
        *,
        guild: discord.Guild,
        owner: discord.Member,
        selected_members: list[discord.Member],
    ) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
        overwrites: dict[
            discord.abc.Snowflake,
            discord.PermissionOverwrite,
        ] = {}

        # Nobody by default.
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            view_channel=False,
            read_message_history=False,
            send_messages=False,
        )

        # Creator.
        overwrites[owner] = discord.PermissionOverwrite(
            view_channel=True,
            read_message_history=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
            use_application_commands=True,
        )

        # Selected users.
        for member in selected_members:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
                use_application_commands=True,
            )

        # Bot itself.
        me = guild.me

        if me is not None:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
                use_application_commands=True,
            )

        # Preserve the effective access of administrators.
        for member in guild.members:
            if member.guild_permissions.administrator:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                    manage_messages=True,
                )

        return overwrites

    # --------------------------------------------------------
    # Actual creation
    # --------------------------------------------------------

    async def create_private_channel(
        self,
        *,
        interaction: discord.Interaction,
        channel_type: str,
        selected_members: list[discord.Member],
    ) -> discord.TextChannel:
        guild = interaction.guild
        assert guild is not None

        owner = guild.get_member(interaction.user.id)

        if owner is None:
            raise RuntimeError(
                "The channel owner could not be resolved."
            )

        category = await self.get_or_create_category(guild)

        channel_name = build_channel_name(
            channel_type,
            owner.display_name,
        )

        overwrites = self.build_overwrites(
            guild=guild,
            owner=owner,
            selected_members=selected_members,
        )

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=(
                f"Private {CHANNEL_TYPES[channel_type]['label']} "
                f"channel created by {owner}."
            ),
            reason=(
                "Lunar Private Channel Manager "
                f"({CHANNEL_TYPES[channel_type]['label']})"
            ),
        )

        record = PrivateChannelRecord(
            channel_id=channel.id,
            guild_id=guild.id,
            owner_id=owner.id,
            channel_type=channel_type,
            user_ids=[
                member.id
                for member in selected_members
            ],
            created_at=utc_now().isoformat(),
        )

        await storage.add(record)

        return channel

    # --------------------------------------------------------
    # /channel
    # --------------------------------------------------------

    @app_commands.command(
        name="channel",
        description="Create a private multi-user channel.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_guild_permissions(manage_channels=True)
    async def channel(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                f"{EMOJI['error']} This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                f"{EMOJI['error']} Could not resolve your member permissions.",
                ephemeral=True,
            )
            return

        view = ChannelSetupView(
            author=interaction.user,
        )

        await interaction.response.send_message(
            embed=view.build_setup_embed(),
            view=view,
            ephemeral=True,
        )

    # --------------------------------------------------------
    # Context information command
    # --------------------------------------------------------

    @app_commands.command(
        name="private-channels",
        description="View private channels registered for this server.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_guild_permissions(manage_channels=True)
    async def private_channels(
        self,
        interaction: discord.Interaction,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                f"{EMOJI['error']} This command can only be used in a server.",
                ephemeral=True,
            )
            return

        records = await storage.load(interaction.guild.id)

        if not records:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{EMOJI['question']} Private Channels",
                    description=(
                        "There are currently no registered "
                        "private channels in this server."
                    ),
                    color=discord.Color.blurple(),
                ),
                ephemeral=False,
            )
            return

        lines: list[str] = []

        for record in records[:20]:
            channel = interaction.guild.get_channel(
                record.channel_id
            )

            channel_text = (
                channel.mention
                if channel is not None
                else f"`{record.channel_id}`"
            )

            info = CHANNEL_TYPES.get(
                record.channel_type,
                {
                    "emoji": "🔒",
                    "label": record.channel_type,
                },
            )

            lines.append(
                f"{info['emoji']} {channel_text} — "
                f"**{info['label']}** — "
                f"`{len(record.user_ids)} users`"
            )

        embed = discord.Embed(
            title=f"{EMOJI['lunar']} Private Channel Registry",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )

        embed.set_footer(
            text=f"{len(records)} registered private channel(s)"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=False,
        )

    # --------------------------------------------------------
    # Delete / unregister
    # --------------------------------------------------------

    @app_commands.command(
        name="channel-delete",
        description="Delete a registered private channel.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_guild_permissions(manage_channels=True)
    async def channel_delete(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                f"{EMOJI['error']} This command can only be used in a server.",
                ephemeral=True,
            )
            return

        record = await storage.get(
            interaction.guild.id,
            channel.id,
        )

        if record is None:
            await interaction.response.send_message(
                f"{EMOJI['error']} That channel is not registered as a private channel.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"{EMOJI['loading']} Removing `{channel.name}`...",
            ephemeral=True,
        )

        await asyncio.sleep(0.8)

        try:
            await channel.delete(
                reason="Lunar Private Channel Manager deletion"
            )
        except discord.HTTPException as exc:
            log.error(
                "Failed deleting private channel %s: %s",
                channel.id,
                exc,
            )

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "I could not delete that channel. "
                    "Check my permissions and role hierarchy."
                )
            )
            return

        await storage.remove(
            interaction.guild.id,
            channel.id,
        )

        await interaction.edit_original_response(
            content=(
                f"{EMOJI['approved']} "
                "Private channel deleted and removed from the registry."
            )
        )

    # --------------------------------------------------------
    # Error handlers
    # --------------------------------------------------------

    @channel.error
    async def channel_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(
            error,
            app_commands.errors.MissingPermissions,
        ):
            message = (
                f"{EMOJI['denied']} "
                "You need **Manage Channels** to use `/channel`."
            )

        elif isinstance(
            error,
            app_commands.errors.CheckFailure,
        ):
            message = (
                f"{EMOJI['denied']} "
                "You do not have permission to use this command."
            )

        else:
            log.exception(
                "Unexpected /channel error",
                exc_info=error,
            )

            message = (
                f"{EMOJI['error']} "
                "An unexpected error occurred while opening the channel manager."
            )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrivateChannel(bot))
