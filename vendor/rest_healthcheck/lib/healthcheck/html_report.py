"""Self-contained HTML healthcheck report with per-area tabs and charts.

Never embeds passwords, JWTs, refresh tokens, or Prometheus scrape tokens.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .posture import build_posture_table
from .remediations import remediation_for

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|jwt|authorization|refresh|scrape)",
    re.IGNORECASE,
)
_MD_FAIL = re.compile(r"\*\*\*(.+?)\*\*\*")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*")

# Finding code prefix -> posture tab (first match wins; longest prefixes first).
_CODE_TAB = (
    ("rot_key", "RoT"),
    ("diskenc_", "Appliance"),
    ("ntp_", "Appliance"),
    ("cluster_", "Appliance"),
    ("svc_", "Appliance"),
    ("banner_", "Appliance"),
    ("smtp_", "Interfaces"),
    ("notification_", "Interfaces"),
    ("backup_", "Backups"),
    ("alarms_", "Alarms"),
    ("feature_", "Licenses"),
    ("license_", "Licenses"),
    ("net_", "Interfaces"),
    ("access_users_", "Users"),
    ("access_pwd_", "Access"),
    ("access_ldap_", "Access"),
    ("access_admin_", "Access"),
    ("access_custom_", "Access"),
    ("sys_property_", "Access"),
    ("sys_", "Appliance"),
    ("keys_orphaned", "Orphaned"),
    ("keys_", "Keys"),
    ("quorum_", "Quorum"),
    ("cte_", "CTE"),
    ("records_", "Audit"),
    ("audit_", "Audit"),
    ("domain_", "Access"),
    ("metrics_", "Keys"),
    ("ca_", "CAs"),
)

_AREA_TAB = {
    "interfaces": "Interfaces",
    "licensing": "Licenses",
    "ca": "CAs",
    "cte": "CTE",
    "records": "Audit",
    "access": "Access",
    "keys": "Keys",
    "quorum": "Quorum",
    "system": "Appliance",
    "domains": "Access",
}

_SECTION_TAB = {
    "auth": "Appliance",
    "identity_self_user": "Users",
    "identity_self_domains": "Access",
    "system_info": "Appliance",
    "services_status": "Appliance",
    "cluster": "Appliance",
    "cluster_summary": "Appliance",
    "cluster_errors": "Appliance",
    "nodes": "Appliance",
    "ntp": "Appliance",
    "banner_pre_auth": "Appliance",
    "disk_encryption": "Appliance",
    "rot_keys": "RoT",
    "licensing_features": "Licenses",
    "licensing_licenses": "Licenses",
    "interfaces": "Interfaces",
    "log_forwarders": "Interfaces",
    "notifications": "Interfaces",
    "backup_status": "Backups",
    "backup_keys": "Backups",
    "backups_list": "Backups",
    "backup_scheduler": "Backups",
    "alarms": "Alarms",
    "ca_trusted": "CAs",
    "ca_local": "CAs",
    "ca_external": "CAs",
    "password_policies": "Access",
    "ldap_connections": "Access",
    "system_properties": "Access",
    "groups": "Access",
    "domains": "Access",
    "orphaned_resources": "Orphaned",
    "quorum_policies": "Quorum",
    "registered_clients": "Clients",
    "audit_records": "Audit",
    "cte_clients": "CTE",
    "cte_policies": "CTE",
    "metrics_status": "Keys",
    "keys_metrics": "Keys",
    "keys_domains": "Keys",
    "users_access": "Users",
}

_PAL = {
    "crit": "#b42318",
    "warn": "#c47d00",
    "info": "#175cd3",
    "pass": "#1b7f4e",
    "fail": "#b42318",
    "muted": "#8b949e",
}


def write_html_report(report: dict[str, Any], path: str | Path) -> Path:
    """Write a full HTML report. Returns the resolved path."""
    out = Path(path)
    if out.suffix.lower() != ".html":
        out = out.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(report), encoding="utf-8")
    return out.resolve()


def render_html(report: dict[str, Any]) -> str:
    overall = str(report.get("overall") or "UNKNOWN")
    base = str(report.get("base") or "")
    host = _host(base)
    version = str(report.get("cm_version") or "n/a")
    ts = str(report.get("timestamp_utc") or "")
    summary = report.get("summary") or {}
    posture = report.get("posture") or {}
    table = build_posture_table(posture)
    if not table:
        table = [r for r in (posture.get("table") or []) if isinstance(r, dict)]
    findings = [f for f in (report.get("findings") or []) if isinstance(f, dict)]
    sections = [s for s in (report.get("sections") or []) if isinstance(s, dict)]

    by_tab: dict[str, list[dict]] = {row.get("area"): [] for row in table if row.get("area")}
    by_tab.setdefault("Overview", [])
    unmatched: list[dict] = []
    for f in findings:
        tab = _finding_tab(f)
        if tab in by_tab:
            by_tab[tab].append(f)
        else:
            unmatched.append(f)
    by_tab["Overview"].extend(unmatched)

    charts = _tab_charts(report, table)
    charts_json = json.dumps(charts, default=str).replace("<", "\\u003c")

    sorted_rows = _sort_area_rows(table)
    nav_parts = [
        "<div class='nav-label'>Report</div>",
        _tab_button(
            "overview",
            "Overview",
            overall if overall in ("OK", "DEGRADED", "CRITICAL", "UNREACHABLE") else "WARN",
            result_label=overall,
        ),
    ]
    panels = [_overview_panel(report, sorted_rows, summary, by_tab, charts.get("overview") or [])]

    last_tone = None
    group_label = {"FAIL": "Fail", "WARN": "Warn", "PASS": "Pass", "MUTED": "Other"}
    for row in sorted_rows:
        area = str(row.get("area") or "")
        slug = _slug(area)
        result = _strip_result_md(row.get("result"))
        tone = _tab_tone(result)
        if tone != last_tone:
            nav_parts.append(f"<div class='nav-label'>{group_label.get(tone, tone)}</div>")
            last_tone = tone
        nav_parts.append(_tab_button(slug, area, result))
        panels.append(_area_panel(slug, row, by_tab.get(area) or [], charts.get(slug) or [], posture, sections))

    nav_parts.append("<div class='nav-label'>More</div>")
    nav_parts.append(_tab_button("raw", "Raw checks", "MUTED", result_label="JSON"))
    panels.append(_raw_panel(sections))

    return (
        "<!DOCTYPE html>\n<html lang='en'>\n<head>\n"
        "<meta charset='utf-8'/>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>\n"
        f"<title>CipherTrust Manager healthcheck — {esc(overall)} — {esc(host)}</title>\n"
        "<script src='https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js'></script>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        "<header>\n"
        "  <div class='head-top'><h1>CipherTrust Manager healthcheck</h1>\n"
        f"  <span class='badge {esc(overall)}'>{esc(overall)}</span></div>\n"
        "  <p class='meta'>\n"
        f"    CM {esc(version)} · {esc(host)} · {esc(ts)}\n"
        "  </p>\n"
        "</header>\n"
        "<div class='wrap'>\n"
        "<div class='layout'>\n"
        f"<nav class='tab-bar' role='tablist'>{''.join(nav_parts)}</nav>\n"
        "<main class='main'>\n"
        f"{''.join(panels)}\n"
        "<footer>CipherTrust Manager healthcheck</footer>\n"
        "</main>\n"
        "</div>\n"
        "</div>\n"
        f"<script>const DATA = {charts_json};\n{_JS}</script>\n"
        "</body>\n</html>\n"
    )


def _host(base: str) -> str:
    try:
        return urlparse(base).hostname or base or "n/a"
    except Exception:
        return base or "n/a"


def esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _md(text: Any) -> str:
    s = html.escape(str(text or ""))
    s = s.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>")
    s = _MD_FAIL.sub(r'<strong class="fail">\1</strong>', s)
    return _MD_BOLD.sub(r'<strong class="warn">\1</strong>', s)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s or "area"


def _strip_result_md(result: Any) -> str:
    return str(result or "").replace("**", "").strip()


def _n(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _finding_tab(finding: dict) -> str:
    code = str(finding.get("code") or "")
    for prefix, tab in _CODE_TAB:
        if code.startswith(prefix):
            return tab
    return _AREA_TAB.get(str(finding.get("area") or ""), "Overview")


def _tab_tone(result: str) -> str:
    r = (result or "").upper()
    if r in ("FAIL", "CRITICAL", "UNREACHABLE"):
        return "FAIL"
    if r in ("WARN", "WARNING", "DEGRADED"):
        return "WARN"
    if r in ("PASS", "OK"):
        return "PASS"
    return "MUTED"


def _sort_area_rows(table: list[dict]) -> list[dict]:
    rank = {"FAIL": 0, "WARN": 1, "PASS": 2, "MUTED": 3}
    return sorted(
        table,
        key=lambda r: (
            rank.get(_tab_tone(_strip_result_md(r.get("result"))), 9),
            str(r.get("area") or ""),
        ),
    )


def _tab_button(
    slug: str,
    label: str,
    result: str,
    result_label: str | None = None,
) -> str:
    tone = _tab_tone(result)
    shown = result_label or result
    return (
        f"<button type='button' class='tab-btn {tone}' role='tab' "
        f"id='tab-{esc(slug)}' data-tab='{esc(slug)}'>"
        f"<span class='name'>{esc(label)}</span>"
        f"<span class='st {tone}'>{esc(shown)}</span></button>"
    )


def _kpi(label: str, n: Any, cls: str) -> str:
    return (
        f"<div class='kpi {esc(cls)}'><div class='n'>{esc(n)}</div>"
        f"<div class='l'>{esc(label)}</div></div>"
    )


def _chart_box(cfg: dict) -> str:
    cid = esc(cfg.get("id"))
    height = _n(cfg.get("height")) or 220
    cap = str(cfg.get("caption") or "").strip()
    cap_html = f"<p class='caption'>{esc(cap)}</p>" if cap else ""
    return (
        f"<div class='chart-box' id='box-{cid}'>"
        f"<h3>{esc(cfg.get('title'))}</h3>"
        f"{cap_html}"
        f"<div class='chart-frame' style='height:{height}px'>"
        f"<canvas id='{cid}'></canvas></div></div>"
    )


# Finding codes whose item lists should be expanded by default in the HTML report.
_OPEN_DETAIL_CODES = frozenset(
    {
        "sys_property_modified",
        "access_custom_group_info",
        "access_admin_never_logged_in",
        "access_users_locked",
        "access_users_never_logged_in",
        "access_users_inactive",
        "access_users_failed_logins",
        "keys_weak_algorithm",
        "keys_non_active",
        "keys_orphaned",
        "ca_trusted_expired",
        "ca_trusted_expiring",
        "ca_local_expired",
        "ca_local_expiring",
        "ca_external_expired",
        "ca_external_expiring",
        "license_expired",
        "license_expiring",
        "license_trial_expiring",
        "feature_expired",
        "feature_trial_expiring",
        "svc_disabled",
        "svc_not_started",
        "net_iface_cert_expired",
        "net_iface_cert_expiring",
        "net_interface_mode_warn",
        "net_interface_tcp_mode",
        "cte_client_disconnected",
        "cte_guardpoint_not_active",
        "cte_policy_learn_mode",
        "alarms_critical",
        "rot_key_critical_age",
        "rot_key_old",
    }
)

# Tabs where INFO findings start expanded (parity tables + names are easy to miss).
_OPEN_INFO_AREAS = frozenset(
    {
        "Access",
        "Keys",
        "Users",
        "Appliance",
        "Licenses",
        "CAs",
        "Interfaces",
        "CTE",
        "Alarms",
        "Orphaned",
        "Audit",
    }
)


def _findings_lists(
    items: list[dict],
    *,
    collapse_info: bool = True,
    open_info: bool = False,
) -> str:
    crit = [f for f in items if f.get("severity") == "CRITICAL"]
    warn = [f for f in items if f.get("severity") == "WARNING"]
    info = [f for f in items if f.get("severity") == "INFO"]
    parts = [
        _findings_block("CRITICAL", crit, "crit-list"),
        _findings_block("WARNING", warn, "warn-list"),
    ]
    info_html = _findings_block("INFO", info, "info-list")
    if collapse_info and len(info) > 4:
        open_attr = " open" if open_info else ""
        parts.append(
            f"<details class='info-fold'{open_attr}>"
            f"<summary>INFO findings ({len(info)}) — expand for properties, groups, and other INFO</summary>"
            f"{info_html}</details>"
        )
    else:
        parts.append(info_html)
    return "".join(parts)


def _group_findings_by_code(items: list[dict]) -> list[dict[str, Any]]:
    """Collapse duplicate codes; remediation is shown once per code."""
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for f in items:
        code = str(f.get("code") or "uncategorized")
        if code not in grouped:
            grouped[code] = {
                "code": code,
                "messages": [],
                "remediation": remediation_for(code),
            }
            order.append(code)
        msg = f.get("message")
        if msg:
            grouped[code]["messages"].append(str(msg))
    return [grouped[c] for c in order]


def _findings_block(title: str, items: list[dict], cls: str) -> str:
    if not items:
        return ""
    summaries = _group_findings_by_code(items)
    lis = []
    for summary in summaries:
        count = len(summary["messages"])
        count_label = f"{count} finding{'s' if count != 1 else ''}"
        rem = esc(summary["remediation"])
        code = esc(summary["code"])
        if count > 1:
            detail_lines = "".join(f"<li>{_md(m)}</li>" for m in summary["messages"])
            open_attr = " open" if summary["code"] in _OPEN_DETAIL_CODES else ""
            details = (
                f"<details class='finding-detail'{open_attr}>"
                f"<summary>Show {count} items</summary>"
                f"<ul>{detail_lines}</ul></details>"
            )
        else:
            details = f"<div class='finding-msg'>{_md(summary['messages'][0])}</div>"
        lis.append(
            f"<li><div class='finding-head'><code class='finding-code'>{code}</code>"
            f" <span class='finding-count'>({count_label})</span></div>"
            f"<div class='finding-fix'><strong>Remediation:</strong> {rem}</div>{details}</li>"
        )
    return (
        f"<div class='card {cls}'><h3>{esc(title)} ({len(items)})</h3>"
        f"<ul class='findings'>{''.join(lis)}</ul></div>"
    )


def _status_pills(items: list[dict]) -> str:
    crit = sum(1 for f in items if f.get("severity") == "CRITICAL")
    warn = sum(1 for f in items if f.get("severity") == "WARNING")
    info = sum(1 for f in items if f.get("severity") == "INFO")
    pills = []
    if crit:
        pills.append(f"<span class='pill crit'>{crit} critical</span>")
    if warn:
        pills.append(f"<span class='pill warn'>{warn} warning</span>")
    if info:
        pills.append(f"<span class='pill info'>{info} info</span>")
    if not pills:
        pills.append("<span class='pill'>no findings</span>")
    return f"<div class='status-pills'>{''.join(pills)}</div>"


def _overview_panel(
    report: dict,
    table: list[dict],
    summary: dict,
    by_tab: dict[str, list[dict]],
    overview_charts: list[dict],
) -> str:
    cards = []
    for row in table:
        area = str(row.get("area") or "")
        result = _strip_result_md(row.get("result"))
        tone = _tab_tone(result)
        items = by_tab.get(area) or []
        crit = sum(1 for f in items if f.get("severity") == "CRITICAL")
        warn = sum(1 for f in items if f.get("severity") == "WARNING")
        counts = []
        if crit:
            counts.append(f"{crit} crit")
        if warn:
            counts.append(f"{warn} warn")
        extra = f"<span class='sub'>{esc(' · '.join(counts))}</span>" if counts else ""
        cards.append(
            f"<button type='button' class='area-card {tone}' data-jump='{_slug(area)}'>"
            f"<span class='area-name'>{esc(area)}</span>"
            f"<span class='st {tone}'>{esc(result)}</span>{extra}</button>"
        )
    chart_html = "".join(_chart_box(c) for c in overview_charts)
    return (
        "<section class='tab-panel' id='panel-overview' role='tabpanel'>"
        "<div class='kpis'>"
        f"{_kpi('Critical', summary.get('critical', 0), 'crit')}"
        f"{_kpi('Warning', summary.get('warning', 0), 'warn')}"
        f"{_kpi('Info', summary.get('info', 0), 'info')}"
        f"{_kpi('Sections FAIL', summary.get('sections_fail', 0), '')}"
        f"{_kpi('Sections WARN', summary.get('sections_warn', 0), '')}"
        f"{_kpi('Checks', len(report.get('sections') or []), '')}"
        "</div>"
        f"<div class='charts'>{chart_html}</div>"
        "<h2>Areas</h2>"
        f"<div class='area-grid'>{''.join(cards)}</div>"
        "</section>"
    )


def _area_panel(
    slug: str,
    row: dict,
    items: list[dict],
    charts: list[dict],
    posture: dict,
    sections: list[dict],
) -> str:
    area = str(row.get("area") or "")
    result = _strip_result_md(row.get("result"))
    tone = _tab_tone(result)
    extra = _area_extras(area, posture, sections)
    chart_html = "".join(_chart_box(c) for c in charts)
    related = [
        s
        for s in sections
        if _SECTION_TAB.get(str(s.get("name") or "")) == area
    ]
    return (
        f"<section class='tab-panel' id='panel-{esc(slug)}' role='tabpanel' hidden>"
        f"<div class='panel-head'>"
        f"<div class='head-row'><h2>{esc(area)}</h2>"
        f"<span class='st {tone}'>{esc(result)}</span></div>"
        f"{_status_pills(items)}"
        f"<div class='summary'>{_md(row.get('summary'))}</div>"
        "</div>"
        f"<div class='charts'>{chart_html}</div>"
        f"{extra}"
        f"{_findings_lists(items, open_info=(area in _OPEN_INFO_AREAS))}"
        f"{_related_sections(related)}"
        "</section>"
    )


def _raw_panel(sections: list[dict]) -> str:
    return (
        "<section class='tab-panel' id='panel-raw' role='tabpanel' hidden>"
        "<div class='panel-head'><div class='head-row'><h2>Raw checks</h2></div></div>"
        f"{_sections_html(sections)}"
        "</section>"
    )


def _related_sections(sections: list[dict]) -> str:
    if not sections:
        return ""
    return (
        "<details class='raw-fold'><summary>Details "
        f"({len(sections)})</summary>{_sections_html(sections)}</details>"
    )


def _area_extras(area: str, posture: dict, sections: list[dict]) -> str:
    if area == "Users":
        return _users_table(posture, sections)
    if area == "Keys":
        return _keys_table(posture, sections)
    if area == "Access":
        return _access_tables(sections)
    if area == "Appliance":
        return _appliance_tables(sections, posture)
    if area == "Backups":
        return _backups_table(posture, sections)
    if area == "CAs":
        return _cas_table(posture, sections)
    if area == "Interfaces":
        return _interfaces_table(sections)
    if area == "CTE":
        return _cte_table(sections)
    if area == "RoT":
        return _rot_table(sections)
    if area == "Licenses":
        return _licenses_table(sections)
    if area == "Alarms":
        return _alarms_table(sections)
    if area == "Orphaned":
        return _orphaned_table(sections)
    if area == "Audit":
        return _audit_samples_table(sections)
    if area == "Quorum":
        return _quorum_table(sections)
    if area == "Clients":
        return _clients_table(sections)
    return ""


def _access_tables(sections: list[dict]) -> str:
    """Surface modified properties + custom groups without digging into INFO folds."""
    props = _sec_detail(sections, "system_properties")
    groups = _sec_detail(sections, "groups")
    ldap = _sec_detail(sections, "ldap_connections")
    pwd = _sec_detail(sections, "password_policies")
    parts: list[str] = []

    modified = [m for m in (props.get("modified") or []) if isinstance(m, dict)]
    if modified:
        rows = []
        for m in modified:
            rows.append(
                "<tr>"
                f"<td><code>{esc(m.get('name'))}</code></td>"
                f"<td>{esc(m.get('value'))}</td>"
                f"<td>{esc(m.get('default'))}</td>"
                f"<td>{esc(m.get('description'))}</td>"
                "</tr>"
            )
        parts.append(
            _table(
                ["Property", "Current", "Default", "Description"],
                rows,
                f"Modified system properties ({len(modified)})",
            )
        )
    elif props:
        parts.append(
            "<div class='card'><h3>Modified system properties</h3>"
            "<p class='muted'>None — all known properties match documented defaults.</p></div>"
        )

    custom = [g for g in (groups.get("custom_groups") or []) if isinstance(g, dict)]
    if custom:
        rows = []
        for g in custom:
            rows.append(
                "<tr>"
                f"<td>{esc(g.get('name'))}</td>"
                f"<td>{esc(g.get('user_count'))}</td>"
                f"<td>{esc(g.get('client_count'))}</td>"
                "</tr>"
            )
        parts.append(
            _table(
                ["Custom group", "Users", "Clients"],
                rows,
                f"Custom groups ({len(custom)})",
            )
        )
    admin_n = groups.get("admin_users_count")
    never_n = groups.get("admin_never_logged_in")
    if admin_n is not None:
        parts.append(
            "<div class='card'><h3>Admin group</h3>"
            f"<p>{esc(admin_n)} member(s)"
            + (
                f"; <strong class='warn'>{esc(never_n)} never logged in</strong>"
                if never_n
                else ""
            )
            + ". See WARNING/INFO findings below for names and remediation.</p></div>"
        )

    weak = [str(x) for x in (pwd.get("weak_policies") or []) if x]
    if weak:
        parts.append(
            _table(
                ["Policy"],
                [f"<tr><td>{esc(n)}</td></tr>" for n in weak],
                f"Weak password policies ({len(weak)})",
            )
        )

    conns = [c for c in (ldap.get("connections") or []) if isinstance(c, dict)]
    if conns:
        rows = []
        for c in conns:
            insecure = c.get("insecure_skip_verify") is True
            rows.append(
                "<tr>"
                f"<td>{esc(c.get('name'))}</td>"
                f"<td>{esc(c.get('server_url'))}</td>"
                f"<td>{'yes' if insecure else 'no'}</td>"
                f"<td>{'yes' if c.get('has_root_ca') else 'no'}</td>"
                "</tr>"
            )
        parts.append(
            _table(
                ["LDAP connection", "URL", "Skip verify", "Root CA"],
                rows,
                f"LDAP connections ({len(conns)})",
            )
        )
    return "".join(parts)


def _appliance_tables(sections: list[dict], posture: dict) -> str:
    parts: list[str] = []
    svc = _sec_detail(sections, "services_status")
    down = [d for d in (svc.get("not_started") or []) if isinstance(d, dict)]
    disabled = [d for d in (svc.get("disabled") or []) if isinstance(d, dict)]
    if down:
        parts.append(
            _table(
                ["Service", "State"],
                [
                    f"<tr><td>{esc(d.get('name'))}</td><td>{esc(d.get('status') or d.get('state'))}</td></tr>"
                    for d in down[:40]
                ],
                f"Services not started ({len(down)})",
            )
        )
    if disabled:
        parts.append(
            _table(
                ["Service", "State"],
                [
                    f"<tr><td>{esc(d.get('name'))}</td><td>{esc(d.get('status') or 'disabled')}</td></tr>"
                    for d in disabled[:40]
                ],
                f"Services disabled ({len(disabled)})",
            )
        )

    ntp = _sec_detail(sections, "ntp")
    servers = ntp.get("servers") or []
    if isinstance(servers, list) and servers:
        rows = []
        for s in servers[:20]:
            if isinstance(s, dict):
                rows.append(
                    f"<tr><td>{esc(s.get('hostname') or s.get('name') or s.get('server'))}</td>"
                    f"<td>{esc(s.get('status') or s.get('state'))}</td></tr>"
                )
            else:
                rows.append(f"<tr><td>{esc(s)}</td><td></td></tr>")
        parts.append(_table(["NTP server", "Status"], rows, "NTP servers"))

    disk = _sec_detail(sections, "disk_encryption")
    if disk:
        parts.append(
            "<div class='card'><h3>Disk encryption</h3>"
            f"<p>status={esc(disk.get('encryptionStatus') or disk.get('state'))}, "
            f"encrypted={esc(disk.get('encrypted'))}, "
            f"attendedBoot={esc(disk.get('attendedBoot'))}</p></div>"
        )

    cerr = _sec_detail(sections, "cluster_errors")
    reasons = cerr.get("reasons") or []
    if reasons:
        parts.append(
            _table(
                ["Cluster error"],
                [f"<tr><td>{esc(r)}</td></tr>" for r in reasons[:30]],
                f"Cluster errors ({len(reasons)})",
            )
        )
    return "".join(parts)


def _table(headers: list[str], rows: list[str], title: str) -> str:
    if not rows:
        return ""
    th = "".join(f"<th>{h}</th>" for h in headers)
    return (
        f"<div class='card'><h3>{esc(title)}</h3>"
        f"<div class='table-wrap'><table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def _users_table(posture: dict, sections: list[dict] | None = None) -> str:
    parts: list[str] = []
    rows = []
    for d in (posture.get("users") or {}).get("by_domain") or []:
        if not isinstance(d, dict):
            continue
        top = d.get("top_by_logins") or []
        top_s = ", ".join(
            f"{t.get('username')}({t.get('logins_count')})"
            for t in top
            if isinstance(t, dict)
        )
        rows.append(
            "<tr>"
            f"<td>{esc(d.get('domain'))}</td><td>{esc(d.get('total'))}</td>"
            f"<td>{esc(d.get('locked'))}</td><td>{esc(d.get('never_logged_in'))}</td>"
            f"<td>{esc(d.get('inactive_30d'))}</td>"
            f"<td>{esc(d.get('failed_logins_not_locked'))}</td>"
            f"<td>{esc(top_s)}</td></tr>"
        )
    parts.append(
        _table(
            ["Domain", "Users", "Locked", "Never login", "Inactive >30d", "Failed logins", "Top logins"],
            rows,
            "Users by domain",
        )
    )

    # Sample usernames from hygiene scans (keys_domains / users_access).
    sample_rows: list[str] = []
    checked = (_sec_detail(sections or [], "keys_domains").get("checked") or [])
    access = _sec_detail(sections or [], "users_access")
    domains_users: list[tuple[str, dict]] = []
    for c in checked:
        if isinstance(c, dict) and isinstance(c.get("users"), dict):
            domains_users.append((str(c.get("domain") or ""), c["users"]))
    if access and isinstance(access.get("samples"), dict):
        domains_users.append(("(current token)", access))
    for domain, users in domains_users:
        samples = users.get("samples") if isinstance(users.get("samples"), dict) else {}
        for kind in ("locked", "never_logged_in", "inactive_30d", "failed_logins"):
            vals = samples.get(kind) or []
            for v in vals[:8]:
                if isinstance(v, dict):
                    uname = v.get("user") or v.get("username")
                    extra = f" fails={v.get('failed_logins_count')}" if v.get("failed_logins_count") else ""
                else:
                    uname, extra = v, ""
                if not uname:
                    continue
                sample_rows.append(
                    f"<tr><td>{esc(domain)}</td><td>{esc(kind)}</td>"
                    f"<td>{esc(uname)}{esc(extra)}</td></tr>"
                )
    if sample_rows:
        parts.append(
            _table(
                ["Domain", "Issue", "User"],
                sample_rows[:60],
                f"User hygiene samples ({min(len(sample_rows), 60)})",
            )
        )
    return "".join(parts)


def _keys_table(posture: dict, sections: list[dict] | None = None) -> str:
    parts: list[str] = []
    rows_data = [
        d
        for d in ((posture.get("keys") or {}).get("domains") or {}).get("by_domain") or []
        if isinstance(d, dict)
    ]
    if rows_data:
        max_total = max((_n(d.get("total")) for d in rows_data), default=0) or 1
        rows = []
        for d in rows_data:
            total = _n(d.get("total"))
            weak = _n(d.get("weak"))
            inactive = _n(d.get("non_active"))
            pct = min(100, round(100 * total / max_total))
            weak_cls = "fail" if weak else "ok"
            ina_cls = "warn" if inactive else "ok"
            rows.append(
                "<tr>"
                f"<td>{esc(d.get('domain'))}</td>"
                "<td><div class='meter-wrap'>"
                f"<div class='meter' title='{esc(total)} keys'>"
                f"<span class='meter-fill' style='width:{pct}%'></span></div>"
                f"<span class='meter-n'>{esc(total)}</span></div></td>"
                f"<td>{esc(d.get('unique'))}</td>"
                f"<td><span class='badge-n {weak_cls}'>{esc(weak)}</span></td>"
                f"<td><span class='badge-n {ina_cls}'>{esc(inactive)}</span></td>"
                "</tr>"
            )
        parts.append(
            "<div class='card'><h3>Keys by domain</h3>"
            "<div class='table-wrap'><table><thead><tr>"
            "<th>Domain</th><th>Total</th><th>Unique</th><th>Weak</th><th>Inactive</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></div></div>"
        )

    weak_rows: list[str] = []
    inactive_rows: list[str] = []
    for c in _sec_detail(sections or [], "keys_domains").get("checked") or []:
        if not isinstance(c, dict):
            continue
        domain = c.get("domain")
        for w in c.get("weak_sample") or []:
            if not isinstance(w, dict):
                continue
            weak_rows.append(
                "<tr>"
                f"<td>{esc(domain)}</td><td>{esc(w.get('name'))}</td>"
                f"<td>{esc(w.get('algorithm'))}</td><td>{esc(w.get('size'))}</td>"
                f"<td>{esc(w.get('curve'))}</td><td>{esc(w.get('reason'))}</td></tr>"
            )
        for n in c.get("non_active_sample") or []:
            if not isinstance(n, dict):
                continue
            inactive_rows.append(
                "<tr>"
                f"<td>{esc(domain)}</td><td>{esc(n.get('name'))}</td>"
                f"<td>{esc(n.get('state'))}</td><td>{esc(n.get('version'))}</td></tr>"
            )
    if weak_rows:
        parts.append(
            _table(
                ["Domain", "Key", "Algorithm", "Size", "Curve", "Reason"],
                weak_rows[:40],
                f"Weak keys (sample, {min(len(weak_rows), 40)})",
            )
        )
    if inactive_rows:
        parts.append(
            _table(
                ["Domain", "Key", "State", "Version"],
                inactive_rows[:40],
                f"Inactive keys (sample, {min(len(inactive_rows), 40)})",
            )
        )
    return "".join(parts)


def _domain_status_rows(
    items: list[Any], cells_ok, empty_cols: int = 3
) -> tuple[list[str], list[str]]:
    ok_rows: list[str] = []
    skipped: list[str] = []
    blanks = "<td></td>" * empty_cols
    for d in items:
        if not isinstance(d, dict):
            continue
        if d.get("skipped") or d.get("error"):
            reason = d.get("reason") or d.get("error") or "n/a"
            skipped.append(
                "<tr>"
                f"<td>{esc(d.get('domain'))}</td>"
                f"<td>skipped ({esc(reason)}; {esc(d.get('status'))})</td>"
                f"{blanks}</tr>"
            )
        else:
            ok_rows.append(cells_ok(d))
    return ok_rows, skipped


def _skipped_fold(rows: list[str], headers: list[str], title: str) -> str:
    if not rows:
        return ""
    th = "".join(f"<th>{h}</th>" for h in headers)
    return (
        f"<details class='info-fold'><summary>{esc(title)} ({len(rows)})</summary>"
        f"<div class='card'><div class='table-wrap'><table><thead><tr>{th}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></div></details>"
    )


def _backups_table(posture: dict, sections: list[dict] | None = None) -> str:
    def cells(d: dict) -> str:
        return (
            "<tr>"
            f"<td>{esc(d.get('domain'))}</td><td>ok</td>"
            f"<td>{esc(d.get('total'))}</td>"
            f"<td>{esc(d.get('system_count'))}</td>"
            f"<td>{esc(d.get('domain_count'))}</td></tr>"
        )

    headers = ["Domain", "Status", "Total", "System", "Domain-scoped"]
    ok_rows, skipped = _domain_status_rows(
        (posture.get("backups") or {}).get("by_domain") or [], cells
    )
    parts = [
        _table(headers, ok_rows, "Backups by domain"),
        _skipped_fold(skipped, headers, "Domains skipped (unauthorized)"),
    ]
    keys = _sec_detail(sections or [], "backup_keys")
    inactive = keys.get("inactive") or []
    if inactive:
        rows = []
        for k in inactive[:30]:
            if isinstance(k, dict):
                rows.append(
                    f"<tr><td>{esc(k.get('name') or k.get('id'))}</td>"
                    f"<td>{esc(k.get('state') or k.get('status'))}</td></tr>"
                )
            else:
                rows.append(f"<tr><td>{esc(k)}</td><td></td></tr>")
        parts.append(_table(["Backup key", "State"], rows, "Inactive backup keys"))
    sched = _sec_detail(sections or [], "backup_scheduler")
    names = sched.get("names") or []
    if names:
        parts.append(
            _table(
                ["Enabled schedule job"],
                [f"<tr><td>{esc(n)}</td></tr>" for n in names[:30]],
                "Backup schedule jobs",
            )
        )
    return "".join(parts)


def _cas_table(posture: dict, sections: list[dict] | None = None) -> str:
    def cells(d: dict) -> str:
        loc = d.get("local") if isinstance(d.get("local"), dict) else {}
        ext = d.get("external") if isinstance(d.get("external"), dict) else {}
        return (
            "<tr>"
            f"<td>{esc(d.get('domain'))}</td><td>ok</td>"
            f"<td>{esc(loc.get('total'))}</td><td>{esc(loc.get('expired'))}</td>"
            f"<td>{esc(ext.get('total'))}</td><td>{esc(ext.get('expired'))}</td></tr>"
        )

    headers = ["Domain", "Status", "Local", "Local expired", "External", "External expired"]
    ok_rows, skipped = _domain_status_rows(
        (posture.get("certificates") or {}).get("by_domain") or [], cells, empty_cols=4
    )
    parts = [
        _table(headers, ok_rows, "CAs by domain"),
        _skipped_fold(skipped, headers, "Domains skipped (unauthorized)"),
    ]

    attention: list[str] = []
    for kind, sec_name in (
        ("trusted", "ca_trusted"),
        ("local", "ca_local"),
        ("external", "ca_external"),
    ):
        detail = _sec_detail(sections or [], sec_name)
        for bucket, label in (("expired", "expired"), ("expiring_soon", "expiring")):
            for ca in detail.get(bucket) or []:
                if not isinstance(ca, dict):
                    continue
                attention.append(
                    "<tr>"
                    f"<td>{esc(kind)}</td><td>{esc(label)}</td>"
                    f"<td>{esc(ca.get('domain') or '')}</td>"
                    f"<td>{esc(ca.get('name'))}</td>"
                    f"<td>{esc(ca.get('days_left'))}</td>"
                    f"<td>{esc(ca.get('notAfter'))}</td></tr>"
                )
    seen: set[str] = set()
    uniq: list[str] = []
    for row in attention:
        if row in seen:
            continue
        seen.add(row)
        uniq.append(row)
    if uniq:
        parts.append(
            _table(
                ["Kind", "Status", "Domain", "CA name", "Days left", "notAfter"],
                uniq[:50],
                f"CAs needing attention ({min(len(uniq), 50)})",
            )
        )
    return "".join(parts)


def _sec_detail(sections: list[dict], name: str) -> dict:
    for s in sections:
        if s.get("name") == name and isinstance(s.get("detail"), dict):
            return s["detail"]
    return {}


def _interfaces_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "interfaces")
    rows = []
    for i in detail.get("interfaces") or []:
        if not isinstance(i, dict):
            continue
        days = i.get("cert_days_left")
        if days is None:
            cert = "n/a"
        elif _n(days) < 0:
            cert = f"expired ({i.get('cert_notAfter')})"
        else:
            cert = f"{days}d ({i.get('cert_notAfter')})"
        rows.append(
            "<tr>"
            f"<td>{esc(i.get('name'))}</td>"
            f"<td>{esc(i.get('interface_type'))}</td>"
            f"<td>{esc(i.get('port'))}</td>"
            f"<td>{esc(i.get('mode_label') or i.get('mode'))}</td>"
            f"<td>{esc(i.get('minimum_tls_version'))}</td>"
            f"<td>{esc(cert)}</td></tr>"
        )
    return _table(
        ["Name", "Type", "Port", "Mode", "Min TLS", "Leaf cert"],
        rows,
        "Interfaces",
    )


def _cte_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "cte_clients")
    rows = []
    seen = set()
    for key in ("disconnected", "unregistered_or_offline"):
        for c in detail.get(key) or []:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if name in seen:
                continue
            seen.add(name)
            rows.append(
                "<tr>"
                f"<td>{esc(name)}</td>"
                f"<td>{esc(c.get('client_health_status'))}</td>"
                f"<td>{esc(c.get('communication_enabled'))}</td></tr>"
            )
    gp_rows = []
    for g in detail.get("guardpoints_not_active") or []:
        if not isinstance(g, dict):
            continue
        gp_rows.append(
            "<tr>"
            f"<td>{esc(g.get('client'))}</td>"
            f"<td>{esc(g.get('guard_path'))}</td>"
            f"<td>{esc(g.get('guard_point_state'))}</td></tr>"
        )
    pol = _sec_detail(sections, "cte_policies")
    learn = pol.get("learn_mode_policies") or []
    learn_rows = []
    for p in learn:
        if isinstance(p, dict):
            learn_rows.append(
                f"<tr><td>{esc(p.get('name'))}</td><td>{esc(p.get('id'))}</td></tr>"
            )
        else:
            learn_rows.append(f"<tr><td>{esc(p)}</td><td></td></tr>")
    return (
        _table(
            ["Client", "Health", "Communication"],
            rows,
            "CTE clients needing attention",
        )
        + _table(
            ["Client", "GuardPoint path", "State"],
            gp_rows,
            "GuardPoints not active",
        )
        + _table(
            ["Policy", "Id"],
            learn_rows[:40],
            f"Learn Mode policies ({len(learn_rows)})",
        )
    )


def _rot_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "rot_keys")
    rows = []
    for k in detail.get("keys") or []:
        if not isinstance(k, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(k.get('id'))}</td>"
            f"<td>{esc(k.get('createdAt'))}</td>"
            f"<td>{esc(k.get('age_label') or k.get('age_years'))}</td></tr>"
        )
    return _table(["Key", "Created", "Age"], rows, "Root-of-trust keys")


def _licenses_table(sections: list[dict]) -> str:
    feat = _sec_detail(sections, "licensing_features")
    lic = _sec_detail(sections, "licensing_licenses")
    parts: list[str] = []

    expired_f = feat.get("expired") or []
    if expired_f:
        parts.append(
            _table(
                ["Feature"],
                [
                    f"<tr><td>{esc(x.get('name') if isinstance(x, dict) else x)}</td></tr>"
                    for x in expired_f[:30]
                ],
                f"Expired features ({len(expired_f)})",
            )
        )
    trials_f = [
        t for t in (feat.get("trials_expiring_soon") or []) if isinstance(t, dict)
    ]
    if trials_f:
        parts.append(
            _table(
                ["Feature", "Trial days remaining"],
                [
                    f"<tr><td>{esc(t.get('name'))}</td>"
                    f"<td>{esc(t.get('trial_days_remaining'))}</td></tr>"
                    for t in trials_f
                ],
                "Feature trials expiring within 30 days",
            )
        )

    expired_l = lic.get("expired") or []
    if expired_l:
        parts.append(
            _table(
                ["License / feature"],
                [
                    f"<tr><td>{esc(x.get('feature') if isinstance(x, dict) else x)}</td></tr>"
                    for x in expired_l[:30]
                ],
                f"Expired licenses ({len(expired_l)})",
            )
        )
    expiring_l = [
        t for t in (lic.get("expiring_soon") or []) if isinstance(t, dict)
    ]
    if expiring_l:
        parts.append(
            _table(
                ["License / feature", "Days left"],
                [
                    f"<tr><td>{esc(t.get('feature'))}</td><td>{esc(t.get('days_left'))}</td></tr>"
                    for t in expiring_l
                ],
                "Licenses expiring within 30 days",
            )
        )
    trials_l = [
        t for t in (lic.get("trials_expiring_soon") or []) if isinstance(t, dict)
    ]
    if trials_l:
        parts.append(
            _table(
                ["License / feature", "Trial days remaining"],
                [
                    f"<tr><td>{esc(t.get('feature'))}</td>"
                    f"<td>{esc(t.get('trial_days_remaining'))}</td></tr>"
                    for t in trials_l
                ],
                "Trial licenses expiring within 30 days",
            )
        )
    return "".join(parts)


def _alarms_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "alarms")
    by_name = detail.get("active_by_name") or {}
    rows = [
        f"<tr><td>{esc(name)}</td><td>{esc(count)}</td></tr>"
        for name, count in list(by_name.items())[:20]
    ]
    parts = [_table(["Alarm", "Active count"], rows, "Active alarms by name")]
    for key, title in (
        ("critical_sample", "Critical alarms"),
        ("warning_sample", "Warning alarm samples"),
    ):
        srows = []
        for a in detail.get(key) or []:
            if not isinstance(a, dict):
                continue
            srows.append(
                "<tr>"
                f"<td>{esc(a.get('name'))}</td>"
                f"<td>{esc(a.get('severity'))}</td>"
                f"<td>{esc(a.get('description'))}</td></tr>"
            )
        parts.append(_table(["Name", "Severity", "Description"], srows, title))
    return "".join(parts)


def _orphaned_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "orphaned_resources")
    sample = detail.get("accounts_sample") or detail.get("sample") or []
    rows = []
    for a in sample[:40]:
        if isinstance(a, dict):
            rows.append(
                "<tr>"
                f"<td>{esc(a.get('name') or a.get('id') or a.get('account'))}</td>"
                f"<td>{esc(a.get('type') or a.get('kind'))}</td>"
                f"<td>{esc(a.get('domain'))}</td></tr>"
            )
        else:
            rows.append(f"<tr><td>{esc(a)}</td><td></td><td></td></tr>")
    total = detail.get("total_orphaned_keys_count")
    head = ""
    if total is not None:
        head = (
            f"<div class='card'><h3>Orphaned resources</h3>"
            f"<p>Orphaned keys count: <strong>{esc(total)}</strong></p></div>"
        )
    return head + _table(["Name", "Type", "Domain"], rows, "Orphaned sample")


def _audit_samples_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "audit_records")
    sample = detail.get("sample") or detail.get("server_sample") or []
    rows = []
    for e in sample[:25]:
        if not isinstance(e, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(e.get('timestamp') or e.get('time') or e.get('createdAt'))}</td>"
            f"<td>{esc(e.get('severity') or e.get('level'))}</td>"
            f"<td>{esc(e.get('message') or e.get('msg') or e.get('event'))}</td></tr>"
        )
    return _table(["Time", "Severity", "Message"], rows, "Audit event samples")


def _quorum_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "quorum_policies")
    ops = detail.get("enabled_operations") or detail.get("operations") or []
    rows = []
    for op in ops[:40]:
        if isinstance(op, dict):
            rows.append(
                f"<tr><td>{esc(op.get('name') or op.get('operation'))}</td>"
                f"<td>{esc(op.get('policy') or op.get('id'))}</td></tr>"
            )
        else:
            rows.append(f"<tr><td>{esc(op)}</td><td></td></tr>")
    parts = [_table(["Operation", "Policy"], rows, "Enabled quorum operations")]
    by_state = detail.get("requests_by_state") or {}
    if isinstance(by_state, dict) and by_state:
        parts.append(
            _table(
                ["State", "Count"],
                [
                    f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
                    for k, v in list(by_state.items())[:20]
                ],
                "Quorum requests by state",
            )
        )
    return "".join(parts)


def _clients_table(sections: list[dict]) -> str:
    detail = _sec_detail(sections, "registered_clients")
    sample = detail.get("sample") or detail.get("resources") or []
    rows = []
    for c in sample[:40]:
        if not isinstance(c, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{esc(c.get('name'))}</td>"
            f"<td>{esc(c.get('id') or c.get('client_id'))}</td>"
            f"<td>{esc(c.get('state') or c.get('status'))}</td></tr>"
        )
    total = detail.get("total")
    head = (
        f"<div class='card'><h3>Registered clients</h3><p>Total: {esc(total)}</p></div>"
        if total is not None
        else ""
    )
    return head + _table(["Name", "Id", "State"], rows, "Client sample")


def _sections_html(sections: list[dict]) -> str:
    blocks = []
    for s in sections:
        name = s.get("name") or "section"
        result = str(s.get("result") or "")
        status = s.get("status")
        tone = _tab_tone(result)
        body = esc(json.dumps(_redact(s.get("detail")), indent=2, default=str))
        open_attr = " open" if result in ("FAIL", "WARN") else ""
        blocks.append(
            f"<details class='section'{open_attr}>"
            f"<summary><span class='st {esc(tone)}'>{esc(result or 'n/a')}</span> "
            f"{esc(name)} · HTTP {esc(status)}</summary>"
            f"<div class='sec-body'><pre>{body}</pre></div></details>"
        )
    return "\n".join(blocks)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)):
                out[k] = "[redacted]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(x) for x in value]
    return value


def _doughnut(slug: str, title: str, caption: str, pairs: list[tuple[str, Any, str]], center_sub: str) -> dict | None:
    labels, values, colors = [], [], []
    for label, val, color in pairs:
        n = _n(val)
        if n <= 0:
            continue
        labels.append(f"{label}  {n}")
        values.append(n)
        colors.append(color)
    if not values:
        return None
    return {
        "id": f"ch-{slug}",
        "type": "doughnut",
        "title": title,
        "caption": caption,
        "labels": labels,
        "values": values,
        "colors": colors,
        "center": sum(values),
        "centerSub": center_sub,
    }


def _barh(
    slug: str,
    title: str,
    caption: str,
    labels: list[str],
    values: list[int],
    color: str,
    colors: list[str] | None = None,
) -> dict | None:
    kept: list[tuple[str, int, str]] = []
    for i, (label, val) in enumerate(zip(labels, values)):
        n = _n(val)
        if n <= 0:
            continue
        col = colors[i] if colors and i < len(colors) else color
        kept.append((str(label), n, col))
    if not kept:
        return None
    return {
        "id": f"ch-{slug}",
        "type": "bar",
        "title": title,
        "caption": caption,
        "labels": [p[0] for p in kept],
        "values": [p[1] for p in kept],
        "colors": [p[2] for p in kept],
        "height": max(180, 44 * len(kept) + 28),
    }


def _tab_charts(report: dict, table: list[dict]) -> dict[str, list[dict]]:
    summary = report.get("summary") or {}
    posture = report.get("posture") or {}
    app = posture.get("appliance") or {}
    alarms = posture.get("alarms") or {}
    net = posture.get("network") or {}
    certs = posture.get("certificates") or {}
    keys = posture.get("keys") or {}
    users = (posture.get("users") or {}).get("totals") or {}
    cte = posture.get("cte") or {}
    audit = posture.get("audit") or {}
    lic = posture.get("licensing") or {}
    backups = posture.get("backups") or {}
    sev = alarms.get("active_by_severity") or {}
    deks = (keys.get("metrics") or {}).get("deks_by_state") or {}
    kd = keys.get("domains") or {}
    loc = certs.get("local") or {}
    ext = certs.get("external") or {}
    tru = certs.get("trusted") or {}
    sc = audit.get("server_counts") or {}
    cc = audit.get("client_counts") or {}

    by_name = {}
    for s in report.get("sections") or []:
        if isinstance(s, dict) and s.get("name") == "alarms":
            by_name = (s.get("detail") or {}).get("active_by_name") or {}
            break

    cte_total = _n(cte.get("clients_total"))
    cte_disc = _n(cte.get("disconnected"))
    cte_unreg = _n(cte.get("unregistered_or_offline"))
    cte_ok = max(cte_total - cte_disc - cte_unreg, 0)

    rot_labels, rot_vals = [], []
    for s in report.get("sections") or []:
        if isinstance(s, dict) and s.get("name") == "rot_keys":
            for k in (s.get("detail") or {}).get("keys") or []:
                if isinstance(k, dict):
                    rot_labels.append(str(k.get("id") or "RoT"))
                    rot_vals.append(_n(round(float(k.get("age_years") or 0))))
            break

    out: dict[str, list[dict]] = {}

    def add(slug: str, cfg: dict | None) -> None:
        if cfg:
            out.setdefault(slug, []).append(cfg)

    add(
        "overview",
        _doughnut(
            "overview-findings",
            "Findings by severity",
            "",
            [
                ("CRITICAL", summary.get("critical"), _PAL["crit"]),
                ("WARNING", summary.get("warning"), _PAL["warn"]),
                ("INFO", summary.get("info"), _PAL["info"]),
            ],
            "findings",
        ),
    )
    area_fail = area_warn = area_pass = 0
    for row in table:
        if not isinstance(row, dict):
            continue
        r = _strip_result_md(row.get("result")).upper()
        if r in ("FAIL", "CRITICAL"):
            area_fail += 1
        elif r in ("WARN", "WARNING"):
            area_warn += 1
        elif r in ("PASS", "OK"):
            area_pass += 1
    add(
        "overview",
        _doughnut(
            "overview-areas",
            "Posture areas by result",
            "",
            [
                ("FAIL", area_fail, _PAL["fail"]),
                ("WARN", area_warn, _PAL["warn"]),
                ("PASS", area_pass, _PAL["pass"]),
            ],
            "areas",
        ),
    )
    add(
        _slug("Appliance"),
        _doughnut(
            "appliance-svc",
            "Services",
            "",
            [
                ("Started", app.get("services_started"), _PAL["pass"]),
                ("Disabled", app.get("services_disabled"), _PAL["muted"]),
                ("Down", app.get("services_not_started"), _PAL["fail"]),
            ],
            "services",
        ),
    )
    add(
        _slug("RoT"),
        _barh(
            "rot-age",
            "Root-of-trust age (years)",
            "",
            rot_labels,
            rot_vals,
            _PAL["fail"] if any(v >= 1 for v in rot_vals) else _PAL["pass"],
        ),
    )
    trials = _n(lic.get("trials_expiring_soon"))
    expired = _n(lic.get("expired"))
    active = _n(lic.get("active"))
    add(
        _slug("Licenses"),
        _doughnut(
            "licenses",
            "Active licenses",
            "",
            [
                ("OK", max(active - trials - expired, 0), _PAL["pass"]),
                ("Trial ≤30d", trials, _PAL["warn"]),
                ("Expired", expired, _PAL["fail"]),
            ],
            "active",
        ),
    )
    add(
        _slug("Alarms"),
        _doughnut(
            "alarms-sev",
            "Active alarms by severity",
            "",
            [
                ("Critical", alarms.get("critical_active") or sev.get("critical"), _PAL["crit"]),
                ("Error", sev.get("error"), _PAL["fail"]),
                ("Warning", alarms.get("warning_active") or sev.get("warning"), _PAL["warn"]),
                ("Info", alarms.get("info_active") or sev.get("info"), _PAL["info"]),
            ],
            "active",
        ),
    )
    anames = list(by_name.keys())[:8]
    add(
        _slug("Alarms"),
        _barh(
            "alarms-names",
            "Top active alarms",
            "",
            [str(n)[:40] for n in anames],
            [_n(by_name.get(n)) for n in anames],
            _PAL["warn"],
        ),
    )
    add(
        _slug("Interfaces"),
        _doughnut(
            "ifaces-certs",
            "Interface TLS certificates",
            "",
            [
                ("Expired", net.get("tls_certs_expired"), _PAL["fail"]),
                ("≤30 days", net.get("tls_certs_expiring_soon"), _PAL["warn"]),
                ("Valid", net.get("tls_certs_ok"), _PAL["pass"]),
            ],
            "certs",
        ),
    )
    add(
        _slug("CAs"),
        _doughnut(
            "cas",
            "Certificate authorities",
            "",
            [
                (
                    "Expired",
                    _n(loc.get("expired")) + _n(ext.get("expired")) + _n(tru.get("expired")),
                    _PAL["fail"],
                ),
                (
                    "≤30 days",
                    _n(loc.get("expiring_soon"))
                    + _n(ext.get("expiring_soon"))
                    + _n(tru.get("expiring_soon")),
                    _PAL["warn"],
                ),
                (
                    "Valid",
                    _n(loc.get("ok")) + _n(ext.get("ok")) + _n(tru.get("ok")),
                    _PAL["pass"],
                ),
            ],
            "CAs",
        ),
    )
    add(
        _slug("Backups"),
        _doughnut(
            "backups",
            "Backups",
            "",
            [
                ("System", backups.get("system_count"), _PAL["info"]),
                ("Domain-scoped", backups.get("domain_count"), _PAL["pass"]),
            ],
            "backups",
        ),
    )
    add(
        _slug("Users"),
        _barh(
            "users",
            "Users",
            "",
            ["Locked", "Never logged in", "Inactive >30d", "Failed logins"],
            [
                _n(users.get("locked")),
                _n(users.get("never_logged_in")),
                _n(users.get("inactive_30d")),
                _n(users.get("failed_logins_not_locked")),
            ],
            _PAL["warn"],
            colors=[_PAL["fail"], _PAL["warn"], _PAL["warn"], _PAL["info"]],
        ),
    )
    dek_pairs = [(str(k), v, None) for k, v in deks.items()]
    dek_colors = {
        "Active": _PAL["pass"],
        "Pre-Active": _PAL["info"],
        "Deactivated": _PAL["warn"],
        "Destroyed": _PAL["muted"],
        "Compromised": _PAL["fail"],
    }
    add(
        _slug("Keys"),
        _doughnut(
            "deks",
            "DEKs by state",
            "",
            [(k, v, dek_colors.get(k, _PAL["muted"])) for k, v, _ in dek_pairs],
            "DEKs",
        ),
    )
    krows = [d for d in (kd.get("by_domain") or []) if isinstance(d, dict)]
    add(
        _slug("Keys"),
        _barh(
            "keys-totals",
            "Keys by domain",
            "",
            [str(d.get("domain") or "") for d in krows],
            [_n(d.get("total")) for d in krows],
            _PAL["info"],
        ),
    )
    issue_labels: list[str] = []
    issue_vals: list[int] = []
    issue_cols: list[str] = []
    for d in krows:
        name = str(d.get("domain") or "")
        weak_n = _n(d.get("weak"))
        ina_n = _n(d.get("non_active"))
        if weak_n:
            issue_labels.append(f"{name} — weak")
            issue_vals.append(weak_n)
            issue_cols.append(_PAL["fail"])
        if ina_n:
            issue_labels.append(f"{name} — inactive")
            issue_vals.append(ina_n)
            issue_cols.append(_PAL["warn"])
    add(
        _slug("Keys"),
        _barh(
            "keys-issues",
            "Weak and inactive keys",
            "",
            issue_labels,
            issue_vals,
            _PAL["fail"],
            colors=issue_cols,
        ),
    )
    add(
        _slug("CTE"),
        _doughnut(
            "cte-clients",
            "CTE client health",
            "",
            [
                ("Healthy / other", cte_ok, _PAL["pass"]),
                ("Disconnected", cte_disc, _PAL["warn"]),
                ("Unregistered / offline", cte_unreg, _PAL["muted"]),
            ],
            "clients",
        ),
    )
    add(
        _slug("Audit"),
        _doughnut(
            "audit-server",
            "Server audit (7 days)",
            "",
            [
                ("Critical / fatal", _n(sc.get("critical")) + _n(sc.get("fatal")), _PAL["crit"]),
                ("Error", sc.get("error"), _PAL["warn"]),
            ],
            "server",
        ),
    )
    add(
        _slug("Audit"),
        _doughnut(
            "audit-client",
            "Client audit (7 days)",
            "",
            [
                ("Critical / fatal", _n(cc.get("critical")) + _n(cc.get("fatal")), _PAL["crit"]),
                ("Error", cc.get("error"), _PAL["warn"]),
            ],
            "client",
        ),
    )
    return out


_CSS = """
:root {
  --bg: #f4f5f7;
  --card: #fff;
  --ink: #1a1d23;
  --muted: #5c6570;
  --line: #d8dde3;
  --ok: #1b7f4e;
  --ok-bg: #e6f6ee;
  --warn: #9a6b00;
  --warn-bg: #fff4d6;
  --fail: #b42318;
  --fail-bg: #fdecea;
  --info: #175cd3;
  --info-bg: #eff4ff;
  --head: #0f2744;
}
* { box-sizing: border-box; }
body {
  margin: 0; font-family: Segoe UI, system-ui, sans-serif;
  color: var(--ink); background: var(--bg); line-height: 1.45;
}
header { background: var(--head); color: #fff; padding: 22px 32px 18px; }
header h1 { margin: 0; font-size: 22px; font-weight: 650; }
header .meta { color: #c5d0dc; font-size: 13px; margin: 8px 0 0; }
.head-top { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.badge {
  display: inline-block; padding: 4px 10px; border-radius: 4px;
  font-weight: 700; letter-spacing: .04em; font-size: 13px;
}
.badge.OK, .badge.PASS { background: var(--ok); color: #fff; }
.badge.DEGRADED, .badge.WARN { background: #c47d00; color: #fff; }
.badge.CRITICAL, .badge.FAIL, .badge.UNREACHABLE { background: var(--fail); color: #fff; }
.badge.JSON { background: #3d4f66; color: #fff; }
.wrap { max-width: 1240px; margin: 0 auto; padding: 20px 24px 64px; }
.layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 32px; align-items: start; }
.tab-bar {
  position: sticky; top: 12px;
  display: flex; flex-direction: column; gap: 0;
  background: transparent; padding: 0; border: none;
}
.nav-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); margin: 16px 0 4px; padding: 0 8px;
}
.nav-label:first-child { margin-top: 0; }
.tab-btn {
  display: flex; justify-content: space-between; align-items: baseline; gap: 10px;
  width: 100%; padding: 7px 8px; border: none; border-bottom: 1px solid transparent;
  border-radius: 0; background: transparent; cursor: pointer;
  min-width: 0; font: inherit; text-align: left; color: var(--ink);
}
.tab-btn:hover .name { color: var(--head); }
.tab-btn.active { box-shadow: none; border-bottom-color: var(--ink); }
.tab-btn.active .name { font-weight: 700; }
.tab-btn .name { font-weight: 500; font-size: 13px; color: var(--ink); }
.st { font-size: 11px; font-weight: 700; letter-spacing: .04em; white-space: nowrap; }
.st.FAIL, .tab-btn.FAIL .st { color: var(--fail); }
.st.WARN, .tab-btn.WARN .st { color: var(--warn); }
.st.PASS, .tab-btn.PASS .st { color: var(--ok); }
.st.MUTED, .tab-btn.MUTED .st { color: var(--muted); }
.tab-btn.FAIL, .tab-btn.WARN, .tab-btn.PASS, .tab-btn.MUTED { background: transparent; }
.tab-panel { padding-top: 0; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 0 0 18px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
.kpi .n { font-size: 26px; font-weight: 700; }
.kpi .l { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
.kpi.crit .n { color: var(--fail); }
.kpi.warn .n { color: var(--warn); }
.kpi.info .n { color: var(--info); }
h2 { font-size: 18px; margin: 8px 0 10px; }
h3 { font-size: 14px; margin: 0 0 8px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin: 0 0 16px; }
.chart-box { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px 10px; }
.chart-box h3 { margin: 0 0 2px; font-size: 14px; }
.caption, .chart-box .caption { color: var(--muted); font-size: 12px; margin: 0 0 8px; }
.chart-frame { position: relative; height: 220px; }
.panel-head { border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin-bottom: 14px; background: var(--card); }
.head-row { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.head-row h2 { margin: 0; }
.head-row .st { font-size: 13px; }
.summary { margin-top: 8px; font-size: 14px; }
.summary strong.fail { color: var(--fail); font-weight: 700; }
.summary strong.warn { color: var(--warn); font-weight: 700; }
.status-pills { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 8px; }
.pill { font-size: 12px; font-weight: 700; padding: 0; background: none; border: none; }
.pill.crit { color: var(--fail); }
.pill.warn { color: var(--warn); }
.pill.info { color: var(--info); }
.area-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0 28px; margin-bottom: 16px; }
.area-card {
  display: flex; flex-direction: row; justify-content: space-between; align-items: baseline;
  gap: 12px; text-align: left; padding: 9px 0;
  border: none; border-bottom: 1px solid var(--line); border-radius: 0;
  background: transparent; cursor: pointer; font: inherit; color: inherit;
}
.area-card.FAIL, .area-card.WARN, .area-card.PASS { background: transparent; }
.area-card .area-name { font-weight: 500; font-size: 13px; }
.area-card .sub { font-size: 11px; color: var(--muted); margin-left: auto; padding-right: 8px; }
.meter-wrap { display: flex; align-items: center; gap: 10px; min-width: 140px; }
.meter { flex: 1; height: 12px; background: #eef1f5; border-radius: 4px; overflow: hidden; }
.meter-fill { display: block; height: 100%; background: #175cd3; border-radius: 4px; }
.meter-n { font-weight: 700; font-size: 13px; min-width: 3.2em; text-align: right; }
.badge-n {
  display: inline-block; font-weight: 700; padding: 2px 8px; border-radius: 999px; font-size: 12px;
}
.badge-n.fail { background: var(--fail-bg); color: var(--fail); }
.badge-n.warn { background: var(--warn-bg); color: var(--warn); }
.badge-n.ok { background: var(--ok-bg); color: var(--ok); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { background: #eef1f5; font-weight: 600; }
.findings { margin: 0; padding-left: 18px; }
.findings li { margin: 0 0 12px; }
.findings .area { color: var(--muted); font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
.finding-head { margin-bottom: 2px; }
.finding-code { font-size: 12px; color: var(--muted); }
.finding-count { font-size: 12px; color: var(--muted); }
.finding-fix { font-size: 13px; margin: 2px 0 4px; }
.finding-msg { font-size: 12px; color: var(--muted); }
.finding-detail { margin-top: 4px; font-size: 12px; color: var(--muted); }
.finding-detail ul { margin: 4px 0 0 1.1rem; padding: 0; }
.crit-list { background: var(--fail-bg); border-left: 4px solid var(--fail); }
.warn-list { background: var(--warn-bg); border-left: 4px solid var(--warn); }
.info-list { background: var(--info-bg); border-left: 4px solid var(--info); }
.caveat { font-size: 13px; color: var(--muted); margin: 8px 0 0; }
details.section, details.info-fold, details.raw-fold {
  border: 1px solid var(--line); border-radius: 6px; margin: 6px 0; background: var(--card);
}
details > summary { cursor: pointer; padding: 8px 12px; font-weight: 600; font-size: 13px; }
details[open] > summary { border-bottom: 1px solid var(--line); }
.sec-body { padding: 10px 12px; overflow-x: auto; }
.sec-body pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-size: 12px; font-family: ui-monospace, Consolas, monospace;
}
footer { color: var(--muted); font-size: 12px; margin-top: 28px; }
@media (max-width: 800px) {
  .layout { grid-template-columns: 1fr; }
  .tab-bar { position: static; flex-direction: row; flex-wrap: wrap; gap: 4px 12px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
  .nav-label { width: 100%; margin: 10px 0 0; }
}
@media print {
  header, .badge, .st { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .layout { grid-template-columns: 1fr; }
  .tab-bar { display: none; }
  .tab-panel { display: block !important; break-after: page; }
  .chart-box { break-inside: avoid; }
}
"""

_JS = """
const PAL = { crit: '#b42318', warn: '#c47d00', info: '#175cd3', pass: '#1b7f4e', muted: '#8b949e' };
const centerText = {
  id: 'centerText',
  afterDraw(chart, _args, opts) {
    if (chart.config.type !== 'doughnut' || !opts || opts.text == null) return;
    const {ctx, chartArea} = chart;
    const x = (chartArea.left + chartArea.right) / 2;
    const y = (chartArea.top + chartArea.bottom) / 2;
    ctx.save();
    ctx.fillStyle = '#1a1d23';
    ctx.font = '700 22px Segoe UI, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(opts.text), x, y - 8);
    ctx.fillStyle = '#5c6570';
    ctx.font = '12px Segoe UI, system-ui, sans-serif';
    ctx.fillText(String(opts.sub || ''), x, y + 14);
    ctx.restore();
  }
};
const barValues = {
  id: 'barValues',
  afterDatasetsDraw(chart) {
    if (chart.config.type !== 'bar') return;
    const {ctx} = chart;
    const meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.fillStyle = '#1a1d23';
    ctx.font = '600 12px Segoe UI, system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    meta.data.forEach((bar, i) => {
      const v = chart.data.datasets[0].data[i];
      if (v == null) return;
      ctx.fillText(String(v), bar.x + 8, bar.y);
    });
    ctx.restore();
  }
};
Chart.register(centerText, barValues);

function makeChart(cfg) {
  const canvas = document.getElementById(cfg.id);
  if (!canvas) return;
  const values = cfg.values || [];
  if (!values.length || values.every(v => !v)) {
    const box = document.getElementById('box-' + cfg.id);
    if (box) box.style.display = 'none';
    return;
  }
  const colors = cfg.colors && cfg.colors.length ? cfg.colors : [PAL.warn];
  if (cfg.type === 'doughnut') {
    new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: cfg.labels,
        datasets: [{ data: values, backgroundColor: colors, borderWidth: 0, hoverOffset: 6 }]
      },
      options: {
        cutout: '64%',
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'right', labels: { boxWidth: 12, padding: 12, font: { size: 12 } } },
          tooltip: { callbacks: { label: (c) => ' ' + c.label } },
          centerText: { text: cfg.center, sub: cfg.centerSub || '' }
        }
      }
    });
    return;
  }
  const barColors = colors.length === values.length ? colors : (colors[0] || PAL.warn);
  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: cfg.labels,
      datasets: [{
        data: values,
        backgroundColor: barColors,
        borderRadius: 4,
        barPercentage: 0.7,
        categoryPercentage: 0.7,
        maxBarThickness: 36
      }]
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => ' ' + c.raw } },
        barValues: { enabled: true }
      },
      layout: { padding: { right: 36 } },
      scales: {
        x: {
          stacked: false,
          beginAtZero: true,
          grace: '12%',
          ticks: { precision: 0, maxTicksLimit: 6 },
          grid: { color: '#eef1f5' }
        },
        y: { stacked: false, grid: { display: false }, ticks: { font: { size: 13 } } }
      }
    }
  });
}

