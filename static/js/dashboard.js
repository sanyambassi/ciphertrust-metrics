import { TAB_CHIP_KEY, RANGE_KEY, RANGE_OPTIONS, getDashboardGroups } from "./config.js";
import { state, getDom } from "./state.js";
import {
  escapeHtml,
  fmt,
  displayUnit,
  yTickCallback,
  truncateLabel,
  formatSeriesTooltip,
  tooltipTitle,
  tsLabel,
  panelSignature,
  isBytesUnit,
  isBytesRateUnit,
  fmtBytes,
} from "./format.js?v=20260723voff1";
import { chartColors, cssVar } from "./theme.js";
import { fetchJSON, refreshStatus } from "./api.js";
import {
  loadAppliances,
  renderApplianceTree,
  renderApplianceList,
  openModal,
  renderFleetHealth,
} from "./appliances.js?v=20260722v120";

function chartXBounds() {
  const secs = RANGE_OPTIONS.find((r) => r.id === state.rangeId)?.seconds || 86400;
  const max = Date.now();
  return { min: max - secs * 1000, max };
}
export function groupForDashboard(dashboardId) {
  const groups = getDashboardGroups();
  for (const g of groups) {
    if ((g.dashboards || []).some((d) => d.id === dashboardId)) return g.id;
  }
  return groups[0]?.id || "overview";
}

export function dashboardsForGroup(groupId) {
  const g = getDashboardGroups().find((x) => x.id === groupId);
  return g?.dashboards || [];
}

export function persistTabChip(groupId, dashboardId) {
  state.tabChips[groupId] = dashboardId;
  try { localStorage.setItem(TAB_CHIP_KEY, JSON.stringify(state.tabChips)); } catch (_) { /* ignore */ }
}

export function syncRangePicker() {
  document.querySelectorAll(".range-picker").forEach((picker) => {
    picker.querySelectorAll("[data-range]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.range === state.rangeId);
    });
  });
}

export function setTimeRange(rangeId, { reload = true } = {}) {
  if (!RANGE_OPTIONS.some((r) => r.id === rangeId)) return;
  if (rangeId === state.rangeId && !reload) {
    syncRangePicker();
    return;
  }
  state.rangeId = rangeId;
  try { localStorage.setItem(RANGE_KEY, rangeId); } catch (_) { /* ignore */ }
  syncRangePicker();
  state.panelMeta = null;
  if (reload && state.viewMode === "dashboard") {
    loadDashboard(state.dashboardId, { forceFull: true });
  }
  if (reload && state.viewMode === "appliances") {
    renderApplianceTree();
  }
}

export function defaultChipForGroup(groupId) {
  const chips = dashboardsForGroup(groupId);
  if (!chips.length) return "overview";
  const saved = state.tabChips[groupId];
  if (saved && chips.some((c) => c.id === saved)) return saved;
  return chips[0].id;
}

export function destroyCharts() {
  state.charts.forEach((c) => {
    try {
      c.chart.destroy();
    } catch (_) {
      /* already destroyed */
    }
  });
  state.charts = [];
}

function safeChartUpdate(chart) {
  if (!chart || chart.destroyed) return;
  try {
    chart.update("none");
  } catch (_) {
    /* ignore mid-destroy races */
  }
}

export function renderPrimaryTabs() {
  const { primaryTabs } = getDom();
  if (!primaryTabs) return;
  primaryTabs.querySelectorAll(".primary-tab").forEach((btn) => {
    let active = false;
    if (state.viewMode === "appliances") {
      active = btn.dataset.group === "appliances";
    } else if (state.viewMode === "healthcheck") {
      active = btn.dataset.group === "healthcheck";
    } else {
      active = btn.dataset.group === state.groupId;
    }
    btn.classList.toggle("active", active);
  });
}

export function renderSecondaryChips() {
  const { secondaryChips } = getDom();
  if (!secondaryChips) return;
  if (state.viewMode === "appliances" || state.viewMode === "healthcheck") {
    secondaryChips.innerHTML = "";
    return;
  }
  const chips = dashboardsForGroup(state.groupId);
  if (chips.length <= 1) {
    secondaryChips.innerHTML = "";
    return;
  }
  secondaryChips.innerHTML = chips
    .map((d) => {
      const active = d.id === state.dashboardId ? " active" : "";
      return `<button type="button" class="secondary-chip${active}" data-id="${d.id}" title="${escapeHtml(d.description || d.title)}">${escapeHtml(d.title)}</button>`;
    })
    .join("");
}

export function syncWorkspaceChrome() {
  const { secondaryRow, appliancesView, panelsEl, fleetMap, healthcheckView } = getDom();
  const appliancesMode = state.viewMode === "appliances";
  const healthcheckMode = state.viewMode === "healthcheck";
  if (secondaryRow) secondaryRow.classList.toggle("is-hidden", appliancesMode || healthcheckMode);
  if (appliancesView) appliancesView.hidden = !appliancesMode;
  if (panelsEl) panelsEl.hidden = appliancesMode || healthcheckMode;
  if (healthcheckView) {
    if (healthcheckMode) {
      healthcheckView.hidden = false;
    } else {
      // display:flex on .healthcheck-view overrides [hidden] unless we force-hide;
      // also tear down iframe/content so it cannot paint over other tabs.
      const iframe = healthcheckView.querySelector("#hc-iframe");
      if (iframe) iframe.src = "about:blank";
      if (healthcheckView.innerHTML) healthcheckView.innerHTML = "";
      healthcheckView.hidden = true;
    }
  }
  if (appliancesMode) {
    renderApplianceTree();
  } else {
    if (!healthcheckMode) {
      state.groupId = groupForDashboard(state.dashboardId);
    }
    if (fleetMap) fleetMap.hidden = true;
  }
  renderPrimaryTabs();
  renderSecondaryChips();
  syncRangePicker();
}

