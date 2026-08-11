"""CipherTrust Manager version parsing / comparison helpers."""

from __future__ import annotations

import re
from typing import Any

_VERSION_RE = re.compile(
    r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?",
)


def parse_cm_version(raw: Any) -> tuple[int, int, int] | None:
    """Extract ``(major, minor, patch)`` from strings like ``2.25.0-beta6``."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    match = _VERSION_RE.search(text)
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch") or 0),
    )


def version_cmp(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def version_at_least(raw: Any, minimum: str) -> bool:
    ver = parse_cm_version(raw)
    floor = parse_cm_version(minimum)
    if ver is None or floor is None:
        return False
    return version_cmp(ver, floor) >= 0


def version_below(raw: Any, exclusive_max: str) -> bool:
    """True when parsed version is strictly less than ``exclusive_max``."""
    ver = parse_cm_version(raw)
    ceiling = parse_cm_version(exclusive_max)
    if ver is None or ceiling is None:
        return False
    return version_cmp(ver, ceiling) < 0


def dashboard_version_ok(
    cm_version: Any,
    *,
    min_version: str | None = None,
    max_version: str | None = None,
) -> bool:
    """Return whether ``cm_version`` satisfies catalog min/max bounds.

    ``max_version`` is exclusive (compatible when version < max_version).
    Unknown / unparseable versions are treated as compatible so dashboards are
    not hidden when CM has not reported a version yet.
    """
    ver = parse_cm_version(cm_version)
    if ver is None:
        return True
    if min_version:
        floor = parse_cm_version(min_version)
        if floor is not None and version_cmp(ver, floor) < 0:
            return False
    if max_version:
        ceiling = parse_cm_version(max_version)
        if ceiling is not None and version_cmp(ver, ceiling) >= 0:
            return False
    return True
