from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps


log = logging.getLogger("lunar.level_card")


# ==============================================================
# LUNAR ASSETS
# ==============================================================

LUNAR_PANEL_URL = (
    "https://vault.lunarx.to/cdn/admin/manga/migrated/"
    "f38cadbc-96ed-4968-bd7e-1e85215b69a5.png"
)

LUNAR_LOGO_DESIGN_1_URL = (
    "https://vault.lunarx.to/cdn/admin/manga/migrated/"
    "33c739ea-0ec7-4971-a1c0-962f8cc7234b.png"
)

LUNAR_LOGO_MAIN_URL = (
    "https://vault.lunarx.to/cdn/admin/manga/migrated/"
    "5a9015dc-1bd5-435b-adab-9912387ee9a5.png"
)


# ==============================================================
# CARD CONFIGURATION
# ==============================================================

CARD_WIDTH = 1200
CARD_HEIGHT = 500

CORNER_RADIUS = 32

BACKGROUND_TOP = (13, 10, 28)
BACKGROUND_BOTTOM = (9, 16, 31)

VIOLET = (124, 58, 237)
CYAN = (6, 182, 212)

WHITE = (245, 247, 255)
MUTED = (163, 170, 194)
DARK_TEXT = (15, 18, 30)

GUILD_ACCENT = VIOLET
LUNAR_ACCENT = CYAN


# ==============================================================
# DATA MODELS
# ==============================================================


@dataclass(slots=True)
class LevelCardData:
    """
    Guild XP card data.

    Kept under the original name so existing imports remain valid.
    """

    username: str
    level: int
    current_xp: int
    required_xp: int
    rank: int
    total_xp: int

    avatar_url: Optional[str] = None


@dataclass(slots=True)
class LunarLevelCardData:
    """
    Lunar website XP card data.

    These values come directly from the Lunar profile API.
    """

    username: str
    level: int
    current_xp: int
    required_xp: int
    total_xp: int

    rank: Optional[int] = None
    avatar_url: Optional[str] = None


@dataclass(slots=True)
class BothLevelCardData:
    """
    Combined Guild XP + Lunar website XP card.
    """

    username: str
    avatar_url: Optional[str]

    guild: LevelCardData
    lunar: LunarLevelCardData


# ==============================================================
# FONT HELPERS
# ==============================================================

_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont:
    paths = (
        (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf"
        )
        if bold
        else (
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans.ttf"
        )
    )

    try:
        return ImageFont.truetype(
            paths,
            size,
        )
    except OSError:
        return ImageFont.load_default()


# ==============================================================
# IMAGE HELPERS
# ==============================================================


async def _download_image(
    url: Optional[str],
    session: Optional[aiohttp.ClientSession],
) -> Optional[Image.Image]:
    if not url:
        return None

    owned_session = False

    try:
        if session is None:
            timeout = aiohttp.ClientTimeout(
                total=10,
                connect=4,
                sock_read=8,
            )

            session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "User-Agent": "LunarDiscordBot/1.0",
                },
            )

            owned_session = True

        async with session.get(url) as response:
            if response.status != 200:
                return None

            raw = await response.read()

        image = Image.open(
            io.BytesIO(raw)
        ).convert("RGBA")

        return image

    except Exception:
        log.exception(
            "Failed to download card asset: %s",
            url,
        )
        return None

    finally:
        if owned_session and session:
            await session.close()


