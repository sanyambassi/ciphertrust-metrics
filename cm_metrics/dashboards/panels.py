"""Shared panel builders and metric helpers for dashboard boards."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from contextvars import ContextVar
from typing import Any

from ..parser import find_samples
from ..store import ApplianceStore

# Active chart window for the current dashboard request (seconds). None = full history.
_dashboard_range_seconds: ContextVar[float | None] = ContextVar(
    "dashboard_range_seconds", default=None
)


def set_dashboard_range(seconds: float | None):
    """Bind the UI time-range for series helpers in this request."""
    return _dashboard_range_seconds.set(seconds)


def reset_dashboard_range(token) -> None:
    _dashboard_range_seconds.reset(token)


def _series_since() -> float | None:
    secs = _dashboard_range_seconds.get()
    if secs is None or secs <= 0:
        return None
    return time.time() - float(secs)


def _with_link(
    panel: dict[str, Any],
    *,
    link_dashboard: str = "",
    link_label: str = "View dashboard",
) -> dict[str, Any]:
    """Attach a jump target to another board (DSPM-style widget → dashboard)."""
    if link_dashboard:
        panel["link_dashboard"] = link_dashboard
        panel["link_label"] = link_label or "View dashboard"
    return panel


def _stat(
    title: str,
    value: float | str | None = None,
    unit: str = "",
    description: str = "",
    *,
    tone: str = "",
    link_dashboard: str = "",
    link_label: str = "View dashboard",
) -> dict[str, Any]:
    out_value: float | str | None
    if value is None:
        out_value = None
    elif isinstance(value, float):
        out_value = round(value, 4)
    else:
        out_value = value
    return _with_link(
        {
            "type": "stat",
            "title": title,
            "description": description,
            "value": out_value,
            "unit": unit,
            "tone": (tone or "").lower(),
        },
        link_dashboard=link_dashboard,
        link_label=link_label,
    )


def _note(text: str, *, title: str = "", tone: str = "") -> dict[str, Any]:
    """Full-width informational banner (e.g. domain-scope caveats).

    Optional tone: pass | warning | fail | info (UI accent only).
    """
    return {
        "type": "note",
        "title": title,
        "text": text,
        "tone": (tone or "").lower(),
        "wide": True,
        "span": 12,
    }


def _timeseries(
    title: str,
    series: list[dict[str, Any]],
    unit: str = "",
    description: str = "",
    *,
    wide: bool = False,
    link_dashboard: str = "",
    link_label: str = "View dashboard",
) -> dict[str, Any]:
    return _with_link(
        {
            "type": "timeseries",
            "title": title,
            "description": description,
            "unit": unit,
            "series": series,
            "wide": wide,
        },
        link_dashboard=link_dashboard,
        link_label=link_label,
    )


def _bar(
    title: str,
    items: list[dict[str, Any]],
    unit: str = "",
    description: str = "",
    *,
    wide: bool = False,
    link_dashboard: str = "",
    link_label: str = "View dashboard",
) -> dict[str, Any]:
    return _with_link(
        {
            "type": "bar",
            "title": title,
            "description": description,
            "unit": unit,
            "items": items,
            "wide": wide,
        },
        link_dashboard=link_dashboard,
        link_label=link_label,
    )


def _short_account_label(account: str) -> str:
    """Turn kylo:...:accounts:kylo-<uuid> into a short chart label."""
    if not account:
        return "unknown"
    if "accounts:" in account:
        account = account.rsplit("accounts:", 1)[-1]
    if account.startswith("kylo-") and len(account) > 16:
        return account[:13] + "…"
    if len(account) > 28:
        return account[:25] + "…"
    return account


def _domain_id_from_account(account: str) -> str | None:
    """Extract subdomain UUID from a key_vault account label, if present."""
    if not account:
        return None
    # e.g. kylo:kylo-<uuid>:admin:accounts:kylo-<uuid>
    m = re.search(
        r"kylo-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        account,
        flags=re.IGNORECASE,
    )
    return m.group(1).lower() if m else None


def _domain_name_map(store: ApplianceStore) -> dict[str, str]:
    """domain_id UUID -> domain_name from license-manager key_usage series."""
    id_to_name: dict[str, str] = {}
    for sample in find_samples(
        store.latest_samples(),
        "ciphertrust_license_manager_key_usage_count_including_subdomains",
    ):
        did = (sample.labels.get("domain_id") or "").strip().lower()
        dname = (sample.labels.get("domain_name") or "").strip()
        if did and dname:
            id_to_name[did] = dname
    return id_to_name


def _friendly_account_label(account: str, id_to_name: dict[str, str] | None = None) -> str:
    """Map account / account_uri to domain name when known; else root or short kylo id."""
    if not account:
        return "unknown"
    did = _domain_id_from_account(account)
    if did:
        if id_to_name and did in id_to_name:
            return id_to_name[did]
        # Unknown / deleted domain — keep a short id rather than the full URI
        return did[:8] + "…"
    # Root account: kylo:kylo:admin:accounts:kylo (no UUID)
    if "accounts:kylo" in account and "kylo-" not in account.split("accounts:", 1)[-1]:
        return "root"
    if account.endswith(":kylo") or account.rstrip("/").endswith("accounts:kylo"):
        return "root"
    return _short_account_label(account)


def _group_by_account_friendly(
    store: ApplianceStore,
    name: str,
    group_label: str = "account_uri",
    *,
    limit: int = 15,
    min_value: float = 0.0,
) -> list[dict[str, Any]]:
    """Group a metric by account label, resolving UUIDs to domain names when possible."""
    id_to_name = _domain_name_map(store)
    buckets: dict[str, float] = defaultdict(float)
    for sample in find_samples(store.latest_samples(), name):
        raw = sample.labels.get(group_label) or ""
        label = _friendly_account_label(raw, id_to_name)
        buckets[label] += float(sample.value)
    items = [
        {"label": k, "value": v}
        for k, v in sorted(buckets.items(), key=lambda x: -x[1])
        if v > min_value
    ]
    return items[:limit]


def _rename_account_series(
    series_list: list[dict[str, Any]],
    id_to_name: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Rewrite timeseries legend names that contain account_uri=… to friendly labels."""
    for series in series_list:
        raw = series.get("name") or ""
        if "account_uri=" in raw:
            uri = raw.split("account_uri=", 1)[-1]
            # Strip trailing ", other=…" if present
            uri = uri.split(",", 1)[0].strip()
            series["name"] = _friendly_account_label(uri, id_to_name)
        elif "account=" in raw:
            uri = raw.split("account=", 1)[-1].split(",", 1)[0].strip()
            series["name"] = _friendly_account_label(uri, id_to_name)
        else:
            series["name"] = _friendly_account_label(raw, id_to_name)
    return series_list