export function syncTabChrome() {
  if (state.viewMode === "appliances" || state.viewMode === "healthcheck") {
    syncWorkspaceChrome();
    return;
  }
  state.groupId = groupForDashboard(state.dashboardId);
  renderPrimaryTabs();
  renderSecondaryChips();
  syncRangePicker();
}

export function showDashboardGroup(groupId) {
  state.viewMode = "dashboard";
  state.groupId = groupId;
  const nextId = defaultChipForGroup(groupId);
  persistTabChip(groupId, nextId);
  state.panelMeta = null;
  syncWorkspaceChrome();
  loadDashboard(nextId, { forceFull: true });
}

function panelSpanClass(panel) {
  const span = Number(panel.span);
  if (Number.isFinite(span) && span >= 1 && span <= 12) return `span-${span}`;
  if (panel.wide || panel.type === "table" || panel.type === "crdp_clients") return "span-12";
  if (panel.type === "stat") return "span-3";
  if (panel.type === "timeseries" || panel.type === "bar") return "span-6";
  return "span-12";
}

function panelHeadHtml(panel) {
  const linkId = (panel.link_dashboard || "").trim();
  const link = linkId
    ? `<button type="button" class="panel-dash-link" data-dashboard="${escapeHtml(linkId)}">${escapeHtml(
        panel.link_label || "View dashboard"
      )}</button>`
    : "";
  return `<div class="panel-head"><h3 class="panel-title">${escapeHtml(panel.title)}</h3>${link}</div>`;
}

/** Jump from an overview widget to its attached board (group tab + chip). */
export async function openAttachedDashboard(dashboardId) {
  const id = String(dashboardId || "").trim();
  if (!id) return;
  const groupId = groupForDashboard(id);
  state.viewMode = "dashboard";
  persistTabChip(groupId, id);
  state.groupId = groupId;
  state.dashboardId = id;
  state.panelMeta = null;
  renderApplianceList(true);
  syncWorkspaceChrome();
  await loadDashboard(id, { forceFull: true });
}

function bindPanelDashLinks(root) {
  root?.querySelectorAll(".panel-dash-link").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openAttachedDashboard(btn.getAttribute("data-dashboard"));
    });
  });
}

function renderStat(panel, animate) {
  const el = document.createElement("article");
  const isText = typeof panel.value === "string";
  const tone = String(panel.tone || "").toLowerCase();
  const toneClass =
    tone === "fail" || tone === "warning" || tone === "pass" || tone === "info"
      ? ` tone-${tone}`
      : "";
  el.className = `panel stat${isText ? " text" : ""}${toneClass} ${panelSpanClass(panel)}${
    animate ? " enter" : ""
  }`;
  el.dataset.panelTitle = panel.title;
  el.dataset.panelType = "stat";
  if (toneClass) el.dataset.tone = tone;
  const unitText = isText ? "" : displayUnit(panel.unit, panel.value);
  el.innerHTML = `
    ${panelHeadHtml(panel)}
    <div class="stat-value"><span class="stat-num">${escapeHtml(fmt(panel.value, panel.unit))}</span>${
      unitText ? `<span class="stat-unit">${escapeHtml(unitText)}</span>` : ""
    }</div>
    ${panel.description ? `<div class="stat-desc">${escapeHtml(panel.description)}</div>` : ""}
  `;
  return el;
}

function renderNote(panel, animate) {
  const el = document.createElement("aside");
  const tone = String(panel.tone || "").toLowerCase();
  const toneClass = tone === "fail" || tone === "warning" || tone === "pass" || tone === "info"
    ? ` note-${tone}`
    : "";
  el.className = `panel note span-12${toneClass}${animate ? " enter" : ""}`;
  el.dataset.panelType = "note";
  el.dataset.panelTitle = panel.title || "note";
  const title = panel.title
    ? `<strong class="note-title">${escapeHtml(panel.title)}</strong>`
    : "";
  el.innerHTML = `${title}<span class="note-text">${escapeHtml(panel.text || "")}</span>`;
  return el;
}

