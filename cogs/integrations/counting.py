import asyncio
import logging
import re

import discord
from discord.ext import commands

from cogs.utilities.database import db
from cogs.utilities.emoji import EMOJI


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

COUNTING_CHANNEL_ID = 1486807743485448203
COUNT_VARIABLE = "last_count"
STARTING_COUNT = 0


# ─────────────────────────────────────────────
# Milestones
# ─────────────────────────────────────────────

MILESTONES = {
    # Early game
    1: "The first one. It begins.",
    2: "Two. Barely a pattern.",
    3: "Three's a trend.",
    5: "Warming up.",
    7: "Lucky number seven.",
    10: "Double digits.",
    13: "Unlucky 13. Bold choice.",
    17: "17. Prime and pointless.",
    20: "20. Okay.",
    21: "21. Technically an adult now.",
    23: "23. Jordan number.",
    24: "24. A full day, if this were hours.",
    25: "Quarter century.",
    27: "27. The infamous club, but for numbers.",
    28: "28. Leap-year energy.",
    30: "30. Still going.",
    33: "33. A third of a century.",
    36: "36 Chambers.",
    37: "37. Another prime, another Tuesday.",
    40: "40. Life supposedly begins now.",
    42: "The answer to life, the universe, and this counter.",
    44: "44. Magnum-sized milestone.",
    45: "45. Halfway to 90.",
    47: "47. The most nerdy number in the universe.",
    48: "48. Two dozen, doubled.",
    50: "Halfway to 100.",
    55: "55. Speed limit reached.",
    60: "60. An hour of counting, theoretically.",
    64: "64. A perfect square and a classic console.",
    67: "67.",
    69: "Nice.",
    70: "70. Fast, furious, and still counting.",
    75: "Three quarters of the way to 100.",
    80: "80. The 80s called, they want their number back.",
    88: "88 miles per hour. Great Scott.",
    90: "90. So close to triple digits.",
    99: "99 problems, and this ain't one.",

    # 100+
    100: "🎉 100 COUNTS!",
    101: "101. Just past the century mark.",
    111: "111. Repdigit spotted.",
    120: "120. A gross, sort of.",
    123: "123. As easy as counting.",
    125: "125. Halfway to 250.",
    144: "144. A literal gross.",
    150: "150. The 100 milestone already wore off.",
    160: "160. No comment.",
    180: "180. Full turnaround.",
    199: "199. One away from 200, agonizingly.",
    200: "200. This is a lifestyle now.",
    222: "222. Angel numbers, apparently.",
    250: "250. The counting has escalated.",
    256: "256. A byte's worth of possibilities.",
    275: "275. No milestone, just vibes.",
    300: "300. This is Sparta levels of commitment.",
    333: "333. Triple three. Suspiciously symmetrical.",
    360: "360. Full circle.",
    365: "365. A whole year of days.",
    400: "400. Four hundred reasons to stop.",
    404: "404: Milestone Not Found.",
    420: "Nice.",
    450: "450. Halfway to 900.",
    500: "500. Someone stop them.",
    550: "550. No particular significance.",
    600: "600. This counter has become self-aware.",
    650: "650. Still climbing.",
    666: "666. A suspiciously memorable number.",
    700: "700. Seven hundred. Why are you still counting?",
    725: "725. Almost a nice round number.",
    750: "750. Three-quarters of a thousand and zero regrets.",
    777: "Jackpot. Somehow.",
    800: "800. There is no ceiling.",
    850: "850. So close to 900.",
    900: "900. 1,000 is basically a formality at this point.",
    950: "950. Fifty away from four figures.",
    999: "999. One shy of glory.",

    # 1,000+
    1000: "1,000. Absolutely ridiculous.",
    1001: "1,001. Four digits have entered the chat.",
    1024: "1,024. Computer people are pleased.",
    1111: "1,111. Repdigit supremacy.",
    1200: "1,200. The counter refuses to die.",
    1234: "1,234. Sequential and satisfying.",
    1250: "1,250. A quarter of the way to 5,000.",
    1337: "l33t. Nerd.",
    1500: "1,500. This has outlived several relationships.",
    1600: "1,600. Civilization has progressed. This counter has not.",
    1729: "1,729. Hardy–Ramanujan would approve.",
    1800: "1,800. Eighteen hundred counts. Insane.",
    1900: "1,900. Triple digits weren't enough.",
    1999: "1,999. One away from 2,000.",
    2000: "2,000. A number, and also a cry for help.",
    2020: "2,020. A rough year, a fine milestone.",
    2048: "2,048. Another power of two.",
    2222: "2,222. The counter is seeing patterns.",
    2345: "2,345. Sequential enough.",
    2500: "2,500. Send help. Or don't, they're clearly fine with this.",
    3000: "3,000. This stopped being normal a while ago.",
    3333: "3,333. Four threes. Nice symmetry.",
    4000: "4,000. Surely this is enough.",
    4096: "4,096. Another power of two has fallen.",
    4200: "Nice, but bigger.",
    4444: "4,444. Four fours.",
    5000: "5,000. This is no longer a bit, it's a personality trait.",
    5555: "5,555. The fives have arrived.",
    6000: "6,000. Six thousand reasons to stop.",
    6666: "6,666. Very suspicious.",
    6969: "Nice, squared.",
    7000: "7,000. The counter has achieved unreasonable longevity.",
    7777: "7,777. Someone hit the jackpot again.",
    8000: "8,000. Overkill.",
    8192: "8,192. Powers of two never rest.",
    9000: "9,000. Almost there.",
    9001: "It's over 9000.",
    9999: "9,999. One shy of five figures.",

    # 10,000+
    10000: "10,000. Hours to mastery, apparently spent counting instead.",
    10001: "10,001. Five digits achieved.",
    10101: "10,101. The counter has discovered symmetry.",
    11111: "11,111. Five ones. Surely this means something.",
    12000: "12,000. Still going.",
    12345: "12,345. Sequential and deeply satisfying.",
    12500: "12,500. Halfway to 25k.",
    13337: "1337, but extra leet.",
    15000: "15,000. This is becoming historical.",
    16384: "16,384. The powers of two continue.",
    20000: "20,000. Someone needs to take the keyboard away.",
    22222: "22,222. The twos have taken over.",
    25000: "25,000. A quarter of the way to 100k.",
    30000: "30,000. This is no longer counting. This is infrastructure.",
    32768: "32,768. Classic power-of-two territory.",
    33333: "33,333. The symmetry is getting ridiculous.",
    40000: "40,000. Forty thousand counts. Why?",
    44444: "44,444. The fours are taking over.",
    50000: "50,000. Halfway to 100k.",
    55555: "55,555. Five five five five five.",
    60000: "60,000. The counter has achieved sentience.",
    65536: "65,536. Another power of two conquered.",
    66666: "66,666. That's an alarming amount of sixes.",
    69420: "Nice and blazed.",
    70000: "70,000. Seven-zero supremacy.",
    75000: "75,000. Three quarters of the way to 100k.",
    77777: "77,777. Jackpot energy.",
    80000: "80,000. The end is nowhere in sight.",
    88888: "88,888. Eighty-eight thousand reasons to stop.",
    90000: "90,000. Ten thousand to go.",
    99999: "99,999. ONE. MORE.",

    # 100,000+
    100000: "100,000. This has become a life's work.",
    100001: "100,001. And they kept going.",
    101010: "101,010. The symmetry is back.",
    111111: "111,111. Six ones. Completely unnecessary.",
    123456: "123,456. Sequential perfection.",
    125000: "125,000. One eighth of a million.",
    131072: "131,072. Another power of two.",
    133333: "133,333. The numbers are getting silly.",
    150000: "150,000. This counter needs a vacation.",
    200000: "200,000. Two hundred thousand counts.",
    222222: "222,222. The twos are unstoppable.",
    250000: "250,000. Quarter million.",
    262144: "262,144. Power of two territory.",
    300000: "300,000. This has officially become an institution.",
    333333: "333,333. Triple-triple-three.",
    400000: "400,000. Four hundred thousand. Insanity.",
    444444: "444,444. The fours are taking over.",
    500000: "500,000. Half a million.",
    555555: "555,555. Five hundred thousand five hundred fifty-five.",
    600000: "600,000. Surely you've had enough.",
    666666: "666,666. Six digits of suspicious symmetry.",
    694200: "694,200. Nice, but significantly larger.",
    700000: "700,000. Seven hundred thousand. Why is this still running?",
    750000: "750,000. Three quarters of a million.",
    777777: "777,777. Jackpot mode.",
    800000: "800,000. There genuinely is no ceiling.",
    888888: "888,888. Eight times the fun.",
    900000: "900,000. The million mark is approaching.",
    999999: "999,999. ONE. MORE. TIME.",
    1000000: "1,000,000. ONE MILLION COUNTS. WHAT ARE YOU DOING?",
}


