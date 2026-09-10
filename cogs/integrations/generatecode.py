import random
import time

from discord.ext import commands


class GenerateCode(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def generate_code(username: str, lunarname: str) -> str:
        random_number = int(
            ((random.random() * 9999) * (random.random() * -5)) ** 2
        )

        current_time = int(time.time() * 1000)
        username_length = len(username)

        # Prevent division by zero.
        if username_length == 0:
            raise ValueError("username cannot be empty")

        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

        number = (random_number + current_time) / username_length
        number_string = str(number)

        characters = "".join(
            random.choice(chars)
            for _ in range(18)
        )

        midpoint = len(number_string) // 2

        return (
            f"{lunarname}-"
            f"{number_string[:midpoint]}-"
            f"{characters[6:12]}-"
            f"{number_string[midpoint:]}-"
            f"{characters[12:18]}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(GenerateCode(bot))
