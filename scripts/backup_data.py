"""Back up AstrBot's runtime data directory into a timestamped zip archive.

Cross-platform (Windows / Linux). The ``.env`` file is excluded by default
because it holds provider keys; pass ``--include-env`` if you intentionally
want a fully self-contained archive.

Usage:
    python scripts/backup_data.py                    # ./data -> ./backups
    python scripts/backup_data.py --out /var/backups/qqbot
    python scripts/backup_data.py --include-env
"""

from __future__ import annotations

import argparse
import datetime
import zipfile
from pathlib import Path

SKIP_DIR_NAMES = {"temp", "__pycache__", "site-packages", "node_modules"}


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if SKIP_DIR_NAMES.intersection(rel.parts):
            continue
        yield path, rel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument("--out", default="backups", help="output directory")
    parser.add_argument("--name", default="data", help="archive name prefix")
    parser.add_argument(
        "--include-env",
        action="store_true",
        help="also archive the repository-root .env (contains secrets)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    data_dir = root / "data"
    if not data_dir.is_dir():
        raise SystemExit(f"data directory not found: {data_dir}")

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = out_dir / f"{args.name}-{stamp}.zip"

    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, rel in iter_files(data_dir):
            zf.write(file_path, rel)
            count += 1
        if args.include_env:
            env_file = root / ".env"
            if env_file.is_file():
                zf.write(env_file, ".env")
                count += 1

    size_mb = archive.stat().st_size / (1024 * 1024)
    print(f"archived {count} files -> {archive} ({size_mb:.2f} MiB)")
    print("note: archive contains chat history and AstrBot secrets; store securely")


if __name__ == "__main__":
    main()
