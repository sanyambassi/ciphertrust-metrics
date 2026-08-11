"""Detect whether Prometheus DB-audit metrics are usable for an appliance."""

from __future__ import annotations

from typing import Any, Protocol

from .cm_version import parse_cm_version, version_cmp

# CM versions at/above this threshold no longer expose Prom DB-audit metrics.
PROM_AUDIT_REMOVED_FROM = (2, 24, 0)

AUDIT_RECORDS_METRIC = "ciphertrust_audit_log_records_total"
AUDIT_CLIENT_LOGS_METRIC = "ciphertrust_audit_log_client_logs_total"
AUDIT_SERVICE_LABELS = {"service": "audit_log"}


class _GaugeStore(Protocol):
    def gauge_value(
        self, name: str, labels: dict[str, str] | None = None
    ) -> float | None: ...


def property_present(appliance: dict[str, Any] | None, name: str) -> bool:
    """True when ops snapshot lists the named system property (any value)."""
    ops = (appliance or {}).get("ops_snapshot") if isinstance(appliance, dict) else None
    if not isinstance(ops, dict):
        return False
    props = ops.get("system_properties")
    if not isinstance(props, dict):
        return False
    items = props.get("items") or []
    if not isinstance(items, list):
        return False
    target = str(name or "").strip()
    for row in items:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip() == target:
            return True
    return False


def audit_series_nonzero(store: _GaugeStore | None) -> bool | None:
    """True if Prom audit gauges are present and non-zero; False if present-but-zero; None if absent."""
    if store is None:
        return None
    total = store.gauge_value(AUDIT_RECORDS_METRIC, AUDIT_SERVICE_LABELS)
    client = store.gauge_value(AUDIT_CLIENT_LOGS_METRIC, AUDIT_SERVICE_LABELS)
    if total is None and client is None:
        return None
    if float(total or 0) > 0 or float(client or 0) > 0:
        return True
    return False


def detect_prom_audit_capability(
    appliance: dict[str, Any] | None,
    store: _GaugeStore | None = None,
) -> bool | None:
    """Return True/False when known, or None when inconclusive.

    Positive signals: ``ENABLE_RECORDS_DB_STORE`` present, or non-zero audit gauges.
    Present-but-zero gauges alone are inconclusive (empty 2.23 vs dead 2.25).
    """
    if property_present(appliance, "ENABLE_RECORDS_DB_STORE"):
        return True
    alive = audit_series_nonzero(store)
    if alive is True:
        return True
    return None


def supports_prom_audit_dashboard(
    appliance: dict[str, Any] | None,
    store: _GaugeStore | None = None,
) -> bool:
    """Whether the Prometheus Audit dashboard should be shown for this appliance.

    Capability first; CM version (>= 2.24 hides when capability is not positive).
    Unknown version keeps the legacy tab visible.
    """
    cap = detect_prom_audit_capability(appliance, store)
    if cap is True:
        return True

    ver = parse_cm_version((appliance or {}).get("cm_version") if appliance else None)
    if ver is not None and version_cmp(ver, PROM_AUDIT_REMOVED_FROM) >= 0:
        return False
    if ver is not None and version_cmp(ver, PROM_AUDIT_REMOVED_FROM) < 0:
        return True
    # Unknown version: keep visible (do not hide on incomplete appliance metadata).
    return True
