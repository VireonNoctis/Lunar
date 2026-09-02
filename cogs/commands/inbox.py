from __future__ import annotations

import math
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


PAGE_SIZE = 10
INBOX_TIMEOUT = 120


class InboxView(discord.ui.View):

    def __init__(
        self,
        cog: "Inbox",
        user_id: int,
        *,
        timeout: float = INBOX_TIMEOUT,
    ):
        super().__init__(timeout=timeout)

        self.cog = cog
        self.user_id = user_id
        self.page = 0

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                f"{EMOJI['denied']} Not your inbox.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(
        label="⬅",
        style=discord.ButtonStyle.secondary,
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.page > 0:
            self.page -= 1

        await self.cog.refresh_message(
            interaction,
            self,
        )

    @discord.ui.button(
        label="➡",
        style=discord.ButtonStyle.secondary,
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.page += 1

        await self.cog.refresh_message(
            interaction,
            self,
        )

    @discord.ui.button(
        label="🔄",
        style=discord.ButtonStyle.primary,
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.refresh_message(
            interaction,
            self,
        )

    @discord.ui.button(
        label="🧹",
        style=discord.ButtonStyle.danger,
    )
    async def archive_all(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if db.mentions is None:
            await interaction.response.send_message(
                f"{EMOJI['denied']} Database is not initialized.",
                ephemeral=True,
            )
            return

        await db.mentions.archive_all(
            interaction.user.id
        )

        self.page = 0

        await self.cog.refresh_message(
            interaction,
            self,
        )


class Inbox(commands.Cog):

    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    # ========================================================
    # DATABASE
    # ========================================================

    async def fetch_page(
        self,
        user_id: int,
        page: int,
    ):
        if db.mentions is None:
            return [], 0

        # Scylla is query-oriented, so we retrieve a bounded set.
        # For a very large inbox, switch this to Cassandra paging
        # rather than OFFSET pagination.
        result = await db.mentions.unread(
            user_id,
            limit=PAGE_SIZE * (page + 1),
        )

        rows = list(result)

        total = len(rows)

        start = page * PAGE_SIZE
        end = start + PAGE_SIZE

        return rows[start:end], total

    # ========================================================
    # EMBED
    # ========================================================

    def build_embed(
        self,
        interaction: discord.Interaction,
        rows,
        total: int,
    ) -> discord.Embed:

        embed = discord.Embed(
            color=0x5865F2,
            timestamp=datetime.now(),
        )

        embed.set_author(
            name=f"{interaction.user.name}'s Inbox",
            icon_url=interaction.user.display_avatar.url,
        )

        embed.title = f"{EMOJI['moon']} Inbox"
        embed.set_footer(
            text=f"Lunar • {total} unread mentions"
        )

        if not rows:
            embed.description = (
                f"{EMOJI['approved']} No unread mentions."
            )
            return embed

        entries = []

        for row in rows:

            created_at = row.created_at

            if isinstance(created_at, datetime):
                timestamp = int(
                    created_at.timestamp()
                )
            else:
                timestamp = 0

            time = f"<t:{timestamp}:R>"

            entries.append(
                "\n".join(
                    [
                        f"{EMOJI['staff']} "
                        f"<@{row.message_author_id}>",
                        f"<#{row.channel_id}>",
                        f"> Message ID: {row.message_id}",
                        f"> {time}",
                        "━━━━━━━━━━━━━━━━━━━━━━",
                    ]
                )
            )

        embed.description = "\n".join(entries)

        return embed

    # ========================================================
    # REFRESH
    # ========================================================

    async def refresh_message(
        self,
        interaction: discord.Interaction,
        view: InboxView,
    ) -> None:

        rows, total = await self.fetch_page(
            interaction.user.id,
            view.page,
        )

        max_page = max(
            0,
            math.ceil(total / PAGE_SIZE) - 1,
        )

        if view.page > max_page:
            view.page = max_page

            rows, total = await self.fetch_page(
                interaction.user.id,
                view.page,
            )

        view.children[0].disabled = view.page <= 0
        view.children[1].disabled = view.page >= max_page

        await interaction.response.edit_message(
            embed=self.build_embed(
                interaction,
                rows,
                total,
            ),
            view=view,
        )

        # Mark currently displayed messages as read.
        if db.mentions is not None:
            for row in rows:
                try:
                    await db.mentions.mark_read(row)
                except Exception:
                    continue

    # ========================================================
    # SLASH COMMAND
    # ========================================================

    @app_commands.command(
        name="inbox",
        description="View your unread mentions."
    )
    async def inbox(
        self,
        interaction: discord.Interaction,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                f"{EMOJI['denied']} This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if db.mentions is None:
            await interaction.response.send_message(
                f"{EMOJI['denied']} Database is not initialized.",
                ephemeral=True,
            )
            return

        view = InboxView(
            self,
            interaction.user.id,
        )

        rows, total = await self.fetch_page(
            interaction.user.id,
            0,
        )

        await interaction.response.send_message(
            embed=self.build_embed(
                interaction,
                rows,
                total,
            ),
            view=view,
        )

        # Mark the first page as read.
        for row in rows:
            try:
                await db.mentions.mark_read(row)
            except Exception:
                continue

    # ========================================================
    # PREFIX COMMAND
    # ========================================================

    @commands.command(
        name="inbox",
    )
    async def inbox_prefix(
        self,
        ctx: commands.Context,
    ):
        if not ctx.guild:
            await ctx.send(
                f"{EMOJI['denied']} This command can only be used in a server."
            )
            return

        if db.mentions is None:
            await ctx.send(
                f"{EMOJI['denied']} Database is not initialized."
            )
            return

        view = InboxView(
            self,
            ctx.author.id,
        )

        rows, total = await self.fetch_page(
            ctx.author.id,
            0,
        )

        await ctx.send(
            embed=self.build_embed(
                ctx,
                rows,
                total,
            ),
            view=view,
        )

        for row in rows:
            try:
                await db.mentions.mark_read(row)
            except Exception:
                continue


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        Inbox(bot)
    )