# ─────────────────────────────────────────────
# Special messages
# ─────────────────────────────────────────────

SPECIAL_MESSAGES = {
    12: (
        "<@756535229933551656> come here, "
        "13 awaits you"
    ),

    22: (
        "<@1267906230634938530> "
        "23 for the 32 year old"
    ),
}


# ─────────────────────────────────────────────
# Special media
# ─────────────────────────────────────────────

SPECIAL_MEDIA = {
    67: (
        "https://images-ext-1.discordapp.net/external/"
        "s_JjhstVcwbUfFvRbEG36mC-b5atAncCn8f_bi0jPew/"
        "https/media1.giphy.com/media/v1.Y2lkPTczYjhmN2IxeHhrazd6Z2JiZWt0MndvbDF4YnBtbmhvaTN4amt6Yno0cmJtd3V0"
        "eSZlcD12MV9naWZzX2d1ZklkJmN0PWc/"
        "08uBcURaMq6vA93TGc/giphy.mp4"
    ),
}


# ─────────────────────────────────────────────
# Counting Cog
# ─────────────────────────────────────────────

class Counting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Prevents two messages from the same bot process
        # from modifying the counter simultaneously.
        self.lock = asyncio.Lock()

    async def _get_state(self):
        """Return the current count and last member."""

        row = await db.variables.get(COUNT_VARIABLE)

        if row is None:
            await db.variables.ensure(
                identifier=COUNT_VARIABLE,
                int_value=STARTING_COUNT,
                string_value=None,
            )

            return STARTING_COUNT, None

        current_count = row.int_value or STARTING_COUNT
        last_member = row.string_value

        return current_count, last_member

    async def _set_state(self, count: int, member_id: str):
        """Persist the current count and last member."""

        await db.variables.update(
            identifier=COUNT_VARIABLE,
            int_value=count,
            string_value=member_id,
        )

    async def _send_milestone(
        self,
        channel: discord.TextChannel,
        count: int,
    ):
        """Send a milestone announcement."""

        description = MILESTONES.get(count)

        if description is None:
            return

        embed = discord.Embed(
            title=f"{EMOJI['moon']} Milestone Reached",
            description=(
                f"{EMOJI['lunar']} **{count:,}**\n\n"
                f"{description}"
            ),
        )

        embed.set_footer(
            text="Lunar Counting System"
        )

        await channel.send(embed=embed)

    async def _handle_success(
        self,
        message: discord.Message,
        count: int,
    ):
        """Handle a successful count."""

        await self._set_state(
            count=count,
            member_id=str(message.author.id),
        )

        try:
            await message.add_reaction(EMOJI["approved"])
        except discord.HTTPException:
            logger.exception(
                "Failed to add success reaction."
            )

        # Special messages happen before the milestone
        # announcement, preserving the original behavior.
        special_message = SPECIAL_MESSAGES.get(count)

        if special_message:
            await message.channel.send(
                special_message
            )

        # Special media.
        special_media = SPECIAL_MEDIA.get(count)

        if special_media:
            await message.channel.send(
                special_media
            )

        # Milestone announcement.
        if count in MILESTONES:
            await self._send_milestone(
                message.channel,
                count,
            )

    async def _handle_failure(
        self,
        message: discord.Message,
        current_count: int,
    ):
        """Handle an incorrect count."""

        # Preserve the original behavior:
        # the person who messed up becomes the last member.
        await self._set_state(
            count=STARTING_COUNT,
            member_id=str(message.author.id),
        )

        try:
            await message.add_reaction(EMOJI["denied"])
        except discord.HTTPException:
            logger.exception(
                "Failed to add denied reaction."
            )

        # Keep the tomato reaction from the original system.
        try:
            await message.add_reaction("🍅")
        except discord.HTTPException:
            logger.exception(
                "Failed to add tomato reaction."
            )

        expected = current_count + 1

        await message.channel.send(
            f"{EMOJI['error']} "
            f"{message.author.mention} messed up.\n"
            f"The expected number was **{expected:,}**.\n"
            f"Click 🍅 to shame."
        )

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ):
        # Ignore bots.
        if message.author.bot:
            return

        # Counting only works inside a guild.
        if message.guild is None:
            return

        # Only process the dedicated counting channel.
        if message.channel.id != COUNTING_CHANNEL_ID:
            return

        # Only accept positive integer messages.
        content = message.content.strip()

        if not re.fullmatch(r"\d+", content):
            return

        try:
            current_number = int(content)
        except ValueError:
            return

        # Prevent absurdly large integers.
        if current_number > 9_223_372_036_854_775_807:
            await message.channel.send(
                f"{EMOJI['error']} "
                "That number is too large for the counter."
            )
            return

        async with self.lock:
            current_count, last_member = await self._get_state()

            # Prevent the same person from counting twice
            # consecutively.
            if str(message.author.id) == last_member:
                try:
                    await message.add_reaction(
                        EMOJI["error"]
                    )
                except discord.HTTPException:
                    logger.exception(
                        "Failed to add error reaction."
                    )

                await message.channel.send(
                    f"{EMOJI['error']} "
                    f"{message.author.mention}, "
                    "you already counted. "
                    "Someone else has to go next."
                )

                return

            expected_number = current_count + 1

            # Correct number.
            if current_number == expected_number:
                await self._handle_success(
                    message,
                    current_number,
                )

            # Incorrect number.
            else:
                await self._handle_failure(
                    message,
                    current_count,
                )


# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Counting(bot))