def _keys_by_domain_from_deks(
    store: ApplianceStore,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Domain key counts from DEKs (includes root). License-manager usage omits root.

    Maps account UUIDs to domain_name via
    ciphertrust_license_manager_key_usage_count_including_subdomains when available.
    """
    id_to_name = _domain_name_map(store)

    buckets: dict[str, float] = defaultdict(float)
    for sample in find_samples(store.latest_samples(), "ciphertrust_key_vault_deks_total"):
        account = sample.labels.get("account") or ""
        did = _domain_id_from_account(account)
        if did:
            label = id_to_name.get(did) or did
        else:
            # Root / default account has no UUID (kylo:kylo:admin:accounts:kylo)
            label = "root"
        buckets[label] += float(sample.value)

    items = [{"label": k, "value": v} for k, v in sorted(buckets.items(), key=lambda x: -x[1])]
    return items[:limit]


def _group_by_label_short(
    store: ApplianceStore,
    name: str,
    group_label: str,
    *,
    limit: int = 20,
    min_value: float = 0.0,
    shortener=None,
) -> list[dict[str, Any]]:
    items = store.group_by_label(name, group_label)
    out = []
    for item in items:
        if (item.get("value") or 0) <= min_value:
            continue
        label = item["label"]
        if shortener:
            label = shortener(label)
        out.append({"label": label, "value": item["value"]})
    return out[:limit]


def _layout_panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign grid spans so consecutive same-type panels fill rows evenly."""

    def _assign_stat_spans(group: list[dict[str, Any]]) -> None:
        count = len(group)
        if count == 1:
            group[0]["span"] = 12
            return
        if count == 2:
            for panel in group:
                panel["span"] = 6
            return
        if count == 5:
            for k, panel in enumerate(group):
                panel["span"] = 4 if k < 3 else 6
            return
        if count == 7:
            # 4 + 3: first row quarters, second row thirds
            for k, panel in enumerate(group):
                panel["span"] = 3 if k < 4 else 4
            return
        # Prefer complete rows of 4, else 3; stretch leftovers across the last row.
        if count % 4 == 0:
            per_row = 4
        elif count % 3 == 0:
            per_row = 3
        else:
            per_row = 4
        span = 12 // per_row
        for panel in group:
            panel["span"] = span
        rem = count % per_row
        if rem == 1:
            # Avoid a lonely card: pull last two into a half/half row
            if count >= 2:
                group[-2]["span"] = 6
                group[-1]["span"] = 6
        elif rem:
            each = 12 // rem
            for panel in group[-rem:]:
                panel["span"] = each

    def _assign_chart_spans(group: list[dict[str, Any]]) -> None:
        count = len(group)
        if count == 1:
            group[0]["span"] = 12
            group[0]["wide"] = True
            return
        for k, panel in enumerate(group):
            if panel.get("wide"):
                panel["span"] = 12
            elif count % 2 == 1 and k == count - 1:
                panel["span"] = 12
            else:
                panel["span"] = 6

    i = 0
    n = len(panels)
    while i < n:
        ptype = panels[i]["type"]
        j = i
        while j < n and panels[j]["type"] == ptype:
            j += 1
        group = panels[i:j]
        if ptype == "stat":
            _assign_stat_spans(group)
        elif ptype in ("timeseries", "bar"):
            _assign_chart_spans(group)
        else:
            for panel in group:
                panel["span"] = 12
                panel["wide"] = True
        i = j
    return panels


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return value * 100


def _bytes_to_gb(value: float | None) -> float | None:
    if value is None:
        return None
    return value / (1024**3)



def _hold_filled_sum(
    series_points: list[dict[float, float]],
) -> list[dict[str, float]]:
    """Sum gauge series across a shared timeline with step hold-fill.

    Long ranges (>2h) downsample individual metric rows, so many timestamps only
    include a subset of fingerprints. A naive sum then under-counts (6h+ Total
    Keys sawtooth). Holding each series' last/first known value across the
    timeline keeps the total stable between real scrapes.
    """
    if not series_points:
        return []
    timeline = sorted({t for pts in series_points for t in pts})
    if not timeline:
        return []
    buckets: dict[float, float] = {t: 0.0 for t in timeline}
    for pts in series_points:
        ordered = sorted(pts.items())
        first_v = ordered[0][1]
        last_v = first_v
        idx = 0
        for t in timeline:
            while idx < len(ordered) and ordered[idx][0] <= t:
                last_v = ordered[idx][1]
                idx += 1
            buckets[t] += first_v if idx == 0 else last_v
    return [{"t": float(t), "v": buckets[t]} for t in timeline]


def _summed_series(
    store: ApplianceStore,
    name: str,
    labels: dict[str, str] | None = None,
    *,
    series_name: str = "Total",
    limit_series: int = 200,
) -> list[dict[str, Any]]:
    """Sum all matching labeled series into one timeseries (e.g. total keys over time).

    Per labeled series, keep only the last sample in each second so overlapping
    scrapes (Auto refresh + background loop) do not double-count. Values are
    hold-filled across the timeline so long-range downsampling cannot under-count.
    """
    raw = store.series_by_name(
        name, labels, since=_series_since(), limit_series=limit_series
    )
    if not raw:
        return []
    series_points: list[dict[float, float]] = []
    for item in raw:
        per_series: dict[float, float] = {}
        for pt in item.get("points") or []:
            key = round(float(pt["t"]))
            per_series[key] = float(pt["v"])
        if per_series:
            series_points.append(per_series)
    points = _hold_filled_sum(series_points)
    if not points:
        return []
    return [{"name": series_name, "points": points}]


def _summed_by_label_series(
    store: ApplianceStore,
    name: str,
    group_label: str,
    labels: dict[str, str] | None = None,
    *,
    limit_series: int = 200,
    max_groups: int = 12,
) -> list[dict[str, Any]]:
    """Sum matching series into one timeseries per distinct label value.

    Same per-second dedupe / hold-fill as ``_summed_series`` so Auto refresh +
    background scrapes and long-range downsampling do not distort group totals.
    """
    raw = store.series_by_name(
        name, labels, since=_series_since(), limit_series=limit_series
    )
    if not raw:
        return []
    # group_key -> list of per-series point maps
    groups: dict[str, list[dict[float, float]]] = {}
    for item in raw:
        labels_map = item.get("labels") or {}
        key = str(labels_map.get(group_label) or "unknown")
        per_series: dict[float, float] = {}
        for pt in item.get("points") or []:
            t = round(float(pt["t"]))
            per_series[t] = float(pt["v"])
        if per_series:
            groups.setdefault(key, []).append(per_series)
    if not groups:
        return []
    built: list[tuple[str, list[dict[str, float]]]] = []
    for legend, series_points in groups.items():
        points = _hold_filled_sum(series_points)
        if points:
            built.append((legend, points))
    # Prefer groups with the highest latest value so charts stay readable.
    ranked = sorted(
        built,
        key=lambda kv: kv[1][-1]["v"] if kv[1] else 0.0,
        reverse=True,
    )[:max_groups]
    out: list[dict[str, Any]] = [
        {"name": legend, "points": points} for legend, points in ranked
    ]
    # Stable alphabetical legend order for the UI (after ranking/truncation).
    out.sort(key=lambda s: str(s["name"]).lower())
    return out


def _named_series(
    store: ApplianceStore,
    name: str,
    labels: dict[str, str] | None = None,
    rate: bool = False,
    limit: int = 10,
    label_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    raw = store.series_by_name(
        name, labels, since=_series_since(), limit_series=limit
    )
    skip_label_keys = {
        "otel_scope_name",
        "otel_scope_schema_url",
        "otel_scope_version",
        "job",
        "instance",
        "service",
        "component",
        "account_id",
        "access_id",
        "cluster_name",
    }
    # Resolve account_uri / account before truncating — a 48-char cut chops the
    # domain UUID and leaves raw kylo:… legends that _rename_account_series cannot fix.
    id_to_name: dict[str, str] | None = None
    account_label_keys = {"account_uri", "account"}
    if label_keys and any(k in account_label_keys for k in label_keys):
        id_to_name = _domain_name_map(store)

    out: list[dict[str, Any]] = []
    for item in raw:
        labels_map = item["labels"]
        if label_keys:
            parts: list[str] = []
            for k in label_keys:
                raw_val = labels_map.get(k)
                if not raw_val:
                    continue
                if k in account_label_keys:
                    parts.append(_friendly_account_label(str(raw_val), id_to_name))
                else:
                    parts.append(str(raw_val))
            legend = " / ".join(parts)
        else:
            preferred = [
                k
                for k in (
                    "name",
                    "akeyless",
                    "instance_id",
                    "port",
                    "device",
                    "operation",
                    "status",
                    "path",
                    "method",
                    "domain_name",
                    "db",
                    "feature",
                    "resource_type",
                )
                if k in labels_map
            ]
            if preferred:
                legend = " / ".join(str(labels_map[k]) for k in preferred[:2])
            else:
                parts = [
                    f"{k}={v}"
                    for k, v in labels_map.items()
                    if k not in skip_label_keys and not str(k).startswith("otel_")
                ][:2]
                legend = ", ".join(parts) if parts else item["name"]
        if not legend:
            legend = item["name"]
        # Keep legends short for UI tooltips
        if len(legend) > 48:
            legend = legend[:45] + "…"
        raw_points = item["points"]
        points = raw_points
        if rate and len(raw_points) >= 2:
            rate_points = []
            for i in range(1, len(raw_points)):
                dt = raw_points[i]["t"] - raw_points[i - 1]["t"]
                if dt <= 0:
                    continue
                rate_points.append(
                    {
                        "t": raw_points[i]["t"],
                        "v": (raw_points[i]["v"] - raw_points[i - 1]["v"]) / dt,
                    }
                )
            # Short ranges (e.g. 5m) often have only 2 scrapes → 1 rate sample.
            # Chart.js line charts need ≥2 points to draw, so stretch across the
            # scrape interval that produced the rate.
            if len(rate_points) == 1:
                rate_points = [
                    {"t": raw_points[-2]["t"], "v": rate_points[0]["v"]},
                    rate_points[0],
                ]
            points = rate_points
        out.append({"name": legend, "points": points})
    return out


def _avg_series(
    store: ApplianceStore,
    sum_name: str,
    count_name: str | None = None,
    labels: dict[str, str] | None = None,
    *,
    limit: int = 10,
    label_keys: list[str] | None = None,
    aggregate: bool = False,
    series_name: str = "avg",
) -> list[dict[str, Any]]:
    """Average latency from histogram/summary counters: Δsum / Δcount per scrape.

    Matches Grafana ``rate(*_sum[1m]) / rate(*_count[1m])``. When ``aggregate``
    is True, all labeled series are combined into one line.
    """
    if not count_name:
        if sum_name.endswith("_sum"):
            count_name = sum_name[: -len("_sum")] + "_count"
        else:
            count_name = sum_name + "_count"

    sum_raw = store.series_by_name(
        sum_name, labels, since=_series_since(), limit_series=max(limit, 50)
    )
    count_raw = store.series_by_name(
        count_name, labels, since=_series_since(), limit_series=max(limit, 50)
    )
    if not sum_raw or not count_raw:
        return []

    skip_label_keys = {
        "otel_scope_name",
        "otel_scope_schema_url",
        "otel_scope_version",
        "job",
        "instance",
        "service",
        "component",
        "account_id",
        "access_id",
        "cluster_name",
    }

    def _label_key(labs: dict[str, Any]) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (str(k), str(v))
                for k, v in (labs or {}).items()
                if k not in skip_label_keys and not str(k).startswith("otel_")
            )
        )

    def _deltas(points: list[dict[str, Any]]) -> list[tuple[float, float, float]]:
        """Return (t, delta_v, dt) for consecutive points."""
        out: list[tuple[float, float, float]] = []
        for i in range(1, len(points)):
            dt = float(points[i]["t"]) - float(points[i - 1]["t"])
            if dt <= 0:
                continue
            out.append((float(points[i]["t"]), float(points[i]["v"]) - float(points[i - 1]["v"]), dt))
        return out

    counts_by_key = {_label_key(item.get("labels") or {}): item for item in count_raw}

    if aggregate:
        # Align by timestamp across all series, then Δtotal_sum / Δtotal_count.
        sum_by_t: dict[float, float] = defaultdict(float)
        cnt_by_t: dict[float, float] = defaultdict(float)
        for item in sum_raw:
            for pt in item.get("points") or []:
                sum_by_t[round(float(pt["t"]))] += float(pt["v"])
        for item in count_raw:
            for pt in item.get("points") or []:
                cnt_by_t[round(float(pt["t"]))] += float(pt["v"])
        timeline = sorted(set(sum_by_t) & set(cnt_by_t))
        if len(timeline) < 2:
            return []
        avg_pts: list[dict[str, float]] = []
        for i in range(1, len(timeline)):
            t0, t1 = timeline[i - 1], timeline[i]
            d_sum = sum_by_t[t1] - sum_by_t[t0]
            d_cnt = cnt_by_t[t1] - cnt_by_t[t0]
            if d_cnt <= 0:
                continue
            avg_pts.append({"t": float(t1), "v": d_sum / d_cnt})
        if len(avg_pts) == 1 and len(timeline) >= 2:
            avg_pts = [{"t": float(timeline[0]), "v": avg_pts[0]["v"]}, avg_pts[0]]
        return [{"name": series_name, "points": avg_pts}] if avg_pts else []

    scored: list[tuple[float, dict[str, Any]]] = []
    for s_item in sum_raw:
        key = _label_key(s_item.get("labels") or {})
        c_item = counts_by_key.get(key)
        if not c_item:
            continue
        s_deltas = {t: (dv, dt) for t, dv, dt in _deltas(s_item.get("points") or [])}
        c_deltas = {t: (dv, dt) for t, dv, dt in _deltas(c_item.get("points") or [])}
        avg_pts = []
        for t in sorted(set(s_deltas) & set(c_deltas)):
            d_sum, _ = s_deltas[t]
            d_cnt, _ = c_deltas[t]
            if d_cnt <= 0:
                continue
            avg_pts.append({"t": t, "v": d_sum / d_cnt})
        if not avg_pts:
            continue
        if len(avg_pts) == 1:
            raw_s = s_item.get("points") or []
            if len(raw_s) >= 2:
                avg_pts = [{"t": float(raw_s[-2]["t"]), "v": avg_pts[0]["v"]}, avg_pts[0]]
        labels_map = s_item.get("labels") or {}
        keys = label_keys or (
            "method",
            "path",
            "service",
            "upstream_service",
            "host",
            "node",
        )
        legend = " / ".join(str(labels_map[k]) for k in keys if labels_map.get(k))
        if not legend:
            legend = series_name
        if len(legend) > 48:
            legend = legend[:45] + "…"
        activity = sum(abs(p["v"]) for p in avg_pts)
        scored.append((activity, {"name": legend, "points": avg_pts}))

    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:limit]]


