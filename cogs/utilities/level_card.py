from __future__ import annotations

import io
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter

log = logging.getLogger("lunar.level_card")


# ============================================================
# Configuration
# ============================================================

CARD_WIDTH = 1200
CARD_HEIGHT = 500

PRIMARY_VIOLET = (124, 58, 237)   # #7c3aed
PRIMARY_CYAN = (6, 182, 212)      # #06b6d4

BACKGROUND = (10, 10, 18)
PANEL = (18, 18, 30)
PANEL_2 = (23, 23, 39)

TEXT = (245, 247, 255)
TEXT_MUTED = (158, 164, 184)

BORDER = (48, 48, 72)

AVATAR_SIZE = 150
AVATAR_X = 54
AVATAR_Y = 86

BRAND_ASSET_PATH = os.getenv(
    "LUNAR_LEVEL_CARD_ASSET",
    "assets/lunar_level_placeholder.png",
)


# ============================================================
# Data
# ============================================================

@dataclass(slots=True)
class LevelCardData:
    username: str
    level: int
    xp: int
    required_xp: int
    rank: int
    total_xp: int
    avatar_url: Optional[str] = None


# ============================================================
# Fonts
# ============================================================

def _font(
    size: int,
    bold: bool = False,
) -> ImageFont.FreeTypeFont:

    candidates = []

    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]
        )

    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(
                path,
                size,
            )

    return ImageFont.load_default()


FONT_USERNAME = _font(42, True)
FONT_LEVEL = _font(52, True)
FONT_LARGE = _font(34, True)
FONT_LABEL = _font(20, False)
FONT_VALUE = _font(24, True)
FONT_SMALL = _font(17, False)


# ============================================================
# Color helpers
# ============================================================

def _lerp(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:

    amount = max(
        0.0,
        min(1.0, amount),
    )

    return tuple(
        int(
            start[index]
            + (
                end[index]
                - start[index]
            )
            * amount
        )
        for index in range(3)
    )


def _gradient(
    width: int,
    height: int,
) -> Image.Image:

    image = Image.new(
        "RGB",
        (width, height),
    )

    pixels = image.load()

    for y in range(height):
        for x in range(width):
            # Mostly horizontal, with a very slight
            # vertical influence for depth.
            horizontal = (
                x / max(1, width - 1)
            )

            vertical = (
                y / max(1, height - 1)
            )

            amount = (
                horizontal * 0.85
                + vertical * 0.15
            )

            pixels[x, y] = _lerp(
                PRIMARY_VIOLET,
                PRIMARY_CYAN,
                amount,
            )

    return image


# ============================================================
# Background
# ============================================================

def _create_background() -> Image.Image:

    canvas = Image.new(
        "RGB",
        (
            CARD_WIDTH,
            CARD_HEIGHT,
        ),
        BACKGROUND,
    )

    # Large soft violet glow.
    glow = Image.new(
        "RGBA",
        canvas.size,
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(
        glow,
        "RGBA",
    )

    draw.ellipse(
        (
            -180,
            -180,
            560,
            520,
        ),
        fill=(
            *PRIMARY_VIOLET,
            85,
        ),
    )

    draw.ellipse(
        (
            760,
            110,
            1430,
            780,
        ),
        fill=(
            *PRIMARY_CYAN,
            70,
        ),
    )

    glow = glow.filter(
        ImageFilter.GaussianBlur(70)
    )

    canvas = Image.alpha_composite(
        canvas.convert("RGBA"),
        glow,
    )

    return canvas


# ============================================================
# Rounded panel
# ============================================================

def _rounded_panel(
    image: Image.Image,
    box: tuple[int, int, int, int],
    radius: int = 30,
    fill: tuple[int, int, int, int] = (
        *PANEL,
        225,
    ),
    outline: Optional[
        tuple[int, int, int, int]
    ] = None,
    width: int = 1,
) -> None:

    draw = ImageDraw.Draw(
        image,
        "RGBA",
    )

    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill,
        outline=outline,
        width=width,
    )


# ============================================================
# Avatar
# ============================================================

async def _download_avatar(
    url: Optional[str],
    session: aiohttp.ClientSession,
) -> Optional[Image.Image]:

    if not url:
        return None

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(
                total=8,
            ),
        ) as response:

            if response.status != 200:
                return None

            data = await response.read()

        avatar = Image.open(
            io.BytesIO(data)
        ).convert("RGBA")

        return avatar

    except Exception:
        log.exception(
            "Failed to download level-card avatar."
        )
        return None


