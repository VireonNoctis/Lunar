import asyncio
import logging
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.generate_code import generate_code


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

LUNAR_API_BASE = "https://api.lunarx.to"

LINK_GUILD_ID = 1330574273760465029
LINKED_ROLE_ID = 1403390546164187217

BYPASS_TOKEN = "bypass_token"
LUNAR_TOKEN = "lunar_token"

FAKE_LOAD_TIME = 3.5


# ─────────────────────────────────────────────
# Username Modal
# ─────────────────────────────────────────────

class LinkUsernameModal(
    discord.ui.Modal,
    title="Link Lunar Anime Account",
):
    username = discord.ui.TextInput(
        label="Lunar Anime Username",
        placeholder="Enter your Lunar Anime username",
        min_length=1,
        max_length=64,
        required=True,
    )

    def __init__(self, cog: "LinkAccount"):
        super().__init__()
        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        await self.cog.start_link(
            interaction,
            self.username.value.strip(),
        )


# ─────────────────────────────────────────────
# Verification Modal
# ─────────────────────────────────────────────

class LinkCodeModal(
    discord.ui.Modal,
    title="Verify Lunar Anime Account",
):
    code = discord.ui.TextInput(
        label="Verification Code",
        placeholder="Paste the code from your Lunar notifications",
        min_length=1,
        max_length=256,
        required=True,
    )

    def __init__(self, cog: "LinkAccount"):
        super().__init__()
        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.defer(
            ephemeral=True
        )

        await self.cog.verify_link(
            interaction,
            self.code.value.strip(),
        )


# ─────────────────────────────────────────────
# Verification Button
# ─────────────────────────────────────────────

