import secrets
import string

from discord.ext import commands


class GenerateCode(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def generate_code(username: str, lunarname: str) -> str:
        if not username:
            raise ValueError("username cannot be empty")

        # Cryptographically secure random characters.
        chars = string.ascii_uppercase + string.digits

        # Generate a 24-character cryptographically secure token.
        characters = "".join(
            secrets.choice(chars)
            for _ in range(24)
        )

        # Keep the Lunar username as the visible identifier while
        # making the actual verification portion cryptographically random.
        return (
            f"{lunarname}-"
            f"{characters[0:6]}-"
            f"{characters[6:12]}-"
            f"{characters[12:18]}-"
            f"{characters[18:24]}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(GenerateCode(bot))