def _make_circle(
    image: Image.Image,
    size: int,
) -> Image.Image:

    image.thumbnail(
        (size, size),
        Image.Resampling.LANCZOS,
    )

    output = Image.new(
        "RGBA",
        (size, size),
        (0, 0, 0, 0),
    )

    x = (
        size - image.width
    ) // 2

    y = (
        size - image.height
    ) // 2

    output.paste(
        image,
        (x, y),
        image,
    )

    mask = Image.new(
        "L",
        (size, size),
        0,
    )

    mask_draw = ImageDraw.Draw(
        mask,
    )

    mask_draw.ellipse(
        (0, 0, size, size),
        fill=255,
    )

    output.putalpha(
        mask
    )

    return output


def _draw_avatar(
    image: Image.Image,
    avatar: Optional[Image.Image],
) -> None:

    draw = ImageDraw.Draw(
        image,
        "RGBA",
    )

    x = AVATAR_X
    y = AVATAR_Y

    # Gradient-like outer rings.
    draw.ellipse(
        (
            x - 7,
            y - 7,
            x + AVATAR_SIZE + 7,
            y + AVATAR_SIZE + 7,
        ),
        outline=(
            *PRIMARY_VIOLET,
            255,
        ),
        width=5,
    )

    draw.ellipse(
        (
            x - 2,
            y - 2,
            x + AVATAR_SIZE + 2,
            y + AVATAR_SIZE + 2,
        ),
        outline=(
            *PRIMARY_CYAN,
            180,
        ),
        width=2,
    )

    if avatar is None:
        draw.ellipse(
            (
                x,
                y,
                x + AVATAR_SIZE,
                y + AVATAR_SIZE,
            ),
            fill=(
                32,
                32,
                50,
                255,
            ),
        )

        font = _font(
            56,
            True,
        )

        draw.text(
            (
                x + AVATAR_SIZE / 2,
                y + AVATAR_SIZE / 2,
            ),
            "?",
            font=font,
            fill=TEXT,
            anchor="mm",
        )

        return

    avatar = _make_circle(
        avatar,
        AVATAR_SIZE,
    )

    image.alpha_composite(
        avatar,
        (x, y),
    )


# ============================================================
# Brand placeholder
# ============================================================

def _draw_brand_placeholder(
    image: Image.Image,
) -> None:

    draw = ImageDraw.Draw(
        image,
        "RGBA",
    )

    center_x = 1080
    center_y = 250
    radius = 78

    # Glow ring.
    for spread in (
        28,
        20,
        12,
    ):

        alpha = {
            28: 25,
            20: 40,
            12: 65,
        }[spread]

        draw.ellipse(
            (
                center_x - radius - spread,
                center_y - radius - spread,
                center_x + radius + spread,
                center_y + radius + spread,
            ),
            outline=(
                *PRIMARY_CYAN,
                alpha,
            ),
            width=3,
        )

    draw.ellipse(
        (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        ),
        fill=(
            12,
            14,
            25,
            230,
        ),
        outline=(
            *PRIMARY_CYAN,
            180,
        ),
        width=3,
    )

    # Crescent placeholder.
    draw.ellipse(
        (
            center_x - 37,
            center_y - 37,
            center_x + 37,
            center_y + 37,
        ),
        fill=(
            235,
            240,
            255,
            240,
        ),
    )

    draw.ellipse(
        (
            center_x - 18,
            center_y - 42,
            center_x + 50,
            center_y + 26,
        ),
        fill=(
            12,
            14,
            25,
            255,
        ),
    )

    draw.text(
        (
            center_x,
            center_y + 100,
        ),
        "LUNAR",
        font=_font(
            20,
            True,
        ),
        fill=TEXT_MUTED,
        anchor="mm",
    )


# ============================================================
# Progress Bar
# ============================================================

def _draw_progress_bar(
    image: Image.Image,
    x: int,
    y: int,
    width: int,
    height: int,
    progress: float,
) -> None:

    draw = ImageDraw.Draw(
        image,
        "RGBA",
    )

    progress = max(
        0.0,
        min(1.0, progress),
    )

    draw.rounded_rectangle(
        (
            x,
            y,
            x + width,
            y + height,
        ),
        radius=height // 2,
        fill=(
            34,
            35,
            52,
            255,
        ),
    )

    if progress <= 0:
        return

    filled_width = max(
        height,
        int(
            width * progress
        ),
    )

    gradient = _gradient(
        filled_width,
        height,
    )

    mask = Image.new(
        "L",
        (
            filled_width,
            height,
        ),
        0,
    )

    mask_draw = ImageDraw.Draw(
        mask,
    )

    mask_draw.rounded_rectangle(
        (
            0,
            0,
            filled_width,
            height,
        ),
        radius=height // 2,
        fill=255,
    )

    gradient.putalpha(
        mask
    )

    image.alpha_composite(
        gradient,
        (
            x,
            y,
        ),
    )


