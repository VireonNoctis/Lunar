import discord
from discord.ext import commands

from utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

OWNERS = {
    1419744000977403994,
    960946185768685618,
}


# ============================================================
# EVAL HELP PAGES
# ============================================================

PAGES = [

    f"""
{EMOJI["new1"]}{EMOJI["new2"]} **Bot**

```py
bot
bot.user
bot.user.name
bot.user.id
bot.user.avatar
bot.latency
bot.uptime
bot.guilds
bot.users
bot.channels
bot.application_id
bot.intents
bot.extensions

{EMOJI["new1"]}{EMOJI["new2"]} Guild

message.guild.name
message.guild.id
message.guild.owner_id
message.guild.member_count
message.guild.created_at
message.guild.icon
message.guild.banner
message.guild.features
message.guild.verification_level
message.guild.premium_tier
message.guild.premium_subscription_count

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} User

message.author.name
message.author.id
message.author.discriminator
message.author.created_at
message.author.avatar
message.author.display_avatar
message.author.mention
message.author.bot

{EMOJI["new1"]}{EMOJI["new2"]} Message

message.content
message.id
message.channel
message.channel.id
message.channel.name
message.created_at
message.attachments
message.embeds
message.mentions
message.role_mentions
message.reference

{EMOJI["new1"]}{EMOJI["new2"]} Members

message.guild.members
len(message.guild.members)

[m.name for m in message.guild.members]

[m for m in message.guild.members if m.bot]

[m for m in message.guild.members if not m.bot]

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} Roles

len(message.guild.roles)

[r.name for r in message.guild.roles]

[r.id for r in message.guild.roles]

sorted(
    message.guild.roles,
    key=lambda r: r.position,
    reverse=True
)

message.author.roles

{EMOJI["new1"]}{EMOJI["new2"]} Permissions

message.author.guild_permissions

message.author.guild_permissions.administrator

message.author.guild_permissions.manage_guild

message.author.guild_permissions.to_dict()

message.guild.default_role.permissions

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} Channels

len(message.guild.channels)

[c.name for c in message.guild.channels]

[c.id for c in message.guild.channels]

[c.type for c in message.guild.channels]

message.channel.topic
message.channel.created_at
message.channel.category
message.channel.category_id

{EMOJI["new1"]}{EMOJI["new2"]} Threads

message.channel.threads

len(message.channel.threads)

[t.name for t in message.channel.threads]

[t.id for t in message.channel.threads]

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} Collections

len(bot.guilds)
len(bot.users)
len(bot.get_all_channels())

[g.name for g in bot.guilds]

[g.id for g in bot.guilds]

[u.name for u in bot.users]

[u.id for u in bot.users]

{EMOJI["new1"]}{EMOJI["new2"]} Emojis

len(bot.emojis)

[e.name for e in bot.emojis]

[e.id for e in bot.emojis]

[e for e in bot.emojis]

discord.utils.get(
    bot.emojis,
    name="emoji_name"
)

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} Voice

message.author.voice

message.author.voice.channel

message.author.voice.channel.id

message.guild.voice_channels

message.guild.voice_client

{EMOJI["new1"]}{EMOJI["new2"]} Invites

await message.guild.invites()

len(await message.guild.invites())

[
    invite.code
    for invite in await message.guild.invites()
]

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} System

import os
import sys
import platform

os.getpid()

platform.system()

platform.platform()

platform.machine()

sys.version

sys.platform

{EMOJI["new1"]}{EMOJI["new2"]} Time

from datetime import datetime

datetime.now()

datetime.utcnow()

datetime.now().timestamp()

datetime.now().isoformat()

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} Utilities

EMOJI

bot

ctx

message

commands

discord

type(variable)

dir(object)

vars(object)

repr(object)

{EMOJI["new1"]}{EMOJI["new2"]} Database

db

database

db.users

db.guilds

db.github

db.stats

await db.users.get(user_id)

await db.guilds.get(guild_id)

""",

f"""

{EMOJI["new1"]}{EMOJI["new2"]} Advanced

type(bot)

type(message)

dir(bot)

dir(message)

vars(bot)

vars(message)

bot.extensions

bot.cogs

bot.commands

bot.tree.get_commands()

{EMOJI["new1"]}{EMOJI["new2"]} Examples

!eval bot.user

!eval bot.latency

!eval message.guild.name

!eval len(message.guild.members)

!eval [r.name for r in message.guild.roles]

!eval [g.name for g in bot.guilds]

!eval len(bot.guilds)

!eval len(bot.users)

!eval EMOJI["lunar"]

""",
]

============================================================

EVAL COG

============================================================

class Eval(commands.Cog):

def __init__(self, bot: commands.Bot):
    self.bot = bot

# ========================================================
# HELP EMBED
# ========================================================

def create_help_embed(
    self,
    page: int,
) -> discord.Embed:

    embed = discord.Embed(
        color=discord.Color.from_rgb(
            212,
            175,
            55,
        ),
        title=(
            f"{EMOJI['lunar']} "
            "Lunar Eval System"
        ),
        description=PAGES[page],
    )

    embed.set_footer(
        text=(
            f"Page {page + 1}/{len(PAGES)} "
            "• Lunar Developer Console"
        )
    )

    embed.timestamp = discord.utils.utcnow()

    return embed

