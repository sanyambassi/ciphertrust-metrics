"""HTTP traffic dashboard."""

from __future__ import annotations

from typing import Any

from ..store import ApplianceStore
from .panels import (
    _stat,
    _timeseries,
    _named_series,
    _avg_series,
)


def build_http(store: ApplianceStore) -> list[dict[str, Any]]:
    err_500 = store.increase(
        "http_response_time_seconds_count",
        {"code": "500"},
        60,
    )
    return [
        _stat("HTTP 500s (last minute)", err_500),
        _timeseries(
            "HTTP Request Rate",
            _named_series(
                store,
                "http_response_time_seconds_count",
                rate=True,
                limit=12,
                label_keys=["method", "path"],
            ),
            "req/s",
            "Scrape-to-scrape rate of http_response_time_seconds_count for the busiest method/path series.",
        ),
        _timeseries(
            "Avg HTTP Response Time",
            _avg_series(
                store,
                "http_response_time_seconds_sum",
                "http_response_time_seconds_count",
                limit=12,
                label_keys=["method", "path"],
            ),
            "s",
            "Δsum / Δcount of http_response_time_seconds (Grafana-style average latency).",
            wide=True,
        ),
        _timeseries(
            "HTTP 500 Errors",
            _named_series(
                store,
                "http_response_time_seconds_count",
                {"code": "500"},
                rate=True,
                label_keys=["method", "path"],
            ),
            "req/s",
        ),
        _timeseries(
            "Internal HTTP Client Response Count",
            _named_series(
                store,
                "httpclient_response_time_seconds_count",
                rate=True,
                label_keys=["method", "path"],
            ),
            "req/s",
        ),
        _timeseries(
            "Avg Internal HTTP Client Response Time",
            _avg_series(
                store,
                "httpclient_response_time_seconds_sum",
                "httpclient_response_time_seconds_count",
                limit=12,
                label_keys=["method", "path"],
            )
            or _avg_series(
                store,
                "ciphertrust_httpclient_response_time_seconds_sum",
                "ciphertrust_httpclient_response_time_seconds_count",
                limit=12,
                label_keys=["method", "path"],
            ),
            "s",
            "Average inter-microservice HTTP client latency (sum/count).",
            wide=True,
        ),
        _timeseries(
            "Network Latency Samples",
            _named_series(
                store,
                "ciphertrust_httpclient_network_latency_seconds_count",
                rate=True,
                label_keys=["service", "upstream_service"],
            ),
            "samples/s",
        ),
        _timeseries(
            "Avg Network Latency",
            _avg_series(
                store,
                "ciphertrust_httpclient_network_latency_seconds_sum",
                "ciphertrust_httpclient_network_latency_seconds_count",
                limit=12,
                label_keys=["service", "upstream_service"],
            ),
            "s",
            "Average inter-service network latency (sum/count by upstream).",
            wide=True,
        ),
    ]