function makeLineChart(canvas, panel) {
  const COLORS = chartColors();
  const grid = cssVar("--chart-grid", "#1c2740");
  const unit = panel.unit || "";
  const xBounds = chartXBounds();
  // Truncate labels up-front. Do NOT override legend.generateLabels by calling
  // Chart.defaults...generateLabels — in Chart.js 4 that recurses forever.
  const datasets = (panel.series || []).map((s, i) => ({
    label: truncateLabel(s.name, 36),
    fullLabel: String(s.name || ""),
    data: (s.points || []).map((p) => ({ x: p.t * 1000, y: p.v })),
    borderColor: COLORS[i % COLORS.length],
    backgroundColor: COLORS[i % COLORS.length] + "33",
    borderWidth: 1.5,
    pointRadius: 0,
    tension: 0.25,
  }));
  const hideYTitle =
    !unit ||
    isBytesUnit(unit) ||
    isBytesRateUnit(unit) ||
    unit === "%" ||
    unit === "unix" ||
    unit === "datetime" ||
    unit === "duration" ||
    unit === "uptime";
  return new Chart(canvas, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      layout: { padding: { top: 4, right: 8, bottom: 0, left: 0 } },
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: {
          display: datasets.length > 1 && datasets.length <= 8,
          position: "bottom",
          align: "start",
          labels: {
            boxWidth: 10,
            boxHeight: 10,
            padding: 12,
            font: { size: 10 },
          },
          onHover: (evt, legendItem, legend) => {
            const ds = legend?.chart?.data?.datasets?.[legendItem.datasetIndex];
            const tip = ds?.fullLabel || ds?.label || "";
            const el = evt?.native?.target;
            if (el && tip) el.title = tip;
          },
          onLeave: (evt) => {
            const el = evt?.native?.target;
            if (el) el.title = "";
          },
        },
        tooltip: {
          displayColors: true,
          callbacks: {
            title: tooltipTitle,
            label: (ctx) => formatSeriesTooltip(unit, ctx),
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: xBounds.min,
          max: xBounds.max,
          ticks: {
            color: cssVar("--muted", "#8b9bb8"),
            callback: (v) => tsLabel(v / 1000, state.rangeId),
            autoSkip: true,
            autoSkipPadding: 12,
            maxTicksLimit: state.rangeId === "30d" ? 10 : state.rangeId === "7d" ? 7 : 8,
            maxRotation: 0,
            minRotation: 0,
            padding: 6,
          },
          grid: { color: grid, drawBorder: false },
          border: { display: false },
        },
        y: {
          grace: "5%",
          grid: { color: grid, drawBorder: false },
          border: { display: false },
          title: hideYTitle
            ? undefined
            : { display: true, text: unit, color: cssVar("--muted", "#8b9bb8"), font: { size: 10 } },
          ticks: {
            padding: 8,
            maxTicksLimit: 6,
            callback: yTickCallback(unit) || (
              unit === "%"
                ? (v) => `${Number(v).toFixed(0)}%`
                : undefined
            ),
          },
        },
      },
    },
  });
}