# ========================================================
# HELP VIEW
# ========================================================

class EvalHelpView(
    discord.ui.View
):

    def __init__(
        self,
        owner_id: int,
        cog,
    ):
        super().__init__(
            timeout=60
        )

        self.owner_id = owner_id
        self.cog = cog
        self.page = 0

    # ----------------------------------------------------
    # Previous
    # ----------------------------------------------------

    @discord.ui.button(
        emoji=EMOJI["left"],
        style=discord.ButtonStyle.secondary,
        custom_id="eval_previous",
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the executor can use this.",
                ephemeral=True,
            )

            return

        self.page -= 1

        if self.page < 0:
            self.page = len(PAGES) - 1

        await interaction.response.edit_message(
            embed=self.cog.create_help_embed(
                self.page
            ),
            view=self,
        )

    # ----------------------------------------------------
    # Next
    # ----------------------------------------------------

    @discord.ui.button(
        emoji=EMOJI["right"],
        style=discord.ButtonStyle.secondary,
        custom_id="eval_next",
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "Only the executor can use this.",
                ephemeral=True,
            )

            return

        self.page += 1

        if self.page >= len(PAGES):
            self.page = 0

        await interaction.response.edit_message(
            embed=self.cog.create_help_embed(
                self.page
            ),
            view=self,
        )

    async def on_timeout(self):

        for item in self.children:
            item.disabled = True

# ========================================================
# SAFE DISPLAY
# ========================================================

@staticmethod
def format_result(
    result,
) -> str:

    if result is None:
        return "None"

    if isinstance(result, str):
        return result

    try:
        return repr(result)

    except Exception:
        return str(result)

# ========================================================
# EVAL
# ========================================================

@commands.command(
    name="eval",
    aliases=("ev",),
)
async def eval_command(
    self,
    ctx: commands.Context,
    *,
    code: str = None,
):

    # ----------------------------------------------------
    # OWNER ONLY
    # ----------------------------------------------------

    if ctx.author.id not in OWNERS:

        await ctx.reply(
            f"{EMOJI['denied']} "
            "You do not have permission "
            "to use this command."
        )

        return

    # ----------------------------------------------------
    # HELP
    # ----------------------------------------------------

    if not code:

        view = self.EvalHelpView(
            owner_id=ctx.author.id,
            cog=self,
        )

        await ctx.reply(
            embed=self.create_help_embed(
                0
            ),
            view=view,
        )

        return

    # ----------------------------------------------------
    # CLEAN CODE BLOCKS
    # ----------------------------------------------------

    code = code.strip()

    if code.startswith("```"):

        lines = code.splitlines()

        if lines:

            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines.pop()

        code = "\n".join(lines)

    # ----------------------------------------------------
    # EVALUATION
    # ----------------------------------------------------

    try:

        # Evaluation environment is intentionally
        # limited to the objects normally useful for
        # bot diagnostics.
        environment = {
            "bot": self.bot,
            "ctx": ctx,
            "message": ctx.message,
            "guild": ctx.guild,
            "channel": ctx.channel,
            "author": ctx.author,
            "discord": discord,
            "commands": commands,
            "EMOJI": EMOJI,
        }

        result = eval(
            code,
            {
                "__builtins__": {},
            },
            environment,
        )

        result = self.format_result(
            result
        )

        if len(result) > 3900:
            result = (
                result[:3900]
                + "\n..."
            )

        embed = discord.Embed(
            color=discord.Color.from_rgb(
                212,
                175,
                55,
            ),
            title=(
                f"{EMOJI['lunar']} "
                "Eval Result"
            ),
        )

        embed.add_field(
            name=(
                f"{EMOJI['right']} Output"
            ),
            value=(
                "```py\n"
                f"{result}"
                "\n```"
            ),
            inline=False,
        )

        embed.set_footer(
            text=(
                f"Executed by "
                f"{ctx.author}"
            )
        )

        embed.timestamp = (
            discord.utils.utcnow()
        )

        await ctx.reply(
            embed=embed
        )

    except Exception as error:

        error_text = (
            f"{type(error).__name__}: "
            f"{error}"
        )

        if len(error_text) > 3900:
            error_text = (
                error_text[:3900]
                + "\n..."
            )

        embed = discord.Embed(
            color=discord.Color.from_rgb(
                139,
                0,
                0,
            ),
            title=(
                f"{EMOJI['error']} "
                "Eval Error"
            ),
            description=(
                "```py\n"
                f"{error_text}"
                "\n```"
            ),
        )

        embed.timestamp = (
            discord.utils.utcnow()
        )

        await ctx.reply(
            embed=embed
        )

============================================================

SETUP

============================================================

async def setup(
bot: commands.Bot,
):

await bot.add_cog(
    Eval(bot)
)


One difference from the JS version is that this version doesn't expose Python's full `__builtins__` namespace through `eval`; the evaluation environment is deliberately limited to the Discord/bot objects needed for diagnostics.
