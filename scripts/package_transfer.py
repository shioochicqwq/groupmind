r"""Package the repo for transfer to another machine (and optional data bundle).

Creates, in ../qqbot-packages by default:
  qqbot-source-<date>.zip   tracked working tree + .git, no secrets/data/tmp/backups
  qqbot-data-bundle-<date>.zip  optional non-secret dataset/memory files (--data-bundle)
  *.sha256                  checksums

Usage:
    python scripts/package_transfer.py
    python scripts/package_transfer.py --data-bundle --out-dir D:\qqbot-packages
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"data", "tmp", "backups", ".git", "__pycache__", ".pytest_cache", ".venv", "venv"}
EXCLUDE_FILES = {".env", ".astrbot", "astrbot.lock", "*.log", "Thumbs.db", ".DS_Store"}
DATA_INCLUDE = [
    "data/sticker_dataset",
    "data/plugin_data",
    "data/config",
    "data/skills",
    "data/mcp_server.json",
    "data/skills.json",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"])
    names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
    return [ROOT / n for n in names]


def add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    try:
        zf.write(path, arcname)
    except OSError as exc:
        print(f"warn: skip {arcname}: {exc}")


def build_source(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    target = out_dir / f"qqbot-source-{stamp}.zip"
    commit = git("rev-parse", "--short", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in tracked_files():
            if path.suffix == ".pyc" or "__pycache__" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            add_file(zf, path, f"qqbot/{rel}")
        for entry in (ROOT / ".git").rglob("*"):
            if entry.is_file() and not entry.name.endswith(".lock"):
                add_file(zf, entry, f"qqbot/.git/{entry.relative_to(ROOT / '.git').as_posix()}")
        manifest = (
            "qqbot source bundle\n"
            f"commit: {commit}\n"
            f"dirty: {dirty}\n"
            f"generated: {datetime.now().isoformat(timespec='seconds')}\n"
            "excluded: .env, data/, tmp/, backups/, logs, caches\n"
            "restore: see docs/transfer-to-new-machine.md\n"
        )
        zf.writestr("qqbot/TRANSFER_MANIFEST.txt", manifest)
    return target


def build_data(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d")
    target = out_dir / f"qqbot-data-bundle-{stamp}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in DATA_INCLUDE:
            src = ROOT / rel
            if not src.exists():
                continue
            files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()]
            for path in files:
                arc = "qqbot/data/" + path.relative_to(ROOT / "data").as_posix()
                add_file(zf, path, arc)
        readme = (
            "qqbot data bundle (non-secret subset)\n"
            "included: sticker_dataset, plugin_data (memory), config (plugin), skills\n"
            "excluded: cmd_config.json (contains API key), data_v4.db (chat history), logs, temp, plugins\n"
            "private: contains chat-derived stickers/memories; upload only to your own private drive.\n"
        )
        zf.writestr("qqbot/DATA_BUNDLE_README.txt", readme)
    return target


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(ROOT.parent / "qqbot-packages"))
    parser.add_argument("--data-bundle", action="store_true")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    made = [build_source(out_dir)]
    if args.data_bundle:
        made.append(build_data(out_dir))
    for path in made:
        digest = sha256(path)
        (path.with_suffix(path.suffix + ".sha256")).write_text(
            f"{digest}  {path.name}\n", encoding="utf-8"
        )
        print(f"{path}  {path.stat().st_size / 1024 / 1024:.2f} MB  sha256={digest[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
