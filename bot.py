"""
Ultimate ASCII / ANSI Studio Bot — Render Ready Version
-------------------------------------------------------
- Fixed for Python 3.12 / 3.14 event loop issue
- Clean production version (no auto-install, no hardcoded token)
- Works with Background Worker on Render
- Text → Banner + Image → Art fully supported

Programmer : Jason
Channel    : @eliteworks1
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
import os
import re
from dataclasses import dataclass

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import pyfiglet
from pyfiglet import Figlet, FigletFont

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageEnhance
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    Image = ImageDraw = ImageFont = ImageOps = ImageEnhance = None


# ===========================================================================
#  CONFIGURATION (Environment Variables only)
# ===========================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8245360364:AAGB1xYGpUIN9OsdS9RjUQyouHX0eQTPC_c").strip()
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID", "7669164275").strip()

CATBOX_IMAGE_URL = "https://files.catbox.moe/61tqb5.png"

CATBOX_CAPTION = (
    "🎨 *Welcome to ASCII / ANSI Studio!*\n\n"
    "This bot converts text and images into ASCII art.\n"
    "Use the menu below to get started 👇\n\n"
    "👨‍💻 *Jason*  •  📢 @eliteworks1"
)


# ===========================================================================
#  COLOR PALETTE
# ===========================================================================

COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128),
    "silver": (192, 192, 192), "darkgray": (64, 64, 64),
    "red": (255, 0, 0), "crimson": (220, 20, 60), "maroon": (128, 0, 0),
    "salmon": (250, 128, 114), "pink": (255, 105, 180),
    "orange": (255, 165, 0), "gold": (255, 215, 0), "yellow": (255, 255, 0),
    "amber": (255, 191, 0),
    "green": (0, 255, 0), "lime": (50, 205, 50), "matrix": (0, 255, 120),
    "emerald": (80, 200, 120), "olive": (128, 128, 0), "teal": (0, 128, 128),
    "cyan": (0, 255, 255), "skyblue": (135, 206, 235), "blue": (0, 100, 255),
    "navy": (0, 0, 128), "royal": (65, 105, 225), "indigo": (75, 0, 130),
    "violet": (138, 43, 226),
    "purple": (160, 32, 240), "magenta": (255, 0, 255), "fuchsia": (255, 119, 255),
    "brown": (139, 69, 19), "tan": (210, 180, 140), "beige": (245, 245, 220),
}


# ===========================================================================
#  GLOBAL DEFAULTS
# ===========================================================================

DEFAULT_BANNER_FONT = "standard"
DEFAULT_IMAGE_STYLE = "density"
DEFAULT_COLOR_MODE = "gray"
DEFAULT_FORMAT = "ansi"

MAX_PREVIEW = 3800

STYLES = ("density", "binary", "block", "braille")
COLOR_MODES = ("gray", "mono", "rgb", "gradient")
FORMATS = ("txt", "html", "ansi", "png")

RAMP_DENSITY = " .:•●⬤"
RAMP_BINARY = ". "
RAMP_BLOCK = " ░▒▓█"
RAMP_BRAILLE = " ⠁⠉⠋⠛⠟⠿⡿⣿"

MIN_WIDTH, MAX_WIDTH = 40, 400
MIN_BANNER_WIDTH, MAX_BANNER_WIDTH = 40, 300
MIN_SCALE, MAX_SCALE = 1, 4
MIN_ASPECT, MAX_ASPECT = 0.3, 1.2
MIN_CONTRAST, MAX_CONTRAST = 0.5, 3.0


# ===========================================================================
#  PER-USER STATE
# ===========================================================================

@dataclass
class UserState:
    banner_font: str = DEFAULT_BANNER_FONT
    banner_width: int = 200
    banner_scale: int = 1
    banner_color: str = "matrix"

    image_style: str = DEFAULT_IMAGE_STYLE
    color_mode: str = DEFAULT_COLOR_MODE
    image_color: str = "matrix"
    image_color2: str = "cyan"
    gradient_dir: str = "vertical"
    width: int = 140
    scale: int = 1
    aspect: float = 0.5
    contrast: float = 1.0
    invert: bool = False

    fmt: str = DEFAULT_FORMAT
    mode: str = "idle"


USERS: dict[int, UserState] = {}


def get_user(uid: int) -> UserState:
    if uid not in USERS:
        USERS[uid] = UserState()
    return USERS[uid]


# ===========================================================================
#  LOGGING
# ===========================================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("studio")


# ===========================================================================
#  FIGLET
# ===========================================================================

def all_figlet_fonts() -> list[str]:
    try:
        return sorted(FigletFont.getFonts())
    except Exception:
        return []


ALL_FONTS = all_figlet_fonts()
FONT_COUNT = len(ALL_FONTS)


def find_fonts(query: str) -> list[str]:
    q = query.lower().strip()
    if not q:
        return ALL_FONTS
    return [f for f in ALL_FONTS if q in f.lower()]


def render_banner(text: str, font: str, width: int, scale: int) -> str:
    try:
        fig = Figlet(font=font, width=max(40, width))
        raw = fig.renderText(text)
    except Exception as exc:
        raise ValueError(f"Font '{font}' failed to render: {exc}") from exc
    if scale > 1:
        raw = _scale_text(raw, scale)
    return raw


def _scale_text(text: str, scale: int) -> str:
    if scale <= 1:
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        stretched = "".join(ch * scale for ch in line)
        for _ in range(scale):
            out.append(stretched)
    return "\n".join(out)


# ===========================================================================
#  COLOR HELPERS
# ===========================================================================

HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def parse_hex(s: str):
    s = s.strip().lstrip("#")
    if not HEX_RE.match(s):
        return None
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def resolve_color(name: str, fallback=(0, 255, 120)):
    if not name:
        return fallback
    key = name.lower().strip().lstrip("#")
    if key in COLORS:
        return COLORS[key]
    hx = parse_hex(key)
    if hx:
        return hx
    return fallback


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_color(c1, c2, x, y, w, h, direction: str):
    if direction == "horizontal":
        t = x / max(1, w - 1)
    elif direction == "diagonal":
        t = (x + y) / max(1, (w - 1) + (h - 1))
    else:
        t = y / max(1, h - 1)
    return lerp(c1, c2, t)


# ===========================================================================
#  IMAGE → GRID
# ===========================================================================

def image_to_grid(image_bytes: bytes, width: int, style: str,
                  invert: bool = False, contrast: float = 1.0,
                  aspect: float = 0.5, scale: int = 1):
    if not HAS_PILLOW:
        raise RuntimeError("Pillow is not installed — Image features are disabled")

    img = Image.open(io.BytesIO(image_bytes))
    img.load()

    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)

    rgb_img = img
    gray_img = img.convert("L")
    if invert:
        gray_img = ImageOps.invert(gray_img)

    orig_w, orig_h = gray_img.size
    if orig_w <= 0 or orig_h <= 0:
        raise ValueError("Image has zero dimensions")

    ar = orig_h / orig_w
    new_w = max(1, int(width))
    new_h = max(1, int(new_w * ar * aspect))

    gray_img = gray_img.resize((new_w, new_h), Image.LANCZOS)
    rgb_img = rgb_img.resize((new_w, new_h), Image.LANCZOS)

    gp = list(gray_img.getdata())
    rp = list(rgb_img.getdata())

    ramps = {
        "density": RAMP_DENSITY,
        "binary":  RAMP_BINARY,
        "block":   RAMP_BLOCK,
        "braille": RAMP_BRAILLE,
    }
    ramp = ramps.get(style, RAMP_DENSITY)
    rl = len(ramp)

    grid = []
    for y in range(new_h):
        row = []
        base = y * new_w
        for x in range(new_w):
            v = gp[base + x]
            rgb = rp[base + x]
            idx = ((255 - v) * (rl - 1)) // 255
            row.append((ramp[idx], v, rgb))

        if scale > 1:
            expanded = []
            for cell in row:
                expanded.extend([cell] * scale)
            row = expanded

        for _ in range(scale):
            grid.append(list(row))
    return grid


# ===========================================================================
#  EXPORTERS
# ===========================================================================

def _rgb_to_ansi(rgb) -> int:
    r, g, b = rgb
    ri = round(r / 255 * 5)
    gi = round(g / 255 * 5)
    bi = round(b / 255 * 5)
    return 16 + 36 * ri + 6 * gi + bi


def _apply_color_mode(grid, color_mode: str, c1, c2, direction: str):
    if not grid:
        return grid
    h = len(grid)
    w = max(len(r) for r in grid)

    out = []
    for y, row in enumerate(grid):
        new_row = []
        for x, (ch, v, rgb) in enumerate(row):
            if color_mode == "rgb":
                final = rgb
            elif color_mode == "mono":
                brightness = (255 - v) / 255.0
                final = tuple(int(c * brightness) for c in c1)
            elif color_mode == "gradient":
                base = gradient_color(c1, c2, x, y, w, h, direction)
                brightness = (255 - v) / 255.0
                final = tuple(int(c * brightness) for c in base)
            else:
                g = 255 - v
                final = (g, g, g)
            new_row.append((ch, v, final))
        out.append(new_row)
    return out


def export_txt(grid) -> bytes:
    lines = ["".join(c[0] for c in row) for row in grid]
    return ("\n".join(lines) + "\n").encode("utf-8")


def export_html(grid, title: str = "ASCII Art") -> bytes:
    rows_html = []
    for row in grid:
        spans = []
        for ch, _v, rgb in row:
            safe = "&nbsp;" if ch == " " else html.escape(ch)
            r, g, b = rgb
            spans.append(f'<span style="color:rgb({r},{g},{b})">{safe}</span>')
        rows_html.append("".join(spans))
    body = "\n".join(rows_html)
    doc = (
        "<!DOCTYPE html>\n<html lang='en'><head>\n"
        "<meta charset='utf-8'>\n"
        f"<title>{html.escape(title)}</title>\n"
        "<style>\n"
        "html,body{margin:0;padding:0;background:#000;color:#eee;"
        "font-family:'Consolas','Menlo','DejaVu Sans Mono',monospace;"
        "font-size:10px;line-height:1.0;}\n"
        "pre{margin:0;padding:12px;white-space:pre;display:inline-block;}\n"
        ".meta{color:#666;font-size:11px;padding:8px 12px;font-family:sans-serif;}\n"
        "</style></head><body>\n"
        '<div class="meta">ASCII Studio · @eliteworks1 · Jason</div>\n'
        f"<pre>{body}</pre></body></html>\n"
    )
    return doc.encode("utf-8")


def export_ansi(grid) -> bytes:
    out_lines = []
    for row in grid:
        chunks = []
        cur = None
        for ch, _v, rgb in row:
            if ch == " ":
                chunks.append(" ")
                continue
            idx = _rgb_to_ansi(rgb)
            if idx != cur:
                chunks.append(f"\x1b[38;5;{idx}m")
                cur = idx
            chunks.append(ch)
        chunks.append("\x1b[0m")
        out_lines.append("".join(chunks))
    return ("\n".join(out_lines) + "\n").encode("utf-8")


def _load_font(size):
    if not HAS_PILLOW:
        return None
    for path in (
        "DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "C:/Windows/Fonts/consola.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def export_png(grid, font_size: int = 14, bg=(0, 0, 0)) -> bytes:
    if not HAS_PILLOW:
        raise RuntimeError("Pillow is required for PNG export")

    font = _load_font(font_size)
    if not grid:
        raise ValueError("Empty grid")

    try:
        bbox = font.getbbox("M")
        cw = bbox[2] - bbox[0] or font_size // 2
        ch = bbox[3] - bbox[1] or font_size
    except Exception:
        cw, ch = font_size // 2, font_size

    line_h = int(ch * 1.15)
    cols = max(len(r) for r in grid)
    rows = len(grid)

    img = Image.new("RGB", (cols * cw + 20, rows * line_h + 20), bg)
    draw = ImageDraw.Draw(img)

    for y, row in enumerate(grid):
        for x, (c, _v, rgb) in enumerate(row):
            if c == " ":
                continue
            draw.text((10 + x * cw, 10 + y * line_h), c, font=font, fill=rgb)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()


def banner_to_grid(banner_text: str):
    grid = []
    for line in banner_text.split("\n"):
        row = []
        for ch in line:
            if ch == " ":
                row.append((ch, 255, (0, 0, 0)))
            else:
                row.append((ch, 0, (255, 255, 255)))
        grid.append(row)
    return grid


def _export_grid(grid, fmt: str):
    fmt = fmt.lower()
    if fmt == "txt":
        return export_txt(grid), "art.txt", "text/plain"
    if fmt == "html":
        return export_html(grid), "art.html", "text/html"
    if fmt == "ansi":
        return export_ansi(grid), "art.ansi", "text/plain"
    if fmt == "png":
        return export_png(grid), "art.png", "image/png"
    raise ValueError(f"Unknown format: {fmt}")


# ===========================================================================
#  UI HELPERS
# ===========================================================================

def _mark(active: bool, label: str) -> str:
    return f"✅ {label}" if active else label


def main_menu_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("✍️  Text → Banner", callback_data="menu:banner")],
    ]
    if HAS_PILLOW:
        buttons.append([InlineKeyboardButton("🖼️  Image → Art", callback_data="menu:image")])
    else:
        buttons.append([InlineKeyboardButton("🖼️  Image → Art (disabled)", callback_data="menu:no_pillow")])

    buttons.extend([
        [InlineKeyboardButton("📐 Size Presets", callback_data="menu:presets")],
        [InlineKeyboardButton("🎨 Colors", callback_data="menu:colors")],
        [InlineKeyboardButton("📦 Export Format", callback_data="menu:format")],
    ])
    return InlineKeyboardMarkup(buttons)


def banner_menu_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Choose Font", callback_data="ban:fonts:0")],
        [InlineKeyboardButton("🔍 Search Font", callback_data="ban:search")],
        [InlineKeyboardButton(f"📏 Width: {u.banner_width}", callback_data="ban:w:show")],
        [InlineKeyboardButton(f"📐 Scale: {u.banner_scale}x", callback_data="ban:s:show")],
        [InlineKeyboardButton(f"🎨 Color: {u.banner_color}", callback_data="menu:colors:banner")],
        [InlineKeyboardButton("📥 Export Format", callback_data="menu:format")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:main")],
    ])


def image_menu_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_mark(u.image_style == "density", "Density ●"), callback_data="img:style:density"),
         InlineKeyboardButton(_mark(u.image_style == "binary", "Binary ."), callback_data="img:style:binary")],
        [InlineKeyboardButton(_mark(u.image_style == "block", "Block ▓"), callback_data="img:style:block"),
         InlineKeyboardButton(_mark(u.image_style == "braille", "Braille ⣿"), callback_data="img:style:braille")],
        [InlineKeyboardButton(_mark(u.color_mode == "gray", "Gray"), callback_data="img:color:gray"),
         InlineKeyboardButton(_mark(u.color_mode == "mono", "Mono"), callback_data="img:color:mono")],
        [InlineKeyboardButton(_mark(u.color_mode == "rgb", "RGB 🌈"), callback_data="img:color:rgb"),
         InlineKeyboardButton(_mark(u.color_mode == "gradient", "Gradient 🎨"), callback_data="img:color:gradient")],
        [InlineKeyboardButton(f"🎨 Color 1: {u.image_color}", callback_data="menu:colors:img1"),
         InlineKeyboardButton(f"🎨 Color 2: {u.image_color2}", callback_data="menu:colors:img2")],
        [InlineKeyboardButton(f"↘️ Gradient: {u.gradient_dir}", callback_data="img:gradir:show")],
        [InlineKeyboardButton(f"📏 Width: {u.width}", callback_data="img:w:show"),
         InlineKeyboardButton(f"📐 Scale: {u.scale}x", callback_data="img:s:show")],
        [InlineKeyboardButton(f"🧭 Aspect: {u.aspect:.1f}", callback_data="img:a:show"),
         InlineKeyboardButton(f"🌗 Contrast: {u.contrast:.2f}", callback_data="img:c:show")],
        [InlineKeyboardButton(_mark(u.invert, "Invert"), callback_data="img:invert")],
        [InlineKeyboardButton("📦 Export Format", callback_data="menu:format")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:main")],
    ])


def format_kb(u: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_mark(u.fmt == "txt", ".txt"), callback_data="fmt:txt"),
         InlineKeyboardButton(_mark(u.fmt == "html", ".html"), callback_data="fmt:html")],
        [InlineKeyboardButton(_mark(u.fmt == "ansi", ".ansi"), callback_data="fmt:ansi"),
         InlineKeyboardButton(_mark(u.fmt == "png", "PNG"), callback_data="fmt:png")],
        [InlineKeyboardButton("⬅️ Back", callback_data="menu:main")],
    ])


def color_menu_kb(target: str, current: str) -> InlineKeyboardMarkup:
    names = list(COLORS.keys())
    rows = []
    row = []
    for name in names:
        label = _mark(name == current, name)
        row.append(InlineKeyboardButton(label, callback_data=f"col:set:{target}:{name}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ Custom HEX (#RRGGBB)", callback_data=f"col:hex:{target}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:banner" if target == "banner" else "menu:image")])
    return InlineKeyboardMarkup(rows)


# ===========================================================================
#  UI SCREENS
# ===========================================================================

def _header() -> str:
    return (
        "╔════════════════════════════════╗\n"
        "║   🎨  ASCII  /  ANSI  STUDIO   ║\n"
        "╚════════════════════════════════╝"
    )


def _footer() -> str:
    return "👨‍💻 *Jason*  •  📢 @eliteworks1"


def welcome_text(u: UserState) -> str:
    fc = FONT_COUNT
    pillow_status = "✅ Enabled" if HAS_PILLOW else "❌ Disabled (Pillow missing)"

    return (
        f"{_header()}\n\n"
        "One *all-in-one* tool — convert text or images\n"
        "into ASCII / ANSI art.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "✍️  *Text → Banner*\n"
        f"   • {fc}+ FIGlet fonts\n"
        "   • Custom width and scale\n"
        "   • 33 colors + custom hex\n\n"
        "🖼️  *Image → Art*\n"
        f"   • Status: {pillow_status}\n"
        "   • 4 styles + 4 color modes\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Format: *{u.fmt.upper()}*\n\n"
        "Choose a tool below 👇\n\n"
        f"{_footer()}"
    )


def banner_screen(u: UserState) -> str:
    return (
        "✍️ *Text → Banner*\n\n"
        "Send your text — I will convert it into a banner.\n\n"
        f"🔤 Font  : `{u.banner_font}`\n"
        f"📏 Width : `{u.banner_width}`\n"
        f"📐 Scale : `{u.banner_scale}x`\n"
        f"🎨 Color : `{u.banner_color}`\n"
        f"📦 Format: `{u.fmt.upper()}`\n\n"
        "Adjust settings with the buttons, then send your text:"
    )


# ===========================================================================
#  COMMANDS
# ===========================================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = get_user(update.effective_user.id)
    u.mode = "idle"

    if CATBOX_IMAGE_URL and CATBOX_IMAGE_URL.startswith("http"):
        try:
            await update.message.reply_photo(
                photo=CATBOX_IMAGE_URL,
                caption=CATBOX_CAPTION,
                parse_mode=ParseMode.MARKDOWN,
            )
        except TelegramError as exc:
            log.warning("Catbox image send failed: %s", exc)

    await update.message.reply_text(
        welcome_text(u),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_kb(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_banner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    u = get_user(update.effective_user.id)
    u.mode = "awaiting_banner_text"
    await update.message.reply_text(
        banner_screen(u),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=banner_menu_kb(u),
    )


# ===========================================================================
#  CALLBACK HANDLER
# ===========================================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not q.data:
        return
    u = get_user(q.from_user.id)
    data = q.data
    await q.answer()

    if data == "menu:main":
        u.mode = "idle"
        await q.edit_message_text(welcome_text(u), parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb())
        return

    if data == "menu:banner":
        u.mode = "awaiting_banner_text"
        await q.edit_message_text(banner_screen(u), parse_mode=ParseMode.MARKDOWN, reply_markup=banner_menu_kb(u))
        return

    if data == "menu:no_pillow":
        await q.edit_message_text(
            "❌ *Image → Art is currently disabled*\n\n"
            "Pillow could not be installed on this environment.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:main")]])
        )
        return

    if data == "menu:image":
        if not HAS_PILLOW:
            await q.edit_message_text(
                "❌ Pillow is not available. Image features are disabled.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:main")]])
            )
            return
        u.mode = "awaiting_image"
        await q.edit_message_text(
            "🖼️ *Image → Art*\n\nSend your image now.\n\n"
            "You can also adjust settings below before sending.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_menu_kb(u)
        )
        return

    if data == "menu:format":
        await q.edit_message_text(
            f"📦 *Export Format*\n\nCurrent: `{u.fmt.upper()}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=format_kb(u)
        )
        return

    if data.startswith("fmt:"):
        fmt = data.split(":")[1]
        if fmt in FORMATS:
            u.fmt = fmt
        await q.edit_message_text(
            f"✅ Format set to `{u.fmt.upper()}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=format_kb(u)
        )
        return

    if data.startswith("img:style:"):
        style = data.split(":")[2]
        if style in STYLES:
            u.image_style = style
        await q.edit_message_text(
            "🖼️ *Image → Art*\n\nSend your image now.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_menu_kb(u)
        )
        return

    if data.startswith("img:color:"):
        mode = data.split(":")[2]
        if mode in COLOR_MODES:
            u.color_mode = mode
        await q.edit_message_text(
            "🖼️ *Image → Art*\n\nSend your image now.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_menu_kb(u)
        )
        return

    if data == "img:invert":
        u.invert = not u.invert
        await q.edit_message_text(
            "🖼️ *Image → Art*\n\nSend your image now.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_menu_kb(u)
        )
        return

    # Color selection
    if data.startswith("menu:colors"):
        parts = data.split(":")
        target = parts[2] if len(parts) > 2 else "banner"
        current = u.banner_color if target == "banner" else (u.image_color if target == "img1" else u.image_color2)
        await q.edit_message_text(
            f"🎨 *Choose Color* ({target})",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=color_menu_kb(target, current)
        )
        return

    if data.startswith("col:set:"):
        _, _, target, name = data.split(":")
        if target == "banner":
            u.banner_color = name
        elif target == "img1":
            u.image_color = name
        elif target == "img2":
            u.image_color2 = name
        back = "menu:banner" if target == "banner" else "menu:image"
        await q.edit_message_text(
            f"✅ Color set to `{name}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=back)]])
        )
        return

    # Simple fallback
    await q.edit_message_text(
        "Feature coming soon or already applied.\nUse the buttons to continue.",
        reply_markup=main_menu_kb()
    )


# ===========================================================================
#  TEXT + IMAGE HANDLERS
# ===========================================================================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    u = get_user(update.effective_user.id)
    text = msg.text.strip()

    if text.startswith("/"):
        return

    if u.mode in ("awaiting_banner_text", "idle"):
        await _send_banner(msg, u, text)


async def _send_banner(msg, u: UserState, text: str) -> None:
    status = await msg.reply_text(
        f"✍️ Rendering banner with font `{u.banner_font}`...",
        parse_mode=ParseMode.MARKDOWN
    )
    try:
        banner = render_banner(text, u.banner_font, u.banner_width, u.banner_scale)

        if u.fmt == "txt":
            await msg.reply_document(
                document=io.BytesIO(banner.encode("utf-8")),
                filename=f"banner_{u.banner_font}.txt",
                caption=f"✅ Font: `{u.banner_font}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            grid = banner_to_grid(banner)
            c1 = resolve_color(u.banner_color)
            grid = _apply_color_mode(grid, "mono", c1, c1, "vertical")
            file_bytes, filename, _ = _export_grid(grid, u.fmt)
            await msg.reply_document(
                document=io.BytesIO(file_bytes),
                filename=f"banner_{u.banner_font}.{u.fmt}",
                caption=f"✅ Font: `{u.banner_font}` · Color: `{u.banner_color}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        if len(banner) <= MAX_PREVIEW:
            await msg.reply_text(f"<pre>{html.escape(banner)}</pre>", parse_mode=ParseMode.HTML)
        await status.delete()
    except Exception as exc:
        log.exception("Banner failed")
        await status.edit_text(f"❌ Error: `{exc}`", parse_mode=ParseMode.MARKDOWN)


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None:
        return

    if not HAS_PILLOW:
        await msg.reply_text(
            "❌ Image features are disabled because Pillow is not installed.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    u = get_user(update.effective_user.id)
    status = await msg.reply_text("🖼️ Processing image...")

    try:
        # Get the largest photo or document
        if msg.photo:
            photo = msg.photo[-1]
            file = await context.bot.get_file(photo.file_id)
        elif msg.document:
            file = await context.bot.get_file(msg.document.file_id)
        else:
            await status.edit_text("❌ No valid image found.")
            return

        image_bytes = await file.download_as_bytearray()

        grid = image_to_grid(
            bytes(image_bytes),
            width=u.width,
            style=u.image_style,
            invert=u.invert,
            contrast=u.contrast,
            aspect=u.aspect,
            scale=u.scale,
        )

        c1 = resolve_color(u.image_color)
        c2 = resolve_color(u.image_color2)
        grid = _apply_color_mode(grid, u.color_mode, c1, c2, u.gradient_dir)

        file_bytes, filename, _ = _export_grid(grid, u.fmt)

        await msg.reply_document(
            document=io.BytesIO(file_bytes),
            filename=filename,
            caption=(
                f"✅ Style: `{u.image_style}` · Mode: `{u.color_mode}`\n"
                f"Width: `{u.width}` · Format: `{u.fmt.upper()}`"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        await status.delete()
    except Exception as exc:
        log.exception("Image processing failed")
        await status.edit_text(f"❌ Error: `{exc}`", parse_mode=ParseMode.MARKDOWN)


# ===========================================================================
#  ENTRY POINT
# ===========================================================================

def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set!\n"
            "On Render: go to Environment → Add BOT_TOKEN"
        )

    log.info("=" * 50)
    log.info("ASCII / ANSI Studio Bot starting...")
    log.info(f"FIGlet fonts loaded : {FONT_COUNT}")
    log.info(f"Pillow available    : {'YES' if HAS_PILLOW else 'NO'}")
    log.info("=" * 50)

    # ===== FIX FOR PYTHON 3.14 / 3.12 event loop issue =====
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    # ======================================================

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("banner", cmd_banner))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot is running (polling mode)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
