"""Best-effort desktop notifications via notify-send. Never fatal -- caelback
works identically with or without a notification daemon. This exists mainly
for the unattended snapshot timer: a diff warning that only lands in the
systemd journal is a warning nobody will ever see.
"""

from __future__ import annotations

import shutil
import subprocess

from . import config


def notify(title: str, body: str = "", *, urgency: str = "normal") -> None:
    if not config.load().get("notify", True):
        return
    if shutil.which("notify-send") is None:
        return
    try:
        subprocess.run(
            ["notify-send", "--app-name", "caelback", "--urgency", urgency, title, body],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        pass