# ============================================================
# Main Renderer
# ============================================================

async def render_level_card(
    data: LevelCardData,
    *,
    session: Optional[aiohttp.ClientSession] = None,
) -> io.BytesIO:

    own_session = False

    if session is None:

        session = aiohttp.ClientSession(
            headers={
                "User-Agent": (
                    "LunarDiscordBot/LevelCard"
                )
            },
        )

        own_session = True

    try:

        canvas = _create_background()

        # Main card.
        _rounded_panel(
            canvas,
            (
                24,
                24,
                CARD_WIDTH - 24,
                CARD_HEIGHT - 24,
            ),
            radius=34,
            fill=(
                *PANEL,
                225,
            ),
            outline=(
                90,
                90,
                120,
                90,
            ),
            width=2,
        )

        # Accent line.
        gradient = _gradient(
            720,
            6,
        )

        gradient_mask = Image.new(
            "L",
            gradient.size,
            0,
        )

        ImageDraw.Draw(
            gradient_mask
        ).rounded_rectangle(
            (
                0,
                0,
                720,
                6,
            ),
            radius=3,
            fill=255,
        )

        gradient.putalpha(
            gradient_mask
        )

        canvas.alpha_composite(
            gradient,
            (
                44,
                42,
            ),
        )

        # Avatar.
        avatar = await _download_avatar(
            data.avatar_url,
            session,
        )

        _draw_avatar(
            canvas,
            avatar,
        )

        draw = ImageDraw.Draw(
            canvas,
            "RGBA",
        )

        # ----------------------------------------------------
        # User
        # ----------------------------------------------------

        draw.text(
            (
                245,
                92,
            ),
            data.username[:28],
            font=FONT_USERNAME,
            fill=TEXT,
        )

        draw.text(
            (
                247,
                146,
            ),
            "LUNAR LEVEL",
            font=FONT_LABEL,
            fill=TEXT_MUTED,
        )

        draw.text(
            (
                245,
                176,
            ),
            f"LEVEL {data.level}",
            font=FONT_LEVEL,
            fill=TEXT,
        )

        # ----------------------------------------------------
        # Rank
        # ----------------------------------------------------

        _rounded_panel(
            canvas,
            (
                760,
                76,
                930,
                150,
            ),
            radius=18,
            fill=(
                30,
                31,
                48,
                220,
            ),
        )

        draw.text(
            (
                785,
                89,
            ),
            "RANK",
            font=FONT_LABEL,
            fill=TEXT_MUTED,
        )

        draw.text(
            (
                855,
                87,
            ),
            f"#{max(1, data.rank)}",
            font=FONT_VALUE,
            fill=TEXT,
        )

        # ----------------------------------------------------
        # XP Progress
        # ----------------------------------------------------

        progress = (
            data.xp / data.required_xp
            if data.required_xp > 0
            else 0
        )

        progress = max(
            0.0,
            min(
                1.0,
                progress,
            ),
        )

        draw.text(
            (
                245,
                265,
            ),
            "XP",
            font=FONT_LABEL,
            fill=TEXT_MUTED,
        )

        _draw_progress_bar(
            canvas,
            245,
            302,
            680,
            24,
            progress,
        )

        draw.text(
            (
                245,
                338,
            ),
            f"{data.xp:,} / {data.required_xp:,}",
            font=FONT_VALUE,
            fill=TEXT,
        )

        draw.text(
            (
                925,
                339,
            ),
            f"{progress * 100:.1f}%",
            font=FONT_SMALL,
            fill=TEXT_MUTED,
            anchor="ra",
        )

        # ----------------------------------------------------
        # Bottom statistics
        # ----------------------------------------------------

        stat_y = 405

        draw.text(
            (
                245,
                stat_y,
            ),
            "TOTAL XP",
            font=FONT_LABEL,
            fill=TEXT_MUTED,
        )

        draw.text(
            (
                365,
                stat_y - 2,
            ),
            f"{data.total_xp:,}",
            font=FONT_VALUE,
            fill=TEXT,
        )

        # ----------------------------------------------------
        # Placeholder brand area.
        # Replace later with the actual Lunar asset.
        # ----------------------------------------------------

        _draw_brand_placeholder(
            canvas
        )

        # ----------------------------------------------------
        # Save
        # ----------------------------------------------------

        output = io.BytesIO()

        canvas.convert(
            "RGB"
        ).save(
            output,
            format="PNG",
            optimize=True,
        )

        output.seek(0)

        return output

    finally:

        if own_session:

            await session.close()