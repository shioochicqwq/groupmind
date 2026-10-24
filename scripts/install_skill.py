"""Install version-controlled Skills from ``skills/`` into AstrBot's data dir.

Repo layout:  skills/<name>/SKILL.md   (source of truth, committed)
Target:       data/skills/<name>/     (gitignored, used by AstrBot at startup)

Usage:
    python scripts/install_skill.py            # install all skills
    python scripts/install_skill.py web-lookup # install one
    python scripts/install_skill.py --force    # overwrite existing
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "skills"
DST = ROOT / "data" / "skills"


def validate(skill_dir: Path) -> str:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SystemExit(f"missing SKILL.md: {skill_md}")
    text = skill_md.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        raise SystemExit(f"SKILL.md lacks YAML frontmatter: {skill_md}")
    head = text.split("---", 2)[1]
    name_line = next((ln for ln in head.splitlines() if ln.startswith("name:")), "")
    declared = name_line.split(":", 1)[1].strip() if name_line else ""
    if declared != skill_dir.name:
        raise SystemExit(
            f"frontmatter name ({declared!r}) != directory ({skill_dir.name!r})"
        )
    return declared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="skill names (default: all)")
    parser.add_argument("--force", action="store_true", help="overwrite existing")
    args = parser.parse_args()

    if not SRC.is_dir():
        raise SystemExit(f"skills source not found: {SRC}")
    candidates = (
        [SRC / n for n in args.names]
        if args.names
        else sorted(p for p in SRC.iterdir() if p.is_dir())
    )
    DST.mkdir(parents=True, exist_ok=True)

    for skill_dir in candidates:
        name = validate(skill_dir)
        target = DST / name
        if target.exists():
            if not args.force:
                print(f"skip (exists, use --force): {name}")
                continue
            shutil.rmtree(target)
        shutil.copytree(skill_dir, target)
        print(f"installed: {name} -> {target}")

    print("note: restart AstrBot to reload skills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