def _first_gauge(store: ApplianceStore, *names: str, labels: dict[str, str] | None = None) -> float | None:
    for name in names:
        val = store.gauge_value(name, labels)
        if val is not None:
            return val
    return None


def _first_sum(store: ApplianceStore, *names: str, labels: dict[str, str] | None = None) -> float:
    for name in names:
        # Prefer a name that actually exists in the latest scrape
        if any(s.name == name for s in store.latest_samples()):
            return store.sum_value(name, labels)
    return 0.0


def _first_rate(
    store: ApplianceStore,
    *names: str,
    labels: dict[str, str] | None = None,
    window_seconds: float = 60.0,
) -> float | None:
    for name in names:
        if any(s.name == name for s in store.latest_samples()):
            return store.rate(name, labels, window_seconds)
    return None


def _op_status_items(store: ApplianceStore, success_name: str, failure_name: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for s in store.latest_samples():
        if s.name == success_name:
            items.append({"label": f"{s.labels.get('operation', '?')}:success", "value": s.value})
        elif s.name == failure_name:
            items.append({"label": f"{s.labels.get('operation', '?')}:failed", "value": s.value})
    items.sort(key=lambda x: -x["value"])
    return items



def _fmt_duration_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins}m"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def _container_cpu_pct(store: ApplianceStore, name: str) -> float | None:
    used = store.rate("docker_container_cpu_used_total", {"name": name})
    cap = store.rate("docker_container_cpu_capacity_total", {"name": name})
    if used is None or cap is None or cap <= 0:
        return None
    return max(0.0, min(100.0, (used / cap) * 100.0))


