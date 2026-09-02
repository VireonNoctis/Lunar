import os

import discord
from discord import app_commands
from discord.ext import commands

from utilities.emoji import EMOJI


OWNERS = {
    1419744000977403994,
    960946185768685618,
}


class Restart(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="restart",
        description="Restart the bot."
    )
    async def restart(self, interaction: discord.Interaction):

        if interaction.user.id not in OWNERS:
            await interaction.response.send_message(
                f"{EMOJI['denied']} You do not have permission to use this command.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{EMOJI['loading']} Restarting bot..."
        )

        await self.bot.close()
        os._exit(0)


async def setup(bot: commands.Bot):
    await bot.add_cog(Restart(bot))