function makeBarChart(canvas, panel) {
  const COLORS = chartColors();
  const grid = cssVar("--chart-grid", "#1c2740");
  const items = panel.items || [];
  const many = items.length > 8;
  const crowded = items.length > 14;
  // Keep axis labels readable; full name still available in tooltip.
  const axisMax = crowded ? 14 : many ? 20 : 28;
  const fullLabels = items.map((i) => String(i.label || ""));
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: fullLabels.map((l) => truncateLabel(l, axisMax)),
      datasets: [{
        data: items.map((i) => i.value),
        backgroundColor: items.map((_, i) => COLORS[i % COLORS.length] + "cc"),
        borderColor: items.map((_, i) => COLORS[i % COLORS.length]),
        borderWidth: 1,
        borderRadius: 4,
        maxBarThickness: crowded ? 22 : many ? 32 : 48,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      // Extra bottom room so rotated category labels are not clipped.
      layout: { padding: { top: 4, right: 8, bottom: many ? 8 : 4, left: 4 } },
      // Show tooltip for the category under the cursor even when the bar is tiny
      // (hover anywhere in that vertical column, not only on the bar pixels).
      interaction: { mode: "index", intersect: false, axis: "x" },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (tipItems) => {
              const idx = tipItems[0]?.dataIndex;
              return idx != null ? (fullLabels[idx] || "") : "";
            },
            label: (ctx) => {
              const raw = ctx.parsed.y;
              if (isBytesUnit(panel.unit)) return fmtBytes(raw, false);
              if (isBytesRateUnit(panel.unit)) return fmtBytes(raw, true);
              const unit = panel.unit ? ` ${panel.unit}` : "";
              return `${fmt(raw, panel.unit)}${isBytesUnit(panel.unit) || isBytesRateUnit(panel.unit) ? "" : unit}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false, drawBorder: false },
          border: { display: false },
          ticks: {
            color: cssVar("--muted", "#8b9bb8"),
            // autoSkip was dropping most/all domain labels when rotated text
            // did not fit the fixed chart height — always show every category.
            autoSkip: false,
            maxRotation: many ? 60 : 45,
            minRotation: many ? 45 : 25,
            font: { size: crowded ? 9 : 10 },
            padding: 4,
          },
        },
        y: {
          beginAtZero: true,
          grace: "5%",
          grid: { color: grid, drawBorder: false },
          border: { display: false },
          ticks: {
            padding: 8,
            maxTicksLimit: 6,
            callback: yTickCallback(panel.unit),
          },
        },
      },
    },
  });
}

function renderTimeseries(panel, animate) {
  const el = document.createElement("article");
  el.className = `panel chart ${panelSpanClass(panel)}${panel.wide ? " wide" : ""}${animate ? " enter" : ""}`;
  el.dataset.panelTitle = panel.title;
  el.dataset.panelType = "timeseries";
  el.innerHTML = `
    ${panelHeadHtml(panel)}
    <div class="chart-wrap"><canvas></canvas></div>
  `;
  const chart = makeLineChart(el.querySelector("canvas"), panel);
  state.charts.push({ chart, type: "timeseries", title: panel.title });
  return el;
}

function renderBar(panel, animate) {
  const el = document.createElement("article");
  el.className = `panel chart ${panelSpanClass(panel)}${panel.wide ? " wide" : ""}${animate ? " enter" : ""}`;
  el.dataset.panelTitle = panel.title;
  el.dataset.panelType = "bar";
  el.innerHTML = `
    ${panelHeadHtml(panel)}
    <div class="chart-wrap"><canvas></canvas></div>
  `;
  const chart = makeBarChart(el.querySelector("canvas"), panel);
  state.charts.push({ chart, type: "bar", title: panel.title });
  return el;
}

function renderTable(panel, animate) {
  const el = document.createElement("article");
  el.className = `panel table wide ${panelSpanClass(panel)}${animate ? " enter" : ""}`;
  el.dataset.panelTitle = panel.title;
  el.dataset.panelType = "table";
  const cols = panel.columns || [];
  const rows = panel.rows || [];
  el.innerHTML = `
    ${panelHeadHtml(panel)}
    <div class="table-wrap">
      <table class="data">
        <thead><tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((r) => `<tr>${cols.map((c) => {
            const cls = c === "metric" || c === "labels" ? "mono" : "";
            return `<td class="${cls}">${escapeHtml(String(r[c] ?? ""))}</td>`;
          }).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
  return el;
}

function renderCrdpClients(panel, animate) {
  const el = document.createElement("article");
  el.className = `panel table crdp-clients wide ${panelSpanClass(panel)}${animate ? " enter" : ""}`;
  el.dataset.panelTitle = panel.title;
  el.dataset.panelType = "crdp_clients";
  const rows = panel.rows || [];
  const revokedCount = Number(panel.revoked_count || 0);
  const desc = panel.description
    ? `<div class="stat-desc">${escapeHtml(panel.description)}</div>`
    : "";
  const clearRevokedBtn =
    revokedCount > 0
      ? `<button type="button" class="btn btn-sm crdp-clear-revoked" title="Delete all revoked rows from local DB">Clear revoked (${revokedCount})</button>`
      : "";
  if (!rows.length) {
    el.innerHTML = `
      <div class="crdp-panel-head">
        <h3 class="panel-title">${escapeHtml(panel.title)}</h3>
        ${clearRevokedBtn}
      </div>
      ${desc}
      <div class="empty">No CRDP clients discovered yet.</div>
    `;
    bindCrdpClientActions(el);
    return el;
  }
  el.innerHTML = `
    <div class="crdp-panel-head">
      <h3 class="panel-title">${escapeHtml(panel.title)}</h3>
      ${clearRevokedBtn}
    </div>
    ${desc}
    <div class="table-wrap">
      <table class="data crdp-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>State</th>
            <th>Connectivity</th>
            <th>Version</th>
            <th>Metrics URL</th>
            <th>Scrape</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${rows
            .map((r) => {
              const id = Number(r.id);
              const active = String(r.state || "") === "active";
              const cmName = String(r.name || r.cm_client_id || "");
              const savedLabel = String(r.display_name || "").trim() || cmName;
              const renamed = Boolean(String(r.display_name || "").trim());
              const savedUrl = String(r.metrics_url || "");
              const urlEmpty = !savedUrl.trim();
              const urlClass = [
                "crdp-url-input",
                active && urlEmpty ? "crdp-url-empty" : "",
              ]
                .filter(Boolean)
                .join(" ");
              const actions = active
                ? `<button type="button" class="btn btn-sm crdp-save" data-id="${id}" disabled>Save</button>
                   <button type="button" class="btn btn-sm crdp-clear-url" data-id="${id}" ${
                     urlEmpty ? "disabled" : ""
                   } title="Clear metrics URL">Clear</button>`
                : `<button type="button" class="btn btn-sm btn-danger crdp-remove" data-id="${id}" title="Delete from local tracking">Remove</button>`;
              const idHint = renamed
                ? `<span class="crdp-cm-id" title="CM client id">${escapeHtml(cmName)}</span>`
                : `<span class="crdp-cm-id is-hidden" title="CM client id">${escapeHtml(cmName)}</span>`;
              return `<tr data-crdp-id="${id}" class="${active ? "" : "crdp-revoked"}">
                <td class="crdp-name-cell">
                  <input type="text" class="crdp-name-input" ${active ? "" : "disabled"}
                    data-cm-name="${escapeHtml(cmName)}"
                    data-saved-name="${escapeHtml(savedLabel)}"
                    value="${escapeHtml(savedLabel)}"
                    placeholder="Friendly name" />
                  ${idHint}
                </td>
                <td>${escapeHtml(String(r.state || ""))}</td>
                <td>${escapeHtml(String(r.connectivity || ""))}</td>
                <td class="mono">${escapeHtml(String(r.version || ""))}</td>
                <td>
                  <input type="text" class="${urlClass}" ${active ? "" : "disabled"}
                    data-saved-url="${escapeHtml(savedUrl)}"
                    value="${escapeHtml(savedUrl)}"
                    placeholder="http://host:8080 or https://host"
                    aria-invalid="${active && urlEmpty ? "true" : "false"}" />
                </td>
                <td class="mono">${escapeHtml(String(r.scrape || ""))}${
                  r.error ? `<div class="crdp-err">${escapeHtml(String(r.error))}</div>` : ""
                }</td>
                <td class="crdp-actions">${actions}</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    </div>
  `;
  el.querySelectorAll("tr[data-crdp-id]").forEach((tr) => {
    syncCrdpUrlRow(tr);
    tr.querySelectorAll(".crdp-url-input, .crdp-name-input").forEach((input) => {
      input.addEventListener("input", () => syncCrdpUrlRow(tr));
      input.addEventListener("change", () => syncCrdpUrlRow(tr));
    });
  });
  bindCrdpClientActions(el);
  return el;
}

/** Enable Save when name or URL differs from saved; Clear when a URL exists. */
function syncCrdpUrlRow(row) {
  if (!row) return;
  const urlInput = row.querySelector(".crdp-url-input");
  const nameInput = row.querySelector(".crdp-name-input");
  const saveBtn = row.querySelector(".crdp-save");
  const clearBtn = row.querySelector(".crdp-clear-url");
  const idHint = row.querySelector(".crdp-cm-id");

  let urlDirty = false;
  if (urlInput && !urlInput.disabled) {
    const saved = String(urlInput.dataset.savedUrl || "");
    const current = String(urlInput.value || "").trim();
    urlDirty = current !== saved.trim();
    urlInput.dataset.dirty = urlDirty ? "1" : "0";
    const empty = !current;
    urlInput.classList.toggle("crdp-url-empty", empty);
    urlInput.setAttribute("aria-invalid", empty ? "true" : "false");
    if (clearBtn) clearBtn.disabled = empty && !saved.trim();
  }

  let nameDirty = false;
  if (nameInput && !nameInput.disabled) {
    const savedName = String(nameInput.dataset.savedName || "");
    const currentName = String(nameInput.value || "").trim();
    const cmName = String(nameInput.dataset.cmName || "").trim();
    nameDirty = currentName !== savedName.trim();
    nameInput.dataset.dirty = nameDirty ? "1" : "0";
    // Show CM id next to friendly name when renamed (saved or typed away from CM name).
    const showId = Boolean(currentName) && currentName !== cmName;
    if (idHint) idHint.classList.toggle("is-hidden", !showId);
  }

  if (saveBtn) saveBtn.disabled = !(urlDirty || nameDirty);
}

function bindCrdpClientActions(el) {
  el.addEventListener("click", async (ev) => {
    const clearRevokedBtn = ev.target.closest(".crdp-clear-revoked");
    if (clearRevokedBtn) {
      if (!state.applianceId) return;
      if (!window.confirm("Remove all revoked CRDP clients from local tracking?")) return;
      clearRevokedBtn.disabled = true;
      try {
        await fetchJSON(
          `/api/appliances/${state.applianceId}/crdp/clients?state=revoked`,
          { method: "DELETE" }
        );
        await loadDashboard("crdp", { forceFull: false });
      } catch (err) {
        window.alert(err?.message || String(err));
        clearRevokedBtn.disabled = false;
      }
      return;
    }

    const removeBtn = ev.target.closest(".crdp-remove");
    if (removeBtn) {
      const clientId = Number(removeBtn.dataset.id);
      if (!clientId || !state.applianceId) return;
      removeBtn.disabled = true;
      try {
        await fetchJSON(
          `/api/appliances/${state.applianceId}/crdp/clients/${clientId}`,
          { method: "DELETE" }
        );
        el.querySelector(`tr[data-crdp-id="${clientId}"]`)?.remove();
        await loadDashboard("crdp", { forceFull: false });
      } catch (err) {
        removeBtn.disabled = false;
        window.alert(err?.message || String(err));
      }
      return;
    }

    const clearUrlBtn = ev.target.closest(".crdp-clear-url");
    if (clearUrlBtn) {
      const clientId = Number(clearUrlBtn.dataset.id);
      const row = el.querySelector(`tr[data-crdp-id="${clientId}"]`);
      const input = row?.querySelector(".crdp-url-input");
      if (!clientId || !input || !state.applianceId) return;
      const hadSaved = Boolean(String(input.dataset.savedUrl || "").trim());
      input.value = "";
      syncCrdpUrlRow(row);
      if (!hadSaved) return;
      clearUrlBtn.disabled = true;
      try {
        await fetchJSON(`/api/appliances/${state.applianceId}/crdp/clients/${clientId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ metrics_url: "" }),
        });
        input.dataset.savedUrl = "";
        input.dataset.dirty = "0";
        syncCrdpUrlRow(row);
        await loadDashboard("crdp", { forceFull: false });
      } catch (err) {
        window.alert(err?.message || String(err));
        clearUrlBtn.disabled = false;
      }
      return;
    }

    const btn = ev.target.closest(".crdp-save");
    if (!btn || btn.disabled) return;
    const clientId = Number(btn.dataset.id);
    const row = el.querySelector(`tr[data-crdp-id="${clientId}"]`);
    const urlInput = row?.querySelector(".crdp-url-input");
    const nameInput = row?.querySelector(".crdp-name-input");
    if (!clientId || !state.applianceId) return;
    btn.disabled = true;
    const prev = btn.textContent;
    btn.textContent = "Saving…";
    const body = {};
    if (urlInput && urlInput.dataset.dirty === "1") {
      body.metrics_url = urlInput.value || "";
    }
    if (nameInput && nameInput.dataset.dirty === "1") {
      body.display_name = nameInput.value || "";
    }
    try {
      const updated = await fetchJSON(
        `/api/appliances/${state.applianceId}/crdp/clients/${clientId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (urlInput) {
        urlInput.dataset.savedUrl = String(updated?.metrics_url || urlInput.value || "").trim();
        urlInput.value = urlInput.dataset.savedUrl;
        urlInput.dataset.dirty = "0";
      }
      if (nameInput) {
        const cmName = String(nameInput.dataset.cmName || "");
        const alias = String(updated?.display_name || "").trim();
        const label = alias || cmName;
        nameInput.dataset.savedName = label;
        nameInput.value = label;
        nameInput.dataset.dirty = "0";
      }
      btn.textContent = "Saved";
      syncCrdpUrlRow(row);
      window.setTimeout(() => {
        btn.textContent = prev || "Save";
        syncCrdpUrlRow(row);
      }, 900);
      loadDashboard("crdp", { forceFull: false }).catch(() => null);
    } catch (err) {
      btn.textContent = "Error";
      window.alert(err?.message || String(err));
      window.setTimeout(() => {
        btn.textContent = prev || "Save";
        syncCrdpUrlRow(row);
      }, 1200);
    }
  });
}

/** Jump to Connectors → CRDP for a given appliance (notification deep-link). */
export async function openCrdpForAppliance(applianceId) {
  const id = Number(applianceId);
  if (id) {
    state.applianceId = id;
    state.panelMeta = null;
  }
  state.viewMode = "dashboard";
  persistTabChip("cloud", "crdp");
  state.groupId = "cloud";
  state.dashboardId = "crdp";
  // Keep the header dropdown / status pill in sync with the deep-linked appliance.
  renderApplianceList(true);
  syncWorkspaceChrome();
  await loadDashboard("crdp", { forceFull: true });
  await refreshStatus().catch(() => null);
}

function fleetTitle(data) {
  const appliance = data.appliance;
  const members = data.cluster_members || [];
  const fleet = Boolean(data.fleet_cluster) && members.length > 1;
  if (!fleet) {
    const host = appliance ? (appliance.display_name || appliance.host) : "";
    return data.title + (host ? ` · ${host.replace(/^https?:\/\//, "")}` : "");
  }
  const clusterName =
    (appliance && (appliance.cluster_display_name || "").trim()) ||
    (appliance && (appliance.display_name || "").trim()) ||
    "Cluster";
  const offline = members.filter(
    (m) => String(m.last_status || "").toLowerCase() === "offline"
  ).length;
  const err = members.filter(
    (m) => String(m.last_status || "").toLowerCase() === "error"
  ).length;
  let title = `${data.title} · ${clusterName} (${members.length} nodes)`;
  if (offline) title += ` · ${offline} offline`;
  if (err) title += ` · ${err} error`;
  return title;
}

export function fullRender(data, animate = true) {
  const { panelsEl, titleEl, descEl } = getDom();
  destroyCharts();
  panelsEl.innerHTML = "";
  titleEl.textContent = fleetTitle(data);
  descEl.textContent = data.description || "";

  const panels = data.panels || [];
  if (!panels.length) {
    panelsEl.innerHTML = `<div class="empty">No panels yet — waiting for metrics scrape.</div>`;
    state.panelMeta = null;
    return;
  }

  // Group consecutive same-type panels into rows so stats never sit beside charts.
  let row = null;
  let rowType = null;
  panels.forEach((panel) => {
    let node;
    if (panel.type === "stat") node = renderStat(panel, animate);
    else if (panel.type === "timeseries") node = renderTimeseries(panel, animate);
    else if (panel.type === "bar") node = renderBar(panel, animate);
    else if (panel.type === "table") node = renderTable(panel, animate);
    else if (panel.type === "crdp_clients") node = renderCrdpClients(panel, animate);
    else if (panel.type === "note") node = renderNote(panel, animate);
    else {
      node = document.createElement("article");
      node.className = "panel wide span-12";
      node.textContent = `Unsupported panel: ${panel.type}`;
    }

    const groupType = panel.type === "timeseries" || panel.type === "bar" ? "chart" : panel.type;
    if (!row || rowType !== groupType) {
      row = document.createElement("div");
      row.className = `panel-row panel-row-${groupType}`;
      panelsEl.appendChild(row);
      rowType = groupType;
    }
    row.appendChild(node);
  });
  bindPanelDashLinks(panelsEl);
  state.panelMeta = panelSignature(data);
}

/** @returns {boolean} false when layout/charts are missing and a full redraw is needed */
export function updateInPlace(data) {
  const { panelsEl, titleEl } = getDom();
  if (!panelsEl) return false;
  titleEl.textContent = fleetTitle(data);

  const panels = data.panels || [];
  for (const panel of panels) {
    if (panel.type === "stat") {
      const panelEl = panelsEl.querySelector(
        `.panel.stat[data-panel-title="${CSS.escape(panel.title)}"]`
      );
      if (!panelEl) return false;
      const numEl = panelEl.querySelector(".stat-num");
      if (numEl) numEl.textContent = fmt(panel.value, panel.unit);
      const tone = String(panel.tone || "").toLowerCase();
      panelEl.classList.remove("tone-fail", "tone-warning", "tone-pass", "tone-info");
      if (tone === "fail" || tone === "warning" || tone === "pass" || tone === "info") {
        panelEl.classList.add(`tone-${tone}`);
        panelEl.dataset.tone = tone;
      } else {
        delete panelEl.dataset.tone;
      }
      let unitEl = panelEl.querySelector(".stat-unit");
      const unitText = displayUnit(panel.unit, panel.value);
      if (unitText) {
        if (!unitEl) {
          unitEl = document.createElement("span");
          unitEl.className = "stat-unit";
          panelEl.querySelector(".stat-value")?.appendChild(unitEl);
        }
        unitEl.textContent = unitText;
      } else if (unitEl) {
        unitEl.remove();
      }
      continue;
    }

    if (panel.type === "timeseries") {
      const entry = state.charts.find((c) => c.type === "timeseries" && c.title === panel.title);
      const chart = entry?.chart;
      if (!entry || !chart || chart.destroyed) return false;
      const COLORS = chartColors();
      const series = panel.series || [];
      const xBounds = chartXBounds();
      chart.data.datasets = series.map((s, i) => ({
        label: truncateLabel(s.name, 36),
        fullLabel: String(s.name || ""),
        data: (s.points || []).map((p) => ({ x: p.t * 1000, y: p.v })),
        borderColor: COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + "33",
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.25,
      }));
      if (chart.options?.scales?.x) {
        chart.options.scales.x.min = xBounds.min;
        chart.options.scales.x.max = xBounds.max;
        chart.options.scales.x.ticks = {
          ...chart.options.scales.x.ticks,
          callback: (v) => tsLabel(v / 1000, state.rangeId),
          maxTicksLimit: state.rangeId === "30d" ? 10 : state.rangeId === "7d" ? 7 : 8,
        };
      }
      // Keep tooltip callbacks from chart creation; only refresh data.
      safeChartUpdate(chart);
      continue;
    }

    if (panel.type === "bar") {
      const entry = state.charts.find((c) => c.type === "bar" && c.title === panel.title);
      const chart = entry?.chart;
      if (!entry || !chart || chart.destroyed) return false;
      const COLORS = chartColors();
      const items = panel.items || [];
      chart.data.labels = items.map((i) => i.label);
      if (!chart.data.datasets[0]) return false;
      chart.data.datasets[0].data = items.map((i) => i.value);
      chart.data.datasets[0].backgroundColor = items.map((_, i) => COLORS[i % COLORS.length] + "cc");
      chart.data.datasets[0].borderColor = items.map((_, i) => COLORS[i % COLORS.length]);
      safeChartUpdate(chart);
      continue;
    }

    if (panel.type === "table") {
      const el = panelsEl.querySelector(
        `.panel.table[data-panel-title="${CSS.escape(panel.title)}"] tbody`
      );
      if (!el) return false;
      const cols = panel.columns || [];
      const rows = panel.rows || [];
      el.innerHTML = rows.map((r) => `<tr>${cols.map((c) => {
        const cls = c === "metric" || c === "labels" ? "mono" : "";
        return `<td class="${cls}">${escapeHtml(String(r[c] ?? ""))}</td>`;
      }).join("")}</tr>`).join("");
      continue;
    }

    if (panel.type === "crdp_clients") {
      // Rebuild only this panel when needed — never fail the whole dashboard
      // update (that destroys charts and flashes stats).
      updateCrdpClientsInPlace(panel);
      continue;
    }

    if (panel.type === "note") {
      const el = panelsEl.querySelector(
        `.panel.note[data-panel-title="${CSS.escape(panel.title || "note")}"] .note-text`
      );
      if (el) el.textContent = panel.text || "";
    }
  }
  return true;
}

/** Keep CRDP clients table in sync without tearing down other panels. */
function updateCrdpClientsInPlace(panel) {
  const { panelsEl } = getDom();
  const root = panelsEl?.querySelector(
    `.panel.crdp-clients[data-panel-title="${CSS.escape(panel.title)}"]`
  );
  if (!root) {
    // Panel missing — let caller soft-rebuild only if layout sig changed.
    return false;
  }
  const rows = panel.rows || [];
  const tbody = root.querySelector("tbody");
  if (!tbody) {
    if (rows.length === 0) return true;
    root.replaceWith(renderCrdpClients(panel, false));
    return true;
  }
  const byId = new Map(rows.map((r) => [String(r.id), r]));
  const existing = [...tbody.querySelectorAll("tr[data-crdp-id]")];
  const existingIds = new Set(existing.map((tr) => tr.getAttribute("data-crdp-id")));
  const nextIds = new Set(rows.map((r) => String(r.id)));
  // Row set changed — swap only this panel (preserve charts/stats).
  if (
    existingIds.size !== nextIds.size ||
    [...nextIds].some((id) => !existingIds.has(id))
  ) {
    root.replaceWith(renderCrdpClients(panel, false));
    return true;
  }
  for (const tr of existing) {
    const id = tr.getAttribute("data-crdp-id");
    const r = byId.get(id);
    if (!r) {
      root.replaceWith(renderCrdpClients(panel, false));
      return true;
    }
    const active = String(r.state || "") === "active";
    tr.classList.toggle("crdp-revoked", !active);
    const cells = tr.children;
    if (cells.length < 6) {
      root.replaceWith(renderCrdpClients(panel, false));
      return true;
    }
    cells[0].textContent = String(r.name || "");
    cells[1].textContent = String(r.state || "");
    cells[2].textContent = String(r.connectivity || "");
    cells[3].textContent = String(r.version || "");
    const nameInput = cells[0]?.querySelector(".crdp-name-input");
    if (nameInput) {
      const cmName = String(r.name || r.cm_client_id || "");
      const alias = String(r.display_name || "").trim();
      const label = alias || cmName;
      const focused = document.activeElement === nameInput;
      const dirty = focused || nameInput.dataset.dirty === "1";
      nameInput.dataset.cmName = cmName;
      if (!dirty) {
        nameInput.value = label;
        nameInput.dataset.savedName = label;
      }
      nameInput.disabled = !active;
      const idHint = cells[0]?.querySelector(".crdp-cm-id");
      if (idHint) {
        idHint.textContent = cmName;
        idHint.classList.toggle(
          "is-hidden",
          !(String(nameInput.value || "").trim() && String(nameInput.value || "").trim() !== cmName)
        );
      }
    }
    const input = cells[4]?.querySelector(".crdp-url-input");
    if (input) {
      const serverUrl = String(r.metrics_url || "");
      const focused = document.activeElement === input;
      const dirty = focused || input.dataset.dirty === "1";
      if (!dirty && input.value !== serverUrl) {
        input.value = serverUrl;
        input.dataset.savedUrl = serverUrl;
      }
      if (!dirty) input.dataset.savedUrl = serverUrl;
      input.disabled = !active;
    }
    syncCrdpUrlRow(tr);
    // Refresh action buttons if active/revoked flipped
    const actions = cells[6];
    if (actions && active && !actions.querySelector(".crdp-save")) {
      root.replaceWith(renderCrdpClients(panel, false));
      return true;
    }
    if (actions && !active && !actions.querySelector(".crdp-remove")) {
      root.replaceWith(renderCrdpClients(panel, false));
      return true;
    }
    const scrapeCell = cells[5];
    const scrapeText = String(r.scrape || "");
    const err = r.error ? String(r.error) : "";
    scrapeCell.className = "mono";
    scrapeCell.innerHTML =
      escapeHtml(scrapeText) +
      (err ? `<div class="crdp-err">${escapeHtml(err)}</div>` : "");
  }
  return true;
}

export function applyDashboard(data, forceFull = false) {
  try {
    const sig = panelSignature(data);
    // Prefer in-place updates on Auto refresh — including table/stat-only boards
    // that have zero Chart.js instances (old charts.length check forced a flash).
    if (!forceFull && state.panelMeta) {
      if (state.panelMeta === sig) {
        if (updateInPlace(data)) return;
        // Charts/DOM missing after a partial destroy — soft rebuild, no spinner.
        fullRender(data, false);
        return;
      }
      // Layout changed (note/chart appeared) — soft rebuild without enter animation.
      fullRender(data, false);
      return;
    }
    fullRender(data, Boolean(forceFull || !state.panelMeta));
  } catch (err) {
    // Recover from Chart.js / render failures (e.g. prior recursive legend bug)
    destroyCharts();
    state.panelMeta = null;
    throw err;
  }
}

export function showSetup() {
  const { titleEl, descEl, panelsEl } = getDom();
  destroyCharts();
  state.panelMeta = null;
  titleEl.textContent = "Connect an appliance";
  descEl.textContent = "Add a CipherTrust Manager host with username and password to start collecting metrics.";
  panelsEl.innerHTML = `
    <div class="empty">
      <p>No CipherTrust Manager appliances configured.</p>
      <p style="margin-top:12px"><button type="button" class="btn btn-primary" id="btn-empty-add">Add appliance</button></p>
    </div>`;
  document.getElementById("btn-empty-add")?.addEventListener("click", openModal);
}

function dashboardTitleHint(id) {
  for (const g of getDashboardGroups()) {
    const hit = (g.dashboards || []).find((d) => d.id === id);
    if (hit) return hit.title || id;
  }
  return id;
}

/** Clear previous panels immediately so tab switches don't leave stale charts on screen. */
export function showDashboardLoading(id) {
  const { panelsEl, titleEl, descEl } = getDom();
  if (!panelsEl) return;
  destroyCharts();
  state.panelMeta = null;
  const title = dashboardTitleHint(id);
  if (titleEl) titleEl.textContent = title;
  if (descEl) descEl.textContent = "Loading...";
  panelsEl.innerHTML = `
    <div class="dash-loading" role="status" aria-live="polite" aria-busy="true">
      <span class="dash-loading-spinner" aria-hidden="true"></span>
      <span class="dash-loading-text">Loading ${escapeHtml(title)}...</span>
    </div>`;
}

export async function loadDashboard(id, { forceFull = false, showLoading = null } = {}) {
  const { panelsEl } = getDom();
  if (state.viewMode === "appliances") return;
  if (state.viewMode === "healthcheck") return;
  const seq = ++state.loadSeq;
  state.dashboardId = id;
  state.groupId = groupForDashboard(id);
  syncTabChrome();
  // Only show the loading wipe on intentional tab/appliance switches — never on
  // Auto refresh / soft polls (that flash zeros and re-animate the page).
  const wipe = showLoading != null ? Boolean(showLoading) : Boolean(forceFull);
  if (wipe) {
    showDashboardLoading(id);
  }
  if (!state.applianceId) {
    if (seq === state.loadSeq) showSetup();
    return;
  }
  const applianceId = state.applianceId;
  try {
    const data = await fetchJSON(
      `/api/dashboards/${id}?appliance_id=${applianceId}&range=${encodeURIComponent(state.rangeId)}`
    );
    if (seq !== state.loadSeq) return;
    if (state.dashboardId !== id || state.applianceId !== applianceId) return;
    if (state.viewMode === "appliances") return;
    applyDashboard(data, forceFull);
  } catch (err) {
    if (seq !== state.loadSeq) return;
    if (err.payload?.needs_setup) {
      showSetup();
      return;
    }
    destroyCharts();
    panelsEl.innerHTML = `<div class="empty">Failed to load dashboard: ${escapeHtml(err.message)}</div>`;
    state.panelMeta = null;
  }
}

export async function tick({ forceFull = false, scrape = false } = {}) {
  // Don't drop auto ticks while a slow load is in flight — queue one follow-up.
  if (state.loading) {
    const prev = state.tickPending || { forceFull: false, scrape: false };
    state.tickPending = {
      forceFull: Boolean(forceFull || prev.forceFull),
      scrape: Boolean(scrape || prev.scrape),
    };
    return;
  }
  state.loading = true;
  try {
    // Manual Refresh / explicit scrape only — Auto relies on the background
    // scraper (SCRAPE_INTERVAL) so UI + loop don't race the same appliance.
    if (scrape && state.applianceId && state.viewMode === "dashboard") {
      await fetchJSON(`/api/appliances/${state.applianceId}/scrape?force=1`, {
        method: "POST",
      }).catch(() => null);
    }
    await loadAppliances({ force: forceFull });
    await refreshStatus();
    if (state.viewMode === "dashboard") {
      // Auto: in-place value updates (no full DOM rebuild / flash).
      // Manual Refresh / tab changes pass forceFull: true when needed.
      await loadDashboard(state.dashboardId, { forceFull });
    } else if (state.viewMode === "appliances") {
      await renderFleetHealth();
    }
    // healthcheck view refreshes via its own poll while running; Auto tick is a no-op there.
  } finally {
    state.loading = false;
    if (state.tickPending) {
      const pending = state.tickPending;
      state.tickPending = null;
      void tick(pending);
    }
  }
}

export function schedule() {
  const { autoRefresh } = getDom();
  if (state.timer) clearInterval(state.timer);
  if (autoRefresh.checked) {
    // UI poll only (no scrape) — matches background SCRAPE_INTERVAL (default 60s).
    // forceFull: false → updateInPlace when panel layout is unchanged.
    state.timer = setInterval(
      () => tick({ forceFull: false, scrape: false }),
      window.CM_METRICS.scrapeInterval || 60000
    );
  }
}
