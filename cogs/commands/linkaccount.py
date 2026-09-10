from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from utilities.database import db
from cogs.utilities.emoji import EMOJI
from cogs.utilities.generate_code import generate_code


log = logging.getLogger("lunar.link")


# ============================================================
# CONFIG
# ============================================================

LUNAR_API_BASE = "https://api.lunarx.to"

LUNAR_PROFILE_ENDPOINT = (
    f"{LUNAR_API_BASE}/api/animes/profile"
)

LUNAR_NOTIFICATION_ENDPOINT = (
    f"{LUNAR_API_BASE}/api/notification/admin-send"
)

LINK_GUILD_ID = 1330574273760465029
VERIFIED_ROLE_ID = 1403390546164187217

LUNAR_BYPASS_TOKEN = os.getenv(
    "LUNAR_BYPASS_TOKEN"
)

LUNAR_TOKEN = os.getenv(
    "LUNAR_TOKEN"
)


# ============================================================
# ROLE MAP
# ============================================================

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
        "id": VERIFIED_ROLE_ID,
        "emoji": "👤",
        "name": "User",
    },
}


# ============================================================
# CONFIGURATION
# ============================================================

FAKE_LOADING_TIME = 3.0
ROLE_SYNC_COOLDOWN = 30.0
LINK_SESSION_TIMEOUT = 600


# ============================================================
# EMBEDS
# ============================================================

def make_embed(
    title: str,
    description: str,
    *,
    color: discord.Color | None = None,
) -> discord.Embed:

    embed = discord.Embed(
        title=title,
        description=description,
        color=color or discord.Color.blurple(),
        timestamp=discord.utils.utcnow(),
    )

    embed.set_footer(
        text="Lunar Sync • Imperial Systems"
    )

    return embed


# ============================================================
# HELPERS
# ============================================================

def normalize_username(
    username: str,
) -> str:

    return username.strip()


def normalize_code(
    code: str,
) -> str:

    return code.strip().upper()


def get_profile_roles(
    profile: dict,
) -> set[str]:

    raw_roles = (
        profile.get("role")
        or ""
    )

    if not isinstance(
        raw_roles,
        str,
    ):
        return set()

    return {
        role.strip().lower()
        for role in raw_roles.split("|")
        if role.strip()
    }


# ============================================================
# USERNAME MODAL
# ============================================================

class LinkUsernameModal(
    discord.ui.Modal,
    title="Link Lunar Account",
):

    username = discord.ui.TextInput(
        label="Lunar Username",
        placeholder="Enter your Lunar Anime username...",
        min_length=1,
        max_length=64,
        required=True,
    )

    def __init__(
        self,
        cog: "LinkAccount",
    ):
        super().__init__()

        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        username = normalize_username(
            str(
                self.username.value
            )
        )

        await interaction.response.defer(
            ephemeral=True
        )

        await self.cog.start_link(
            interaction,
            username,
        )


# ============================================================
# VERIFICATION MODAL
# ============================================================

class LinkCodeModal(
    discord.ui.Modal,
    title="Verify Lunar Account",
):

    code = discord.ui.TextInput(
        label="Verification Code",
        placeholder="Paste the code from your Lunar notifications...",
        min_length=1,
        max_length=256,
        required=True,
    )

    def __init__(
        self,
        cog: "LinkAccount",
    ):
        super().__init__()

        self.cog = cog

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        code = normalize_code(
            str(
                self.code.value
            )
        )

        await interaction.response.defer(
            ephemeral=True
        )

        await self.cog.verify_link(
            interaction,
            code,
        )


# ============================================================
# VERIFICATION VIEW
# ============================================================

