import aiohttp
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

GITHUB_API = "https://api.github.com"

GITHUB_REPOSITORY = "VireonNoctis/Lunar"

GITHUB_TOKEN = "YOUR_GITHUB_TOKEN"


# ─────────────────────────────────────────────
# Suggest Cog
# ─────────────────────────────────────────────

class Suggest(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="suggest",
        description="Create a suggestion as a GitHub issue."
    )
    @app_commands.describe(
        suggestion="Describe your suggestion in detail."
    )
    async def suggest(
        self,
        interaction: discord.Interaction,
        suggestion: str,
    ):

        # ─────────────────────────────────────
        # Basic validation
        # ─────────────────────────────────────

        suggestion = suggestion.strip()

        if not suggestion:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Invalid Suggestion",
                    description="You cannot submit an empty suggestion.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        if len(suggestion) < 10:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{EMOJI['question']} Suggestion Too Short",
                    description=(
                        "Please provide a little more detail so the suggestion "
                        "can actually be evaluated."
                    ),
                    color=discord.Color.orange(),
                ),
                ephemeral=True,
            )
            return

        if len(suggestion) > 5000:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Suggestion Too Long",
                    description=(
                        "Suggestions are limited to **5,000 characters**."
                    ),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # ─────────────────────────────────────
        # Loading state
        # ─────────────────────────────────────

        loading_embed = discord.Embed(
            title=f"{EMOJI['loading']} Preparing Suggestion",
            description=(
                "Your suggestion is being prepared for the Lunar development system..."
            ),
            color=discord.Color.blurple(),
        )

        await interaction.edit_original_response(
            embed=loading_embed
        )

        # ─────────────────────────────────────
        # Get repository configuration
        # ─────────────────────────────────────

        repository = await db.github.get(
            GITHUB_REPOSITORY
        )

        if repository is None:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Repository Not Configured",
                    description=(
                        "The GitHub repository has not been configured in the database."
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        if not repository.enabled:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f"{EMOJI['denied']} Suggestions Disabled",
                    description=(
                        "GitHub suggestions are currently disabled."
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        owner = repository.owner
        repo_name = repository.name

        # ─────────────────────────────────────
        # Build GitHub issue
        # ─────────────────────────────────────

        issue_title = (
            f"[Suggestion] "
            f"{suggestion[:90]}"
        )

        issue_body = (
            "## Suggestion\n\n"
            f"{suggestion}\n\n"
            "---\n"
            "### Submitted By\n"
            f"- **Discord:** {interaction.user.mention}\n"
            f"- **User ID:** `{interaction.user.id}`\n"
            f"- **Discord Username:** `{interaction.user}`\n\n"
            "### Source\n"
            "Lunar Discord Suggestion System"
        )

        payload = {
            "title": issue_title,
            "body": issue_body,
            "labels": [
                "suggestion"
            ],
        }

        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Lunar-Bot",
        }

        # ─────────────────────────────────────
        # Create GitHub issue
        # ─────────────────────────────────────

        await interaction.edit_original_response(
            embed=discord.Embed(
                title=f"{EMOJI['loading']} Creating GitHub Issue",
                description=(
                    f"{EMOJI['moon']} Sending your suggestion to "
                    f"**{owner}/{repo_name}**..."
                ),
                color=discord.Color.blurple(),
            )
        )

        issue_data = None

        try:
            async with aiohttp.ClientSession(
                headers=headers
            ) as session:

                async with session.post(
                    f"{GITHUB_API}/repos/{owner}/{repo_name}/issues",
                    json=payload,
                ) as response:

                    response_data = await response.json()

                    if response.status not in (200, 201):
                        error_message = response_data.get(
                            "message",
                            "Unknown GitHub error."
                        )

                        await interaction.edit_original_response(
                            embed=discord.Embed(
                                title=f"{EMOJI['error']} GitHub Error",
                                description=(
                                    "GitHub rejected the suggestion.\n\n"
                                    f"```text\n{error_message}\n```"
                                ),
                                color=discord.Color.red(),
                            )
                        )
                        return

                    issue_data = response_data

        except aiohttp.ClientError as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Connection Failed",
                    description=(
                        "I could not connect to GitHub right now.\n\n"
                        f"```text\n{exc}\n```"
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        except Exception as exc:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f"{EMOJI['error']} Unexpected Error",
                    description=(
                        "Something went wrong while creating the issue.\n\n"
                        f"```text\n{exc}\n```"
                    ),
                    color=discord.Color.red(),
                )
            )
            return

        # ─────────────────────────────────────
        # Store issue in ScyllaDB
        # ─────────────────────────────────────

        try:
            await db.github.record_issue(
                GITHUB_REPOSITORY,
                issue_number=issue_data["number"],
                title=issue_data["title"],
                body=issue_body,
                author_id=interaction.user.id,
                html_url=issue_data["html_url"],
                state=issue_data.get(
                    "state",
                    "open"
                ),
                issue_type="suggestion",
                metadata={
                    "discord_username": str(interaction.user),
                    "discord_user_id": str(interaction.user.id),
                    "github_id": str(issue_data.get("id", "")),
                },
            )

        except Exception as exc:
            # The GitHub issue already exists, so don't tell
            # the user the issue failed completely.
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f"{EMOJI['approved']} Suggestion Created",
                    description=(
                        "Your suggestion was successfully created on GitHub, "
                        "but I could not save its database record.\n\n"
                        f"**Issue:** #{issue_data['number']}\n"
                        f"**GitHub:** [View Issue]({issue_data['html_url']})\n\n"
                        f"{EMOJI['error']} Database error:\n"
                        f"```text\n{exc}\n```"
                    ),
                    color=discord.Color.orange(),
                )
            )
            return

        # ─────────────────────────────────────
        # Success
        # ─────────────────────────────────────

        success_embed = discord.Embed(
            title=f"{EMOJI['approved']} Suggestion Submitted",
            description=(
                f"{EMOJI['lunar']} Your suggestion has been successfully "
                "submitted to the Lunar development system.\n\n"
                f"{EMOJI['right']} **GitHub Issue:** "
                f"[#{issue_data['number']}]({issue_data['html_url']})"
            ),
            color=discord.Color.green(),
        )

        success_embed.add_field(
            name=f"{EMOJI['staff']} Suggestion",
            value=(
                suggestion[:1024]
            ),
            inline=False,
        )

        success_embed.add_field(
            name="Status",
            value=f"{EMOJI['approved']} Open",
            inline=True,
        )

        success_embed.add_field(
            name="Issue Type",
            value="Suggestion",
            inline=True,
        )

        success_embed.set_footer(
            text=(
                f"Submitted by {interaction.user} • "
                f"Issue #{issue_data['number']}"
            )
        )

        await interaction.edit_original_response(
            embed=success_embed
        )


# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(
        Suggest(bot)
    )
