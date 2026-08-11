"""Loki-backed Audit lite when Prometheus DB-audit metrics are unavailable."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from typing import Any

from . import db
from .client import CMClient, CMClientError

logger = logging.getLogger(__name__)

SIGNIFICANT_SEVERITIES = frozenset({"error", "critical", "fatal"})
SERVER_JOB = '{job="server_audit_records"}'
CLIENT_JOB = '{job="client_audit_records"}'

# Cap Loki lookback so a 30d UI range does not pull huge log windows.
_MAX_WINDOW_SECONDS = 7 * 86400
_DEFAULT_LIMIT = 250
_CACHE_TTL = 45.0

_cache_lock = threading.Lock()
_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}


def _severity_of(obj: dict[str, Any]) -> str:
    raw = obj.get("severity") or obj.get("level") or obj.get("Severity") or ""
    return str(raw).strip().lower() or "?"


def _message_of(obj: dict[str, Any], fallback: str = "") -> str:
    for key in ("message", "msg", "Message", "event", "action"):
        val = obj.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return (fallback or "").strip()


def _parse_line(line: str) -> dict[str, Any]:
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass
    return {"_raw": (line or "")[:300]}


def _ns_to_iso(ts_ns: str | int) -> str:
    try:
        seconds = int(ts_ns) / 1_000_000_000
        return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(seconds))
    except Exception:  # noqa: BLE001
        return str(ts_ns)


def flatten_loki_result(
    payload: dict[str, Any] | None,
    *,
    source: str,
) -> list[dict[str, Any]]:
    """Turn Loki query_range JSON into flat event dicts."""
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    result = (data or {}).get("result") if isinstance(data, dict) else None
    if not isinstance(result, list):
        return []
    events: list[dict[str, Any]] = []
    for stream in result:
        if not isinstance(stream, dict):
            continue
        for pair in stream.get("values") or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            ts_ns, line = pair[0], pair[1]
            obj = _parse_line(str(line))
            sev = _severity_of(obj)
            events.append(
                {
                    "ts_ns": str(ts_ns),
                    "time": _ns_to_iso(ts_ns),
                    "severity": sev,
                    "message": _message_of(obj, str(line))[:200],
                    "user": str(
                        obj.get("username")
                        or obj.get("user")
                        or obj.get("user_name")
                        or obj.get("preferred_username")
                        or ""
                    )[:80],
                    "source": source,
                    "raw": obj,
                }
            )
    events.sort(key=_event_ts, reverse=True)
    return events


def _event_ts(event: dict[str, Any]) -> int:
    try:
        return int(event.get("ts_ns") or 0)
    except (TypeError, ValueError):
        return 0


def summarize_events(
    server_events: list[dict[str, Any]],
    client_events: list[dict[str, Any]],
    *,
    window_seconds: float,
) -> dict[str, Any]:
    all_events = [*server_events, *client_events]
    all_events.sort(key=_event_ts, reverse=True)
    sev = Counter(str(e.get("severity") or "?") for e in all_events)
    significant = [
        e for e in all_events if str(e.get("severity") or "").lower() in SIGNIFICANT_SEVERITIES
    ]
    return {
        "ok": True,
        "window_seconds": float(window_seconds),
        "server_count": len(server_events),
        "client_count": len(client_events),
        "total": len(all_events),
        "severity": dict(sorted(sev.items(), key=lambda kv: (-kv[1], kv[0]))),
        "significant_count": len(significant),
        "error_count": sum(1 for e in all_events if e.get("severity") == "error"),
        "critical_count": sum(
            1 for e in all_events if e.get("severity") in {"critical", "fatal"}
        ),
        "recent": all_events[:25],
        "recent_significant": significant[:25],
    }


def query_audit_lite(
    client: CMClient,
    *,
    window_seconds: float = 86400.0,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Fetch server+client Loki audit events and return a lite summary."""
    window = max(60.0, min(float(window_seconds), float(_MAX_WINDOW_SECONDS)))
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = int((time.time() - window) * 1_000_000_000)
    server_payload = client.query_audit_loki_range(
        SERVER_JOB, start_ns=start_ns, end_ns=end_ns, limit=limit
    )
    client_payload = client.query_audit_loki_range(
        CLIENT_JOB, start_ns=start_ns, end_ns=end_ns, limit=limit
    )
    server_events = flatten_loki_result(server_payload, source="server")
    client_events = flatten_loki_result(client_payload, source="client")
    summary = summarize_events(server_events, client_events, window_seconds=window)
    summary["capped_7d"] = float(window_seconds) > float(_MAX_WINDOW_SECONDS)
    summary["requested_window_seconds"] = float(window_seconds)
    return summary


def fetch_audit_lite_for_appliance(
    appliance_id: int,
    *,
    window_seconds: float = 86400.0,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Login (or reuse JWT) and query Loki; short TTL cache per appliance/window."""
    window = max(60.0, min(float(window_seconds), float(_MAX_WINDOW_SECONDS)))
    cache_key = (int(appliance_id), int(window), int(limit))
    now = time.time()
    with _cache_lock:
        hit = _cache.get(cache_key)
        if hit and hit[0] > now:
            return dict(hit[1])

    appliance = db.get_appliance(int(appliance_id), include_secrets=True)
    if not appliance:
        return {"ok": False, "error": "Appliance not found"}
    if str(appliance.get("last_status") or "").lower() not in {"ok", "pending", ""}:
        # Still try — sticky error may still accept login — but surface status.
        pass

    client = CMClient(
        host=appliance["host"],
        username=appliance["username"],
        password=appliance["password"],
        domain=appliance.get("domain") or "",
        timeout=35.0,
    )
    if appliance.get("jwt") and appliance.get("jwt_expires_at"):
        client.jwt = appliance["jwt"]
        client.jwt_expires_at = float(appliance["jwt_expires_at"])
    try:
        summary = query_audit_lite(client, window_seconds=window, limit=limit)
        # Persist refreshed JWT when login refreshed it.
        if client.jwt and client.jwt_expires_at:
            try:
                db.update_appliance_auth(
                    int(appliance_id),
                    jwt=client.jwt,
                    jwt_expires_at=client.jwt_expires_at,
                    metrics_token=appliance.get("metrics_token"),
                )
            except Exception:  # noqa: BLE001
                pass
    except CMClientError as exc:
        logger.info("Audit Loki lite failed appliance=%s: %s", appliance_id, exc)
        summary = {
            "ok": False,
            "error": str(exc),
            "status_code": getattr(exc, "status_code", None),
            "window_seconds": window,
            "requested_window_seconds": float(window_seconds),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Audit Loki lite unexpected appliance=%s", appliance_id)
        summary = {
            "ok": False,
            "error": str(exc),
            "window_seconds": window,
            "requested_window_seconds": float(window_seconds),
        }
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    with _cache_lock:
        _cache[cache_key] = (now + _CACHE_TTL, dict(summary))
    return summary


def prefers_loki_audit(
    appliance: dict[str, Any] | None,
    store: Any = None,
) -> bool:
    """True when Prom DB-audit path is not usable — use Loki lite instead."""
    from .audit_capability import supports_prom_audit_dashboard

    return not supports_prom_audit_dashboard(appliance, store)
