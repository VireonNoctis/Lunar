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


# ═══════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════

LUNAR_API_BASE = "https://api.lunarx.to"

LINK_GUILD_ID = 1330574273760465029
LINKED_ROLE_ID = 1403390546164187217

# Replace these with your existing configuration values.
BYPASS_TOKEN = "bypass_token"
LUNAR_TOKEN = "lunar_token"

# Fake UX delay.
# These are intentionally longer than the actual requests
# so the process feels deliberate and polished.
FAKE_LOADING_TIME = 3.5


# ═══════════════════════════════════════════════
# Lunar → Discord Role Mapping
# ═══════════════════════════════════════════════

LUNAR_ROLE_MAP = {
    "admin": {
        "id": 1343141519283978260,
        "emoji": "👑",
        "name": "Admin",
    },
    "moderator": {
        "id": 1343141581334511616,
        "emoji": "🛡️",
        "name": "Moderator",
    },
    "donor": {
        "id": 1515063228223455442,
        "emoji": "💎",
        "name": "Donor",
    },
    "novel": {
        "id": 1515331236825137152,
        "emoji": "📖",
        "name": "Novel",
    },
    "manga": {
        "id": 1498726205937942598,
        "emoji": "📚",
        "name": "Manga",
    },
    "user": {
        "id": 1403390546164187217,
        "emoji": "🤵",
        "name": "User",
    },
}


# ═══════════════════════════════════════════════
# Shared Embed Helpers
# ═══════════════════════════════════════════════

def make_embed(
    title: str,
    description: str,
) -> discord.Embed:
    """Create a consistent Lunar-style embed."""

    embed = discord.Embed(
        title=title,
        description=description,
    )

    embed.set_footer(
        text="✨ Lunar Sync • Made by Vireon"
    )

    return embed


# ═══════════════════════════════════════════════
# Username Modal
# ═══════════════════════════════════════════════

