"""Manifest: JSON record of exactly what a snapshot contains, plus a human render."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .util import human_size

MANIFEST_VERSION = 1


@dataclass
class ManifestEntry:
    label: str
    src: str
    size_bytes: int


@dataclass
class ManifestUnit:
    name: str
    enabled: bool


@dataclass
class ManifestPackage:
    name: str
    version: str
    cached: bool
    cached_pkg: str | None  # path relative to snapshot root, if cached


@dataclass
class Manifest:
    name: str
    created_at: str
    hostname: str
    version: int = MANIFEST_VERSION
    config_dirs: list[ManifestEntry] = field(default_factory=list)
    state_dirs: list[ManifestEntry] = field(default_factory=list)
    extra_matches: list[ManifestEntry] = field(default_factory=list)
    systemd_units: list[ManifestUnit] = field(default_factory=list)
    sddm_sessions: list[str] = field(default_factory=list)
    packages: list[ManifestPackage] = field(default_factory=list)

    def all_path_entries(self) -> list[ManifestEntry]:
        return self.config_dirs + self.state_dirs + self.extra_matches

    def total_size_bytes(self) -> int:
        return sum(e.size_bytes for e in self.all_path_entries())

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def write(self, snapshot_dir: Path) -> None:
        (snapshot_dir / "manifest.json").write_text(self.to_json() + "\n")
        (snapshot_dir / "MANIFEST.md").write_text(render_markdown(self))

    @staticmethod
    def load(snapshot_dir: Path) -> "Manifest":
        data = json.loads((snapshot_dir / "manifest.json").read_text())
        return Manifest(
            name=data["name"],
            created_at=data["created_at"],
            hostname=data["hostname"],
            version=data.get("version", MANIFEST_VERSION),
            config_dirs=[ManifestEntry(**e) for e in data.get("config_dirs", [])],
            state_dirs=[ManifestEntry(**e) for e in data.get("state_dirs", [])],
            extra_matches=[ManifestEntry(**e) for e in data.get("extra_matches", [])],
            systemd_units=[ManifestUnit(**u) for u in data.get("systemd_units", [])],
            sddm_sessions=data.get("sddm_sessions", []),
            packages=[ManifestPackage(**p) for p in data.get("packages", [])],
        )


def render_markdown(m: Manifest) -> str:
    lines = [
        f"# caelback snapshot — {m.name}",
        "",
        f"Taken {m.created_at} on `{m.hostname}`. Total size: {human_size(m.total_size_bytes())}.",
        "",
        "## To restore",
        "```bash",
        f"caelback restore {m.name}",
        "```",
        "",
    ]

    def section(title: str, entries: list[ManifestEntry]) -> None:
        lines.append(f"## {title}")
        if not entries:
            lines.append("_none found_")
        for e in entries:
            lines.append(f"- `{e.src}` ({human_size(e.size_bytes)})")
        lines.append("")

    section("Config directories", m.config_dirs)
    section("State directories", m.state_dirs)
    section('Extra matches (fuzzy scan for "caelestia")', m.extra_matches)

    lines.append("## Packages")
    if not m.packages:
        lines.append("_none found_")
    for p in m.packages:
        status = "cached, offline-restorable" if p.cached else "**NOT cached** — restore needs network/AUR"
        lines.append(f"- `{p.name}` {p.version} — {status}")
    lines.append("")

    lines.append("## systemd --user units")
    if not m.systemd_units:
        lines.append("_none found_")
    for u in m.systemd_units:
        lines.append(f"- `{u.name}` ({'enabled' if u.enabled else 'not enabled'})")
    lines.append("")

    lines.append("## sddm session entries")
    if not m.sddm_sessions:
        lines.append("_none found_")
    for s in m.sddm_sessions:
        lines.append(f"- `{s}`")
    lines.append("")

    return "\n".join(lines)
