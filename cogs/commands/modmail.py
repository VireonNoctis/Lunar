from __future__ import annotations

import discord

from discord import app_commands
from discord.ext import commands

from cogs.integrations.modmail import ModmailConfig, ModmailIntegration
from cogs.utilities.emoji import EMOJI


# ============================================================
# MODMAIL COMMAND
# ============================================================

class Modmail(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

    # ========================================================
    # /modmail
    # ========================================================

    @app_commands.command(
        name="modmail",
        description="Manage the Lunar Modmail system.",
    )
    @app_commands.describe(
        action="The Modmail action to perform.",
        category="Category where Modmail tickets will be created.",
        log_channel="Channel where Modmail logs and transcripts are sent.",
        staff_role="Role that can access and manage Modmail tickets.",
        user_id="Discord user ID for block/unblock.",
        reason="Reason for closing a ticket.",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(
                name="Setup",
                value="setup",
            ),
            app_commands.Choice(
                name="Status",
                value="status",
            ),
            app_commands.Choice(
                name="Close",
                value="close",
            ),
            app_commands.Choice(
                name="Reopen",
                value="reopen",
            ),
            app_commands.Choice(
                name="Transcript",
                value="transcript",
            ),
            app_commands.Choice(
                name="Block",
                value="block",
            ),
            app_commands.Choice(
                name="Unblock",
                value="unblock",
            ),
        ]
    )
    async def modmail(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        staff_role: discord.Role | None = None,
        user_id: str | None = None,
        reason: str | None = None,
    ) -> None:

        # ----------------------------------------------------
        # Guild Check
        # ----------------------------------------------------

        if interaction.guild is None:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Modmail management can only be used in a server.",
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Integration Lookup
        # ----------------------------------------------------

        integration = (
            self.bot.get_cog(
                "ModmailIntegration"
            )
        )

        if not isinstance(
            integration,
            ModmailIntegration,
        ):

            await interaction.response.send_message(
                f"{EMOJI['error']} "
                "The Modmail integration is not loaded.",
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Staff Permission
        # ----------------------------------------------------

        if not isinstance(
            interaction.user,
            discord.Member,
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "I couldn't verify your permissions.",
                ephemeral=True,
            )

            return

        if not integration.member_is_staff(
            interaction.user
        ):

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "You are not authorized to manage Modmail.",
                ephemeral=True,
            )

            return

        selected_action = action.value

        # ====================================================
        # SETUP
        # ====================================================

        if selected_action == "setup":

            if category is None:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "You must provide a **category** for Modmail tickets.",
                    ephemeral=True,
                )

                return

            if log_channel is None:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "You must provide a **log channel** for Modmail logs.",
                    ephemeral=True,
                )

                return

            if staff_role is None:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "You must provide a **staff role**.",
                    ephemeral=True,
                )

                return

            # ------------------------------------------------
            # Validate Category
            # ------------------------------------------------

            if category.guild.id != interaction.guild.id:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "The selected category must belong to this server.",
                    ephemeral=True,
                )

                return

            # ------------------------------------------------
            # Validate Log Channel
            # ------------------------------------------------

            if log_channel.guild.id != interaction.guild.id:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "The selected log channel must belong to this server.",
                    ephemeral=True,
                )

                return

            # ------------------------------------------------
            # Validate Staff Role
            # ------------------------------------------------

            if staff_role.guild.id != interaction.guild.id:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "The selected staff role must belong to this server.",
                    ephemeral=True,
                )

                return

            # ------------------------------------------------
            # Bot Permission Check
            # ------------------------------------------------

            me = interaction.guild.me

            if me is None:

                await interaction.response.send_message(
                    f"{EMOJI['error']} "
                    "I couldn't resolve my server member object.",
                    ephemeral=True,
                )

                return

            category_permissions = (
                category.permissions_for(me)
            )

            if not category_permissions.manage_channels:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "I need **Manage Channels** permission "
                    "to create Modmail tickets in that category.",
                    ephemeral=True,
                )

                return

            log_permissions = (
                log_channel.permissions_for(me)
            )

            if not log_permissions.send_messages:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "I cannot send messages in the selected log channel.",
                    ephemeral=True,
                )

                return

            # ------------------------------------------------
            # Save Configuration
            # ------------------------------------------------

            await interaction.response.defer(
                ephemeral=True
            )

            try:

                await integration.save_config(
                    ModmailConfig(
                        guild_id=interaction.guild.id,
                        category_id=category.id,
                        log_channel_id=log_channel.id,
                        staff_role_id=staff_role.id,
                    )
                )

                integration.rebuild_ticket_cache()

            except Exception as exc:

                print(
                    "[Modmail] Failed to save configuration: "
                    f"{type(exc).__name__}: {exc}"
                )

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "I couldn't save the Modmail configuration."
                    )
                )

                return

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['approved']} "
                    "**Modmail configured successfully.**\n\n"
                    f"**Ticket Category:** {category.mention}\n"
                    f"**Log Channel:** {log_channel.mention}\n"
                    f"**Staff Role:** {staff_role.mention}\n\n"
                    "Users can now DM the bot to open a Modmail ticket."
                )
            )

            return

        # ====================================================
        # STATUS
        # ====================================================

        if selected_action == "status":

            configured = (
                integration.configured()
            )

            embed = discord.Embed(
                title=(
                    f"{EMOJI['moon']} "
                    "Modmail Status"
                ),
                color=(
                    discord.Color.green()
                    if configured
                    else discord.Color.red()
                ),
                timestamp=discord.utils.utcnow(),
            )

            if configured:

                category_channel = (
                    interaction.guild.get_channel(
                        integration.config.category_id
                    )
                )

                log_channel_obj = (
                    interaction.guild.get_channel(
                        integration.config.log_channel_id
                    )
                )

                staff_role_obj = (
                    interaction.guild.get_role(
                        integration.config.staff_role_id
                    )
                )

                embed.description = (
                    f"{EMOJI['approved']} "
                    "**Modmail is configured and active.**"
                )

                embed.add_field(
                    name="Ticket Category",
                    value=(
                        category_channel.mention
                        if isinstance(
                            category_channel,
                            discord.CategoryChannel,
                        )
                        else f"`{integration.config.category_id}`"
                    ),
                    inline=False,
                )

                embed.add_field(
                    name="Log Channel",
                    value=(
                        log_channel_obj.mention
                        if isinstance(
                            log_channel_obj,
                            discord.TextChannel,
                        )
                        else f"`{integration.config.log_channel_id}`"
                    ),
                    inline=False,
                )

                embed.add_field(
                    name="Staff Role",
                    value=(
                        staff_role_obj.mention
                        if staff_role_obj is not None
                        else f"`{integration.config.staff_role_id}`"
                    ),
                    inline=False,
                )

                embed.add_field(
                    name="Open Tickets",
                    value=str(
                        len(
                            integration.loaded_tickets
                        )
                    ),
                    inline=True,
                )

                embed.add_field(
                    name="Blocked Users",
                    value=str(
                        len(
                            integration.blocked_users
                        )
                    ),
                    inline=True,
                )

            else:

                embed.description = (
                    f"{EMOJI['denied']} "
                    "**Modmail is not configured.**\n\n"
                    "Use `/modmail action:Setup` to configure it."
                )

            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
            )

            return

        # ====================================================
        # CURRENT CHANNEL CHECK
        # ====================================================

        if selected_action in {
            "close",
            "reopen",
            "transcript",
        }:

            if not isinstance(
                interaction.channel,
                discord.TextChannel,
            ):

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "This action can only be used inside a Modmail ticket.",
                    ephemeral=True,
                )

                return

            ticket_channel = (
                interaction.channel
            )

            ticket_user_id = (
                integration.parse_user_id_from_topic(
                    ticket_channel.topic
                )
            )

            if ticket_user_id is None:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "This channel is not a valid Modmail ticket.",
                    ephemeral=True,
                )

                return

        # ====================================================
        # CLOSE
        # ====================================================

        if selected_action == "close":

            await interaction.response.defer(
                ephemeral=True
            )

            result = (
                await integration.close_ticket(
                    ticket_channel,
                    interaction.user,
                    reason=(
                        reason
                        or "Closed using /modmail."
                    ),
                )
            )

            if result is None:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "I couldn't close this ticket."
                    )
                )

                return

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['approved']} "
                    "Modmail ticket closed successfully."
                )
            )

            return

        # ====================================================
        # REOPEN
        # ====================================================

        if selected_action == "reopen":

            if not integration.is_closed_topic(
                ticket_channel.topic
            ):

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "This Modmail ticket is already open.",
                    ephemeral=True,
                )

                return

            await interaction.response.defer(
                ephemeral=True
            )

            result = (
                await integration.reopen_ticket(
                    ticket_channel,
                    interaction.user,
                )
            )

            if result is None:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "I couldn't reopen this ticket."
                    )
                )

                return

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['approved']} "
                    "Modmail ticket reopened successfully."
                )
            )

            return

        # ====================================================
        # TRANSCRIPT
        # ====================================================

        if selected_action == "transcript":

            await interaction.response.defer(
                ephemeral=True
            )

            success = (
                await integration.send_transcript(
                    ticket_channel,
                    interaction.user,
                )
            )

            await interaction.edit_original_response(
                content=(
                    (
                        f"{EMOJI['approved']} "
                        "Transcript generated and sent to the "
                        "configured Modmail log channel."
                    )
                    if success
                    else
                    (
                        f"{EMOJI['error']} "
                        "I couldn't generate or send the transcript."
                    )
                )
            )

            return

        # ====================================================
        # USER ID VALIDATION
        # ====================================================

        if selected_action in {
            "block",
            "unblock",
        }:

            if not user_id:

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "You must provide a Discord **user ID**.",
                    ephemeral=True,
                )

                return

            user_id = user_id.strip()

            if not user_id.isdigit():

                await interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "The user ID must contain numbers only.",
                    ephemeral=True,
                )

                return

            target_user_id = int(
                user_id
            )

        # ====================================================
        # BLOCK
        # ====================================================

        if selected_action == "block":

            await interaction.response.defer(
                ephemeral=True
            )

            added = (
                await integration.block_user(
                    target_user_id,
                    interaction.user,
                )
            )

            if added:

                content = (
                    f"{EMOJI['approved']} "
                    f"User `{target_user_id}` has been blocked "
                    "from using Modmail."
                )

            else:

                content = (
                    f"{EMOJI['denied']} "
                    f"User `{target_user_id}` is already blocked."
                )

            await interaction.edit_original_response(
                content=content
            )

            return

        # ====================================================
        # UNBLOCK
        # ====================================================

        if selected_action == "unblock":

            await interaction.response.defer(
                ephemeral=True
            )

            removed = (
                await integration.unblock_user(
                    target_user_id,
                    interaction.user,
                )
            )

            if removed:

                content = (
                    f"{EMOJI['approved']} "
                    f"User `{target_user_id}` has been unblocked "
                    "from Modmail."
                )

            else:

                content = (
                    f"{EMOJI['denied']} "
                    f"User `{target_user_id}` is not currently blocked."
                )

            await interaction.edit_original_response(
                content=content
            )

            return

        # ====================================================
        # UNKNOWN ACTION
        # ====================================================

        await interaction.response.send_message(
            f"{EMOJI['error']} "
            "Unknown Modmail action.",
            ephemeral=True,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        Modmail(bot)
    )