class VerificationView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "LinkAccount",
    ):

        super().__init__(
            timeout=LINK_SESSION_TIMEOUT
        )

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
    ):

        await interaction.response.send_modal(
            LinkCodeModal(
                self.cog
            )
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        embed = make_embed(
            f"{EMOJI['denied']} Linking Cancelled",
            (
                "Your Lunar account linking session "
                "has been cancelled."
            ),
            color=discord.Color.dark_grey(),
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None,
        )

    async def on_timeout(
        self,
    ) -> None:

        for item in self.children:
            item.disabled = True


# ============================================================
# ROLE SYNC VIEW
# ============================================================

class RoleSyncView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "LinkAccount",
    ):

        super().__init__(
            timeout=300
        )

        self.cog = cog

    @discord.ui.button(
        label="Sync My Roles",
        style=discord.ButtonStyle.success,
        emoji="🔄",
    )
    async def sync_roles(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await self.cog.sync_roles(
            interaction
        )

    @discord.ui.button(
        label="Skip",
        style=discord.ButtonStyle.secondary,
        emoji="⏭️",
    )
    async def skip_roles(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        embed = make_embed(
            f"{EMOJI['approved']} Account Linked",
            (
                f"{EMOJI['lunar']} **Lunar Account**\n"
                "> Your Lunar Anime account is linked successfully.\n\n"
                f"{EMOJI['approved']} **Verification**\n"
                "> Your account has been verified.\n\n"
                "⏭️ **Role Sync**\n"
                "> Skipped for now.\n\n"
                "You can synchronize your Lunar roles later."
            ),
            color=discord.Color.green(),
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.response.edit_message(
            content=None,
            embed=embed,
            view=None,
        )

    async def on_timeout(
        self,
    ) -> None:

        for item in self.children:
            item.disabled = True


# ============================================================
# LINK COG
# ============================================================

class LinkAccount(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ):

        self.bot = bot

        self.session: Optional[
            aiohttp.ClientSession
        ] = None

        self.role_sync_cooldowns: dict[
            int,
            float,
        ] = {}

    # ========================================================
    # LIFECYCLE
    # ========================================================

    async def cog_load(
        self,
    ) -> None:

        self.session = (
            aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=15
                )
            )
        )

    async def cog_unload(
        self,
    ) -> None:

        if (
            self.session
            and not self.session.closed
        ):

            await self.session.close()

    # ========================================================
    # LOADING UX
    # ========================================================

    async def loading(
        self,
        interaction: discord.Interaction,
        title: str,
        description: str,
        *,
        delay: float = FAKE_LOADING_TIME,
    ) -> None:

        embed = make_embed(
            f"{EMOJI['loading']} {title}",
            description,
            color=discord.Color.blurple(),
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=None,
        )

        await asyncio.sleep(
            delay
        )

    # ========================================================
    # LUNAR PROFILE
    # ========================================================

    async def fetch_profile(
        self,
        username: str,
    ) -> Optional[dict]:

        if self.session is None:
            return None

        headers = {}

        if LUNAR_BYPASS_TOKEN:
            headers[
                "X-Scraper-Guard-Bypass"
            ] = LUNAR_BYPASS_TOKEN

        try:

            async with self.session.get(
                LUNAR_PROFILE_ENDPOINT,
                params={
                    "username": username,
                },
                headers=headers,
            ) as response:

                if response.status != 200:

                    log.warning(
                        "Lunar profile failed: "
                        "username=%s status=%s",
                        username,
                        response.status,
                    )

                    return None

                payload = await response.json()

                if not isinstance(
                    payload,
                    dict,
                ):
                    return None

                profile = payload.get(
                    "data"
                )

                if not isinstance(
                    profile,
                    dict,
                ):
                    return None

                return profile

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            log.exception(
                "Lunar profile request failed: %s",
                username,
            )

            return None

    # ========================================================
    # LUNAR NOTIFICATION
    # ========================================================

    async def send_notification(
        self,
        username: str,
        code: str,
    ) -> bool:

        if self.session is None:
            return False

        headers = {
            "Content-Type": "application/json",
            "union": "lnr",
        }

        if LUNAR_BYPASS_TOKEN:
            headers[
                "X-Scraper-Guard-Bypass"
            ] = LUNAR_BYPASS_TOKEN

        if LUNAR_TOKEN:
            headers[
                "Authorization"
            ] = LUNAR_TOKEN

        payload = {
            "user_identifier": username,
            "type_": "custom",
            "content": (
                "Please send this back "
                f"!link-code {code}"
            ),
        }

        try:

            async with self.session.post(
                LUNAR_NOTIFICATION_ENDPOINT,
                json=payload,
                headers=headers,
            ) as response:

                if 200 <= response.status < 300:
                    return True

                log.warning(
                    "Lunar notification failed: "
                    "username=%s status=%s",
                    username,
                    response.status,
                )

                return False

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            log.exception(
                "Lunar notification request failed: %s",
                username,
            )

            return False

    # ========================================================
    # DATABASE
    # ========================================================

    async def get_link(
        self,
        discord_id: int,
    ):

        return await db.account_links.get(
            str(discord_id)
        )

    async def get_username(
        self,
        discord_id: int,
    ) -> Optional[str]:

        return await db.account_links.get_username(
            str(discord_id)
        )

    # ========================================================
    # /LINK
    # ========================================================

    @app_commands.command(
        name="link",
        description="Link your Lunar Anime account to Discord.",
    )
    async def link(
        self,
        interaction: discord.Interaction,
    ) -> None:

        await interaction.response.send_modal(
            LinkUsernameModal(
                self
            )
        )

    # ========================================================
    # START LINK
    # ========================================================

    async def start_link(
        self,
        interaction: discord.Interaction,
        username: str,
    ) -> None:

        # ----------------------------------------------------
        # Fetch Lunar profile
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Checking Lunar Anime",
            (
                f"{EMOJI['loading']} "
                "Connecting to Lunar Anime...\n"
                f"{EMOJI['loading']} "
                "Looking up your account..."
            ),
        )

        profile = await self.fetch_profile(
            username
        )

        if not profile:

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Account Not Found",
                    (
                        f"I couldn't find a Lunar Anime account "
                        f"for `{username}`.\n\n"
                        "Check the username and try `/link` again."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Read actual Lunar identity
        # ----------------------------------------------------

        lunar_username = str(
            profile.get(
                "username"
            )
            or username
        ).strip()

        lunar_uuid = profile.get(
            "user_id"
        )

        if not lunar_uuid:

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Invalid Lunar Profile",
                    (
                        "Lunar returned the profile, but "
                        "no valid account UUID was provided."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Existing Discord link
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Checking Existing Link",
            (
                f"{EMOJI['approved']} "
                "Lunar account found.\n"
                f"{EMOJI['loading']} "
                "Checking your current Discord link..."
            ),
        )

        existing = await self.get_link(
            interaction.user.id
        )

        if existing:

            existing_uuid = getattr(
                existing,
                "lunar_uuid",
                None,
            )

            existing_username = (
                await self.get_username(
                    interaction.user.id
                )
            )

            if (
                existing_uuid
                and str(existing_uuid)
                == str(lunar_uuid)
                and getattr(
                    existing,
                    "verified",
                    False,
                )
            ):

                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['approved']} Already Linked",
                        (
                            f"{EMOJI['lunar']} "
                            f"**Lunar:** `{existing_username or lunar_username}`\n\n"
                            f"{EMOJI['approved']} "
                            "This Lunar account is already "
                            "linked and verified."
                        ),
                        color=discord.Color.green(),
                    ),
                )

                return

            if (
                existing_uuid
                and str(existing_uuid)
                != str(lunar_uuid)
            ):

                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['denied']} Account Already Linked",
                        (
                            "Your Discord account is already "
                            "linked to a different Lunar account.\n\n"
                            "Unlink the existing account before "
                            "linking another one."
                        ),
                        color=discord.Color.red(),
                    ),
                )

                return

        # ----------------------------------------------------
        # Check whether Lunar account is already linked
        # elsewhere
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Checking Lunar Ownership",
            (
                f"{EMOJI['approved']} "
                "Discord link checked.\n"
                f"{EMOJI['loading']} "
                "Making sure this Lunar account isn't "
                "already linked elsewhere..."
            ),
        )

        try:

            lunar_existing = (
                await db.account_links.get_by_lunar_uuid(
                    lunar_uuid
                )
            )

        except Exception:

            log.exception(
                "Failed Lunar UUID lookup."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Database Error",
                    (
                        "I couldn't verify whether this "
                        "Lunar account is already linked."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        if (
            lunar_existing
            and str(
                lunar_existing.snowflake_id
            ) != str(
                interaction.user.id
            )
        ):

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['denied']} Lunar Account Already Linked",
                    (
                        "This Lunar account is already linked "
                        "to another Discord account.\n\n"
                        "One Lunar account can only be linked "
                        "to one Discord account."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Generate code
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Generating Verification",
            (
                f"{EMOJI['approved']} "
                "Account ownership checks passed.\n"
                f"{EMOJI['loading']} "
                "Generating your verification code..."
            ),
        )

        try:

            code = generate_code(
                interaction.user.name,
                lunar_username,
            )

        except Exception:

            log.exception(
                "Verification code generation failed."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Verification Error",
                    (
                        "I couldn't generate your verification code."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Save pending link
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Preparing Verification",
            (
                f"{EMOJI['approved']} "
                "Verification generated.\n"
                f"{EMOJI['loading']} "
                "Saving your account-link request..."
            ),
        )

        try:

            await db.account_links.link(
                interaction.user.id,
                lunar_uuid,
                code,
                verified=False,
                metadata={
                    "username": lunar_username,
                },
            )

        except Exception:

            log.exception(
                "Failed to create account link."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Database Error",
                    (
                        "I couldn't save your verification request."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Send Lunar notification
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Contacting Lunar",
            (
                f"{EMOJI['approved']} "
                "Verification request saved.\n"
                f"{EMOJI['loading']} "
                "Sending your code to Lunar notifications..."
            ),
        )

        notification_sent = (
            await self.send_notification(
                lunar_username,
                code,
            )
        )

        if not notification_sent:

            # Keep the pending link so a retry can use
            # the stored code/request if necessary.
            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Notification Failed",
                    (
                        "Your account was found, but Lunar "
                        "didn't accept the verification notification.\n\n"
                        "Please try `/link` again."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Verification screen
        # ----------------------------------------------------

        embed = make_embed(
            f"{EMOJI['verify']} Lunar Verification",
            (
                f"{EMOJI['lunar']} **Account Found**\n"
                f"> `{lunar_username}`\n\n"
                f"{EMOJI['approved']} **Verification Sent**\n"
                "> I've sent your verification code to "
                "your Lunar notifications.\n\n"
                f"{EMOJI['loading']} **Next Step**\n"
                "> Open Lunar, find the notification, and "
                "copy the verification code.\n\n"
                "Then click **I've Checked Lunar** below."
            ),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Verification",
            value="`Waiting for code`",
            inline=True,
        )

        embed.add_field(
            name="Session",
            value="`10 minutes`",
            inline=True,
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=VerificationView(
                self
            ),
        )

    # ========================================================
    # VERIFY LINK
    # ========================================================

    async def verify_link(
        self,
        interaction: discord.Interaction,
        code: str,
    ) -> None:

        # ----------------------------------------------------
        # Retrieve account
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Checking Verification",
            (
                f"{EMOJI['loading']} "
                "Loading your pending Lunar link..."
            ),
        )

        account = await self.get_link(
            interaction.user.id
        )

        if not account:

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} No Verification Found",
                    (
                        "You don't currently have a pending "
                        "Lunar verification request.\n\n"
                        "Start again with `/link`."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        if getattr(
            account,
            "verified",
            False,
        ):

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['approved']} Already Verified",
                    (
                        "Your Lunar account is already verified "
                        "and linked to Discord."
                    ),
                    color=discord.Color.green(),
                ),
            )

            return

        expected_code = str(
            getattr(
                account,
                "verification_code",
                "",
            )
            or ""
        ).strip().upper()

        if not expected_code:

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Verification Missing",
                    (
                        "Your verification request no longer "
                        "contains a valid verification code.\n\n"
                        "Please start `/link` again."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Compare code
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Validating Code",
            (
                f"{EMOJI['approved']} "
                "Verification request found.\n"
                f"{EMOJI['loading']} "
                "Comparing your verification code..."
            ),
        )

        if not secrets_compare(
            expected_code,
            code,
        ):

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['denied']} Incorrect Code",
                    (
                        "The verification code you entered "
                        "doesn't match the code sent by Lunar.\n\n"
                        "Check your Lunar notifications and try again."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Verify
        # ----------------------------------------------------

        await self.loading(
            interaction,
            "Finalizing Account",
            (
                f"{EMOJI['approved']} "
                "Verification code matched.\n"
                f"{EMOJI['loading']} "
                "Finalizing your Lunar account link..."
            ),
        )

        try:

            verified = (
                await db.account_links.set_verified(
                    interaction.user.id,
                    True,
                )
            )

            if not verified:

                raise RuntimeError(
                    "Account link disappeared while verifying."
                )

            username = (
                await db.account_links.get_username(
                    interaction.user.id
                )
            )

        except Exception:

            log.exception(
                "Failed to verify Lunar account."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Verification Error",
                    (
                        "The verification code was correct, "
                        "but I couldn't finalize your account link."
                    ),
                    color=discord.Color.red(),
                ),
            )

            return

        # ----------------------------------------------------
        # Success
        # ----------------------------------------------------

        embed = make_embed(
            f"{EMOJI['approved']} Account Verified",
            (
                f"{EMOJI['lunar']} **Lunar Account**\n"
                f"> `{username or 'Unknown'}`\n\n"
                f"{EMOJI['verify']} **Verification Complete**\n"
                "> Your Lunar Anime account is now linked "
                "and verified with Discord.\n\n"
                "Would you like to synchronize your "
                "Lunar roles with Discord?"
            ),
            color=discord.Color.green(),
        )

        embed.add_field(
            name="Lunar",
            value=f"`{username or 'Unknown'}`",
            inline=True,
        )

        embed.add_field(
            name="Status",
            value=f"{EMOJI['approved']} Verified",
            inline=True,
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        await interaction.edit_original_response(
            content=None,
            embed=embed,
            view=RoleSyncView(
                self
            ),
        )

        log.info(
            "Lunar account verified: Discord=%s Lunar=%s",
            interaction.user.id,
            username,
        )

    # ========================================================
    # ROLE SYNC
    # ========================================================

    async def sync_roles(
        self,
        interaction: discord.Interaction,
    ) -> None:

        now = asyncio.get_running_loop().time()

        last_sync = (
            self.role_sync_cooldowns.get(
                interaction.user.id
            )
        )

        if (
            last_sync is not None
            and now - last_sync < ROLE_SYNC_COOLDOWN
        ):

            remaining = int(
                ROLE_SYNC_COOLDOWN
                - (
                    now - last_sync
                )
            )

            await interaction.response.send_message(
                (
                    f"{EMOJI['loading']} "
                    f"Role sync is on cooldown. "
                    f"Try again in `{remaining}s`."
                ),
                ephemeral=True,
            )

            return

        self.role_sync_cooldowns[
            interaction.user.id
        ] = now

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            # ------------------------------------------------
            # Database
            # ------------------------------------------------

            await self.loading(
                interaction,
                "Loading Linked Account",
                (
                    f"{EMOJI['loading']} "
                    "Checking your verified Lunar account..."
                ),
            )

            account = await self.get_link(
                interaction.user.id
            )

            if not account or not account.verified:

                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['denied']} Account Not Verified",
                        (
                            "You need a verified Lunar account "
                            "before roles can be synchronized."
                        ),
                        color=discord.Color.red(),
                    ),
                    view=None,
                )

                return

            username = (
                await db.account_links.get_username(
                    interaction.user.id
                )
            )

            if not username:

                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['error']} Username Missing",
                        (
                            "Your account is verified, but the "
                            "Lunar username could not be retrieved."
                        ),
                        color=discord.Color.red(),
                    ),
                    view=None,
                )

                return

            # ------------------------------------------------
            # Lunar profile
            # ------------------------------------------------

            await self.loading(
                interaction,
                "Fetching Lunar Roles",
                (
                    f"{EMOJI['approved']} "
                    f"Verified as `{username}`.\n"
                    f"{EMOJI['loading']} "
                    "Fetching your latest Lunar roles..."
                ),
            )

            profile = await self.fetch_profile(
                username
            )

            if not profile:

                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['error']} Lunar Unavailable",
                        (
                            "I couldn't retrieve your latest "
                            "Lunar roles right now.\n\n"
                            "Your account remains linked."
                        ),
                        color=discord.Color.red(),
                    ),
                    view=None,
                )

                return

            lunar_roles = get_profile_roles(
                profile
            )

            # ------------------------------------------------
            # Discord member
            # ------------------------------------------------

            guild = self.bot.get_guild(
                LINK_GUILD_ID
            )

            if guild is None:

                await interaction.edit_original_response(
                    content=None,
                    embed=make_embed(
                        f"{EMOJI['error']} Guild Unavailable",
                        (
                            "I couldn't access the Lunar Discord server."
                        ),
                        color=discord.Color.red(),
                    ),
                    view=None,
                )

                return

            member = guild.get_member(
                interaction.user.id
            )

            if member is None:

                try:

                    member = await guild.fetch_member(
                        interaction.user.id
                    )

                except discord.NotFound:

                    await interaction.edit_original_response(
                        content=None,
                        embed=make_embed(
                            f"{EMOJI['error']} Member Not Found",
                            (
                                "I couldn't find your Discord "
                                "member profile in the Lunar server."
                            ),
                            color=discord.Color.red(),
                        ),
                        view=None,
                    )

                    return

            # ------------------------------------------------
            # Apply roles
            # ------------------------------------------------

            await self.loading(
                interaction,
                "Synchronizing Roles",
                (
                    f"{EMOJI['approved']} "
                    "Lunar roles retrieved.\n"
                    f"{EMOJI['loading']} "
                    "Comparing Discord roles..."
                ),
            )

            added: list[str] = []
            removed: list[str] = []
            unchanged: list[str] = []

            configured_role_ids = {
                role_data["id"]
                for role_data in (
                    LUNAR_ROLE_MAP.values()
                )
            }

            # Add / keep mapped roles.
            for role_name, role_data in (
                LUNAR_ROLE_MAP.items()
            ):

                role = guild.get_role(
                    role_data["id"]
                )

                if role is None:
                    continue

                should_have = (
                    role_name
                    in lunar_roles
                )

                has_role = (
                    role
                    in member.roles
                )

                if should_have:

                    if not has_role:

                        await member.add_roles(
                            role,
                            reason=(
                                "Lunar role synchronization"
                            ),
                        )

                        added.append(
                            f"{role_data['emoji']} "
                            f"{role_data['name']}"
                        )

                    else:

                        unchanged.append(
                            f"{role_data['emoji']} "
                            f"{role_data['name']}"
                        )

                elif (
                    has_role
                    and role.id != VERIFIED_ROLE_ID
                ):

                    await member.remove_roles(
                        role,
                        reason=(
                            "Lunar role synchronization"
                        ),
                    )

                    removed.append(
                        f"{role_data['emoji']} "
                        f"{role_data['name']}"
                    )

            # ------------------------------------------------
            # Result
            # ------------------------------------------------

            added_text = (
                "\n".join(
                    f"> {value}"
                    for value in added
                )
                if added
                else "> None"
            )

            removed_text = (
                "\n".join(
                    f"> {value}"
                    for value in removed
                )
                if removed
                else "> None"
            )

            unchanged_text = (
                "\n".join(
                    f"> {value}"
                    for value in unchanged
                )
                if unchanged
                else "> None"
            )

            embed = make_embed(
                f"{EMOJI['approved']} Role Sync Complete",
                (
                    f"{EMOJI['lunar']} **Lunar Account**\n"
                    f"> `{username}`\n\n"
                    "➕ **Added**\n"
                    f"{added_text}\n\n"
                    "➖ **Removed**\n"
                    f"{removed_text}\n\n"
                    "✅ **Already Correct**\n"
                    f"{unchanged_text}"
                ),
                color=discord.Color.green(),
            )

            embed.add_field(
                name="Changes",
                value=(
                    f"`{len(added)}` added\n"
                    f"`{len(removed)}` removed"
                ),
                inline=True,
            )

            embed.add_field(
                name="Lunar Roles",
                value=(
                    ", ".join(
                        sorted(
                            lunar_roles
                        )
                    )
                    or "None"
                ),
                inline=True,
            )

            embed.set_thumbnail(
                url=interaction.user.display_avatar.url
            )

            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=None,
            )

            log.info(
                (
                    "Role sync complete: "
                    "Discord=%s Lunar=%s Added=%s Removed=%s"
                ),
                interaction.user.id,
                username,
                len(added),
                len(removed),
            )

        except discord.Forbidden:

            log.exception(
                "Discord permissions prevented role sync."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Permission Error",
                    (
                        "Discord denied a role change.\n\n"
                        "Make sure the bot's highest role is "
                        "above the Lunar roles it needs to manage."
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
            )

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ):

            log.exception(
                "Lunar API error during role sync."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Lunar API Error",
                    (
                        "Lunar couldn't be reached while "
                        "synchronizing your roles.\n\n"
                        "Your account remains linked."
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
            )

        except Exception:

            log.exception(
                "Unexpected Lunar role synchronization error."
            )

            await interaction.edit_original_response(
                content=None,
                embed=make_embed(
                    f"{EMOJI['error']} Role Sync Failed",
                    (
                        "Something unexpected happened while "
                        "synchronizing your roles.\n\n"
                        "Your Lunar account remains linked."
                    ),
                    color=discord.Color.red(),
                ),
                view=None,
            )


# ============================================================
# CONSTANT-TIME STRING COMPARISON
# ============================================================

def secrets_compare(
    expected: str,
    supplied: str,
) -> bool:

    import secrets

    return secrets.compare_digest(
        expected,
        supplied,
    )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):

    await bot.add_cog(
        LinkAccount(bot)
    )
