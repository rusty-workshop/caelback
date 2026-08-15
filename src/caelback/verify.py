"""Post-restore verification: confirms the *live* system actually matches
what a restore was supposed to produce, instead of only trusting that each
step printed success. A step can "succeed" (exit 0) while still leaving
the system wrong -- e.g. pacman -U succeeding doesn't mean the shell picked
up the new config, and a path copy succeeding doesn't mean the app that
reads it is actually happy.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import discovery, packages
from .manifest import Manifest


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


def verify_restore(m: Manifest) -> VerifyReport:
    report = VerifyReport()

    for e in m.all_path_entries():
        exists = Path(e.src).exists()
        report.checks.append(Check(f"path {e.src}", exists, "present" if exists else "MISSING"))

    for pkg in m.packages:
        if not pkg.cached:
            continue  # never attempted -- not a restore failure, already reported separately
        installed = packages.installed_version(pkg.name)
        if installed is None:
            report.checks.append(Check(f"package {pkg.name}", False, "not installed"))
        else:
            report.checks.append(Check(f"package {pkg.name}", True, f"installed {installed}"))

    for u in m.systemd_units:
        if not u.enabled:
            continue  # restore only enables units that were enabled at snapshot time
        result = subprocess.run(["systemctl", "--user", "is-enabled", u.name], text=True, capture_output=True)
        state = result.stdout.strip()
        report.checks.append(Check(f"systemd unit {u.name}", state == "enabled", state or "unknown"))

    for s in m.sddm_sessions:
        p = discovery.SDDM_SESSIONS_DIR / s
        report.checks.append(Check(f"sddm session {s}", p.exists(), "present" if p.exists() else "MISSING"))

    qs_running = subprocess.run(["pgrep", "-f", "qs -c caelestia"], capture_output=True).returncode == 0
    report.checks.append(Check("caelestia shell process", qs_running, "running" if qs_running else "not running"))

    if shutil.which("livewall"):
        result = subprocess.run(["livewall", "doctor"], text=True, capture_output=True)
        healthy = "issue(s) found" not in result.stdout
        detail = "healthy" if healthy else "issues found — run `livewall doctor` for details"
        report.checks.append(Check("livewall doctor", healthy, detail))

    return report


def render_report(report: VerifyReport) -> str:
    lines = [f"\n== Post-restore verification ({len(report.checks)} check(s)) =="]
    for c in report.checks:
        mark = "✓" if c.ok else "✗"
        lines.append(f"  {mark} {c.name}: {c.detail}")
    if report.ok:
        lines.append("All checks passed.")
    else:
        lines.append(f"{len(report.failures)} check(s) failed — see above.")
    return "\n".join(lines)
