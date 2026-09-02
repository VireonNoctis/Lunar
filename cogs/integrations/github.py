import re
from datetime import datetime
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

from ..utilities.database import db
from ..utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

# The ONE GitHub repository to monitor.
GITHUB_REPO = "https://github.com/VireonNoctis/Lunar/"

# Discord channel where commit embeds are sent.
CHANNEL_ID = 1489719944135442607

# GitHub polling interval in seconds.
CHECK_INTERVAL = 25

# Maximum changed files shown inside the embed.
MAX_FILE_PREVIEW = 6


class GitHubCommits(commands.Cog):
    """
    GitHub commit monitoring integration.

    Monitors one repository and sends a Discord embed whenever
    a new commit is detected.

    Commit state and commit history are stored in ScyllaDB.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None

        self.repository_key = self._get_repository_key()

        self.check_commits.start()

    # ========================================================
    # CLEANUP
    # ========================================================

    def cog_unload(self):
        self.check_commits.cancel()

        if (
            self.session is not None
            and not self.session.closed
        ):
            self.bot.loop.create_task(
                self.session.close()
            )

    # ========================================================
    # REPOSITORY
    # ========================================================

    def _get_repository_key(self) -> str:
        """
        Returns:

            OWNER/REPOSITORY
        """

        repo = GITHUB_REPO.strip().rstrip("/")

        repo = re.sub(
            r"^https?://",
            "",
            repo,
            flags=re.IGNORECASE,
        )

        repo = re.sub(
            r"^www\.",
            "",
            repo,
            flags=re.IGNORECASE,
        )

        if repo.startswith("github.com/"):
            repo = repo[len("github.com/"):]

        repo = repo.removesuffix(".git")

        parts = repo.split("/")

        if len(parts) < 2:
            raise ValueError(
                "Invalid GITHUB_REPO. Expected "
                "'https://github.com/OWNER/REPOSITORY'."
            )

        return f"{parts[0]}/{parts[1]}"

    def _get_owner_repo(self):
        owner, repository = (
            self.repository_key.split("/", 1)
        )

        return owner, repository

    # ========================================================
    # HTTP
    # ========================================================

    async def get_session(self):
        if (
            self.session is None
            or self.session.closed
        ):
            self.session = aiohttp.ClientSession(
                headers={
                    "Accept": (
                        "application/vnd.github+json"
                    ),
                    "User-Agent": (
                        "Lunar-GitHub-Commit-Monitor"
                    ),
                    "X-GitHub-Api-Version": (
                        "2022-11-28"
                    ),
                }
            )

        return self.session

    async def github_get(self, url: str):
        session = await self.get_session()

        try:
            async with session.get(url) as response:

                if response.status == 404:
                    print(
                        f"[GitHub] Not found: {url}"
                    )
                    return None

                if response.status == 403:
                    print(
                        "[GitHub] Request rejected or "
                        "rate limited."
                    )
                    return None

                if response.status != 200:
                    print(
                        f"[GitHub] HTTP "
                        f"{response.status}: {url}"
                    )
                    return None

                return await response.json()

        except aiohttp.ClientError as error:
            print(
                f"[GitHub] Request failed: {error}"
            )

            return None

    # ========================================================
    # GITHUB API
    # ========================================================

    async def get_repository_info(self):
        owner, repository = (
            self._get_owner_repo()
        )

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repository}"
        )

        return await self.github_get(url)

    async def get_latest_commit(self):
        owner, repository = (
            self._get_owner_repo()
        )

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repository}"
            f"/commits?per_page=1"
        )

        commits = await self.github_get(
            url
        )

        if not commits:
            return None

        return commits[0]

    async def get_commit_details(
        self,
        sha: str,
    ):
        owner, repository = (
            self._get_owner_repo()
        )

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repository}"
            f"/commits/{sha}"
        )

        return await self.github_get(
            url
        )

    # ========================================================
    # REPOSITORY REGISTRATION
    # ========================================================

    async def ensure_repository(self):
        """
        Ensures the monitored repository exists
        in ScyllaDB.
        """

        repository = await db.github.get(
            self.repository_key
        )

        if repository:
            return repository

        repository_info = (
            await self.get_repository_info()
        )

        if not repository_info:
            return None

        await db.github.register_repository(
            self.repository_key,
            url=GITHUB_REPO,
            owner=repository_info.get(
                "owner",
                {},
            ).get(
                "login",
                self._get_owner_repo()[0],
            ),
            name=repository_info.get(
                "name",
                self._get_owner_repo()[1],
            ),
            branch=repository_info.get(
                "default_branch",
                "main",
            ),
            channel_id=CHANNEL_ID,
            enabled=True,
        )

        return await db.github.get(
            self.repository_key
        )

    # ========================================================
    # FORMATTERS
    # ========================================================

    @staticmethod
    def truncate(
        text: str,
        length: int,
    ) -> str:

        if len(text) <= length:
            return text

        return text[: length - 3] + "..."

    @staticmethod
    def get_message_parts(
        message: str,
    ):
        lines = message.splitlines()

        if not lines:
            return (
                "No commit message.",
                "",
            )

        title = lines[0].strip()

        body = "\n".join(
            line.rstrip()
            for line in lines[1:]
        ).strip()

        return title, body

    @staticmethod
    def get_author(
        commit: dict,
    ) -> str:

        github_author = (
            commit.get("author")
            or {}
        )

        git_author = (
            commit.get("commit", {})
            .get("author")
            or {}
        )

        return (
            github_author.get("login")
            or github_author.get("name")
            or git_author.get("name")
            or "Unknown"
        )

    @staticmethod
    def get_committer(
        commit: dict,
    ) -> str:

        github_committer = (
            commit.get("committer")
            or {}
        )

        git_committer = (
            commit.get("commit", {})
            .get("committer")
            or {}
        )

        return (
            github_committer.get("login")
            or github_committer.get("name")
            or git_committer.get("name")
            or "Unknown"
        )

    @staticmethod
    def get_avatar(
        commit: dict,
    ) -> Optional[str]:

        author = commit.get(
            "author"
        )

        if not author:
            return None

        return author.get(
            "avatar_url"
        )

    @staticmethod
    def get_timestamp(
        commit: dict,
    ) -> Optional[datetime]:

        raw_date = (
            commit.get("commit", {})
            .get("author", {})
            .get("date")
        )

        if not raw_date:
            return None

        try:
            return datetime.fromisoformat(
                raw_date.replace(
                    "Z",
                    "+00:00",
                )
            )

        except ValueError:
            return None

    # ========================================================
    # FILES
    # ========================================================

    def format_files(
        self,
        files: list[dict],
    ) -> str:

        if not files:
            return (
                "No changed-file information "
                "available."
            )

        output = []

        for file in files[
            :MAX_FILE_PREVIEW
        ]:

            filename = file.get(
                "filename",
                "Unknown",
            )

            status = file.get(
                "status",
                "modified",
            )

            additions = file.get(
                "additions",
                0,
            )

            deletions = file.get(
                "deletions",
                0,
            )

            if status == "added":
                icon = "🆕"

            elif status == "removed":
                icon = "🗑️"

            elif status == "renamed":
                icon = "↪️"

            else:
                icon = "📝"

            output.append(
                f"{icon} `{filename}` "
                f"`+{additions} -{deletions}`"
            )

        remaining = (
            len(files)
            - MAX_FILE_PREVIEW
        )

        if remaining > 0:
            output.append(
                f"*...and {remaining} "
                f"more file(s)*"
            )

        return "\n".join(output)

    # ========================================================
    # EMBED
    # ========================================================

    def create_embed(
        self,
        commit: dict,
        repository_info: Optional[dict],
        previous_sha: Optional[str],
    ) -> discord.Embed:

        commit_info = commit.get(
            "commit",
            {},
        )

        sha = commit.get(
            "sha",
            "",
        )

        short_sha = sha[:7]

        message = commit_info.get(
            "message",
            "No commit message.",
        )

        title, body = (
            self.get_message_parts(
                message
            )
        )

        author = self.get_author(
            commit
        )

        committer = self.get_committer(
            commit
        )

        timestamp = self.get_timestamp(
            commit
        )

        stats = commit.get(
            "stats",
            {},
        )

        additions = int(
            stats.get(
                "additions",
                0,
            )
        )

        deletions = int(
            stats.get(
                "deletions",
                0,
            )
        )

        total_changes = int(
            stats.get(
                "total",
                additions + deletions,
            )
        )

        files = commit.get(
            "files",
            [],
        )

        file_count = len(
            files
        )

        verification = (
            commit_info.get(
                "verification"
            )
            or {}
        )

        verified = bool(
            verification.get(
                "verified",
                False,
            )
        )

        is_merge = (
            len(
                commit_info.get(
                    "parents",
                    [],
                )
            )
            > 1
        )

        # ----------------------------------------------------
        # REPOSITORY INFO
        # ----------------------------------------------------

        owner, repository = (
            self._get_owner_repo()
        )

        full_name = (
            repository_info.get(
                "full_name"
            )
            if repository_info
            else None
        )

        if not full_name:
            full_name = (
                f"{owner}/{repository}"
            )

        branch = (
            repository_info.get(
                "default_branch",
                "main",
            )
            if repository_info
            else "main"
        )

        repo_description = (
            repository_info.get(
                "description"
            )
            if repository_info
            else None
        )

        repo_url = (
            repository_info.get(
                "html_url"
            )
            if repository_info
            else GITHUB_REPO
        )

        # ----------------------------------------------------
        # COLOR
        # ----------------------------------------------------

        if is_merge:
            embed_color = (
                discord.Color.purple()
            )

        elif verified:
            embed_color = (
                discord.Color.green()
            )

        else:
            embed_color = (
                discord.Color.dark_theme()
            )

        # ----------------------------------------------------
        # EMBED
        # ----------------------------------------------------

        embed = discord.Embed(
            title=(
                f"{EMOJI['new1']} "
                "New GitHub Commit"
            ),
            url=commit.get(
                "html_url",
                GITHUB_REPO,
            ),
            color=embed_color,
            timestamp=timestamp,
        )

        # ----------------------------------------------------
        # DESCRIPTION
        # ----------------------------------------------------

        description_parts = [
            f"### {self.truncate(title, 256)}"
        ]

        if body:
            description_parts.append(
                self.truncate(
                    body,
                    700,
                )
            )

        description_parts.append(
            f"\n{EMOJI['right']} "
            f"[View Commit]"
            f"({commit['html_url']})"
        )

        embed.description = (
            "\n".join(
                description_parts
            )
        )

        # ----------------------------------------------------
        # AUTHOR
        # ----------------------------------------------------

        embed.add_field(
            name=(
                f"{EMOJI['dev']} Author"
            ),
            value=f"`{author}`",
            inline=True,
        )

        # ----------------------------------------------------
        # COMMITTER
        # ----------------------------------------------------

        embed.add_field(
            name="👤 Committer",
            value=f"`{committer}`",
            inline=True,
        )

        # ----------------------------------------------------
        # SHA
        # ----------------------------------------------------

        embed.add_field(
            name="🔑 Commit",
            value=(
                f"[`{short_sha}`]"
                f"({commit['html_url']})"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # BRANCH
        # ----------------------------------------------------

        embed.add_field(
            name="🌿 Branch",
            value=f"`{branch}`",
            inline=True,
        )

        # ----------------------------------------------------
        # REPOSITORY
        # ----------------------------------------------------

        embed.add_field(
            name="📁 Repository",
            value=(
                f"[`{full_name}`]"
                f"({repo_url})"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # SIGNATURE
        # ----------------------------------------------------

        signature = (
            f"{EMOJI['verify']} **Verified**"
            if verified
            else
            f"{EMOJI['denied']} "
            "**Not Verified**"
        )

        embed.add_field(
            name="🔐 Signature",
            value=signature,
            inline=True,
        )

        # ----------------------------------------------------
        # CHANGES
        # ----------------------------------------------------

        embed.add_field(
            name="📊 Changes",
            value=(
                f"`{file_count}` files changed\n"
                f"`{total_changes}` total changes\n"
                f"`+{additions}` additions • "
                f"`-{deletions}` deletions"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # COMMIT TYPE
        # ----------------------------------------------------

        embed.add_field(
            name="🔀 Type",
            value=(
                "Merge Commit"
                if is_merge
                else "Commit"
            ),
            inline=True,
        )

        # ----------------------------------------------------
        # CHANGED FILES
        # ----------------------------------------------------

        embed.add_field(
            name="📂 Changed Files",
            value=self.format_files(
                files
            ),
            inline=False,
        )

        # ----------------------------------------------------
        # COMPARE
        # ----------------------------------------------------

        if previous_sha:

            compare_url = (
                f"https://github.com/"
                f"{owner}/{repository}"
                f"/compare/"
                f"{previous_sha}...{sha}"
            )

            embed.add_field(
                name="⚡ Changes",
                value=(
                    f"[Compare with Previous Commit]"
                    f"({compare_url})"
                ),
                inline=False,
            )

        # ----------------------------------------------------
        # REPOSITORY DESCRIPTION
        # ----------------------------------------------------

        if repo_description:

            embed.add_field(
                name="Repository Description",
                value=self.truncate(
                    repo_description,
                    300,
                ),
                inline=False,
            )

        # ----------------------------------------------------
        # AVATAR
        # ----------------------------------------------------

        avatar = self.get_avatar(
            commit
        )

        if avatar:

            embed.set_thumbnail(
                url=avatar
            )

        # ----------------------------------------------------
        # FOOTER
        # ----------------------------------------------------

        embed.set_footer(
            text=(
                f"{full_name} • "
                "GitHub Commit Monitor"
            )
        )

        return embed

    # ========================================================
    # INITIALIZATION
    # ========================================================

    async def initialize_repository(
        self,
    ):

        repository = (
            await self.ensure_repository()
        )

        if not repository:
            return None

        # ----------------------------------------------------
        # If Scylla already has a commit, use it.
        # ----------------------------------------------------

        if repository.last_commit_sha:
            return repository

        # ----------------------------------------------------
        # First launch.
        #
        # Record current HEAD but do NOT send notification.
        # ----------------------------------------------------

        latest = (
            await self.get_latest_commit()
        )

        if not latest:
            return repository

        sha = latest.get(
            "sha"
        )

        if not sha:
            return repository

        await db.github.set_last_commit(
            self.repository_key,
            sha,
        )

        print(
            f"[GitHub] Initialized "
            f"{self.repository_key} at "
            f"{sha[:7]}"
        )

        return await db.github.get(
            self.repository_key
        )

    # ========================================================
    # COMMIT PROCESSING
    # ========================================================

    async def process_commit(
        self,
        latest_commit: dict,
        repository,
    ):

        current_sha = latest_commit.get(
            "sha"
        )

        if not current_sha:
            return

        previous_sha = (
            repository.last_commit_sha
        )

        # ----------------------------------------------------
        # Nothing changed.
        # ----------------------------------------------------

        if current_sha == previous_sha:
            return

        # ----------------------------------------------------
        # Get complete commit information.
        # ----------------------------------------------------

        detailed_commit = (
            await self.get_commit_details(
                current_sha
            )
        )

        if not detailed_commit:
            return

        # ----------------------------------------------------
        # Repository info.
        # ----------------------------------------------------

        repository_info = (
            await self.get_repository_info()
        )

        # ----------------------------------------------------
        # Channel.
        # ----------------------------------------------------

        channel = self.bot.get_channel(
            CHANNEL_ID
        )

        if channel is None:

            try:
                channel = (
                    await self.bot.fetch_channel(
                        CHANNEL_ID
                    )
                )

            except discord.HTTPException as error:

                print(
                    f"[GitHub] Could not access "
                    f"channel {CHANNEL_ID}: "
                    f"{error}"
                )

                return

        # ----------------------------------------------------
        # Build embed.
        # ----------------------------------------------------

        embed = self.create_embed(
            detailed_commit,
            repository_info,
            previous_sha,
        )

        # ----------------------------------------------------
        # Send notification FIRST.
        #
        # We only update Scylla after Discord confirms
        # the message was sent successfully.
        # ----------------------------------------------------

        try:

            await channel.send(
                embed=embed
            )

        except discord.HTTPException as error:

            print(
                f"[GitHub] Failed to send "
                f"notification: {error}"
            )

            return

        # ----------------------------------------------------
        # Extract commit data for persistence.
        # ----------------------------------------------------

        commit_info = (
            detailed_commit.get(
                "commit",
                {},
            )
        )

        timestamp = (
            self.get_timestamp(
                detailed_commit
            )
        )

        if timestamp is None:
            timestamp = (
                datetime.now()
            )

        author = self.get_author(
            detailed_commit
        )

        committer = self.get_committer(
            detailed_commit
        )

        message = commit_info.get(
            "message",
            "",
        )

        branch = (
            repository_info.get(
                "default_branch",
                repository.branch
                or "main",
            )
            if repository_info
            else (
                repository.branch
                or "main"
            )
        )

        verification = (
            commit_info.get(
                "verification"
            )
            or {}
        )

        verified = bool(
            verification.get(
                "verified",
                False,
            )
        )

        stats = detailed_commit.get(
            "stats",
            {},
        )

        additions = int(
            stats.get(
                "additions",
                0,
            )
        )

        deletions = int(
            stats.get(
                "deletions",
                0,
            )
        )

        files = detailed_commit.get(
            "files",
            [],
        )

        changed_file_names = [
            file.get(
                "filename",
                "Unknown",
            )
            for file in files
        ]

        # ----------------------------------------------------
        # Persist commit history.
        # ----------------------------------------------------

        await db.github.record_commit(
            self.repository_key,

            committed_at=timestamp,

            sha=current_sha,

            author=author,

            committer=committer,

            message=message,

            branch=branch,

            verified=verified,

            additions=additions,

            deletions=deletions,

            changed_files=len(files),

            html_url=detailed_commit.get(
                "html_url",
                GITHUB_REPO,
            ),

            files=changed_file_names,
        )

        # ----------------------------------------------------
        # Move repository HEAD forward.
        # ----------------------------------------------------

        await db.github.set_last_commit(
            self.repository_key,
            current_sha,
        )

        # ----------------------------------------------------
        # Statistics.
        # ----------------------------------------------------

        await db.stats.increment(
            "github_commits",
            1,
        )

        print(
            f"[GitHub] New commit "
            f"{self.repository_key}@"
            f"{current_sha[:7]}"
        )

    # ========================================================
    # WATCHER
    # ========================================================

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_commits(self):

        try:

            repository = (
                await db.github.get(
                    self.repository_key
                )
            )

            # ------------------------------------------------
            # Register repository if necessary.
            # ------------------------------------------------

            if repository is None:

                repository = (
                    await self.ensure_repository()
                )

            if repository is None:
                return

            # ------------------------------------------------
            # Respect disabled state.
            # ------------------------------------------------

            if not repository.enabled:
                return

            # ------------------------------------------------
            # If it has never been initialized,
            # establish the current HEAD without notifying.
            # ------------------------------------------------

            if not repository.last_commit_sha:

                await self.initialize_repository()

                return

            # ------------------------------------------------
            # Check latest commit.
            # ------------------------------------------------

            latest_commit = (
                await self.get_latest_commit()
            )

            if latest_commit is None:
                return

            # ------------------------------------------------
            # Process.
            # ------------------------------------------------

            await self.process_commit(
                latest_commit,
                repository,
            )

        except Exception as error:

            print(
                f"[GitHub] Watcher error: {error}"
            )

    # ========================================================
    # STARTUP
    # ========================================================

    @check_commits.before_loop
    async def before_check_commits(self):

        await self.bot.wait_until_ready()

        # Make absolutely sure Scylla has been initialized.
        if not getattr(
            db,
            "_initialized",
            False,
        ):

            await db.initialize()

        # Make sure repository exists before
        # the first polling iteration.
        await self.initialize_repository()

    # ========================================================
    # MANUAL CHECK
    # ========================================================

    @commands.hybrid_command(
        name="githubcheck",
        description=(
            "Check the latest GitHub commit."
        ),
    )
    @commands.has_permissions(
        manage_guild=True
    )
    async def githubcheck(
        self,
        ctx: commands.Context,
    ):

        latest = (
            await self.get_latest_commit()
        )

        if not latest:

            await ctx.send(
                f"{EMOJI['error']} "
                "Unable to retrieve the "
                "latest GitHub commit."
            )

            return

        sha = latest.get(
            "sha",
            "unknown",
        )

        commit_url = latest.get(
            "html_url",
            GITHUB_REPO,
        )

        await ctx.send(
            f"{EMOJI['approved']} "
            f"Latest commit: "
            f"[`{sha[:7]}`]"
            f"({commit_url})"
        )

    # ========================================================
    # MANUAL RE-SYNC
    # ========================================================

    @commands.hybrid_command(
        name="githubsync",
        description=(
            "Set the stored GitHub commit to the "
            "current repository HEAD."
        ),
    )
    @commands.has_permissions(
        manage_guild=True
    )
    async def githubsync(
        self,
        ctx: commands.Context,
    ):

        latest = (
            await self.get_latest_commit()
        )

        if not latest:

            await ctx.send(
                f"{EMOJI['error']} "
                "Could not retrieve the "
                "latest GitHub commit."
            )

            return

        sha = latest.get(
            "sha"
        )

        if not sha:
            await ctx.send(
                f"{EMOJI['error']} "
                "GitHub returned an invalid "
                "commit response."
            )

            return

        await db.github.set_last_commit(
            self.repository_key,
            sha,
        )

        await ctx.send(
            f"{EMOJI['approved']} "
            f"GitHub monitor synchronized "
            f"to [`{sha[:7]}`]"
            f"({latest['html_url']})."
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        GitHubCommits(bot)
    )