class VerificationButton(discord.ui.Button):
    def __init__(self, cog: "LinkAccount"):
        super().__init__(
            label="I've Checked Lunar",
            style=discord.ButtonStyle.primary,
            emoji=EMOJI["verify"],
            custom_id="lunar_link:verify",
        )

        self.cog = cog

    async def callback(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_modal(
            LinkCodeModal(self.cog)
        )


# ─────────────────────────────────────────────
# Verification View
# ─────────────────────────────────────────────

class VerificationView(discord.ui.View):
    def __init__(self, cog: "LinkAccount"):
        super().__init__(timeout=600)

        self.add_item(
            VerificationButton(cog)
        )


# ─────────────────────────────────────────────
# Link Account Cog
# ─────────────────────────────────────────────

class LinkAccount(commands.Cog):
    """Interactive Lunar Anime account linking."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None

    # ─────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )

    async def cog_unload(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # ─────────────────────────────────────────
    # Loading
    # ─────────────────────────────────────────

    @staticmethod
    async def fake_load(
        interaction: discord.Interaction,
        text: str,
        duration: float = FAKE_LOAD_TIME,
    ) -> None:
        """Display a temporary loading state."""

        await interaction.edit_original_response(
            content=f"{EMOJI['loading']} {text}",
            embed=None,
            view=None,
        )

        await asyncio.sleep(duration)

    async def send_loading(
        self,
        interaction: discord.Interaction,
        text: str,
    ) -> None:
        await interaction.edit_original_response(
            content=f"{EMOJI['loading']} {text}",
            embed=None,
            view=None,
        )

    # ─────────────────────────────────────────
    # Lunar API
    # ─────────────────────────────────────────

    async def fetch_account(
        self,
        username: str,
    ) -> Optional[dict]:
        if self.session is None:
            return None

        try:
            async with self.session.get(
                f"{LUNAR_API_BASE}/api/animes/profile",
                params={"username": username},
                headers={
                    "X-Scraper-Guard-Bypass": BYPASS_TOKEN,
                },
            ) as response:

                if response.status != 200:
                    logger.warning(
                        "Lunar API returned HTTP %s for %s",
                        response.status,
                        username,
                    )
                    return None

                return await response.json()

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            logger.exception(
                "Failed to fetch Lunar account for %s",
                username,
            )
            return None

    async def send_notification(
        self,
        username: str,
        code: str,
    ) -> bool:
        if self.session is None:
            return False

        try:
            async with self.session.post(
                f"{LUNAR_API_BASE}/api/notification/admin-send",
                json={
                    "user_identifier": username,
                    "type_": "custom",
                    "content": (
                        "Please send this back "
                        f"!link-code {code}"
                    ),
                },
                headers={
                    "X-Scraper-Guard-Bypass": BYPASS_TOKEN,
                    "Authorization": LUNAR_TOKEN,
                    "Content-Type": "application/json",
                    "union": "lnr",
                },
            ) as response:

                return 200 <= response.status < 300

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            logger.exception(
                "Failed to send Lunar notification to %s",
                username,
            )
            return False

    # ─────────────────────────────────────────
    # Database
    # ─────────────────────────────────────────

    async def get_link(
        self,
        discord_id: int,
    ):
        result = await db.execute(
            """
            SELECT *
            FROM account_links
            WHERE snowflake_id = ?
            """,
            [str(discord_id)],
        )

        return result.one()

    async def save_link(
        self,
        discord_id: int,
        lunar_uuid,
        username: str,
        code: str,
    ) -> None:
        await db.execute(
            """
            INSERT INTO account_links (
                snowflake_id,
                lunar_uuid,
                verification_code,
                verified,
                linked_at,
                metadata
            )
            VALUES (?, ?, ?, ?, toTimestamp(now()), ?)
            """,
            [
                str(discord_id),
                lunar_uuid,
                code,
                False,
                {
                    "lunar_username": username,
                },
            ],
        )

    async def mark_verified(
        self,
        discord_id: int,
    ) -> None:
        await db.execute(
            """
            UPDATE account_links
            SET verified = ?,
                verified_at = toTimestamp(now())
            WHERE snowflake_id = ?
            """,
            [
                True,
                str(discord_id),
            ],
        )

    # ─────────────────────────────────────────
    # /link
    # ─────────────────────────────────────────

    @app_commands.command(
        name="link",
        description="Link your Lunar Anime account.",
    )
    async def link(
        self,
        interaction: discord.Interaction,
    ) -> None:
        await interaction.response.send_modal(
            LinkUsernameModal(self)
        )

    # ─────────────────────────────────────────
    # Start Linking
    # ─────────────────────────────────────────

    async def start_link(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:

        if not username:
            await interaction.followup.send(
                f"{EMOJI['error']} "
                "Please enter a valid Lunar Anime username.",
                ephemeral=True,
            )
            return

        # Stage 1
        await self.send_loading(
            interaction,
            "Checking Lunar Anime...",
        )

        account_info = await self.fetch_account(
            username
        )

        if not account_info:
            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Account Not Found",
                    description=(
                        "I couldn't find a Lunar Anime account "
                        f"named `{username}`."
                    ),
                ),
            )
            return

        # Stage 2
        await self.fake_load(
            interaction,
            "Reading Lunar account information...",
            1.5,
        )

        try:
            account_data = account_info["data"]["data"]

            lunar_uuid = account_data["user_id"]
            lunar_username = account_data.get(
                "username",
                username,
            )

        except (KeyError, TypeError):
            logger.exception(
                "Invalid Lunar API response."
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Invalid Response",
                    description=(
                        "Lunar Anime returned an invalid account "
                        "response."
                    ),
                ),
            )
            return

        # Stage 3
        await self.send_loading(
            interaction,
            "Checking existing account links...",
        )

        try:
            existing_link = await self.get_link(
                interaction.user.id
            )

        except Exception:
            logger.exception(
                "Database error while checking account link."
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Database Error",
                    description=(
                        "I couldn't check your existing account link."
                    ),
                ),
            )
            return

        if existing_link:
            if (
                str(existing_link.lunar_uuid)
                == str(lunar_uuid)
                and existing_link.verified
            ):
                await interaction.edit_original_response(
                    content=None,
                    embed=discord.Embed(
                        title=(
                            f"{EMOJI['approved']} "
                            "Already Linked"
                        ),
                        description=(
                            "This Lunar Anime account is "
                            "already linked to your Discord account."
                        ),
                    ),
                )
                return

        # Stage 4
        await self.fake_load(
            interaction,
            "Generating a secure verification code...",
            1.5,
        )

        try:
            verification_code = generate_code(
                interaction.user.name,
                lunar_username,
            )
        except Exception:
            logger.exception(
                "Failed to generate verification code."
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Generation Failed",
                    description=(
                        "I couldn't generate your verification code."
                    ),
                ),
            )
            return

        # Stage 5
        await self.send_loading(
            interaction,
            "Sending verification request to Lunar Anime...",
        )

        notification_sent = await self.send_notification(
            lunar_username,
            verification_code,
        )

        if not notification_sent:
            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Notification Failed",
                    description=(
                        "I couldn't send a notification to "
                        "your Lunar Anime account."
                    ),
                ),
            )
            return

        # Stage 6
        await self.fake_load(
            interaction,
            "Saving your verification request...",
            1.5,
        )

        try:
            await self.save_link(
                discord_id=interaction.user.id,
                lunar_uuid=lunar_uuid,
                username=lunar_username,
                code=verification_code,
            )

        except Exception:
            logger.exception(
                "Failed to save pending account link."
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Database Error",
                    description=(
                        "Your verification request could not be saved."
                    ),
                ),
            )
            return

        # Final state
        embed = discord.Embed(
            title=(
                f"{EMOJI['verify']} "
                "Verification Required"
            ),
            description=(
                f"A verification notification has been sent to "
                f"**{lunar_username}**.\n\n"
                "Open Lunar Anime and check your notifications "
                "for your verification code.\n\n"
                f"{EMOJI['loading']} "
                "**Waiting for your verification...**"
            ),
        )

        embed.add_field(
            name="Lunar Account",
            value=f"`{lunar_username}`",
            inline=True,
        )

        embed.add_field(
            name="Status",
            value=(
                f"{EMOJI['loading']} "
                "Waiting"
            ),
            inline=True,
        )

        embed.set_footer(
            text="This verification session expires after 10 minutes."
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=VerificationView(self),
        )

    # ─────────────────────────────────────────
    # Verify Link
    # ─────────────────────────────────────────

    async def verify_link(
        self,
        interaction: discord.Interaction,
        code: str,
    ) -> None:

        if not code:
            await interaction.followup.send(
                f"{EMOJI['error']} "
                "Please enter your verification code.",
                ephemeral=True,
            )
            return

        # Stage 1
        await self.send_loading(
            interaction,
            "Checking your verification request...",
        )

        try:
            account_link = await self.get_link(
                interaction.user.id
            )

        except Exception:
            logger.exception(
                "Database error while retrieving account link."
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Database Error",
                    description=(
                        "I couldn't check your verification request."
                    ),
                ),
            )
            return

        if account_link is None:
            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} No Request Found",
                    description=(
                        "You don't have an active account-linking request."
                    ),
                ),
            )
            return

        if account_link.verified:
            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['approved']} "
                        "Already Verified"
                    ),
                    description=(
                        "This account is already linked."
                    ),
                ),
            )
            return

        # Stage 2
        await self.fake_load(
            interaction,
            "Comparing verification credentials...",
            1.5,
        )

        if account_link.verification_code != code:
            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['denied']} "
                        "Verification Failed"
                    ),
                    description=(
                        "The verification code you entered "
                        "does not match our records."
                    ),
                ),
            )
            return

        # Stage 3
        await self.send_loading(
            interaction,
            "Verifying your Lunar Anime account...",
        )

        try:
            await self.mark_verified(
                interaction.user.id
            )

        except Exception:
            logger.exception(
                "Failed to mark account as verified."
            )

            await interaction.edit_original_response(
                content=None,
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Verification Error",
                    description=(
                        "I couldn't finish verifying your account."
                    ),
                ),
            )
            return

        # Stage 4
        await self.fake_load(
            interaction,
            "Finalizing your account link...",
            1.5,
        )

        lunar_username = "Unknown"

        if account_link.metadata:
            lunar_username = account_link.metadata.get(
                "lunar_username",
                "Unknown",
            )

        # Role assignment
        role_assigned = False

        try:
            guild = self.bot.get_guild(
                LINK_GUILD_ID
            )

            if guild is None:
                guild = await self.bot.fetch_guild(
                    LINK_GUILD_ID
                )

            member = guild.get_member(
                interaction.user.id
            )

            if member is None:
                member = await guild.fetch_member(
                    interaction.user.id
                )

            role = guild.get_role(
                LINKED_ROLE_ID
            )

            if role and role not in member.roles:
                await member.add_roles(
                    role,
                    reason="Lunar Anime account linked",
                )

            role_assigned = role is not None

        except discord.HTTPException:
            logger.exception(
                "Failed to assign linked role."
            )

        # Final success
        embed = discord.Embed(
            title=(
                f"{EMOJI['approved']} "
                "Account Linked"
            ),
            description=(
                "Your Lunar Anime account has been "
                "successfully linked to Discord."
            ),
        )

        embed.add_field(
            name="Lunar Account",
            value=f"`{lunar_username}`",
            inline=True,
        )

        embed.add_field(
            name="Verification",
            value=(
                f"{EMOJI['approved']} "
                "Verified"
            ),
            inline=True,
        )

        if role_assigned:
            embed.add_field(
                name="Discord Role",
                value=(
                    f"{EMOJI['approved']} "
                    "Assigned"
                ),
                inline=True,
            )

        embed.set_footer(
            text="Lunar Account Linking"
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=None,
        )

        logger.info(
            "Lunar account linked: Discord=%s Lunar=%s UUID=%s",
            interaction.user.id,
            lunar_username,
            account_link.lunar_uuid,
        )


# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(LinkAccount(bot))
