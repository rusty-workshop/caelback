"""Fancy ASCII-art banner shown at the top of every interactive caelback run.

Purely cosmetic -- skipped automatically whenever stdout isn't a real
terminal (the install-timer's systemd unit, output piped/redirected, the
`caelback list` calls the shell completions shell out to) so it never
clutters logs or breaks anything downstream, and can be turned off
entirely with `banner = false` in the config file.
"""

from __future__ import annotations

import sys

from . import config

# 7-row block font, just the letters CAELBACK actually needs.
_FONT = {
    "C": [" ███ ", "██   ", "██   ", "██   ", "██   ", "██   ", " ███ "],
    "A": [" ███ ", "██ ██", "██ ██", "█████", "██ ██", "██ ██", "██ ██"],
    "E": ["█████", "██   ", "██   ", "████ ", "██   ", "██   ", "█████"],
    "L": ["██   ", "██   ", "██   ", "██   ", "██   ", "██   ", "█████"],
    "B": ["████ ", "██ ██", "██ ██", "████ ", "██ ██", "██ ██", "████ "],
    "K": ["██ ██", "██ ██", "████ ", "███  ", "██ ██", "██ ██", "██ ██"],
}

_WORD = "CAELBACK"

# Cool-to-warm gradient (blue -> violet -> pink), one color per row.
_GRADIENT = [
    (137, 180, 250),
    (148, 156, 246),
    (166, 133, 243),
    (203, 116, 237),
    (235, 111, 214),
    (243, 111, 175),
    (245, 120, 140),
]


def _rows() -> list[str]:
    letters = [_FONT[ch] for ch in _WORD]
    return [" ".join(letter[row] for letter in letters) for row in range(len(_GRADIENT))]


def render(*, color: bool = True) -> str:
    rows = _rows()
    if not color:
        return "\n".join(rows)
    return "\n".join(f"\x1b[38;2;{r};{g};{b}m{row}\x1b[0m" for row, (r, g, b) in zip(rows, _GRADIENT))


def print_banner() -> None:
    if not config.load().get("banner", True):
        return
    if not sys.stdout.isatty():
        return
    print(render())
    print()
