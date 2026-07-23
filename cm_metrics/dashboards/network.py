"""Cluster / node network dashboard (single-node or fleet overlay)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..store import ApplianceStore
from .panels import (
    _stat,
    _timeseries,
    _named_series,
)

# ~2–3 scrape cycles — samples older than this are treated as stale for "now" views.
_STALE_SAMPLE_SECONDS = 360.0


def _host_key(raw: str | None) -> str:
    """Normalize host / URL / IP for peer legend matching."""
    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = f"https://{s}"
    try:
        host = urlparse(s).hostname or ""
    except Exception:
        host = ""
    return host.strip().lower()


def _node_label(appliance: dict[str, Any]) -> str:
    return (appliance.get("display_name") or f"Node {appliance.get('id', '?')}").strip()


def _peer_display(host_label: str, host_names: dict[str, str]) -> str:
    key = (host_label or "").strip().lower()
    return host_names.get(key) or host_label or "?"


def _member_status(member: dict[str, Any]) -> str:
    status = str(member.get("last_status") or "").strip().lower()
    if status in ("ok", "offline", "error", "pending"):
        return status
    return status or "unknown"


def _member_unreachable(member: dict[str, Any]) -> bool:
    return _member_status(member) in ("offline", "error")


def _peer_legend(origin: str, target: str, *, offline: bool = False) -> str:
    """Short chart legend — full Origin/Target wording lives in Cluster Peers table."""
    origin = (origin or "?").strip()
    target = (target or "").strip()
    if target and target != origin:
        # ASCII only — Chart.js canvas fonts often make Unicode arrows look like hyphens.
        legend = f"{origin}  -->  {target}"
    else:
        legend = origin
    if offline:
        legend = f"{legend} (offline)"
    if len(legend) > 48:
        return legend[:45] + "…"
    return legend


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {mins}m"
    if hours:
        return f"{hours}h {mins}m"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def _fmt_connect_time(epoch: float | None) -> str:
    """Grafana table uses dateTimeAsSystem for connect_time (unix seconds)."""
    if epoch is None:
        return "—"
    try:
        ts = float(epoch)
    except (TypeError, ValueError):
        return "—"
    if ts <= 0:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _latest_metric_sample(
    store: ApplianceStore,
    *metric_names: str,
    peer_host: str | None = None,
    since: float | None = None,
) -> tuple[float | None, float | None]:
    """Return ``(value, sample_ts)`` for the newest matching point."""
    since = since if since is not None else time.time() - 7200.0
    peer_key = _host_key(peer_host) if peer_host else ""
    for name in metric_names:
        series = store.series_by_name(name, since=since, limit_series=50)
        for item in series:
            labs = item.get("labels") or {}
            if peer_key:
                lab_host = _host_key(str(labs.get("host") or labs.get("node") or ""))
                if lab_host and lab_host != peer_key:
                    continue
            pts = item.get("points") or []
            if pts:
                return float(pts[-1]["v"]), float(pts[-1]["t"])
            if item.get("value") is not None:
                return float(item["value"]), None
    return None, None


def _latest_metric_value(
    store: ApplianceStore,
    *metric_names: str,
    peer_host: str | None = None,
    since: float | None = None,
) -> float | None:
    value, _ = _latest_metric_sample(
        store, *metric_names, peer_host=peer_host, since=since
    )
    return value


def _row_is_stale(
    member: dict[str, Any],
    sample_ts: float | None,
    *,
    now: float | None = None,
) -> bool:
    if _member_unreachable(member):
        return True
    if sample_ts is None:
        return True
    age = (now if now is not None else time.time()) - float(sample_ts)
    return age > _STALE_SAMPLE_SECONDS


def _fleet_series(
    member_stores: list[tuple[dict[str, Any], ApplianceStore]],
    host_names: dict[str, str],
    *metric_names: str,
    label_keys: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Overlay the same metric from every cluster member onto one chart."""
    keys = label_keys or ["host"]
    merged: list[dict[str, Any]] = []
    for member, store in member_stores:
        origin = _node_label(member)
        offline = _member_unreachable(member)
        series: list[dict[str, Any]] = []
        for name in metric_names:
            series = _named_series(store, name, label_keys=keys, limit=limit)
            if series:
                break
        for item in series:
            peer_raw = (item.get("name") or "").strip()
            # _named_series joins label_keys with " / "; take first token as host.
            peer_host = peer_raw.split(" / ", 1)[0].strip() if peer_raw else ""
            target = _peer_display(peer_host, host_names)
            merged.append(
                {
                    "name": _peer_legend(origin, target, offline=offline),
                    "points": item.get("points") or [],
                }
            )
    return merged