def _paste_cover(
    base: Image.Image,
    image: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    x1, y1, x2, y2 = box

    width = max(
        1,
        x2 - x1,
    )

    height = max(
        1,
        y2 - y1,
    )

    fitted = ImageOps.fit(
        image,
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    base.alpha_composite(
        fitted,
        (x1, y1),
    )


def _rounded_rectangle(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill,
        outline=outline,
        width=width,
    )


# ==============================================================
# DRAWING HELPERS
# ==============================================================


def _gradient_background() -> Image.Image:
    image = Image.new(
        "RGBA",
        (
            CARD_WIDTH,
            CARD_HEIGHT,
        ),
    )

    pixels = image.load()

    for y in range(CARD_HEIGHT):
        ratio = y / max(
            1,
            CARD_HEIGHT - 1,
        )

        r = int(
            BACKGROUND_TOP[0]
            + (
                BACKGROUND_BOTTOM[0]
                - BACKGROUND_TOP[0]
            )
            * ratio
        )

        g = int(
            BACKGROUND_TOP[1]
            + (
                BACKGROUND_BOTTOM[1]
                - BACKGROUND_TOP[1]
            )
            * ratio
        )

        b = int(
            BACKGROUND_TOP[2]
            + (
                BACKGROUND_BOTTOM[2]
                - BACKGROUND_TOP[2]
            )
            * ratio
        )

        for x in range(CARD_WIDTH):
            pixels[x, y] = (
                r,
                g,
                b,
                255,
            )

    return image


def _draw_progress_bar(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    current: int,
    required: int,
    start,
    end,
) -> None:
    required = max(
        1,
        required,
    )

    ratio = max(
        0.0,
        min(
            1.0,
            current / required,
        ),
    )

    # Track.
    draw.rounded_rectangle(
        (
            x,
            y,
            x + width,
            y + height,
        ),
        radius=height // 2,
        fill=(40, 43, 61),
    )

    fill_width = int(
        width * ratio
    )

    if fill_width <= 0:
        return

    for px in range(fill_width):
        t = px / max(
            1,
            fill_width - 1,
        )

        color = tuple(
            int(
                start[index]
                + (
                    end[index]
                    - start[index]
                )
                * t
            )
            for index in range(3)
        )

        draw.line(
            (
                x + px,
                y,
                x + px,
                y + height,
            ),
            fill=color,
            width=1,
        )

    # Round off the filled portion.
    draw.rounded_rectangle(
        (
            x,
            y,
            x + fill_width,
            y + height,
        ),
        radius=height // 2,
        outline=None,
    )


def _draw_avatar(
    canvas: Image.Image,
    avatar: Optional[Image.Image],
    *,
    center: tuple[int, int],
    size: int,
) -> None:
    x = center[0] - size // 2
    y = center[1] - size // 2

    if avatar is None:
        draw = ImageDraw.Draw(canvas)

        draw.ellipse(
            (
                x,
                y,
                x + size,
                y + size,
            ),
            fill=(48, 52, 72),
            outline=VIOLET,
            width=5,
        )

        return

    avatar = ImageOps.fit(
        avatar,
        (
            size,
            size,
        ),
        method=Image.Resampling.LANCZOS,
    )

    mask = Image.new(
        "L",
        (
            size,
            size,
        ),
        0,
    )

    mask_draw = ImageDraw.Draw(
        mask
    )

    mask_draw.ellipse(
        (
            0,
            0,
            size,
            size,
        ),
        fill=255,
    )

    avatar_layer = Image.new(
        "RGBA",
        (
            size,
            size,
        ),
        (0, 0, 0, 0),
    )

    avatar_layer.paste(
        avatar,
        (0, 0),
        mask,
    )

    canvas.alpha_composite(
        avatar_layer,
        (
            x,
            y,
        ),
    )

    draw = ImageDraw.Draw(
        canvas
    )

    draw.ellipse(
        (
            x,
            y,
            x + size,
            y + size,
        ),
        outline=(255, 255, 255, 90),
        width=4,
    )


def _draw_panel_art(
    canvas: Image.Image,
    panel: Optional[Image.Image],
) -> None:
    """
    Places the provided Lunar panel artwork on the right side.

    The artwork itself remains untouched and is used as an actual
    Lunar asset rather than recreating it with generic shapes.
    """

    if panel is None:
        return

    panel_box = (
        760,
        0,
        CARD_WIDTH,
        CARD_HEIGHT,
    )

    fitted = ImageOps.fit(
        panel,
        (
            panel_box[2] - panel_box[0],
            panel_box[3] - panel_box[1],
        ),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )

    # Slight transparency keeps the statistics readable.
    fitted.putalpha(
        195
    )

    canvas.alpha_composite(
        fitted,
        (
            panel_box[0],
            panel_box[1],
        ),
    )


def _draw_logo(
    canvas: Image.Image,
    logo: Optional[Image.Image],
    *,
    x: int,
    y: int,
    width: int,
) -> None:
    if logo is None:
        return

    ratio = (
        logo.height
        / max(
            1,
            logo.width,
        )
    )

    height = max(
        1,
        int(width * ratio),
    )

    logo = logo.copy()
    logo.thumbnail(
        (
            width,
            height,
        ),
        Image.Resampling.LANCZOS,
    )

    canvas.alpha_composite(
        logo,
        (
            x,
            y,
        ),
    )


# ==============================================================
# GUILD CARD
# ==============================================================


async def render_guild_level_card(
    data: LevelCardData,
    session: Optional[aiohttp.ClientSession] = None,
) -> io.BytesIO:
    canvas = _gradient_background()

    panel = await _download_image(
        LUNAR_PANEL_URL,
        session,
    )

    logo = await _download_image(
        LUNAR_LOGO_MAIN_URL,
        session,
    )

    avatar = await _download_image(
        data.avatar_url,
        session,
    )

    _draw_panel_art(
        canvas,
        panel,
    )

    draw = ImageDraw.Draw(
        canvas
    )

    # Main readable area.
    _rounded_rectangle(
        draw,
        (
            30,
            30,
            795,
            470,
        ),
        CORNER_RADIUS,
        fill=(13, 14, 29, 235),
        outline=(124, 58, 237, 110),
        width=2,
    )

    _draw_logo(
        canvas,
        logo,
        x=55,
        y=50,
        width=125,
    )

    _draw_avatar(
        canvas,
        avatar,
        center=(
            105,
            220,
        ),
        size=130,
    )

    draw.text(
        (
            180,
            135,
        ),
        data.username,
        font=_font(
            34,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            180,
            180,
        ),
        "Guild Level",
        font=_font(
            18
        ),
        fill=MUTED,
    )

    draw.text(
        (
            180,
            208,
        ),
        f"LEVEL {data.level}",
        font=_font(
            38,
            bold=True,
        ),
        fill=(189, 168, 255),
    )

    # Rank.
    draw.text(
        (
            180,
            275,
        ),
        "RANK",
        font=_font(
            14,
            bold=True,
        ),
        fill=MUTED,
    )

    rank_text = (
        f"#{data.rank}"
        if data.rank > 0
        else "—"
    )

    draw.text(
        (
            180,
            297,
        ),
        rank_text,
        font=_font(
            27,
            bold=True,
        ),
        fill=WHITE,
    )

    # Total XP.
    draw.text(
        (
            330,
            275,
        ),
        "TOTAL XP",
        font=_font(
            14,
            bold=True,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            330,
            297,
        ),
        f"{data.total_xp:,}",
        font=_font(
            27,
            bold=True,
        ),
        fill=WHITE,
    )

    # Current progress.
    draw.text(
        (
            180,
            355,
        ),
        f"{data.current_xp:,} / {data.required_xp:,} XP",
        font=_font(
            18,
            bold=True,
        ),
        fill=WHITE,
    )

    _draw_progress_bar(
        draw,
        x=180,
        y=390,
        width=520,
        height=18,
        current=data.current_xp,
        required=data.required_xp,
        start=VIOLET,
        end=CYAN,
    )

    return _save_png(
        canvas
    )


# ==============================================================
# LUNAR CARD
# ==============================================================


async def render_lunar_level_card(
    data: LunarLevelCardData,
    session: Optional[aiohttp.ClientSession] = None,
) -> io.BytesIO:
    canvas = _gradient_background()

    panel = await _download_image(
        LUNAR_PANEL_URL,
        session,
    )

    logo = await _download_image(
        LUNAR_LOGO_DESIGN_1_URL,
        session,
    )

    avatar = await _download_image(
        data.avatar_url,
        session,
    )

    _draw_panel_art(
        canvas,
        panel,
    )

    draw = ImageDraw.Draw(
        canvas
    )

    _rounded_rectangle(
        draw,
        (
            30,
            30,
            795,
            470,
        ),
        CORNER_RADIUS,
        fill=(9, 17, 28, 238),
        outline=(6, 182, 212, 115),
        width=2,
    )

    _draw_logo(
        canvas,
        logo,
        x=55,
        y=50,
        width=125,
    )

    _draw_avatar(
        canvas,
        avatar,
        center=(
            105,
            220,
        ),
        size=130,
    )

    draw.text(
        (
            180,
            135,
        ),
        data.username,
        font=_font(
            34,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            180,
            180,
        ),
        "Lunar Website",
        font=_font(
            18
        ),
        fill=MUTED,
    )

    draw.text(
        (
            180,
            208,
        ),
        f"LEVEL {data.level}",
        font=_font(
            38,
            bold=True,
        ),
        fill=(122, 232, 255),
    )

    draw.text(
        (
            180,
            275,
        ),
        "TOTAL XP",
        font=_font(
            14,
            bold=True,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            180,
            297,
        ),
        f"{data.total_xp:,}",
        font=_font(
            27,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            380,
            275,
        ),
        "RANK",
        font=_font(
            14,
            bold=True,
        ),
        fill=MUTED,
    )

    rank_text = (
        f"#{data.rank}"
        if data.rank is not None and data.rank > 0
        else "—"
    )

    draw.text(
        (
            380,
            297,
        ),
        rank_text,
        font=_font(
            27,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            180,
            355,
        ),
        f"{data.current_xp:,} / {data.required_xp:,} XP",
        font=_font(
            18,
            bold=True,
        ),
        fill=WHITE,
    )

    _draw_progress_bar(
        draw,
        x=180,
        y=390,
        width=520,
        height=18,
        current=data.current_xp,
        required=data.required_xp,
        start=CYAN,
        end=VIOLET,
    )

    return _save_png(
        canvas
    )


# ==============================================================
# BOTH CARD
# ==============================================================


async def render_both_level_card(
    data: BothLevelCardData,
    session: Optional[aiohttp.ClientSession] = None,
) -> io.BytesIO:
    canvas = _gradient_background()

    panel = await _download_image(
        LUNAR_PANEL_URL,
        session,
    )

    logo = await _download_image(
        LUNAR_LOGO_MAIN_URL,
        session,
    )

    avatar = await _download_image(
        data.avatar_url,
        session,
    )

    _draw_panel_art(
        canvas,
        panel,
    )

    draw = ImageDraw.Draw(
        canvas
    )

    # Outer card.
    _rounded_rectangle(
        draw,
        (
            25,
            25,
            1175,
            475,
        ),
        CORNER_RADIUS,
        fill=(11, 13, 27, 242),
        outline=(124, 58, 237, 120),
        width=2,
    )

    _draw_logo(
        canvas,
        logo,
        x=55,
        y=48,
        width=105,
    )

    _draw_avatar(
        canvas,
        avatar,
        center=(
            105,
            245,
        ),
        size=115,
    )

    draw.text(
        (
            175,
            78,
        ),
        data.username,
        font=_font(
            32,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            175,
            122,
        ),
        "Lunar Progression",
        font=_font(
            17
        ),
        fill=MUTED,
    )

    # ----------------------------------------------------------
    # GUILD SECTION
    # ----------------------------------------------------------

    _rounded_rectangle(
        draw,
        (
            175,
            180,
            610,
            430,
        ),
        24,
        fill=(27, 20, 49, 245),
        outline=(124, 58, 237, 80),
        width=2,
    )

    draw.text(
        (
            205,
            205,
        ),
        "GUILD XP",
        font=_font(
            18,
            bold=True,
        ),
        fill=(191, 169, 255),
    )

    draw.text(
        (
            205,
            242,
        ),
        f"LEVEL {data.guild.level}",
        font=_font(
            31,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            205,
            295,
        ),
        f"{data.guild.current_xp:,}",
        font=_font(
            24,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            330,
            295,
        ),
        f"/ {data.guild.required_xp:,} XP",
        font=_font(
            16
        ),
        fill=MUTED,
    )

    _draw_progress_bar(
        draw,
        x=205,
        y=335,
        width=350,
        height=16,
        current=data.guild.current_xp,
        required=data.guild.required_xp,
        start=VIOLET,
        end=CYAN,
    )

    draw.text(
        (
            205,
            375,
        ),
        f"Rank #{data.guild.rank}"
        if data.guild.rank > 0
        else "Unranked",
        font=_font(
            15,
            bold=True,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            405,
            375,
        ),
        f"{data.guild.total_xp:,} total XP",
        font=_font(
            15
        ),
        fill=MUTED,
    )

    # ----------------------------------------------------------
    # LUNAR SECTION
    # ----------------------------------------------------------

    _rounded_rectangle(
        draw,
        (
            635,
            180,
            1070,
            430,
        ),
        24,
        fill=(10, 31, 43, 245),
        outline=(6, 182, 212, 85),
        width=2,
    )

    draw.text(
        (
            665,
            205,
        ),
        "LUNAR WEBSITE XP",
        font=_font(
            18,
            bold=True,
        ),
        fill=(118, 230, 255),
    )

    draw.text(
        (
            665,
            242,
        ),
        f"LEVEL {data.lunar.level}",
        font=_font(
            31,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            665,
            295,
        ),
        f"{data.lunar.current_xp:,}",
        font=_font(
            24,
            bold=True,
        ),
        fill=WHITE,
    )

    draw.text(
        (
            790,
            295,
        ),
        f"/ {data.lunar.required_xp:,} XP",
        font=_font(
            16
        ),
        fill=MUTED,
    )

    _draw_progress_bar(
        draw,
        x=665,
        y=335,
        width=350,
        height=16,
        current=data.lunar.current_xp,
        required=data.lunar.required_xp,
        start=CYAN,
        end=VIOLET,
    )

    if (
        data.lunar.rank is not None
        and data.lunar.rank > 0
    ):
        lunar_rank_text = (
            f"Rank #{data.lunar.rank}"
        )
    else:
        lunar_rank_text = "Rank unavailable"

    draw.text(
        (
            665,
            375,
        ),
        lunar_rank_text,
        font=_font(
            15,
            bold=True,
        ),
        fill=MUTED,
    )

    draw.text(
        (
            865,
            375,
        ),
        f"{data.lunar.total_xp:,} total XP",
        font=_font(
            15
        ),
        fill=MUTED,
    )

    return _save_png(
        canvas
    )


# ==============================================================
# BACKWARDS-COMPATIBLE ENTRY POINT
# ==============================================================


async def render_level_card(
    data,
    session: Optional[aiohttp.ClientSession] = None,
) -> io.BytesIO:
    """
    Generic renderer.

    Existing Guild XP code can continue using:

        render_level_card(LevelCardData(...))

    New code can use:
        LunarLevelCardData
        BothLevelCardData
    """

    if isinstance(
        data,
        BothLevelCardData,
    ):
        return await render_both_level_card(
            data,
            session,
        )

    if isinstance(
        data,
        LunarLevelCardData,
    ):
        return await render_lunar_level_card(
            data,
            session,
        )

    if isinstance(
        data,
        LevelCardData,
    ):
        return await render_guild_level_card(
            data,
            session,
        )

    raise TypeError(
        "Unsupported level card data type: "
        f"{type(data).__name__}"
    )


# ==============================================================
# OUTPUT
# ==============================================================


def _save_png(
    image: Image.Image,
) -> io.BytesIO:
    output = io.BytesIO()

    image.save(
        output,
        format="PNG",
        optimize=True,
    )

    output.seek(0)

    return output