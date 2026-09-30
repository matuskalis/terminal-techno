"""Draw a terminal screen as an image, one character cell at a time.

Shared by tools/capture_tui.py (the TUI screenshot) and tools/render_demo.py (the spectrogram),
so both pictures use the same face, the same grid and the same palette.

Block elements and the box-drawing line are drawn as rectangles, the way terminals draw them,
so bars touch with no seams. Every other glyph comes from the font.
"""

import os

from PIL import Image, ImageDraw, ImageFont

# Tomorrow Night. The app only uses the eight basic ANSI colours, so this is the whole theme.
# pyte calls ANSI yellow "brown".
BACKGROUND = "#1d1f21"
FOREGROUND = "#c5c8c6"
ANSI = {
    "black": "#1d1f21",
    "red": "#cc6666",
    "green": "#b5bd68",
    "brown": "#f0c674",
    "blue": "#81a2be",
    "magenta": "#b294bb",
    "cyan": "#8abeb7",
    "white": "#c5c8c6",
}

ADVANCE_EM = 0.6  # JetBrains Mono advance width in em, so font size = cell width / 0.6
LINE_EM = 1.32  # JetBrains Mono line height in em


class Fonts:
    def __init__(self, regular_path, bold_path=None, cell_w=16):
        if not os.path.exists(regular_path):
            raise SystemExit(f"font not found: {regular_path} (pass --font and --bold)")
        self.size = cell_w / ADVANCE_EM
        self.regular = ImageFont.truetype(regular_path, self.size)
        self.bold = ImageFont.truetype(bold_path or regular_path, self.size)
        self.cell_w = cell_w
        self.cell_h = round(self.size * LINE_EM)
        ascent, descent = self.regular.getmetrics()
        self.baseline = round((self.cell_h - (ascent + descent)) / 2 + ascent)


def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def blend(fg, bg, alpha):
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg, strict=True))


def resolve(name, default):
    """pyte gives a colour name, 'default', or a 6-digit hex string for 256-colour and truecolor."""
    if name == "default":
        return default
    if name in ANSI:
        return hex_to_rgb(ANSI[name])
    return hex_to_rgb(name)


def snapshot(screen):
    """Copy the cells of a pyte screen so later output cannot change a frame already taken."""
    return [[screen.buffer[row][col] for col in range(screen.columns)] for row in range(screen.lines)]


def _block(draw, x, y, fonts, ch, fg, bg):
    """Draw ch as geometry when it is a block element or the light horizontal line."""
    cw, chh = fonts.cell_w, fonts.cell_h
    code = ord(ch)
    if 0x2581 <= code <= 0x2588:  # lower one eighth up to the full block
        eighths = code - 0x2580
        top = y + chh - round(chh * eighths / 8)
        draw.rectangle([x, top, x + cw - 1, y + chh - 1], fill=fg)
        return True
    if ch == "░":
        draw.rectangle([x, y, x + cw - 1, y + chh - 1], fill=blend(fg, bg, 0.25))
        return True
    if ch == "─":
        mid = y + chh // 2
        thickness = max(1, cw // 8)
        draw.rectangle([x, mid - thickness // 2, x + cw - 1, mid - thickness // 2 + thickness - 1], fill=fg)
        return True
    return False


def cells_to_image(cells, fonts, margin_cells=1):
    """Render a snapshot (rows of pyte Char cells) to a PIL image."""
    cw, chh = fonts.cell_w, fonts.cell_h
    margin_x, margin_y = margin_cells * cw, margin_cells * chh // 2
    default_bg = hex_to_rgb(BACKGROUND)
    default_fg = hex_to_rgb(FOREGROUND)
    width = len(cells[0]) * cw + 2 * margin_x
    height = len(cells) * chh + 2 * margin_y
    img = Image.new("RGB", (width, height), default_bg)
    draw = ImageDraw.Draw(img)
    for row, line in enumerate(cells):
        for col, cell in enumerate(line):
            fg = resolve(cell.fg, default_fg)
            bg = resolve(cell.bg, default_bg)
            if cell.reverse:
                fg, bg = bg, fg
            x, y = margin_x + col * cw, margin_y + row * chh
            if bg != default_bg:
                draw.rectangle([x, y, x + cw - 1, y + chh - 1], fill=bg)
            if cell.data.strip() == "":
                continue
            if _block(draw, x, y, fonts, cell.data, fg, bg):
                continue
            font = fonts.bold if cell.bold else fonts.regular
            draw.text((x, y + fonts.baseline), cell.data, font=font, fill=fg, anchor="ls")
    return img