def _nearest_value(points: list[dict[str, Any]], t: float, max_delta: float = 180.0) -> float | None:
    """Return value of the sample nearest to ``t`` within ``max_delta`` seconds."""
    best: float | None = None
    best_dt = max_delta + 1.0
    for p in points:
        try:
            pt = float(p["t"])
            pv = float(p["v"])
        except (KeyError, TypeError, ValueError):
            continue
        dt = abs(pt - t)
        if dt < best_dt:
            best_dt = dt
            best = pv
    if best is None or best_dt > max_delta:
        return None
    return best


def _fleet_time_since_connect(
    member_stores: list[tuple[dict[str, Any], ApplianceStore]],
    host_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Connection age only while ``ciphertrust_cluster_connected`` is 1 at that scrape."""
    since = time.time() - 7200.0
    merged: list[dict[str, Any]] = []
    for member, store in member_stores:
        origin = _node_label(member)
        offline = _member_unreachable(member)
        connect_series = _named_series(
            store, "ciphertrust_cluster_connect_time", label_keys=["host"], limit=20
        )
        connected_by_peer: dict[str, list[dict[str, Any]]] = {}
        for item in store.series_by_name(
            "ciphertrust_cluster_connected", since=since, limit_series=50
        ):
            labs = item.get("labels") or {}
            peer_key = _host_key(str(labs.get("host") or labs.get("node") or ""))
            if not peer_key:
                continue
            connected_by_peer[peer_key] = list(item.get("points") or [])
        if not connected_by_peer:
            for item in store.series_by_name(
                "ciphertrust_cluster_node_connected", since=since, limit_series=50
            ):
                labs = item.get("labels") or {}
                peer_key = _host_key(str(labs.get("host") or labs.get("node") or ""))
                if peer_key:
                    connected_by_peer[peer_key] = list(item.get("points") or [])

        for item in connect_series:
            peer_raw = (item.get("name") or "").strip()
            peer_host = peer_raw.split(" / ", 1)[0].strip() if peer_raw else ""
            peer_key = _host_key(peer_host)
            target = _peer_display(peer_host, host_names)
            conn_pts = connected_by_peer.get(peer_key) or []
            pts: list[dict[str, Any]] = []
            for p in item.get("points") or []:
                try:
                    t = float(p["t"])
                    connect_at = float(p["v"])
                except (KeyError, TypeError, ValueError):
                    continue
                if connect_at <= 0:
                    continue
                cval = _nearest_value(conn_pts, t)
                if cval is None or cval < 1.0:
                    continue
                pts.append({"t": t, "v": max(0.0, t - connect_at)})
            merged.append(
                {
                    "name": _peer_legend(origin, target, offline=offline),
                    "points": pts,
                }
            )
    return merged


def _fleet_peer_table(
    member_stores: list[tuple[dict[str, Any], ApplianceStore]],
    host_names: dict[str, str],
) -> dict[str, Any]:
    """Grafana-style peer table with Live/Stale honesty for offline origins."""
    now = time.time()
    since = now - 7200.0
    rows: list[dict[str, Any]] = []
    for member, store in member_stores:
        origin = _node_label(member)
        origin_status = _member_status(member)
        series: list[dict[str, Any]] = []
        for name in (
            "ciphertrust_cluster_connected",
            "ciphertrust_cluster_node_connected",
        ):
            series = store.series_by_name(name, since=since, limit_series=50)
            if series:
                break
        for item in series:
            labs = item.get("labels") or {}
            peer_raw = labs.get("host") or labs.get("node") or "?"
            target = _peer_display(str(peer_raw), host_names)
            pts = item.get("points") or []
            if not pts and item.get("value") is None:
                continue
            connected = float(pts[-1]["v"]) if pts else float(item.get("value") or 0)
            sample_ts = float(pts[-1]["t"]) if pts else None
            stale = _row_is_stale(member, sample_ts, now=now)
            blocked = _latest_metric_value(
                store,
                "ciphertrust_cluster_replication_blocked",
                peer_host=str(peer_raw),
                since=since,
            )
            connect_ts = _latest_metric_value(
                store,
                "ciphertrust_cluster_connect_time",
                peer_host=str(peer_raw),
                since=since,
            )
            uptime = _latest_metric_value(
                store,
                "ciphertrust_cluster_uptime",
                peer_host=str(peer_raw),
                since=since,
            )
            if stale:
                was = "Yes" if connected >= 1 else "No"
                connected_cell = f"Stale (was {was})"
                uptime_cell = "—"
            elif connected >= 1:
                connected_cell = "Yes"
                uptime_cell = _fmt_duration(uptime)
            else:
                connected_cell = "No"
                uptime_cell = "—"
            rows.append(
                {
                    "Origin Node": origin,
                    "Target Node": target,
                    "Origin status": origin_status,
                    "Data": "Stale" if stale else "Live",
                    "Connected?": connected_cell,
                    "Replication Blocked?": (
                        "Yes"
                        if blocked is not None and blocked >= 1
                        else "No"
                        if blocked is not None
                        else "—"
                    ),
                    "Last Connected": _fmt_connect_time(connect_ts),
                    "Uptime": uptime_cell,
                }
            )
    rows.sort(key=lambda r: (r["Origin Node"].lower(), r["Target Node"].lower()))
    return {
        "type": "table",
        "title": "Cluster Peers",
        "description": (
            "Each row is one origin node's view of a target peer. "
            "Stale = origin offline/unreachable or samples older than a few scrape cycles."
        ),
        "columns": [
            "Origin Node",
            "Target Node",
            "Origin status",
            "Data",
            "Connected?",
            "Replication Blocked?",
            "Last Connected",
            "Uptime",
        ],
        "rows": rows,
        "wide": True,
    }


def _pick_ops_source(
    member_stores: list[tuple[dict[str, Any], ApplianceStore]],
    appliance: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer a reachable member's ops snapshot for raft/status tiles."""
    # Prefer primary (index 0) when reachable.
    ordered = list(member_stores)
    for member, _ in ordered:
        if not _member_unreachable(member):
            ops = member.get("ops_snapshot") if isinstance(member, dict) else None
            if isinstance(ops, dict) and ops.get("cluster_api"):
                return ops
    for member, _ in ordered:
        if not _member_unreachable(member):
            ops = member.get("ops_snapshot") if isinstance(member, dict) else None
            if isinstance(ops, dict):
                return ops
    if appliance and isinstance(appliance.get("ops_snapshot"), dict):
        return appliance["ops_snapshot"]
    if ordered:
        ops = ordered[0][0].get("ops_snapshot") if isinstance(ordered[0][0], dict) else None
        if isinstance(ops, dict):
            return ops
    return {}


def build_cluster(
    store: ApplianceStore,
    appliance: dict[str, Any] | None = None,
    *,
    member_stores: list[tuple[dict[str, Any], ApplianceStore]] | None = None,
) -> list[dict[str, Any]]:
    """Cluster dashboard — overlays all cluster members when ``member_stores`` is set."""
    if member_stores is None:
        member_stores = [(appliance or {}, store)]

    host_names: dict[str, str] = {}
    for member, _ in member_stores:
        label = _node_label(member)
        for key in ("private_host", "public_host", "node_host", "host"):
            hk = _host_key(member.get(key) if isinstance(member, dict) else None)
            if hk:
                host_names[hk] = label

    ops = _pick_ops_source(member_stores, appliance)
    if not isinstance(ops, dict):
        ops = {}
    cluster_api = ops.get("cluster_api") if isinstance(ops, dict) else None
    if not isinstance(cluster_api, dict):
        cluster_api = {}

    node_count_raw = cluster_api.get("nodeCount")
    try:
        node_count = (
            float(node_count_raw) if node_count_raw is not None else float(len(member_stores))
        )
    except (TypeError, ValueError):
        node_count = float(len(member_stores)) if member_stores else None

    reachable = sum(1 for m, _ in member_stores if not _member_unreachable(m))

    raft = cluster_api.get("raftStatus")
    status = cluster_api.get("status")
    node_id = cluster_api.get("nodeID")
    api_err = cluster_api.get("error")

    fleet = len(member_stores) > 1
    peer_table = _fleet_peer_table(member_stores, host_names)

    panels: list[dict[str, Any]] = [
        _stat(
            "Cluster Nodes",
            node_count,
            description=str(api_err) if api_err and node_count is None else "Configured members",
        ),
        _stat(
            "Reachable Nodes",
            float(reachable),
            description=f"{reachable} of {len(member_stores)} members scraping OK",
            tone="fail" if fleet and reachable < len(member_stores) else "",
        ),
        _stat("Raft Status", raft if isinstance(raft, (str, int, float)) else None),
        _stat("Node Status", status if isinstance(status, (str, int, float)) else None),
        _stat(
            "Primary Node ID" if fleet else "This Node ID",
            node_id if isinstance(node_id, (str, int, float)) else None,
        ),
        peer_table,
    ]

    def _add_ts(
        title: str,
        series: list[dict[str, Any]],
        unit: str = "",
        description: str = "",
        *,
        wide: bool = False,
        hide_if_empty: bool = False,
    ) -> None:
        if hide_if_empty and not series:
            return
        panels.append(_timeseries(title, series, unit, description, wide=wide))

    _add_ts(
        "Write Lag",
        _fleet_series(
            member_stores,
            host_names,
            "ciphertrust_cluster_write_lag",
            "ciphertrust_cluster_write_lag_seconds",
        ),
        "s",
        wide=True,
    )
    _add_ts(
        "Replay Lag",
        _fleet_series(
            member_stores,
            host_names,
            "ciphertrust_cluster_replay_lag",
            "ciphertrust_cluster_replay_lag_seconds",
        ),
        "s",
        wide=True,
    )
    _add_ts(
        "Flush Lag",
        _fleet_series(member_stores, host_names, "ciphertrust_cluster_flush_lag"),
        "s",
    )
    _add_ts(
        "Sent Lag Bytes",
        _fleet_series(
            member_stores,
            host_names,
            "ciphertrust_cluster_sent_lag_bytes",
            "ciphertrust_cluster_sent_lag_size",
        ),
        "bytes",
        "Bytes between sent_lsn and current WAL write position.",
    )
    _add_ts(
        "Write Lag Bytes",
        _fleet_series(
            member_stores,
            host_names,
            "ciphertrust_cluster_write_lag_bytes",
            "ciphertrust_cluster_write_lag_size",
        ),
        "bytes",
        "Bytes between write_lsn and current WAL write position.",
    )
    _add_ts(
        "Flush Lag Bytes",
        _fleet_series(
            member_stores,
            host_names,
            "ciphertrust_cluster_flush_lag_bytes",
            "ciphertrust_cluster_flush_lag_size",
        ),
        "bytes",
        "Bytes between flush_lsn and current WAL write position.",
    )
    _add_ts(
        "Replay Lag Bytes",
        _fleet_series(
            member_stores,
            host_names,
            "ciphertrust_cluster_replay_lag_bytes",
            "ciphertrust_cluster_replay_lag_size",
        ),
        "bytes",
        "Bytes between replay_lsn and current WAL write position.",
    )
    _add_ts(
        "Catchup Interval",
        _fleet_series(member_stores, host_names, "ciphertrust_cluster_catchup_interval"),
        "s",
        "Approximate time for the peer to catch up on unapplied changes.",
        hide_if_empty=True,
    )
    _add_ts(
        "Apply Rate",
        _fleet_series(member_stores, host_names, "ciphertrust_cluster_apply_rate"),
        "LSN/s",
        "LSNs applied per second at the peer node.",
        hide_if_empty=True,
    )
    _add_ts(
        "Time Since Connect",
        _fleet_time_since_connect(member_stores, host_names),
        "duration",
        "How long the peer link has been up while connected. Stops while disconnected. "
        "Absolute last-connected timestamps are in Cluster Peers. Offline origins are labeled.",
    )
    _add_ts(
        "Cluster Uptime",
        _fleet_series(member_stores, host_names, "ciphertrust_cluster_uptime"),
        "duration",
        wide=True,
    )
    return panels
