"""Appliance deletion — synchronous (per-appliance metrics file unlink)."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from . import db

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_started = False


def pause_purges() -> None:
    """No-op — history purge batches are unused with per-appliance metrics files."""


def resume_purges() -> None:
    """No-op — history purge batches are unused with per-appliance metrics files."""


@contextmanager
def purges_paused() -> Iterator[None]:
    """No-op context manager kept for scraper/connect call-site compatibility."""
    yield


def _label(meta: dict[str, Any]) -> str:
    name = (meta.get("display_name") or "").strip()
    host = (meta.get("host") or "").replace("https://", "").replace("http://", "")
    return name or host or f"#{meta.get('id')}"


def start_appliance_delete(appliance_id: int, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synchronously remove the appliance (catalog row + metrics DB file)."""
    label = _label(meta or {"id": appliance_id})
    # begin_appliance_delete may already have removed it; delete is idempotent.
    db.delete_appliance(int(appliance_id))
    return {
        "accepted": True,
        "already_running": False,
        "appliance_id": int(appliance_id),
        "label": label,
    }


def resume_pending_deletes() -> int:
    """Clear any leftover delete_pending rows via sync delete (upgrade leftover)."""
    pending = db.list_delete_pending_appliances()
    n = 0
    for row in pending:
        aid = int(row["id"])
        try:
            db.delete_appliance(aid)
            n += 1
            logger.info("Cleared leftover delete_pending appliance %s", aid)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to clear delete_pending appliance %s", aid)
    if n:
        logger.info("Cleared %s leftover delete_pending appliance(s)", n)
    return n


def ensure_started() -> None:
    """Idempotent: clear any leftover delete_pending rows once per process."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    try:
        resume_pending_deletes()
    except Exception:  # noqa: BLE001
        logger.exception("resume_pending_deletes failed")
