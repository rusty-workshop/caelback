"""Optional config file at ~/.config/caelback/config.toml for defaults that
would otherwise mean retyping the same flags every time.

Read-only -- caelback never writes this file, it's meant to be hand-edited.
Uses tomllib (stdlib since Python 3.11), so this adds no dependency. Missing
or unreadable is silently treated as "no overrides" rather than an error,
since the whole point is that caelback works identically without one.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".config/caelback/config.toml"


def load() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        print(f"warning: couldn't read {CONFIG_PATH}, ignoring it: {exc}", file=sys.stderr)
        return {}
