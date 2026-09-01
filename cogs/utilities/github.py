import asyncio
import json
import os
import re
from datetime import datetime
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

from ..utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

GITHUB_REPO = "https://https://github.com/VireonNoctis/Lunar/"

# Put the Discord channel ID here
CHANNEL_ID = 1489719944135442607

# How often GitHub is checked
CHECK_INTERVAL = 30

# Maximum amount of changed files displayed in the embed
MAX_FILE_PREVIEW = 6

# Persistent commit tracking
DATA_FILE = "github_commit.json"


class GitHubCommits(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_commit = self.load_last_commit()

        self.check_commits.start()

    def cog_unload(self):
        self.check_commits.cancel()

        if self.session and not self.session.closed:
            self.bot.loop.create_task(self.session.close())

    # ========================================================
    # DATA
    # ========================================================

    def load_last_commit(self) -> Optional[str]:
        if not os.path.exists(DATA_FILE):
            return None

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)

            return data.get("last_commit")

        except (OSError, json.JSONDecodeError):
            return None

    def save_last_commit(self, commit_sha: str):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as file:
                json.dump(
                    {
                        "last_commit": commit_sha
                    },
                    file,
                    indent=4
                )

        except OSError as error:
            print(f"[GitHub] Failed to save commit data: {error}")

    # ========================================================
    # REPOSITORY
    # ========================================================

    def get_repo(self):
        """
        Converts:

        https://github.com/Owner/Repository
        github.com/Owner/Repository
        Owner/Repository

        into:

        owner, repository
        """

        repo_url = GITHUB_REPO.strip().rstrip("/")

        repo_url = re.sub(
            r"^https?://",
            "",
            repo_url,
            flags=re.IGNORECASE
        )

        repo_url = re.sub(
            r"^www\.",
            "",
            repo_url,
            flags=re.IGNORECASE
        )

        if repo_url.startswith("github.com/"):
            repo_url = repo_url[len("github.com/"):]

        repo_url = repo_url.removesuffix(".git")

        parts = repo_url.split("/")

        if len(parts) < 2:
            raise ValueError(
                "Invalid GITHUB_REPO. Expected "
                "'https://github.com/OWNER/REPOSITORY'."
            )

        owner = parts[0]
        repository = parts[1]

        return owner, repository

    # ========================================================
    # HTTP SESSION
    # ========================================================

    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "Lunar-GitHub-Commit-Monitor",
                    "X-GitHub-Api-Version": "2022-11-28"
                }
            )

        return self.session

    # ========================================================
    # GITHUB API
    # ========================================================

    async def github_get(self, url: str):
        session = await self.get_session()

        try:
            async with session.get(url) as response:

                if response.status == 404:
                    print(f"[GitHub] Resource not found: {url}")
                    return None

                if response.status == 403:
                    print(
                        "[GitHub] API rate limit reached or request "
                        "was forbidden."
                    )
                    return None

                if response.status != 200:
                    print(
                        f"[GitHub] API returned HTTP "
                        f"{response.status}: {url}"
                    )
                    return None

                return await response.json()

        except aiohttp.ClientError as error:
            print(f"[GitHub] Request failed: {error}")
            return None

    async def get_latest_commit(self):
        owner, repository = self.get_repo()

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repository}/commits?per_page=1"
        )

        commits = await self.github_get(url)

        if not commits:
            return None

        return commits[0]

    async def get_commit_details(self, sha: str):
        owner, repository = self.get_repo()

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repository}/commits/{sha}"
        )

        return await self.github_get(url)

    async def get_repository_info(self):
        owner, repository = self.get_repo()

        url = (
            f"https://api.github.com/repos/"
            f"{owner}/{repository}"
        )

        return await self.github_get(url)

    # ========================================================
    # FORMATTERS
    # ========================================================

    @staticmethod
    def truncate(text: str, length: int) -> str:
        if len(text) <= length:
            return text

        return text[:length - 3] + "..."

    @staticmethod
    def parse_commit_message(message: str):
        lines = message.splitlines()

        if not lines:
            return "No commit message.", ""

        title = lines[0].strip()

        body = "\n".join(
            line.rstrip()
            for line in lines[1:]
        ).strip()

        return title, body

    @staticmethod
    def format_change_count(additions: int, deletions: int) -> str:
        return (
            f"`+{additions}` additions • "
            f"`-{deletions}` deletions"
        )

    def get_commit_author(self, commit):
        github_author = commit.get("author")
        git_author = commit["commit"].get("author") or {}

        if github_author:
            return (
                github_author.get("login")
                or github_author.get("name")
                or git_author.get("name")
                or "Unknown"
            )

        return git_author.get("name") or "Unknown"

    def get_commit_avatar(self, commit):
        author = commit.get("author")

        if author:
            return author.get("avatar_url")

        return None

    def get_committer(self, commit):
        github_committer = commit.get("committer")
        git_committer = commit["commit"].get("committer") or {}

        if github_committer:
            return (
                github_committer.get("login")
                or github_committer.get("name")
                or git_committer.get("name")
                or "Unknown"
            )

        return git_committer.get("name") or "Unknown"

    def get_verification(self, commit) -> bool:
        verification = commit["commit"].get("verification")

        if not verification:
            return False

        return bool(
            verification.get("verified", False)
        )

    # ========================================================
    # CHANGED FILES
    # ========================================================

    def format_changed_files(self, files):
        if not files:
            return "No file information available."

        output = []

        for file in files[:MAX_FILE_PREVIEW]:
            filename = file.get("filename", "Unknown file")
            status = file.get("status", "modified")

            additions = file.get("additions", 0)
            deletions = file.get("deletions", 0)

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

        remaining = len(files) - MAX_FILE_PREVIEW

        if remaining > 0:
            output.append(
                f"*...and {remaining} more file(s)*"
            )

        return "\n".join(output)

    # ========================================================
    # EMBED
    # ========================================================

    def create_embed(
        self,
        commit,
        repository_info=None,
        previous_sha: Optional[str] = None
    ):
        commit_info = commit["commit"]

        sha = commit["sha"]
        short_sha = sha[:7]

        message = commit_info.get(
            "message",
            "No commit message."
        )

        title, body = self.parse_commit_message(
            message
        )

        author = self.get_commit_author(commit)
        committer = self.get_committer(commit)

        additions = commit.get("stats", {}).get(
            "additions",
            0
        )

        deletions = commit.get("stats", {}).get(
            "deletions",
            0
        )

        total_changes = commit.get("stats", {}).get(
            "total",
            additions + deletions
        )

        files = commit.get("files", [])
        file_count = len(files)

        verified = self.get_verification(
            commit
        )

        timestamp = None

        raw_date = commit_info.get(
            "author",
            {}
        ).get("date")

        if raw_date:
            try:
                timestamp = datetime.fromisoformat(
                    raw_date.replace(
                        "Z",
                        "+00:00"
                    )
                )
            except ValueError:
                timestamp = None

        # ----------------------------------------------------
        # REPOSITORY
        # ----------------------------------------------------

        if repository_info:
            full_name = repository_info.get(
                "full_name",
                f"{self.get_repo()[0]}/{self.get_repo()[1]}"
            )

            default_branch = repository_info.get(
                "default_branch",
                "unknown"
            )

            description = repository_info.get(
                "description"
            )

            repo_icon = repository_info.get(
                "html_url",
                GITHUB_REPO
            )

        else:
            owner, repository = self.get_repo()

            full_name = (
                f"{owner}/{repository}"
            )

            default_branch = "unknown"
            description = None
            repo_icon = GITHUB_REPO

        # ----------------------------------------------------
        # BRANCH
        # ----------------------------------------------------
        #
        # The monitored endpoint returns the latest commit
        # of the repository's default branch.
        #
        # Therefore the default branch is the monitored branch.
        # ----------------------------------------------------

        branch = default_branch

        # ----------------------------------------------------
        # COLORS
        # ----------------------------------------------------

        embed_color = (
            discord.Color.green()
            if verified
            else discord.Color.dark_theme()
        )

        # ----------------------------------------------------
        # TITLE
        # ----------------------------------------------------

        embed = discord.Embed(
            title=(
                f"{EMOJI['new1']} New GitHub Commit"
            ),
            url=commit["html_url"],
            color=embed_color,
            timestamp=timestamp
        )

        # ----------------------------------------------------
        # DESCRIPTION
        # ----------------------------------------------------

        description_parts = [
            f"### {self.truncate(title, 256)}"
        ]

        if body:
            description_parts.append(
                self.truncate(body, 700)
            )

        description_parts.append(
            f"\n{EMOJI['right']} "
            f"[View Commit]({commit['html_url']})"
        )

        embed.description = "\n".join(
            description_parts
        )

        # ----------------------------------------------------
        # AUTHOR
        # ----------------------------------------------------

        embed.add_field(
            name=f"{EMOJI['dev']} Author",
            value=f"`{author}`",
            inline=True
        )

        embed.add_field(
            name="👤 Committer",
            value=f"`{committer}`",
            inline=True
        )

        # ----------------------------------------------------
        # COMMIT
        # ----------------------------------------------------

        embed.add_field(
            name="🔑 Commit",
            value=(
                f"[`{short_sha}`]"
                f"({commit['html_url']})"
            ),
            inline=True
        )

        # ----------------------------------------------------
        # BRANCH
        # ----------------------------------------------------

        embed.add_field(
            name="🌿 Branch",
            value=f"`{branch}`",
            inline=True
        )

        # ----------------------------------------------------
        # REPOSITORY
        # ----------------------------------------------------

        embed.add_field(
            name="📁 Repository",
            value=(
                f"[`{full_name}`]"
                f"({repo_icon})"
            ),
            inline=True
        )

        # ----------------------------------------------------
        # VERIFICATION
        # ----------------------------------------------------

        verification_text = (
            f"{EMOJI['verify']} **Verified**"
            if verified
            else f"{EMOJI['denied']} **Not Verified**"
        )

        embed.add_field(
            name="🔐 Signature",
            value=verification_text,
            inline=True
        )

        # ----------------------------------------------------
        # STATISTICS
        # ----------------------------------------------------

        embed.add_field(
            name="📊 Changes",
            value=(
                f"`{file_count}` files changed\n"
                f"`{total_changes}` total changes\n"
                f"`+{additions}` additions • "
                f"`-{deletions}` deletions"
            ),
            inline=True
        )

        # ----------------------------------------------------
        # MERGE STATUS
        # ----------------------------------------------------

        is_merge = len(
            commit_info.get("parent", [])
        ) > 1

        embed.add_field(
            name="🔀 Type",
            value=(
                "Merge Commit"
                if is_merge
                else "Commit"
            ),
            inline=True
        )

        # ----------------------------------------------------
        # FILE PREVIEW
        # ----------------------------------------------------

        embed.add_field(
            name="📂 Changed Files",
            value=self.format_changed_files(
                files
            ),
            inline=False
        )

        # ----------------------------------------------------
        # COMPARE
        # ----------------------------------------------------

        if previous_sha:
            owner, repository = self.get_repo()

            compare_url = (
                f"https://github.com/"
                f"{owner}/{repository}/compare/"
                f"{previous_sha}...{sha}"
            )

            embed.add_field(
                name="⚡ Changes",
                value=(
                    f"[Compare with Previous Commit]("
                    f"{compare_url})"
                ),
                inline=False
            )

        # ----------------------------------------------------
        # DESCRIPTION FROM REPO
        # ----------------------------------------------------

        if description:
            embed.add_field(
                name="Repository Description",
                value=self.truncate(
                    description,
                    300
                ),
                inline=False
            )

        # ----------------------------------------------------
        # AUTHOR AVATAR
        # ----------------------------------------------------

        avatar_url = self.get_commit_avatar(
            commit
        )

        if avatar_url:
            embed.set_thumbnail(
                url=avatar_url
            )

        # ----------------------------------------------------
        # FOOTER
        # ----------------------------------------------------

        embed.set_footer(
            text=(
                f"{full_name} • "
                f"GitHub Commit Monitor"
            )
        )

        return embed

    # ========================================================
    # COMMIT CHECKER
    # ========================================================

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def check_commits(self):

        commit = await self.get_latest_commit()

        if commit is None:
            return

        current_sha = commit["sha"]

        # ----------------------------------------------------
        # FIRST RUN
        # ----------------------------------------------------
        #
        # Establish the current commit without notifying.
        # ----------------------------------------------------

        if self.last_commit is None:
            self.last_commit = current_sha
            self.save_last_commit(current_sha)

            print(
                f"[GitHub] Initialized at "
                f"{current_sha[:7]}"
            )

            return

        # ----------------------------------------------------
        # NO CHANGE
        # ----------------------------------------------------

        if current_sha == self.last_commit:
            return

        # ----------------------------------------------------
        # GET CHANNEL
        # ----------------------------------------------------

        channel = self.bot.get_channel(
            CHANNEL_ID
        )

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    CHANNEL_ID
                )
            except discord.HTTPException as error:
                print(
                    f"[GitHub] Could not access "
                    f"channel {CHANNEL_ID}: {error}"
                )
                return

        # ----------------------------------------------------
        # GET COMMIT DETAILS
        # ----------------------------------------------------

        detailed_commit = (
            await self.get_commit_details(
                current_sha
            )
        )

        if detailed_commit is None:
            return

        # ----------------------------------------------------
        # GET REPOSITORY INFO
        # ----------------------------------------------------

        repository_info = (
            await self.get_repository_info()
        )

        # ----------------------------------------------------
        # CREATE EMBED
        # ----------------------------------------------------

        embed = self.create_embed(
            detailed_commit,
            repository_info=repository_info,
            previous_sha=self.last_commit
        )

        # ----------------------------------------------------
        # SEND
        # ----------------------------------------------------

        try:
            await channel.send(
                embed=embed
            )

            self.last_commit = current_sha
            self.save_last_commit(
                current_sha
            )

            print(
                f"[GitHub] New commit detected: "
                f"{current_sha[:7]}"
            )

        except discord.HTTPException as error:
            print(
                f"[GitHub] Failed to send commit "
                f"notification: {error}"
            )

    # ========================================================
    # STARTUP
    # ========================================================

    @check_commits.before_loop
    async def before_check_commits(self):
        await self.bot.wait_until_ready()

    # ========================================================
    # MANUAL CHECK
    # ========================================================

    @commands.command(
        name="githubcheck"
    )
    @commands.has_permissions(
        manage_guild=True
    )
    async def githubcheck(
        self,
        ctx: commands.Context
    ):
        """
        Manually check the configured
        GitHub repository.
        """

        commit = await self.get_latest_commit()

        if commit is None:
            await ctx.send(
                f"{EMOJI['error']} "
                "Could not retrieve the latest GitHub commit."
            )
            return

        await ctx.send(
            f"{EMOJI['approved']} "
            f"Latest commit: "
            f"[`{commit['sha'][:7]}`]"
            f"({commit['html_url']})"
        )


# ============================================================
# SETUP
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(
        GitHubCommits(bot)
    )
