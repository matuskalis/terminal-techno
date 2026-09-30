#!/usr/bin/env python3
"""Capture the real TUI as a PNG screenshot and a GIF.

techno.py runs unchanged in a pseudo-terminal. tools/null_audio stands in for sounddevice, so no
sound card is opened and nothing is played. The app's terminal output goes through the pyte
terminal emulator and termshot.py draws the resulting screen cell by cell: the pictures are the
real screen, not a mockup. The session is scripted with key presses, the way a player drives it.

    pip install pyte pillow
    python tools/capture_tui.py --png docs/tui.png --gif docs/tui.gif

The face is JetBrains Mono (SIL OFL, https://github.com/JetBrains/JetBrainsMono). Put
JetBrainsMono-Regular.ttf and JetBrainsMono-Bold.ttf in tools/fonts/ or pass --font and --bold.
"""

import argparse
import re
import sys
from pathlib import Path

from PIL import Image

from ptyapp import Session
from termshot import Fonts, cells_to_image

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "tools" / "fonts"
FRAME_SECONDS = 0.15
GIF_CELL_W = 9
GIF_COLOURS = 48
HOLD_LAST_MS = 1500
FADE_TARGET = (40, 60)  # crossfade percentages the still is picked from


def row_text(cells, row):
    return "".join(cell.data for cell in cells[row])


def play(session):
    """Arm a board, crossfade into another. Every wait is on the screen, none is a fixed delay."""
    every = FRAME_SECONDS
    session.wait_for(lambda lines: "BAR 001" in lines[0], "the first bar")  # frames start once it is playing
    session.pump(0.9, every)
    session.send(b"]")  # arm board 2, it lands on the next bar line
    session.wait_for(lambda lines: "[2]" in lines[1], "board 2 going live", sample_every=every)
    session.send(b"6")  # cursor to the LED track, on an accented step
    session.pump(0.6, every)
    session.send(b"]")  # arm board 3
    session.wait_for(lambda lines: "NEXT 3" in lines[1], "the board 3 countdown", sample_every=every)
    session.pump(0.6, every)
    session.send(b"t")  # crossfade: deck B takes the armed board
    session.wait_for(lambda lines: "<3>" in lines[1], "deck B", sample_every=every)
    while "<3>" in session.lines()[1]:  # run the fader up, 100 percent commits the swap
        session.send(b"0")
        session.pump(0.15, every)
    session.wait_for(lambda lines: "[3]" in lines[1], "board 3 going live", sample_every=every)
    session.pump(0.9, every)


def liveness(cells):
    """How much of the screen is moving: lit meter cells plus scope and spectrum cells."""
    meters = sum(cell.data == "█" for row in range(3, 9) for cell in cells[row])
    plots = sum(cell.data.strip() != "" for row in range(11, len(cells) - 5) for cell in cells[row])
    return meters + plots


def pick_hero(frames):
    """The fullest frame while the crossfade is about half way: playhead, meters, scope, spectrum."""
    low, high = FADE_TARGET
    candidates = []
    for _, cells in frames:
        match = re.search(r"B acid\s+(\d+)%", row_text(cells, 1))
        if match and low <= int(match.group(1)) <= high:
            candidates.append(cells)
    if not candidates:
        raise SystemExit(f"no frame with the crossfade between {low} and {high} percent")
    return max(candidates, key=liveness)


def save_gif(frames, fonts, path):
    images = [cells_to_image(cells, fonts) for _, cells in frames]
    stamps = [stamp for stamp, _ in frames]
    durations = [round((b - a) * 1000) for a, b in zip(stamps, stamps[1:], strict=False)] + [HOLD_LAST_MS]
    montage = Image.new("RGB", (images[0].width, images[0].height * 4))
    for slot, index in enumerate(range(0, len(images), max(1, len(images) // 4))[:4]):
        montage.paste(images[index], (0, slot * images[0].height))
    palette = montage.quantize(colors=GIF_COLOURS, dither=Image.Dither.NONE)
    paletted = [img.quantize(palette=palette, dither=Image.Dither.NONE) for img in images]
    paletted[0].save(path, save_all=True, append_images=paletted[1:], duration=durations, loop=0, optimize=False)


def find_fonts(args):
    regular = Path(args.font) if args.font else FONT_DIR / "JetBrainsMono-Regular.ttf"
    bold = Path(args.bold) if args.bold else FONT_DIR / "JetBrainsMono-Bold.ttf"
    return regular, bold


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--png", default=str(ROOT / "docs" / "tui.png"))
    ap.add_argument("--gif", default=None, help="also write the whole session as a GIF")
    ap.add_argument("--cols", type=int, default=96)
    ap.add_argument("--rows", type=int, default=32)
    ap.add_argument("--font")
    ap.add_argument("--bold")
    args = ap.parse_args()

    regular, bold = find_fonts(args)
    still_fonts = Fonts(regular, bold)  # before the session, so a missing font fails at once
    gif_fonts = Fonts(regular, bold, cell_w=GIF_CELL_W)
    session = Session(args.cols, args.rows)
    try:
        play(session)
    finally:
        session.close()

    Path(args.png).parent.mkdir(parents=True, exist_ok=True)
    cells_to_image(pick_hero(session.frames), still_fonts).save(args.png, optimize=True)
    print(f"wrote {args.png}")
    if args.gif:
        save_gif(session.frames, gif_fonts, args.gif)
        print(f"wrote {args.gif}  {len(session.frames)} frames")


if __name__ == "__main__":
    sys.exit(main())
