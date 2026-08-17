"""Custom groups + admin group membership (ksctl/Metrics parity)."""
from __future__ import annotations

from typing import Any

from cm_client import CmClient

from ..context import ReportCtx


def _is_system_group(group: dict[str, Any]) -> bool:
    meta = group.get("app_metadata")
    return isinstance(meta, dict) and meta.get("system") is True


def check_groups(ctx: ReportCtx, client: CmClient, *, max_admin_users: int = 200) -> None:
    """List groups; INFO custom groups; audit admin members (never-login WARNING)."""
    try:
        page = client.get_paginated("/v1/usermgmt/groups", limit=100, max_items=500)
    except Exception as exc:  # noqa: BLE001
        ctx.section("groups", "WARN", {"error": str(exc)}, None)
        return

    resources = [g for g in (page.get("resources") or []) if isinstance(g, dict)]
    custom: list[dict[str, Any]] = []
    for g in resources:
        if _is_system_group(g):
            continue
        name = str(g.get("name") or "").strip()
        if not name:
            continue
        custom.append(
            {
                "name": name,
                "user_count": g.get("user_count"),
                "client_count": g.get("client_count"),
            }
        )
        ctx.add(
            "access",
            "access_custom_group_info",
            "INFO",
            f"Custom (non-system) group '{name}' is present.",
        )

    admin_users: list[dict[str, Any]] = []
    admin_err: str | None = None
    try:
        admin_page = client.get_paginated(
            "/v1/usermgmt/users/?group=admin",
            limit=100,
            max_items=max_admin_users,
        )
        admin_users = [u for u in (admin_page.get("resources") or []) if isinstance(u, dict)]
    except Exception as exc:  # noqa: BLE001
        admin_err = str(exc)

    never_admin = 0
    for u in admin_users:
        username = u.get("username") or u.get("name") or "?"
        display = u.get("name") or u.get("nickname") or username
        last_login = u.get("last_login")
        if not last_login:
            never_admin += 1
            ctx.add(
                "access",
                "access_admin_never_logged_in",
                "WARNING",
                f"Admin group member '{username}' ({display}) has never logged in.",
            )
        else:
            ctx.add(
                "access",
                "access_admin_member_info",
                "INFO",
                f"User '{username}' ({display}) is a member of the 'admin' system group.",
            )

    result = "WARN" if never_admin or admin_err else "PASS"
    ctx.section(
        "groups",
        result,
        {
            "total_groups": page.get("total", len(resources)),
            "fetched_groups": len(resources),
            "custom_groups_count": len(custom),
            "custom_groups": custom[:40],
            "admin_users_count": len(admin_users),
            "admin_never_logged_in": never_admin,
            "admin_error": admin_err,
        },
        200 if not admin_err else None,
    )
