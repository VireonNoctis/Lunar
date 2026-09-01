import dotenv
import discord
import os

dotenv.load_dotenv()

# https://guide.pycord.dev/getting-started/creating-your-first-bot

bot = discord.Bot()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))