const rendered = {};
function renderTabCharts(slug) {
  if (rendered[slug]) return;
  rendered[slug] = true;
  (DATA[slug] || []).forEach(makeChart);
}

function showTab(slug) {
  const known = document.getElementById('panel-' + slug);
  if (!known) slug = 'overview';
  document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = true; });
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === slug);
    b.setAttribute('aria-selected', b.dataset.tab === slug ? 'true' : 'false');
  });
  const panel = document.getElementById('panel-' + slug);
  if (panel) panel.hidden = false;
  const btn = document.getElementById('tab-' + slug);
  if (btn) btn.scrollIntoView({ inline: 'nearest', block: 'nearest' });
  renderTabCharts(slug);
  if (location.hash.replace('#','') !== slug) {
    history.replaceState(null, '', '#' + slug);
  }
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => showTab(btn.dataset.tab));
});
document.querySelectorAll('.area-card').forEach(btn => {
  btn.addEventListener('click', () => showTab(btn.dataset.jump));
});
window.addEventListener('hashchange', () => showTab(location.hash.replace('#','')));
window.addEventListener('beforeprint', () => {
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.hidden = false;
    renderTabCharts(p.id.replace('panel-', ''));
  });
});
showTab((location.hash || '#overview').replace('#',''));
"""
