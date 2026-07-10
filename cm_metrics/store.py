"""In-memory + SQLite-backed multi-appliance metrics store."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from . import db
from .config import Config
from .parser import Sample, find_samples, first_value, labels_match, sum_samples


@dataclass
class Snapshot:
    timestamp: float
    samples: list[Sample]
    source: str = "live"
    error: str | None = None


def _series_maxlen(history_seconds: int) -> int:
    """Room for ~one point per scrape over the retention window, with headroom."""
    interval = max(1, int(Config.SCRAPE_INTERVAL))
    return max(50_000, int(history_seconds / interval) + 2_000)


class ApplianceStore:
    def __init__(self, appliance_id: int, history_seconds: int) -> None:
        self.appliance_id = appliance_id
        self.history_seconds = history_seconds
        self._lock = threading.RLock()
        maxlen = _series_maxlen(history_seconds)
        self._series: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=maxlen)
        )
        self._labels: dict[str, tuple[str, dict[str, str]]] = {}
        self._latest: Snapshot | None = None
        self._hydrated = False

    def hydrate_from_db(self) -> None:
        if self._hydrated:
            return
        since = time.time() - self.history_seconds
        rows = db.load_series(self.appliance_id, since=since, limit=200_000)
        latest_rows = db.load_latest_samples(self.appliance_id, max_age_seconds=90.0)
        with self._lock:
            for row in rows:
                fp = row["fingerprint"]
                self._series[fp].append((row["t"], row["v"]))
                self._labels[fp] = (row["name"], row["labels"])
            if latest_rows:
                samples = [
                    Sample(name=r["name"], labels=r["labels"], value=r["v"])
                    for r in latest_rows
                ]
                self._latest = Snapshot(
                    timestamp=max(r["t"] for r in latest_rows),
                    samples=samples,
                    source="db",
                )
            self._hydrated = True

    def ingest(
        self,
        samples: list[Sample],
        source: str = "live",
        error: str | None = None,
        persist: bool = True,
    ) -> None:
        now = time.time()
        with self._lock:
            self._latest = Snapshot(timestamp=now, samples=samples, source=source, error=error)
            cutoff = now - self.history_seconds
            persist_rows: list[tuple[str, str, dict[str, str], float, float]] = []
            for sample in samples:
                fp = sample.fingerprint
                self._series[fp].append((now, sample.value))
                self._labels[fp] = (sample.name, sample.labels)
                while self._series[fp] and self._series[fp][0][0] < cutoff:
                    self._series[fp].popleft()
                persist_rows.append((fp, sample.name, sample.labels, now, sample.value))
            if persist and persist_rows and source in {"live", "demo"}:
                # Persist all scraped samples except noisy/internal prefixes.
                # Live dashboards already use the full in-memory scrape.
                skip_prefixes = ("dummy_",)
                skip_suffixes = ("_bucket",)  # histogram buckets explode cardinality
                to_store = [
                    r
                    for r in persist_rows
                    if not r[1].startswith(skip_prefixes)
                    and not r[1].endswith(skip_suffixes)
                ]
                db.insert_metric_points(self.appliance_id, to_store)

    def record_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        *,
        persist: bool = True,
    ) -> None:
        """Append one synthetic gauge point (e.g. vault API key total) into history."""
        sample = Sample(name=name, labels=dict(labels or {}), value=float(value))
        now = time.time()
        with self._lock:
            fp = sample.fingerprint
            self._series[fp].append((now, sample.value))
            self._labels[fp] = (sample.name, sample.labels)
            cutoff = now - self.history_seconds
            while self._series[fp] and self._series[fp][0][0] < cutoff:
                self._series[fp].popleft()
            # Merge into latest snapshot so gauges/sum_value can see it too.
            if self._latest:
                samples = [s for s in self._latest.samples if s.fingerprint != fp]
                samples.append(sample)
                self._latest = Snapshot(
                    timestamp=now,
                    samples=samples,
                    source=self._latest.source,
                    error=self._latest.error,
                )
            else:
                self._latest = Snapshot(timestamp=now, samples=[sample], source="derived")
            if persist:
                db.insert_metric_points(
                    self.appliance_id,
                    [(fp, sample.name, sample.labels, now, sample.value)],
                )

    def latest_samples(self) -> list[Sample]:
        with self._lock:
            return list(self._latest.samples) if self._latest else []

    def latest_snapshot(self) -> Snapshot | None:
        with self._lock:
            return self._latest

    def series_by_name(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        since: float | None = None,
        limit_series: int = 20,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results: list[dict[str, Any]] = []
            # Prefer matching against known fingerprints
            for fp, (metric_name, metric_labels) in self._labels.items():
                if metric_name != name:
                    continue
                if not labels_match(metric_labels, labels):
                    continue
                pts = self._series.get(fp, deque())
                series_pts = [{"t": t, "v": v} for t, v in pts if since is None or t >= since]
                value = series_pts[-1]["v"] if series_pts else None
                results.append(
                    {
                        "fingerprint": fp,
                        "name": metric_name,
                        "labels": metric_labels,
                        "points": series_pts,
                        "value": value,
                    }
                )
                if len(results) >= limit_series:
                    break

            # Fallback: latest samples may have gauges not yet labeled in _labels after hydrate
            if not results and self._latest:
                matched = [
                    s
                    for s in self._latest.samples
                    if s.name == name and labels_match(s.labels, labels)
                ][:limit_series]
                for sample in matched:
                    pts = self._series.get(sample.fingerprint, deque())
                    series_pts = [{"t": t, "v": v} for t, v in pts if since is None or t >= since]
                    results.append(
                        {
                            "fingerprint": sample.fingerprint,
                            "name": sample.name,
                            "labels": sample.labels,
                            "points": series_pts,
                            "value": sample.value,
                        }
                    )
            return results

    def gauge_value(self, name: str, labels: dict[str, str] | None = None) -> float | None:
        return first_value(self.latest_samples(), name, labels)

    def sum_value(self, name: str, labels: dict[str, str] | None = None) -> float:
        return sum_samples(self.latest_samples(), name, labels)

    def rate(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        window_seconds: float = 60.0,
    ) -> float | None:
        series_list = self.series_by_name(name, labels, since=time.time() - window_seconds * 3)
        if not series_list:
            return None
        total_rate = 0.0
        any_points = False
        now = time.time()
        for item in series_list:
            pts = item["points"]
            if len(pts) < 2:
                continue
            window_pts = [p for p in pts if p["t"] >= now - window_seconds]
            if len(window_pts) < 2:
                window_pts = pts[-2:]
            dt = window_pts[-1]["t"] - window_pts[0]["t"]
            if dt <= 0:
                continue
            total_rate += (window_pts[-1]["v"] - window_pts[0]["v"]) / dt
            any_points = True
        return total_rate if any_points else None

    def increase(
        self,
        name: str,
        labels: dict[str, str] | None = None,
        window_seconds: float = 60.0,
    ) -> float | None:
        rate = self.rate(name, labels, window_seconds)
        if rate is None:
            return None
        return rate * window_seconds

    def group_by_label(
        self,
        name: str,
        group_label: str,
        labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        samples = find_samples(self.latest_samples(), name, labels)
        buckets: dict[str, float] = defaultdict(float)
        for sample in samples:
            key = sample.labels.get(group_label, "unknown")
            buckets[key] += sample.value
        return [{"label": k, "value": v} for k, v in sorted(buckets.items(), key=lambda x: -x[1])]


class MetricsStore:
    """Registry of per-appliance stores."""

    def __init__(self, history_seconds: int | None = None) -> None:
        self.history_seconds = history_seconds or Config.HISTORY_SECONDS
        self._lock = threading.RLock()
        self._stores: dict[int, ApplianceStore] = {}

    def for_appliance(self, appliance_id: int) -> ApplianceStore:
        with self._lock:
            store = self._stores.get(appliance_id)
            if store is None:
                store = ApplianceStore(appliance_id, self.history_seconds)
                store.hydrate_from_db()
                self._stores[appliance_id] = store
            return store

    def drop(self, appliance_id: int) -> None:
        with self._lock:
            self._stores.pop(appliance_id, None)

    def status_all(self) -> dict[str, Any]:
        appliances = db.list_appliances()
        return {
            "appliance_count": len(appliances),
            "scrape_interval": Config.SCRAPE_INTERVAL,
            "history_seconds": self.history_seconds,
            "appliances": [
                {
                    "id": a["id"],
                    "host": a["host"],
                    "display_name": a["display_name"],
                    "enabled": a["enabled"],
                    "last_status": a["last_status"],
                    "last_scrape_at": a["last_scrape_at"],
                    "last_error": a["last_error"],
                    "sample_count": a["sample_count"],
                    "fail_count": int(a.get("fail_count") or 0),
                    "is_clustered": a["is_clustered"],
                    "cluster_id": a.get("cluster_id"),
                }
                for a in appliances
            ],
        }
