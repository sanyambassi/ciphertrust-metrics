#!/usr/bin/env python3
"""Manual SQLite VACUUM for CipherTrust Metrics.

Reclaims free space after large deletes across the catalog DB and every
per-appliance metrics file under ``data/metrics/``. This is rare maintenance —
the live scrape loop already runs ``PRAGMA optimize`` after prune.

Usage (from the install root, with the same env/DB path as the service):

    # Prefer stopping the service first so VACUUM is not fighting scrapes:
    sudo systemctl stop cm-metrics
    sudo /opt/cm-metrics/venv/bin/python /opt/cm-metrics/scripts/vacuum_db.py
    sudo systemctl start cm-metrics

Needs roughly as much free disk as the largest file being rewritten.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running from repo or /opt/cm-metrics install layout.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cm_metrics import db  # noqa: E402
from cm_metrics.config import Config  # noqa: E402


def _free_bytes(path: Path) -> int | None:
    try:
        usage = os.statvfs(path)
        return int(usage.f_bavail * usage.f_frsize)
    except (AttributeError, OSError):
        try:
            import shutil

            return int(shutil.disk_usage(path).free)
        except OSError:
            return None


def main() -> int:
    catalog = Config.DATABASE_PATH
    if not catalog.exists():
        print(f"Catalog database not found: {catalog}", file=sys.stderr)
        return 1

    db.init_db()
    paths = [catalog, *db.list_metrics_db_paths()]
    total = sum(p.stat().st_size for p in paths if p.exists())
    largest = max((p.stat().st_size for p in paths if p.exists()), default=0)
    free = _free_bytes(catalog.parent)

    print(f"Catalog: {catalog}")
    print(f"Metrics dir: {db.metrics_dir()}")
    print(f"Files: {len(paths)} (catalog + {len(paths) - 1} metrics)")
    print(f"Total size: {total / 1024**3:.2f} GiB")
    if free is not None:
        print(f"Free disk: {free / 1024**3:.2f} GiB")
        if free < largest * 1.05:
            print(
                "Refusing VACUUM: need about as much free disk as the largest DB file.",
                file=sys.stderr,
            )
            return 2

    print("Running VACUUM on catalog + metrics DBs...")
    result = db.vacuum_db()
    before = result["before_bytes"] / 1024**3
    after = result["after_bytes"] / 1024**3
    reclaimed = result["reclaimed_bytes"] / 1024**3
    print(f"Done. {before:.2f} GiB → {after:.2f} GiB (reclaimed {reclaimed:.2f} GiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
