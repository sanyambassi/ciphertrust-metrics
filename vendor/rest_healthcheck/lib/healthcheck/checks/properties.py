"""System properties vs documented defaults (ksctl/Metrics parity)."""
from __future__ import annotations

from typing import Any

from cm_client import CmClient

from ..context import ReportCtx
from ..util import cm_version_at_least, parse_cm_version

# Documented defaults (same set as CipherTrust Metrics / ksctl properties help).
DEFAULT_PROPERTIES: dict[str, str] = {
    "UI_IDLE_SESSION_TIMEOUT": "10m",
    "MAXIMUM_REFRESH_TOKEN_LIFETIME": "",
    "LOAD_BALANCER_ADDRESS": "",
    "HIDE_COMPOSITE_KEY": "false",
    "DEPRECATED_LEGACY_SYSLOG": "true",
    "CERT_REV_CHECK_TIMEOUT": "5",
    "ALLOW_USER_IMPERSONATION_ACROSS_DOMAIN": "false",
    "ALLOW_UNKNOWN_FIELDS": "false",
    "NAE_KEY_VERSION_FOR_OPERATIONS": "latest_key_version",
    "NAE_AUTH_RESPONSE_FOR_INTERNAL_SERVER_ERROR": "",
    "KEY_CACHE_EXPIRES_DURATION": "2",
    "ENFORCE_NAE_CLIENT_VALIDATION": "false",
    "ENFORCE_NAE_CLIENT_REGISTRATION": "false",
    "ENABLE_NAE_CRYPTO_RECORDS": "false",
    "ENABLE_NAE_ACTIVITY_LOGS": "false",
    "ENABLE_KMIP_ACTIVITY_LOGS": "false",
    "ENABLE_CERT_REV_CHECK": "true",
    "DISABLE_TLS_SESSION_RESUMPTION": "false",
    "PASSWORD_HASH_ITERATIONS": "10000",
    "KEY_STATES_METRIC_INTERVAL": "3600",
    "ENABLE_REST_CRYPTO_RECORDS": "false",
    "ENABLE_KEY_CACHE": "false",
    "PREVENT_DELETE_INUSE_CONNECTIONS": "true",
    "ENABLE_RECORDS_DB_STORE": "false",
    "ENABLE_ML_KEM_FOR_CLUSTER": "false",
    "CLUSTER_CERT_AUTO_RENEW_THRESHOLD": "30",
    "KMIP_DISALLOW_AES_GCM_NO_IV": "true",
}

_PROPERTIES_REMOVED_FROM_224 = frozenset({"ENABLE_RECORDS_DB_STORE"})
_PROPERTIES_ADDED_FROM_224 = frozenset({"KMIP_DISALLOW_AES_GCM_NO_IV"})


def defaults_for_cm_version(cm_version: Any = None) -> dict[str, str]:
    ver = parse_cm_version(cm_version) if isinstance(cm_version, str) else None
    if ver is None and cm_version is not None:
        ver = parse_cm_version(str(cm_version))
    if cm_version_at_least(cm_version, 2, 24) is True:
        return {
            k: v
            for k, v in DEFAULT_PROPERTIES.items()
            if k not in _PROPERTIES_REMOVED_FROM_224
        }
    if ver is not None and ver < (2, 24, 0):
        return {
            k: v
            for k, v in DEFAULT_PROPERTIES.items()
            if k not in _PROPERTIES_ADDED_FROM_224
        }
    return dict(DEFAULT_PROPERTIES)


def check_properties(ctx: ReportCtx, client: CmClient, *, cm_version: Any = None) -> None:
    """Flag properties whose value differs from documented defaults (INFO)."""
    try:
        page = client.get_paginated("/v1/configs/properties", limit=100, max_items=500)
    except Exception as exc:  # noqa: BLE001
        ctx.section("system_properties", "WARN", {"error": str(exc)}, None)
        return

    resources = page.get("resources") or []
    defaults = defaults_for_cm_version(cm_version)
    modified: list[dict[str, str]] = []
    for prop in resources:
        if not isinstance(prop, dict):
            continue
        name = str(prop.get("name") or "").strip()
        if not name or name not in defaults:
            continue
        current = "" if prop.get("value") is None else str(prop.get("value"))
        default = defaults[name]
        if current != default:
            modified.append(
                {
                    "name": name,
                    "value": current,
                    "default": default,
                    "description": str(prop.get("description") or "")[:240],
                }
            )
            ctx.add(
                "system",
                "sys_property_modified",
                "INFO",
                f"System property '{name}' has been modified. "
                f"Current value: '{current}' (default: '{default}').",
            )

    modified.sort(key=lambda r: r["name"].lower())
    ctx.section(
        "system_properties",
        "PASS",
        {
            "total": page.get("total", len(resources)),
            "fetched": len(resources),
            "known_defaults": len(defaults),
            "modified_count": len(modified),
            "modified": modified[:50],
        },
        200,
    )