class LinkUsernameModal(
    discord.ui.Modal,
    title="Link Lunar Anime Account",
):
    username = discord.ui.TextInput(
        label="Lunar Anime Username",
        placeholder="Enter your Lunar Anime username...",
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


# ═══════════════════════════════════════════════
# Verification Code Modal
# ═══════════════════════════════════════════════

class LinkCodeModal(
    discord.ui.Modal,
    title="Verify Lunar Anime Account",
):
    code = discord.ui.TextInput(
        label="Verification Code",
        placeholder="Paste the code from Lunar notifications...",
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


# ═══════════════════════════════════════════════
# Role Sync View
# ═══════════════════════════════════════════════

class RoleSyncView(discord.ui.View):
    def __init__(self, cog: "LinkAccount"):
        super().__init__(timeout=300)

        self.cog = cog

    @discord.ui.button(
        label="Sync My Roles",
        style=discord.ButtonStyle.success,
        emoji="✨",
    )
    async def sync_roles(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self.cog.sync_roles(interaction)

    @discord.ui.button(
        label="Skip",
        style=discord.ButtonStyle.secondary,
        emoji="⏭️",
    )
    async def skip_roles(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        embed = make_embed(
            f"{EMOJI['approved']} Account Linked",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['lunar']} **Lunar Account**\n"
                "> Your Lunar Anime account is linked successfully.\n\n"
                f"{EMOJI['approved']} **Verification**\n"
                "> Your account has been verified.\n\n"
                f"⏭️ **Role Sync**\n"
                "> Skipped for now.\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "You can synchronize your Lunar roles later."
            ),
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ═══════════════════════════════════════════════
# Verification View
# ═══════════════════════════════════════════════

class VerificationView(discord.ui.View):
    def __init__(self, cog: "LinkAccount"):
        super().__init__(timeout=600)

        self.cog = cog

    @discord.ui.button(
        label="I've Checked Lunar",
        style=discord.ButtonStyle.primary,
        emoji="✅",
    )
    async def verify(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            LinkCodeModal(self.cog)
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


# ═══════════════════════════════════════════════
# Link Account Cog
# ═══════════════════════════════════════════════

class LinkAccount(commands.Cog):
    """Interactive Lunar Anime account linking."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None

    # ═══════════════════════════════════════════
    # Lifecycle
    # ═══════════════════════════════════════════

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )

    async def cog_unload(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # ═══════════════════════════════════════════
    # Loading UX
    # ═══════════════════════════════════════════

    async def loading(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        delay: float = FAKE_LOADING_TIME,
    ) -> None:
        """Display a loading state with a deliberate UX delay."""

        embed = make_embed(
            f"{EMOJI['loading']} {title}",
            description,
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=None,
        )

        await asyncio.sleep(delay)

    # ═══════════════════════════════════════════
    # Lunar API
    # ═══════════════════════════════════════════

    async def fetch_account(
        self,
        username: str,
    ) -> Optional[dict]:
        """Fetch a Lunar Anime account by username."""

        if self.session is None:
            return None

        try:
            async with self.session.get(
                f"{LUNAR_API_BASE}/api/animes/profile",
                params={
                    "username": username,
                },
                headers={
                    "X-Scraper-Guard-Bypass": BYPASS_TOKEN,
                },
            ) as response:

                if response.status != 200:
                    logger.warning(
                        "Lunar account lookup failed: %s [%s]",
                        username,
                        response.status,
                    )
                    return None

                return await response.json()

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            logger.exception(
                "Lunar API request failed for %s",
                username,
            )
            return None

    async def send_notification(
        self,
        username: str,
        code: str,
    ) -> bool:
        """Send the verification code to Lunar notifications."""

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

                if 200 <= response.status < 300:
                    return True

                logger.warning(
                    "Lunar notification failed for %s: HTTP %s",
                    username,
                    response.status,
                )

                return False

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            logger.exception(
                "Failed to send Lunar notification to %s",
                username,
            )
            return False

    # ═══════════════════════════════════════════
    # Database
    # ═══════════════════════════════════════════

    async def get_link(
        self,
        discord_id: int,
    ):
        """Get the Discord user's account-link record."""

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
        """Create a pending Lunar account link."""

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
        """Mark a pending link as verified."""

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

    # ═══════════════════════════════════════════
    # /link
    # ═══════════════════════════════════════════

    @app_commands.command(
        name="link",
        description="Link your Lunar Anime account.",
    )
    async def link(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Open the interactive Lunar account linker."""

        await interaction.response.send_modal(
            LinkUsernameModal(self)
        )

    # ═══════════════════════════════════════════
    # Start Linking
    # ═══════════════════════════════════════════

    async def start_link(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:

        if not username:
            await interaction.followup.send(
                f"{EMOJI['error']} "
                "Please enter a Lunar Anime username.",
                ephemeral=True,
            )
            return

        # ───────────────────────────────────────
        # Step 1 — Fetch account
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Checking Lunar Anime",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['loading']} Connecting to Lunar Anime...\n"
                "🔍 Looking up your account...\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
        )

        account_info = await self.fetch_account(
            username
        )

        if not account_info:
            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Account Not Found",
                    (
                        "I couldn't find a Lunar Anime account "
                        f"matching `{username}`.\n\n"
                        "Please check the username and try `/link` again."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Step 2 — Read account
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Reading Account",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Lunar account found\n"
                f"{EMOJI['loading']} Reading account information...\n"
                "⬜ Checking existing links\n"
                "⬜ Preparing verification\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
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
                embed=make_embed(
                    f"{EMOJI['error']} Invalid Account Response",
                    (
                        "Lunar Anime returned account information "
                        "that I couldn't process."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Step 3 — Database check
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Checking Existing Links",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Lunar account found\n"
                f"{EMOJI['approved']} Account information loaded\n"
                f"{EMOJI['loading']} Checking linked accounts...\n"
                "⬜ Generating verification\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            1.5,
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
                embed=make_embed(
                    f"{EMOJI['error']} Database Error",
                    (
                        "Something went wrong while checking "
                        "your existing account link."
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
                    embed=make_embed(
                        f"{EMOJI['approved']} Already Linked",
                        (
                            "━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"{EMOJI['lunar']} **Lunar Account**\n"
                            f"> `{lunar_username}`\n\n"
                            f"{EMOJI['approved']} This account is "
                            "already linked to your Discord account.\n\n"
                            "━━━━━━━━━━━━━━━━━━━━"
                        ),
                    ),
                )
                return

        # ───────────────────────────────────────
        # Step 4 — Generate verification
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Generating Verification",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Account confirmed\n"
                f"{EMOJI['loading']} Generating verification code...\n"
                "🔐 Preparing secure verification request\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            2.0,
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
                embed=make_embed(
                    f"{EMOJI['error']} Verification Error",
                    (
                        "I couldn't generate a verification code.\n\n"
                        "Please try `/link` again."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Step 5 — Send notification
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Contacting Lunar Anime",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Account confirmed\n"
                f"{EMOJI['approved']} Verification generated\n"
                f"{EMOJI['loading']} Sending Lunar notification...\n"
                "⬜ Saving verification request\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            1.5,
        )

        notification_sent = await self.send_notification(
            lunar_username,
            verification_code,
        )

        if not notification_sent:
            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Notification Failed",
                    (
                        "I couldn't send the verification request "
                        "to your Lunar Anime account.\n\n"
                        "Please try again in a moment."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Step 6 — Save request
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Saving Verification",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Lunar notification sent\n"
                f"{EMOJI['loading']} Saving verification request...\n"
                "🔗 Preparing account link\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
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
                embed=make_embed(
                    f"{EMOJI['error']} Database Error",
                    (
                        "Your verification request couldn't be saved.\n\n"
                        "Please try `/link` again."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Final waiting screen
        # ───────────────────────────────────────

        embed = make_embed(
            f"{EMOJI['verify']} Verification Required",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['lunar']} **LUNAR ANIME**\n"
                f"> 👤 **Account:** `{lunar_username}`\n\n"
                f"{EMOJI['approved']} **Notification Sent**\n"
                "> A verification request has been sent to "
                "your Lunar Anime notifications.\n\n"
                f"{EMOJI['loading']} **Waiting for you...**\n"
                "> Open Lunar Anime and copy the verification "
                "code from your notifications.\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Once you've found it, click:\n"
                "> ✅ **I've Checked Lunar**\n\n"
                "Your verification session remains active for "
                "**10 minutes**."
            ),
        )

        embed.add_field(
            name="Verification",
            value=(
                f"{EMOJI['loading']} Waiting"
            ),
            inline=True,
        )

        embed.add_field(
            name="Account",
            value=f"🌙 `{lunar_username}`",
            inline=True,
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=VerificationView(self),
        )

    # ═══════════════════════════════════════════
    # Verify Link
    # ═══════════════════════════════════════════

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

        # ───────────────────────────────────────
        # Step 1 — Load pending request
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Checking Verification",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['loading']} Loading verification request...\n"
                "🔐 Preparing credential check\n"
                "⬜ Confirming account\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            1.5,
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
                embed=make_embed(
                    f"{EMOJI['error']} Database Error",
                    (
                        "I couldn't retrieve your verification request."
                    ),
                ),
            )
            return

        if account_link is None:
            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} No Verification Found",
                    (
                        "You don't currently have an active "
                        "Lunar account-linking request.\n\n"
                        "Start again with `/link`."
                    ),
                ),
            )
            return

        if account_link.verified:
            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['approved']} Already Verified",
                    (
                        "This Lunar Anime account has already "
                        "been linked to your Discord account."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Step 2 — Compare code
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Validating Verification",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Verification request found\n"
                f"{EMOJI['loading']} Comparing verification code...\n"
                "🔎 Checking account ownership\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            2.0,
        )

        if account_link.verification_code != code:
            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['denied']} Verification Failed",
                    (
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "The verification code you entered "
                        "doesn't match the code associated with "
                        "your pending request.\n\n"
                        "Please check your Lunar notifications "
                        "and try again."
                    ),
                ),
            )
            return

        # ───────────────────────────────────────
        # Step 3 — Verify database record
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Verifying Account",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['approved']} Verification code matched\n"
                f"{EMOJI['loading']} Confirming account ownership...\n"
                "🔗 Finalizing account link\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            1.5,
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
                embed=make_embed(
                    f"{EMOJI['error']} Verification Error",
                    (
                        "The verification code was correct, "
                        "but I couldn't finalize the account link."
                    ),
                ),
            )
            return

        lunar_username = "Unknown"

        if account_link.metadata:
            lunar_username = account_link.metadata.get(
                "lunar_username",
                "Unknown",
            )

        # ───────────────────────────────────────
        # Verified — Offer role sync
        # ───────────────────────────────────────

        embed = make_embed(
            f"{EMOJI['approved']} Account Verified",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['lunar']} **LUNAR ACCOUNT**\n"
                f"> 👤 **Username:** `{lunar_username}`\n\n"
                f"{EMOJI['approved']} **VERIFICATION COMPLETE**\n"
                "> Your Lunar Anime account is now securely "
                "linked to your Discord account.\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "✨ **One Last Step**\n\n"
                "Would you like me to synchronize your "
                "Lunar Anime roles with your Discord roles?\n\n"
                "This will add missing roles and remove roles "
                "that you no longer have on Lunar.\n\n"
                "Choose an option below:"
            ),
        )

        embed.add_field(
            name="🌙 Lunar",
            value=f"`{lunar_username}`",
            inline=True,
        )

        embed.add_field(
            name="🔗 Discord",
            value=interaction.user.mention,
            inline=True,
        )

        embed.add_field(
            name="✅ Status",
            value="Verified",
            inline=True,
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=RoleSyncView(self),
        )

        logger.info(
            "Lunar account verified: Discord=%s Lunar=%s UUID=%s",
            interaction.user.id,
            lunar_username,
            account_link.lunar_uuid,
        )

    # ═══════════════════════════════════════════
    # Role Synchronization
    # ═══════════════════════════════════════════

    async def sync_roles(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Synchronize Lunar roles with Discord roles."""

        started = asyncio.get_running_loop().time()

        # ───────────────────────────────────────
        # Starting
        # ───────────────────────────────────────

        await self.loading(
            interaction,
            "Starting Role Sync",
            (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['loading']} **Fetching Lunar Account**\n"
                "⬜ Checking Lunar Roles\n"
                "⬜ Checking Discord Roles\n"
                "⬜ Applying Changes\n\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            1.5,
        )

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

            # ───────────────────────────────────
            # Database
            # ───────────────────────────────────

            await self.loading(
                interaction,
                "Loading Linked Account",
                (
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{EMOJI['approved']} **Guild Connected**\n"
                    f"{EMOJI['loading']} **Loading Account Link**\n"
                    "⬜ Checking Lunar Roles\n"
                    "⬜ Applying Changes\n\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                ),
                1.25,
            )

            link = await self.get_link(
                interaction.user.id
            )

            if link is None or not link.verified:
                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['error']} Account Not Linked",
                        (
                            "I couldn't find a verified Lunar Anime "
                            "account for your Discord account."
                        ),
                    ),
                    view=None,
                )
                return

            # ───────────────────────────────────
            # Lunar API
            # ───────────────────────────────────

            await self.loading(
                interaction,
                "Fetching Lunar Roles",
                (
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{EMOJI['approved']} **Account Found**\n"
                    f"{EMOJI['loading']} **Fetching Lunar Roles**\n"
                    "⬜ Checking Discord Roles\n"
                    "⬜ Applying Changes\n\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                ),
                1.5,
            )

            if self.session is None:
                raise RuntimeError(
                    "HTTP session is not initialized."
                )

            async with self.session.get(
                f"{LUNAR_API_BASE}/api/animes/profile",
                params={
                    "user_id": str(link.lunar_uuid),
                },
                headers={
                    "X-Scraper-Guard-Bypass": BYPASS_TOKEN,
                    "Authorization": LUNAR_TOKEN,
                },
            ) as response:

                if response.status != 200:
                    raise RuntimeError(
                        f"Lunar API returned HTTP {response.status}."
                    )

                account = await response.json()

            lunar_data = account["data"]["data"]

            lunar_username = lunar_data.get(
                "username",
                "Unknown",
            )

            lunar_roles = (
                lunar_data
                .get("role", "")
                .split("|")
            )

            lunar_roles = {
                role.strip().lower()
                for role in lunar_roles
                if role.strip()
            }

            # ───────────────────────────────────
            # Discord role check
            # ───────────────────────────────────

            await self.loading(
                interaction,
                "Checking Discord Roles",
                (
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{EMOJI['approved']} **Lunar Account Found**\n"
                    f"{EMOJI['approved']} **Lunar Roles Retrieved**\n"
                    f"{EMOJI['loading']} **Checking Discord Roles**\n"
                    "⬜ Applying Changes\n\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                ),
                1.5,
            )

            added: list[str] = []
            owned: list[str] = []
            removed: list[str] = []

            # ───────────────────────────────────
            # Apply role changes
            # ───────────────────────────────────

            await self.loading(
                interaction,
                "Applying Roles",
                (
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{EMOJI['approved']} **Lunar Account Found**\n"
                    f"{EMOJI['approved']} **Lunar Roles Retrieved**\n"
                    f"{EMOJI['approved']} **Discord Roles Checked**\n"
                    f"{EMOJI['loading']} **Applying Changes**\n\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                ),
                1.5,
            )

            for role_name, role_data in LUNAR_ROLE_MAP.items():

                role = guild.get_role(
                    role_data["id"]
                )

                if role is None:
                    logger.warning(
                        "Configured role does not exist: %s (%s)",
                        role_name,
                        role_data["id"],
                    )
                    continue

                has_role = role in member.roles
                should_have = role_name in lunar_roles

                if should_have and not has_role:
                    await member.add_roles(
                        role,
                        reason="Lunar Anime role synchronization",
                    )

                    added.append(
                        f"{role_data['emoji']} "
                        f"{role_data['name']}"
                    )

                elif should_have and has_role:
                    owned.append(
                        f"{role_data['emoji']} "
                        f"{role_data['name']}"
                    )

                elif not should_have and has_role:
                    await member.remove_roles(
                        role,
                        reason="Lunar Anime role synchronization",
                    )

                    removed.append(
                        f"{role_data['emoji']} "
                        f"{role_data['name']}"
                    )

            # ───────────────────────────────────
            # Unmapped Lunar roles
            # ───────────────────────────────────

            unmapped = [
                role
                for role in lunar_roles
                if role not in LUNAR_ROLE_MAP
            ]

            elapsed = (
                asyncio.get_running_loop().time()
                - started
            )

            # ───────────────────────────────────
            # Build result
            # ───────────────────────────────────

            added_text = (
                "\n".join(added)
                if added
                else "> None"
            )

            owned_text = (
                "\n".join(owned)
                if owned
                else "> None"
            )

            removed_text = (
                "\n".join(removed)
                if removed
                else "> None"
            )

            description = (
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{EMOJI['lunar']} **LUNAR ACCOUNT**\n"
                f"> 👤 **User:** `{lunar_username}`\n"
                f"> 🆔 **UUID:** `{link.lunar_uuid}`\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"➕ **Added**\n"
                f"{added_text}\n\n"
                f"✔️ **Already Owned**\n"
                f"{owned_text}\n\n"
                f"➖ **Removed**\n"
                f"{removed_text}\n"
            )

            if unmapped:
                description += (
                    "\n⚠️ **Unmapped Lunar Roles**\n"
                    + "\n".join(
                        f"> `{role}`"
                        for role in unmapped
                    )
                    + "\n"
                )

            description += (
                "\n━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✨ **Updated:** "
                f"`{len(added) + len(removed)}`\n"
                f"⏱️ **Time:** `{elapsed:.2f}s`"
            )

            embed = make_embed(
                f"{EMOJI['lunar']} Role Sync Complete",
                description,
            )

            embed.set_thumbnail(
                url=interaction.user.display_avatar.url
            )

            embed.timestamp = discord.utils.utcnow()

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            logger.info(
                (
                    "Role sync completed: "
                    "Discord=%s Lunar=%s Added=%s Removed=%s"
                ),
                interaction.user.id,
                lunar_username,
                len(added),
                len(removed),
            )

        except discord.Forbidden:
            logger.exception(
                "Discord denied a role synchronization action."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Permission Error",
                    (
                        "I couldn't modify one or more Discord roles.\n\n"
                        "Please make sure the bot's role is positioned "
                        "above the roles it needs to manage."
                    ),
                ),
                view=None,
            )

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):
            logger.exception(
                "Lunar API error during role synchronization."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Lunar API Error",
                    (
                        "I couldn't retrieve your latest Lunar roles.\n\n"
                        "Your account is still linked successfully."
                    ),
                ),
                view=None,
            )

        except Exception:
            logger.exception(
                "Unexpected role synchronization error."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Role Sync Failed",
                    (
                        "Something went wrong while synchronizing "
                        "your Lunar roles.\n\n"
                        f"{EMOJI['approved']} Your account is still "
                        "linked successfully."
                    ),
                ),
                view=None,
            )


# ═══════════════════════════════════════════════
# Cog Setup
# ═══════════════════════════════════════════════

async def setup(bot: commands.Bot):
    await bot.add_cog(LinkAccount(bot))
