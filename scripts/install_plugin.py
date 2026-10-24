"""Install version-controlled plugins from ``plugins/`` into AstrBot's data dir.

Repo layout:  plugins/<dir>/main.py + metadata.yaml  (source of truth, committed)
Target:       data/plugins/<dir>/                   (gitignored, loaded by AstrBot)

Usage:
    python scripts/install_plugin.py
    python scripts/install_plugin.py astrbot_plugin_strip_refs --force
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "plugins"
DST = ROOT / "data" / "plugins"


def validate(plugin_dir: Path) -> None:
    if not (plugin_dir / "main.py").is_file():
        raise SystemExit(f"missing main.py: {plugin_dir}")
    meta = plugin_dir / "metadata.yaml"
    if not meta.is_file():
        raise SystemExit(f"missing metadata.yaml: {plugin_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="plugin dir names (default: all)")
    parser.add_argument("--force", action="store_true", help="overwrite existing")
    args = parser.parse_args()

    if not SRC.is_dir():
        raise SystemExit(f"plugins source not found: {SRC}")
    candidates = (
        [SRC / n for n in args.names]
        if args.names
        else sorted(p for p in SRC.iterdir() if p.is_dir())
    )
    DST.mkdir(parents=True, exist_ok=True)

    for plugin_dir in candidates:
        validate(plugin_dir)
        target = DST / plugin_dir.name
        if target.exists():
            if not args.force:
                print(f"skip (exists, use --force): {plugin_dir.name}")
                continue
            shutil.rmtree(target)
        shutil.copytree(
            plugin_dir,
            target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        print(f"installed: {plugin_dir.name} -> {target}")

    print("note: restart AstrBot to load plugins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
