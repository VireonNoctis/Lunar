from __future__ import annotations

import asyncio
from typing import Optional

import akinator
import discord

from discord import app_commands
from discord.ext import commands

from cogs.utilities.emoji import EMOJI


# ============================================================
# CONFIG
# ============================================================

GAME_TIMEOUT = 600
MAX_DESCRIPTION_LENGTH = 1000


# ============================================================
# AKINATOR SESSION
# ============================================================

class AkinatorSession:

    def __init__(
        self,
        user_id: int,
    ) -> None:

        self.user_id = user_id

        self.aki = akinator.Akinator()

        self.message: Optional[discord.InteractionMessage] = None

        self.lock = asyncio.Lock()

        self.finished = False


# ============================================================
# AKINATOR VIEW
# ============================================================

class AkinatorView(
    discord.ui.View
):

    def __init__(
        self,
        cog: "Akinator",
        session: AkinatorSession,
    ) -> None:

        super().__init__(
            timeout=GAME_TIMEOUT
        )

        self.cog = cog
        self.session = session

    # ========================================================
    # USER CHECK
    # ========================================================

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:

        if interaction.user.id != self.session.user_id:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This Akinator game belongs to someone else.",
                ephemeral=True,
            )

            return False

        return True

    # ========================================================
    # DISABLE BUTTONS
    # ========================================================

    def disable_all(
        self,
    ) -> None:

        for child in self.children:

            if isinstance(
                child,
                discord.ui.Button,
            ):

                child.disabled = True

    # ========================================================
    # YES
    # ========================================================

    @discord.ui.button(
        label="Yes",
        emoji="✅",
        style=discord.ButtonStyle.success,
        row=0,
    )
    async def yes(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_answer(
            interaction,
            self.session,
            "y",
        )

    # ========================================================
    # NO
    # ========================================================

    @discord.ui.button(
        label="No",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        row=0,
    )
    async def no(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_answer(
            interaction,
            self.session,
            "n",
        )

    # ========================================================
    # DON'T KNOW
    # ========================================================

    @discord.ui.button(
        label="Don't Know",
        emoji="❓",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def dont_know(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_answer(
            interaction,
            self.session,
            "i",
        )

    # ========================================================
    # PROBABLY
    # ========================================================

    @discord.ui.button(
        label="Probably",
        emoji="🤔",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def probably(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_answer(
            interaction,
            self.session,
            "p",
        )

    # ========================================================
    # PROBABLY NOT
    # ========================================================

    @discord.ui.button(
        label="Probably Not",
        emoji="↩️",
        style=discord.ButtonStyle.primary,
        row=1,
    )
    async def probably_not(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_answer(
            interaction,
            self.session,
            "pn",
        )

    # ========================================================
    # BACK
    # ========================================================

    @discord.ui.button(
        label="Back",
        emoji="◀️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def back(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.handle_back(
            interaction,
            self.session,
        )

    # ========================================================
    # CANCEL
    # ========================================================

    @discord.ui.button(
        label="Cancel",
        emoji="🛑",
        style=discord.ButtonStyle.danger,
        row=1,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:

        await self.cog.cancel_game(
            interaction,
            self.session,
        )

    # ========================================================
    # TIMEOUT
    # ========================================================

    async def on_timeout(
        self,
    ) -> None:

        session = self.session

        if session.finished:
            return

        session.finished = True

        self.disable_all()

        try:

            if session.message is not None:

                await session.message.edit(
                    embed=discord.Embed(
                        title=(
                            f"{EMOJI['loading']} "
                            "Akinator Game Expired"
                        ),
                        description=(
                            "This game expired because there "
                            "was no response for too long."
                        ),
                        color=discord.Color.dark_grey(),
                    ),
                    view=self,
                )

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):

            pass

        self.cog.remove_session(
            session.user_id
        )


# ============================================================
# AKINATOR COG
# ============================================================

class Akinator(
    commands.Cog
):

    def __init__(
        self,
        bot: commands.Bot,
    ) -> None:

        self.bot = bot

        self.sessions: dict[
            int,
            AkinatorSession,
        ] = {}

    # ========================================================
    # SESSION MANAGEMENT
    # ========================================================

    def remove_session(
        self,
        user_id: int,
    ) -> None:

        self.sessions.pop(
            user_id,
            None,
        )

    # ========================================================
    # CREATE QUESTION EMBED
    # ========================================================

    @staticmethod
    def build_question_embed(
        aki: akinator.Akinator,
    ) -> discord.Embed:

        question = str(aki).strip()

        if not question:

            question = (
                "Akinator is thinking..."
            )

        embed = discord.Embed(
            title=(
                "🔮 Akinator"
            ),
            description=(
                f"**Question {getattr(aki, 'step', 1)}**\n\n"
                f"> {question}\n\n"
                "Think about your character and choose "
                "the answer that fits best."
            ),
            color=0x7C5CFF,
        )

        progression = getattr(
            aki,
            "progression",
            None,
        )

        if progression is not None:

            try:

                embed.set_footer(
                    text=(
                        f"Progress: "
                        f"{float(progression):.1f}%"
                    )
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

        return embed

    # ========================================================
    # CREATE RESULT EMBED
    # ========================================================

    @staticmethod
    def build_result_embed(
        aki: akinator.Akinator,
        user: discord.abc.User,
    ) -> discord.Embed:

        name = (
            str(
                getattr(
                    aki,
                    "name_proposition",
                    None,
                )
                or "Unknown Character"
            ).strip()
        )

        description = (
            str(
                getattr(
                    aki,
                    "description_proposition",
                    None,
                )
                or "Akinator couldn't provide a description."
            ).strip()
        )

        if len(description) > MAX_DESCRIPTION_LENGTH:

            description = (
                description[
                    :MAX_DESCRIPTION_LENGTH - 3
                ]
                + "..."
            )

        embed = discord.Embed(
            title="🔮 Akinator's Guess",
            description=(
                f"**I think your character is:**\n"
                f"## {name}\n\n"
                f"{description}"
            ),
            color=0x7C5CFF,
            timestamp=discord.utils.utcnow(),
        )

        photo = getattr(
            aki,
            "photo",
            None,
        )

        if photo:

            embed.set_image(
                url=str(photo)
            )

        embed.set_footer(
            text=(
                f"Played by {user.display_name}"
            )
        )

        return embed

    # ========================================================
    # /aki
    # ========================================================

    @app_commands.command(
        name="aki",
        description="Play Akinator and let it guess your character.",
    )
    async def aki(
        self,
        interaction: discord.Interaction,
    ) -> None:

        user_id = interaction.user.id

        # ----------------------------------------------------
        # Existing Game Check
        # ----------------------------------------------------

        if user_id in self.sessions:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "You already have an Akinator game running.",
                ephemeral=True,
            )

            return

        # ----------------------------------------------------
        # Create Session
        # ----------------------------------------------------

        session = AkinatorSession(
            user_id=user_id
        )

        self.sessions[
            user_id
        ] = session

        # ----------------------------------------------------
        # Initial Response
        # ----------------------------------------------------

        await interaction.response.defer(
            ephemeral=True
        )

        try:

            await asyncio.wait_for(
                session.aki.start_game(),
                timeout=30,
            )

        except asyncio.TimeoutError:

            self.remove_session(
                user_id
            )

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "Akinator took too long to respond. "
                    "Please try again."
                )
            )

            return

        except Exception as exc:

            self.remove_session(
                user_id
            )

            print(
                f"[Akinator] Failed to start game: "
                f"{type(exc).__name__}: {exc}"
            )

            await interaction.edit_original_response(
                content=(
                    f"{EMOJI['error']} "
                    "I couldn't start an Akinator game "
                    "right now. Please try again later."
                )
            )

            return

        # ----------------------------------------------------
        # Build View
        # ----------------------------------------------------

        view = AkinatorView(
            cog=self,
            session=session,
        )

        embed = self.build_question_embed(
            session.aki
        )

        # ----------------------------------------------------
        # Send Game
        # ----------------------------------------------------

        try:

            session.message = (
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    view=view,
                )
            )

        except discord.HTTPException:

            self.remove_session(
                user_id
            )

    # ========================================================
    # HANDLE ANSWER
    # ========================================================

    async def handle_answer(
        self,
        interaction: discord.Interaction,
        session: AkinatorSession,
        answer: str,
    ) -> None:

        if session.finished:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This game has already ended.",
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        async with session.lock:

            if session.finished:
                return

            try:

                await asyncio.wait_for(
                    session.aki.answer(
                        answer
                    ),
                    timeout=30,
                )

            except asyncio.TimeoutError:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "Akinator took too long to respond. "
                        "Please try again."
                    ),
                    view=None,
                )

                session.finished = True

                self.remove_session(
                    session.user_id
                )

                return

            except akinator.InvalidChoiceError:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "Akinator rejected that answer. "
                        "Please try again."
                    )
                )

                return

            except Exception as exc:

                print(
                    f"[Akinator] Answer failed: "
                    f"{type(exc).__name__}: {exc}"
                )

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "Something went wrong while "
                        "processing your answer."
                    ),
                    view=None,
                )

                session.finished = True

                self.remove_session(
                    session.user_id
                )

                return

            # ------------------------------------------------
            # Finished
            # ------------------------------------------------

            if session.aki.finished:

                await self.finish_game(
                    interaction,
                    session,
                )

                return

            # ------------------------------------------------
            # Next Question
            # ------------------------------------------------

            view = AkinatorView(
                cog=self,
                session=session,
            )

            embed = self.build_question_embed(
                session.aki
            )

            try:

                session.message = (
                    await interaction.edit_original_response(
                        content=None,
                        embed=embed,
                        view=view,
                    )
                )

            except discord.HTTPException:

                session.finished = True

                self.remove_session(
                    session.user_id
                )

    # ========================================================
    # HANDLE BACK
    # ========================================================

    async def handle_back(
        self,
        interaction: discord.Interaction,
        session: AkinatorSession,
    ) -> None:

        if session.finished:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This game has already ended.",
                ephemeral=True,
            )

            return

        await interaction.response.defer()

        async with session.lock:

            if session.finished:
                return

            try:

                await asyncio.wait_for(
                    session.aki.back(),
                    timeout=30,
                )

            except akinator.CantGoBackAnyFurther:

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['denied']} "
                        "You are already on the first question."
                    )
                )

                return

            except Exception as exc:

                print(
                    f"[Akinator] Back failed: "
                    f"{type(exc).__name__}: {exc}"
                )

                await interaction.edit_original_response(
                    content=(
                        f"{EMOJI['error']} "
                        "I couldn't go back to the "
                        "previous question."
                    )
                )

                return

            # ------------------------------------------------
            # Refresh Question
            # ------------------------------------------------

            view = AkinatorView(
                cog=self,
                session=session,
            )

            embed = self.build_question_embed(
                session.aki
            )

            try:

                session.message = (
                    await interaction.edit_original_response(
                        content=None,
                        embed=embed,
                        view=view,
                    )
                )

            except discord.HTTPException:

                session.finished = True

                self.remove_session(
                    session.user_id
                )

    # ========================================================
    # FINISH GAME
    # ========================================================

    async def finish_game(
        self,
        interaction: discord.Interaction,
        session: AkinatorSession,
    ) -> None:

        session.finished = True

        embed = self.build_result_embed(
            session.aki,
            interaction.user,
        )

        view = discord.ui.View(
            timeout=180
        )

        # ----------------------------------------------------
        # Correct Button
        # ----------------------------------------------------

        async def correct_callback(
            button_interaction: discord.Interaction,
        ) -> None:

            if (
                button_interaction.user.id
                != session.user_id
            ):

                await button_interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "This Akinator game belongs to someone else.",
                    ephemeral=True,
                )

                return

            await button_interaction.response.edit_message(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['approved']} "
                        "Akinator Won"
                    ),
                    description=(
                        "I got it right!\n\n"
                        "That character was identified "
                        "successfully."
                    ),
                    color=discord.Color.green(),
                ),
                view=None,
            )

            self.remove_session(
                session.user_id
            )

        # ----------------------------------------------------
        # Wrong Button
        # ----------------------------------------------------

        async def wrong_callback(
            button_interaction: discord.Interaction,
        ) -> None:

            if (
                button_interaction.user.id
                != session.user_id
            ):

                await button_interaction.response.send_message(
                    f"{EMOJI['denied']} "
                    "This Akinator game belongs to someone else.",
                    ephemeral=True,
                )

                return

            self.remove_session(
                session.user_id
            )

            await button_interaction.response.edit_message(
                embed=discord.Embed(
                    title=(
                        f"{EMOJI['approved']} "
                        "Akinator Finished"
                    ),
                    description=(
                        "I couldn't identify your character "
                        "correctly.\n\n"
                        "Use **/aki** to start another game."
                    ),
                    color=discord.Color.orange(),
                ),
                view=None,
            )

        # ----------------------------------------------------
        # Buttons
        # ----------------------------------------------------

        correct_button = discord.ui.Button(
            label="Correct!",
            emoji="✅",
            style=discord.ButtonStyle.success,
        )

        wrong_button = discord.ui.Button(
            label="Wrong",
            emoji="❌",
            style=discord.ButtonStyle.danger,
        )

        correct_button.callback = correct_callback
        wrong_button.callback = wrong_callback

        view.add_item(
            correct_button
        )

        view.add_item(
            wrong_button
        )

        # ----------------------------------------------------
        # Final Result
        # ----------------------------------------------------

        try:

            session.message = (
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    view=view,
                )
            )

        except discord.HTTPException:

            self.remove_session(
                session.user_id
            )

    # ========================================================
    # CANCEL GAME
    # ========================================================

    async def cancel_game(
        self,
        interaction: discord.Interaction,
        session: AkinatorSession,
    ) -> None:

        if session.finished:

            await interaction.response.send_message(
                f"{EMOJI['denied']} "
                "This game has already ended.",
                ephemeral=True,
            )

            return

        session.finished = True

        self.remove_session(
            session.user_id
        )

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=(
                    f"{EMOJI['approved']} "
                    "Akinator Cancelled"
                ),
                description=(
                    "Your Akinator game has been cancelled."
                ),
                color=discord.Color.red(),
            ),
            view=None,
        )


# ============================================================
# SETUP
# ============================================================

async def setup(
    bot: commands.Bot,
) -> None:

    await bot.add_cog(
        Akinator(bot)
    )