import { escapeHtml, appliancesSignature, formatCmUptime } from "./format.js";
import { fetchJSON, refreshStatus } from "./api.js";
import { state, getDom } from "./state.js";
import { currentTheme } from "./theme.js";
import { initLocationFields, readLocationKey } from "./locations.js";

let loadDashboard = async () => {};
let destroyCharts = () => {};
let syncWorkspaceChrome = () => {};
let openOverview = async () => {};

/** Inject dashboard helpers from main to avoid circular imports. */
export function setDashboardLoader(fn) {
  if (typeof fn === "function") loadDashboard = fn;
}

export function setDashboardChrome({
  destroyCharts: dc,
  syncWorkspaceChrome: swc,
  openOverview: ov,
} = {}) {
  if (typeof dc === "function") destroyCharts = dc;
  if (typeof swc === "function") syncWorkspaceChrome = swc;
  if (typeof ov === "function") openOverview = ov;
}

export function openModal() {
  const { modal, formError, form, connectLocationFields } = getDom();
  modal.hidden = false;
  formError.hidden = true;
  formError.textContent = "";
  initLocationFields(connectLocationFields || form, { selectedKey: "" }).catch(() => null);
  form.querySelector("input[name=host]")?.focus();
}

export function closeModal() {
  getDom().modal.hidden = true;
}

export function openEditModal(appliance, target = "appliance") {
  const {
    editModal,
    editForm,
    editFormError,
    editModalTitle,
    editModalSub,
    editNameLabel,
    editLocationWrap,
    editCloudWrap,
  } = getDom();
  if (!editModal || !editForm || !appliance) return;
  const shortHost = shortHostOf(appliance);
  const isCluster = target === "cluster";
  if (editModalTitle) {
    editModalTitle.textContent = isCluster ? "Edit cluster" : "Edit appliance";
  }
  if (editModalSub) {
    editModalSub.textContent = isCluster
      ? "Update the cluster display name. Location and cloud are set on each node, not the cluster."
      : "Update the display name, location, and cloud for this node.";
  }
  if (editNameLabel) {
    const input = editNameLabel.querySelector("input");
    // Keep the input; rewrite only the label text node before it.
    editNameLabel.childNodes[0].textContent = isCluster ? "Cluster name " : "Display name ";
    if (input) {
      input.name = isCluster ? "cluster_display_name" : "display_name";
      input.placeholder = isCluster ? "Prod Cluster" : "Prod CM";
      input.value = isCluster
        ? clusterTitle(appliance)
        : (appliance.display_name || shortHost || "");
    }
  }
  if (editLocationWrap) {
    // Clusters never have a location — only individual nodes do.
    if (isCluster) {
      editLocationWrap.hidden = true;
      const hiddenLoc = editLocationWrap.querySelector("input[name=location]");
      if (hiddenLoc) hiddenLoc.value = "";
    } else {
      editLocationWrap.hidden = false;
      const mapped = appliance.location_mapped;
      const key = mapped ? appliance.location || "" : "";
      const previous = !mapped
        ? appliance.location_previous || appliance.location_label || appliance.location || ""
        : "";
      initLocationFields(editLocationWrap, {
        selectedKey: key,
        previousLabel: previous,
      }).catch(() => null);
    }
  }
  if (editCloudWrap) {
    const cloudInput = editCloudWrap.querySelector("input[name=cloud]");
    if (isCluster) {
      editCloudWrap.hidden = true;
      if (cloudInput) cloudInput.value = "";
    } else {
      editCloudWrap.hidden = false;
      if (cloudInput) cloudInput.value = appliance.cloud || "";
    }
  }
  editForm.querySelector("input[name=appliance_id]").value = String(appliance.id);
  editForm.querySelector("input[name=edit_target]").value = target;
  if (editFormError) {
    editFormError.hidden = true;
    editFormError.textContent = "";
  }
  editModal.hidden = false;
  editForm.querySelector("input[name=display_name], input[name=cluster_display_name]")?.focus();
}

export function closeEditModal() {
  const { editModal } = getDom();
  if (editModal) editModal.hidden = true;
}

export function groupAppliances(list) {
  const byId = new Map((list || []).map((a) => [a.id, a]));
  const children = new Map();
  const roots = [];
  (list || []).forEach((a) => {
    const parentId = a.parent_appliance_id != null ? Number(a.parent_appliance_id) : null;
    if (parentId && byId.has(parentId) && parentId !== a.id) {
      if (!children.has(parentId)) children.set(parentId, []);
      children.get(parentId).push(a);
    } else {
      roots.push(a);
    }
  });
  children.forEach((arr, parentId) => {
    const parent = byId.get(parentId);
    // Include primary as first node under the cluster heading
    const nodes = parent ? [parent, ...arr] : arr.slice();
    nodes.sort((x, y) => {
      const xr = x.cluster_role === "primary" || x.id === parentId ? 0 : 1;
      const yr = y.cluster_role === "primary" || y.id === parentId ? 0 : 1;
      if (xr !== yr) return xr - yr;
      return String(x.host || "").localeCompare(String(y.host || ""));
    });
    children.set(parentId, nodes.filter((n, i, all) => all.findIndex((x) => x.id === n.id) === i));
  });
  return { roots, children, byId };
}

export function shortHostOf(a) {
  return (a.host || "").replace(/^https?:\/\//, "");
}

function networkMetaHtml(a) {
  const hostname = (a.cm_hostname || a.cm_name || "").trim();
  const publicIp = (a.public_host || "").trim();
  const privateIp = (a.private_host || "").trim();
  const location = (a.location_label || a.location || "").trim();
  const cloud = (a.cloud || "").trim();
  const rows = [];
  if (hostname) {
    rows.push(`<span class="tree-meta-row"><span class="tree-meta-label">CM hostname</span><span class="tree-meta-value">${escapeHtml(hostname)}</span></span>`);
  }
  if (publicIp) {
    rows.push(`<span class="tree-meta-row"><span class="tree-meta-label">Public IP</span><span class="tree-meta-value">${escapeHtml(publicIp)}</span></span>`);
  }
  if (privateIp) {
    rows.push(`<span class="tree-meta-row"><span class="tree-meta-label">Private IP</span><span class="tree-meta-value">${escapeHtml(privateIp)}</span></span>`);
  }
  if (location) {
    const needsUpdate = a.location_mapped === false ? " (update)" : "";
    rows.push(`<span class="tree-meta-row"><span class="tree-meta-label">Location</span><span class="tree-meta-value">${escapeHtml(location)}${needsUpdate}</span></span>`);
  }
  if (cloud) {
    rows.push(`<span class="tree-meta-row"><span class="tree-meta-label">Cloud</span><span class="tree-meta-value">${escapeHtml(cloud)}</span></span>`);
  }
  if (!rows.length) {
    rows.push(`<span class="tree-meta-row"><span class="tree-meta-label">Connect</span><span class="tree-meta-value">${escapeHtml(shortHostOf(a))}</span></span>`);
  }
  return `<span class="tree-node-meta">${rows.join("")}</span>`;
}

export function clusterTitle(primary) {
  const clusterName = (primary.cluster_display_name || "").trim();
  if (clusterName) return clusterName;
  const name = (primary.display_name || "").trim();
  // Legacy: older data stored the cluster title in display_name
  if (name && !/^Node\s+\d+$/i.test(name)) return name;
  return `Cluster · ${shortHostOf(primary)}`;
}

export function nodeLabel(a, index, { isPrimary = false } = {}) {
  const name = (a.display_name || "").trim();
  if (/^Node\s+\d+$/i.test(name)) return name;
  if (name) return name;
  return `Node ${index}`;
}

export function applianceStatusBadge(a) {
  if (a.last_status === "ok") return { cls: "ok", text: "online" };
  if (a.last_status === "offline") return { cls: "offline", text: "offline" };
  if (a.last_status === "error") return { cls: "err", text: "error" };
  if (a.last_status === "delete_failed") return { cls: "err", text: "delete failed" };
  if (a.last_status === "pending") return { cls: "", text: "retrying" };
  return { cls: "", text: a.last_status || "pending" };
}

function nodeActionsHtml(a, { editTarget = "appliance", label = "" } = {}) {
  const offline = a.last_status === "offline";
  const syncTitle = offline ? "Retry contact" : "Sync this appliance";
  const syncLabel = offline ? `Retry ${label}` : `Sync ${label}`;
  const syncing = state.syncingApplianceIds?.has(a.id);
  return `
    <span class="tree-node-actions">
      <button type="button" class="appliance-open-overview" data-id="${a.id}" title="Open Overview dashboard" aria-label="Open Overview for ${escapeHtml(label)}">
        Overview
      </button>
      <button type="button" class="appliance-retry${syncing ? " is-syncing" : ""}" data-id="${a.id}" title="${escapeHtml(syncTitle)}" aria-label="${escapeHtml(syncLabel)}"${syncing ? " disabled" : ""}>
        <svg class="icon-retry" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
          <path fill="currentColor" d="M12 6V3L8 7l4 4V8c2.76 0 5 2.24 5 5a5 5 0 0 1-9.9 1H5.08A7 7 0 0 0 19 13c0-3.87-3.13-7-7-7z"/>
        </svg>
      </button>
      <button type="button" class="appliance-edit" data-id="${a.id}" data-edit-target="${editTarget}" title="Edit" aria-label="Edit ${escapeHtml(label)}">
        <svg class="icon-pencil" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
          <path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1.003 1.003 0 0 0 0-1.42l-2.34-2.34a1.003 1.003 0 0 0-1.42 0l-1.83 1.83 3.75 3.75 1.84-1.82z"/>
        </svg>
      </button>
      <button type="button" class="appliance-delete" data-id="${a.id}" title="Remove appliance" aria-label="Remove ${escapeHtml(label)}">
        <svg class="icon-trash" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
          <path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v9h-2V9zm4 0h2v9h-2V9zM7 9h2v9H7V9zm-1 12h12a1 1 0 0 0 1-1V8H5v12a1 1 0 0 0 1 1z"/>
        </svg>
      </button>
    </span>`;
}

function treeNodeHtml(a, { nodeIndex = null, isPrimary = false, nested = false } = {}) {
  const active = a.id === state.applianceId ? " active" : "";
  const badge = applianceStatusBadge(a);
  const shortHost = shortHostOf(a);
  const label =
    nested && nodeIndex != null
      ? nodeLabel(a, nodeIndex, { isPrimary })
      : a.display_name || shortHost;
  const offline = a.last_status === "offline";
  const role =
    isPrimary || a.cluster_role === "primary"
      ? "primary"
      : nested
        ? "member"
        : "";
  const uptime =
    a.last_status === "ok" ? formatCmUptime(a.cm_uptime) : "";
  return `
    <div class="tree-node${active}${offline ? " is-offline" : ""}" data-id="${a.id}" role="treeitem" aria-selected="${a.id === state.applianceId}">
      <button type="button" class="tree-node-select" data-id="${a.id}" title="${escapeHtml(`${label} · ${shortHost}${uptime ? ` · up ${uptime}` : ""}`)}">
        <span class="tree-node-status ${badge.cls}" aria-hidden="true"></span>
        <span class="tree-node-body">
          <span class="tree-node-top">
            <span class="tree-node-name">${escapeHtml(label)}</span>
            ${role ? `<span class="tree-node-role">${role}</span>` : ""}
            ${uptime ? `<span class="tree-node-uptime" title="Uptime">${escapeHtml(uptime)}</span>` : ""}
          </span>
          ${networkMetaHtml(a)}
        </span>
        <span class="tree-node-badge ${badge.cls}">${escapeHtml(badge.text)}</span>
      </button>
      ${nodeActionsHtml(a, { editTarget: nested ? "node" : "appliance", label })}
    </div>`;
}

function clusterIconSvg() {
  return `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
    <path fill="currentColor" d="M12 2a3 3 0 0 1 3 3v1.1a7 7 0 0 1 3.9 3.9H20a3 3 0 1 1 0 6h-1.1a7 7 0 0 1-3.9 3.9V20a3 3 0 1 1-6 0v-1.1A7 7 0 0 1 5.1 15H4a3 3 0 1 1 0-6h1.1A7 7 0 0 1 9 5.1V5a3 3 0 0 1 3-3zm0 6a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/>
  </svg>`;
}

export function setApplianceMenuOpen(open) {
  const { btnApplianceCurrent, applianceMenu } = getDom();
  state.menuOpen = !!open;
  if (btnApplianceCurrent) btnApplianceCurrent.setAttribute("aria-expanded", state.menuOpen ? "true" : "false");
  if (applianceMenu) applianceMenu.hidden = !state.menuOpen;
}

export function currentAppliance() {
  return state.appliances.find((a) => a.id === state.applianceId) || null;
}

export function renderCurrentSelector() {
  const { btnApplianceCurrent, applianceCurrentLabel, applianceCurrentMeta } = getDom();
  if (!btnApplianceCurrent) return;
  const a = currentAppliance();
  const dot = btnApplianceCurrent.querySelector(".appliance-current-dot");
  if (!a) {
    if (applianceCurrentLabel) applianceCurrentLabel.textContent = "No appliance";
    if (applianceCurrentMeta) applianceCurrentMeta.textContent = "Add one to begin";
    if (dot) dot.className = "appliance-current-dot";
    return;
  }
  const badge = applianceStatusBadge(a);
  const shortHost = shortHostOf(a);
  const { roots, children, byId } = groupAppliances(state.appliances);
  let clusterHint = "";
  const parentId = a.parent_appliance_id != null ? Number(a.parent_appliance_id) : null;
  if (parentId && byId.has(parentId)) {
    clusterHint = clusterTitle(byId.get(parentId));
  } else if ((children.get(a.id) || []).length || a.is_clustered || a.cluster_role === "primary") {
    clusterHint = clusterTitle(a);
  }
  const label = a.display_name || shortHost;
  if (applianceCurrentLabel) applianceCurrentLabel.textContent = label;
  if (applianceCurrentMeta) {
    applianceCurrentMeta.textContent = clusterHint
      ? `${clusterHint} · ${shortHost}`
      : shortHost;
  }
  if (dot) dot.className = `appliance-current-dot ${badge.cls}`;
}

function menuItemHtml(a, { nested = false, nodeIndex = null, isPrimary = false } = {}) {
  const badge = applianceStatusBadge(a);
  const shortHost = shortHostOf(a);
  const label =
    nested && nodeIndex != null
      ? nodeLabel(a, nodeIndex, { isPrimary })
      : a.display_name || shortHost;
  const active = a.id === state.applianceId ? " active" : "";
  const role =
    isPrimary || a.cluster_role === "primary"
      ? "primary"
      : nested
        ? "member"
        : "";
  return `
    <button type="button" class="appliance-menu-item${active}${nested ? " nested" : ""}" data-id="${a.id}" role="option" aria-selected="${a.id === state.applianceId}">
      <span class="menu-dot ${badge.cls}" aria-hidden="true"></span>
      <span class="menu-text">
        <span class="menu-name">${escapeHtml(label)}</span>
        <span class="menu-host">${escapeHtml(shortHost)}</span>
      </span>
      ${role ? `<span class="menu-role">${role}</span>` : ""}
    </button>`;
}

export function renderApplianceMenu() {
  const { applianceMenu } = getDom();
  if (!applianceMenu) return;
  if (!state.appliances.length) {
    applianceMenu.innerHTML = `
      <div class="appliance-menu-empty">No appliances yet.</div>
      <div class="appliance-menu-footer">
        <button type="button" class="appliance-menu-link" data-action="open-appliances">Open Appliances tab</button>
      </div>`;
    return;
  }
  const { roots, children } = groupAppliances(state.appliances);
  const sections = roots
    .map((root) => {
      const members = children.get(root.id) || [];
      const isCluster = root.is_clustered || members.length > 1 || root.cluster_role === "primary";
      if (!isCluster || members.length === 0) {
        if (isCluster && members.length === 0) {
          return `
            <div class="appliance-menu-section">
              <div class="appliance-menu-heading">${escapeHtml(clusterTitle(root))}</div>
              ${menuItemHtml(root, { nested: true, nodeIndex: 1, isPrimary: true })}
            </div>`;
        }
        return `<div class="appliance-menu-section">${menuItemHtml(root)}</div>`;
      }
      return `
        <div class="appliance-menu-section">
          <div class="appliance-menu-heading">${escapeHtml(clusterTitle(root))}</div>
          ${members
            .map((m, i) =>
              menuItemHtml(m, {
                nested: true,
                nodeIndex: i + 1,
                isPrimary: m.id === root.id,
              })
            )
            .join("")}
        </div>`;
    })
    .join("");
  applianceMenu.innerHTML = `
    ${sections}
    <div class="appliance-menu-footer">
      <button type="button" class="appliance-menu-link" data-action="open-appliances">Manage in Appliances tab</button>
    </div>`;
}

function clusterHeadHtml(root, nodeCount) {
  return `
    <div class="tree-cluster-head">
      <div class="tree-cluster-mark">${clusterIconSvg()}</div>
      <div class="tree-cluster-meta">
        <div class="tree-cluster-kicker">Cluster</div>
        <div class="tree-cluster-name" title="${escapeHtml(clusterTitle(root))}">${escapeHtml(clusterTitle(root))}</div>
        <div class="tree-cluster-count">${nodeCount} node${nodeCount === 1 ? "" : "s"}</div>
      </div>
      <div class="tree-cluster-actions">
        <button type="button" class="appliance-edit" data-id="${root.id}" data-edit-target="cluster" title="Edit cluster" aria-label="Edit cluster">
          <svg class="icon-pencil" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">
            <path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1.003 1.003 0 0 0 0-1.42l-2.34-2.34a1.003 1.003 0 0 0-1.42 0l-1.83 1.83 3.75 3.75 1.84-1.82z"/>
          </svg>
        </button>
      </div>
    </div>`;
}

function treeBranchHtml(nodes, rootId) {
  return `
    <ul class="tree-diagram" role="group">
      ${nodes
        .map((m, i) => {
          const last = i === nodes.length - 1;
          return `
            <li class="tree-diagram-item${last ? " is-last" : ""}">
              <span class="tree-diagram-guide" aria-hidden="true">
                <span class="tree-diagram-rail"></span>
                <span class="tree-diagram-elbow"></span>
              </span>
              ${treeNodeHtml(m, {
                nested: true,
                nodeIndex: i + 1,
                isPrimary: m.id === rootId || m.cluster_role === "primary",
              })}
            </li>`;
        })
        .join("")}
    </ul>`;
}

function destroyFleetMap() {
  if (state.fleetMap) {
    try { state.fleetMap.remove(); } catch (_) { /* ignore */ }
  }
  state.fleetMap = null;
  state.fleetMapTileLayer = null;
  state.fleetMapLabelLayer = null;
  state.fleetMapContinents = null;
  state.fleetMapMarkers = null;
  state.fleetMapLinks = null;
  state.fleetMapSig = null;
  state.fleetMapFitted = false;
  state.fleetMapTheme = null;
}

/** Dark-mode only at world zoom — light Carto tiles already print continent names. */
const CONTINENT_LABELS = [
  { name: "North America", lat: 48, lng: -100 },
  { name: "South America", lat: -14, lng: -58 },
  { name: "Europe", lat: 54, lng: 15 },
  { name: "Africa", lat: 8, lng: 20 },
  { name: "Asia", lat: 45, lng: 90 },
  { name: "Oceania", lat: -25, lng: 134 },
];
const CONTINENT_LABEL_MAX_ZOOM = 3.5;

function syncContinentLabels() {
  const map = state.fleetMap;
  const group = state.fleetMapContinents;
  if (!map || !group) return;
  try {
    // Light basemap already has continent labels; ours would duplicate them.
    const show =
      currentTheme() !== "light" && map.getZoom() <= CONTINENT_LABEL_MAX_ZOOM;
    if (show) {
      if (!map.hasLayer(group)) group.addTo(map);
    } else if (map.hasLayer(group)) {
      map.removeLayer(group);
    }
  } catch (_) { /* ignore */ }
}

function ensureContinentLabels(map) {
  if (!map) return;
  if (!state.fleetMapContinents) {
    if (!map.getPane("fleetContinents")) {
      map.createPane("fleetContinents");
      const pane = map.getPane("fleetContinents");
      pane.style.zIndex = "450";
      pane.style.pointerEvents = "none";
    }

    const group = L.layerGroup();
    for (const c of CONTINENT_LABELS) {
      const icon = L.divIcon({
        className: "fleet-continent-label-icon",
        html: `<span class="fleet-continent-label">${c.name}</span>`,
        iconSize: [0, 0],
        iconAnchor: [0, 0],
      });
      L.marker([c.lat, c.lng], {
        icon,
        pane: "fleetContinents",
        interactive: false,
        keyboard: false,
      }).addTo(group);
    }
    state.fleetMapContinents = group;
    map.on("zoomend", syncContinentLabels);
    map.on("viewreset", syncContinentLabels);
  }
  syncContinentLabels();
}

function fleetMapSignature() {
  const positions = computeMapPositions();
  const rows = [];
  for (const [id, pos] of positions) {
    rows.push([
      id,
      Number(pos.lat.toFixed(5)),
      Number(pos.lng.toFixed(5)),
      applianceMapTone(pos.appliance),
      pos.appliance.location || "",
      pos.appliance.parent_appliance_id || "",
    ]);
  }
  rows.sort((a, b) => a[0] - b[0]);
  // Theme affects tile style + cluster line color.
  return JSON.stringify({ theme: currentTheme(), markers: rows });
}

/** Basemap + optional label overlay. Dark Carto labels are too dim; Esri ref is readable. */
function mapBasemapSpec() {
  if (currentTheme() === "light") {
    return {
      base: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      labels: null,
      subdomains: "abcd",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    };
  }
  return {
    base: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    labels:
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    subdomains: null,
    attribution: 'Tiles &copy; <a href="https://www.esri.com/">Esri</a>',
  };
}

function removeFleetMapTileLayers() {
  if (!state.fleetMap) return;
  for (const key of ["fleetMapTileLayer", "fleetMapLabelLayer"]) {
    const layer = state[key];
    if (!layer) continue;
    try {
      state.fleetMap.removeLayer(layer);
    } catch (_) { /* ignore */ }
    state[key] = null;
  }
}

function applyFleetMapTiles(map) {
  removeFleetMapTileLayers();
  const spec = mapBasemapSpec();
  const baseOpts = {
    maxZoom: 8,
    minZoom: 1,
    attribution: spec.attribution,
  };
  if (spec.subdomains) baseOpts.subdomains = spec.subdomains;
  const tiles = L.tileLayer(spec.base, baseOpts);
  tiles.addTo(map);
  state.fleetMapTileLayer = tiles;

  if (spec.labels) {
    if (!map.getPane("fleetLabels")) {
      map.createPane("fleetLabels");
      const pane = map.getPane("fleetLabels");
      pane.style.zIndex = "350";
      pane.style.pointerEvents = "none";
    }
    const labels = L.tileLayer(spec.labels, {
      maxZoom: 8,
      minZoom: 1,
      pane: "fleetLabels",
      opacity: 1,
    });
    labels.addTo(map);
    state.fleetMapLabelLayer = labels;
  }
}

function applianceMapTone(a) {
  const status = String(a.last_status || "").toLowerCase();
  if (status === "ok") return "online";
  if (status === "pending") return "pending";
  return "offline";
}

function ensureFleetMap() {
  const { fleetMapCanvas } = getDom();
  if (!fleetMapCanvas || typeof L === "undefined") return null;
  if (state.fleetMap) return state.fleetMap;

  const map = L.map(fleetMapCanvas, {
    worldCopyJump: true,
    zoomControl: true,
    attributionControl: true,
  }).setView([20, 0], 2);

  applyFleetMapTiles(map);
  ensureContinentLabels(map);

  const links = L.layerGroup().addTo(map);
  const markers = L.layerGroup().addTo(map);
  state.fleetMap = map;
  state.fleetMapLinks = links;
  state.fleetMapMarkers = markers;
  state.fleetMapTheme = currentTheme();
  state.fleetMapFitted = false;

  // Leaflet needs a size refresh after becoming visible.
  setTimeout(() => {
    try { map.invalidateSize({ animate: false }); } catch (_) { /* ignore */ }
  }, 50);

  return map;
}

function syncFleetMapTiles({ force = false } = {}) {
  if (!state.fleetMap) return;
  const theme = currentTheme();
  if (!force && state.fleetMapTheme === theme && state.fleetMapTileLayer) {
    syncContinentLabels();
    return;
  }
  applyFleetMapTiles(state.fleetMap);
  state.fleetMapTheme = theme;
  ensureContinentLabels(state.fleetMap);
}

function clusterRootId(a, byId) {
  const parentId = a.parent_appliance_id != null ? Number(a.parent_appliance_id) : null;
  if (parentId && byId.has(parentId)) return parentId;
  if (a.is_clustered || a.cluster_role === "primary") return Number(a.id);
  return null;
}

/** Spread co-located nodes so online/offline dots don't stack into one pin. */
function offsetCoLocated(lat, lng, index, total) {
  if (total <= 1) return [lat, lng];
  // ~0.35° ring — visible at continent zoom without looking far apart.
  const radius = 0.35;
  const angle = (2 * Math.PI * index) / total - Math.PI / 2;
  const latRad = (lat * Math.PI) / 180;
  const dLat = radius * Math.cos(angle);
  const dLng = (radius * Math.sin(angle)) / Math.max(Math.cos(latRad), 0.2);
  return [lat + dLat, lng + dLng];
}

/** Display lat/lng per appliance (includes co-location offsets). Shared by dots + cluster lines. */
function computeMapPositions() {
  /** @type {Map<string, any[]>} */
  const groups = new Map();
  for (const a of state.appliances || []) {
    if (!a.location_mapped || a.location_lat == null || a.location_lng == null) continue;
    const key = `${a.location_lat},${a.location_lng}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(a);
  }

  /** @type {Map<number, {lat:number,lng:number,appliance:any}>} */
  const positions = new Map();
  for (const items of groups.values()) {
    // Stable order so auto-refresh reordering doesn't reshuffle offsets.
    items.sort((a, b) => Number(a.id) - Number(b.id));
    items.forEach((a, index) => {
      const [lat, lng] = offsetCoLocated(
        Number(a.location_lat),
        Number(a.location_lng),
        index,
        items.length
      );
      positions.set(Number(a.id), { lat, lng, appliance: a });
    });
  }
  return positions;
}

function paintClusterLinks(byId, positions) {
  if (!state.fleetMapLinks) return;
  state.fleetMapLinks.clearLayers();

  const isLight = currentTheme() === "light";
  const lineColor = isLight ? "#2563eb" : "#60a5fa";

  /** @type {Map<number, number[]>} clusterRoot -> appliance ids with map positions */
  const clusterMembers = new Map();
  for (const [id, pos] of positions) {
    const a = pos.appliance;
    const root = clusterRootId(a, byId);
    if (!root) continue;
    if (!clusterMembers.has(root)) clusterMembers.set(root, []);
    clusterMembers.get(root).push(id);
  }

  for (const [rootId, memberIds] of clusterMembers) {
    if (memberIds.length < 2) continue;
    const hubPos = positions.get(rootId) || positions.get(memberIds[0]);
    if (!hubPos) continue;

    for (const id of memberIds) {
      if (id === rootId) continue;
      const pos = positions.get(id);
      if (!pos) continue;
      if (pos.lat === hubPos.lat && pos.lng === hubPos.lng) continue;
      const line = L.polyline(
        [
          [hubPos.lat, hubPos.lng],
          [pos.lat, pos.lng],
        ],
        {
          color: lineColor,
          weight: 2,
          opacity: 0.75,
          dashArray: "6 6",
          interactive: false,
        }
      );
      state.fleetMapLinks.addLayer(line);
    }
  }
}

function paintFleetMap({ forceFit = false } = {}) {
  const map = ensureFleetMap();
  if (!map || !state.fleetMapMarkers) return;

  const sig = fleetMapSignature();
  if (!forceFit && sig === state.fleetMapSig) {
    // Markers unchanged — don't clear/rebuild (that caused the flash).
    try { map.invalidateSize({ animate: false }); } catch (_) { /* ignore */ }
    return;
  }
  const shouldFit = forceFit || !state.fleetMapFitted || state.fleetMapSig == null;
  state.fleetMapSig = sig;

  state.fleetMapMarkers.clearLayers();
  if (state.fleetMapLinks) state.fleetMapLinks.clearLayers();

  const byId = new Map((state.appliances || []).map((a) => [Number(a.id), a]));
  const positions = computeMapPositions();
  paintClusterLinks(byId, positions);

  const bounds = [];
  for (const [id, pos] of positions) {
    const a = pos.appliance;
    const tone = applianceMapTone(a);
    const name = a.display_name || shortHostOf(a);
    const locLabel = a.location_label || a.location || "Location";
    // Larger icon box so the online ping rings aren't clipped by Leaflet.
    const markerHtml =
      tone === "online"
        ? `<div class="fleet-map-marker-wrap is-online" title="${escapeHtml(name)}"><span class="fleet-map-ping" aria-hidden="true"></span><span class="fleet-map-ping fleet-map-ping-delay" aria-hidden="true"></span><div class="fleet-map-marker online"></div></div>`
        : `<div class="fleet-map-marker-wrap" title="${escapeHtml(name)}"><div class="fleet-map-marker ${tone}"></div></div>`;
    const icon = L.divIcon({
      className: "fleet-map-icon",
      html: markerHtml,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    });
    const cloudLabel = (a.cloud || "").trim();
    const popupMeta = [locLabel, cloudLabel, tone].filter(Boolean).join(" · ");
    const html = `<div class="fleet-map-popup"><strong>${escapeHtml(name)}</strong>
        <div class="muted">${escapeHtml(popupMeta)}</div>
        <button type="button" data-appliance-id="${id}">Open Overview</button></div>`;
    const marker = L.marker([pos.lat, pos.lng], { icon }).bindPopup(html);
    marker.on("popupopen", (ev) => {
      const el = ev.popup.getElement();
      el?.querySelectorAll("[data-appliance-id]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const aid = Number(btn.getAttribute("data-appliance-id"));
          if (!aid) return;
          await selectAppliance(aid);
          if (typeof openOverview === "function") await openOverview();
        });
      });
    });
    state.fleetMapMarkers.addLayer(marker);
    bounds.push([pos.lat, pos.lng]);
  }

  setTimeout(() => {
    try {
      map.invalidateSize({ animate: false });
      if (!shouldFit) return;
      if (bounds.length === 1) {
        map.setView(bounds[0], 4, { animate: false });
      } else if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [36, 36], maxZoom: 5, animate: false });
      } else {
        map.setView([20, 0], 2, { animate: false });
      }
      state.fleetMapFitted = true;
    } catch (_) { /* ignore */ }
  }, 40);
}

/** Render the Appliances-tab world map (replaces former fleet health chart). */
export async function renderFleetHealth() {
  const { fleetMap, fleetMapSummary } = getDom();
  if (!fleetMap) return;
  if (state.viewMode !== "appliances") {
    fleetMap.hidden = true;
    return;
  }
  fleetMap.hidden = false;

  const list = state.appliances || [];
  let online = 0;
  let offline = 0;
  let unmapped = 0;
  for (const a of list) {
    const tone = applianceMapTone(a);
    if (tone === "online") online += 1;
    else offline += 1;
    if (!a.location_mapped) unmapped += 1;
  }
  if (fleetMapSummary) {
    fleetMapSummary.textContent =
      `${online} online · ${offline} offline` +
      (unmapped ? ` · ${unmapped} unmapped` : "") +
      (list.length ? ` · ${list.length} total` : "");
  }

  if (typeof L === "undefined") {
    if (fleetMapSummary) {
      fleetMapSummary.textContent = "Map library failed to load";
    }
    return;
  }

  // Only swap tiles on theme change — reloading tiles every poll flashed the map.
  syncFleetMapTiles();
  paintFleetMap();
}

export function renderApplianceTree() {
  const { applianceTree } = getDom();
  if (!applianceTree) return;
  if (!state.appliances.length) {
    applianceTree.innerHTML = `<div class="tree-empty">No appliances yet — click <strong>Add appliance</strong> to connect a CipherTrust Manager.</div>`;
    renderFleetHealth();
    return;
  }
  const { roots, children } = groupAppliances(state.appliances);
  applianceTree.innerHTML = roots
    .map((root) => {
      const members = children.get(root.id) || [];
      const isCluster = root.is_clustered || members.length > 0 || root.cluster_role === "primary";
      if (!isCluster) {
        return `<div class="tree-standalone">${treeNodeHtml(root)}</div>`;
      }
      const nodes = members.length ? members : [root];
      return `
        <div class="tree-cluster" data-parent-id="${root.id}">
          ${clusterHeadHtml(root, nodes.length)}
          ${treeBranchHtml(nodes, root.id)}
        </div>`;
    })
    .join("");
  renderFleetHealth();
}

export function renderApplianceList(force = false) {
  const { applianceTree } = getDom();
  const nextSig = appliancesSignature(state.appliances);
  if (!force && nextSig === state._applianceSig) {
    renderCurrentSelector();
    if (state.viewMode === "appliances") {
      // Lightweight active-state refresh on tree
      applianceTree?.querySelectorAll(".tree-node").forEach((node) => {
        const id = Number(node.dataset.id);
        const a = state.appliances.find((x) => x.id === id);
        if (!a) return;
        node.classList.toggle("active", id === state.applianceId);
        node.classList.toggle("is-offline", a.last_status === "offline");
        node.setAttribute("aria-selected", id === state.applianceId ? "true" : "false");
        const badge = node.querySelector(".tree-node-badge");
        const status = node.querySelector(".tree-node-status");
        const info = applianceStatusBadge(a);
        if (badge) {
          badge.className = `tree-node-badge ${info.cls}`;
          badge.textContent = info.text;
        }
        if (status) status.className = `tree-node-status ${info.cls}`;
      });
      // Summary text only — paintFleetMap skips when marker signature is unchanged.
      renderFleetHealth();
    }
    if (state.menuOpen) renderApplianceMenu();
    return;
  }
  state._applianceSig = nextSig;
  renderCurrentSelector();
  if (state.menuOpen) renderApplianceMenu();
  if (state.viewMode === "appliances") renderApplianceTree();
}

export async function selectAppliance(id, { load = true } = {}) {
  const next = Number(id);
  if (!next || next === state.applianceId) {
    setApplianceMenuOpen(false);
    return;
  }
  state.applianceId = next;
  state.panelMeta = null;
  setApplianceMenuOpen(false);
  renderApplianceList(true);
  if (load && state.viewMode === "dashboard") {
    await loadDashboard(state.dashboardId, { forceFull: true });
  } else if (load && state.viewMode === "healthcheck") {
    const { refreshHealthcheckStatus } = await import("./healthcheck.js");
    await refreshHealthcheckStatus();
  }
  refreshStatus();
}

export function showAppliancesTab() {
  state.viewMode = "appliances";
  setApplianceMenuOpen(false);
  destroyCharts();
  try {
    import("./healthcheck.js").then((m) => m.hideHealthcheckView?.());
  } catch (_) {
    /* ignore */
  }
  const { panelsEl, healthcheckView } = getDom();
  if (panelsEl) {
    panelsEl.innerHTML = "";
    panelsEl.hidden = true;
  }
  if (healthcheckView) {
    healthcheckView.innerHTML = "";
    healthcheckView.hidden = true;
  }
  state.panelMeta = null;
  syncWorkspaceChrome();
  renderApplianceList(true);
}

export async function loadAppliances({ force = false } = {}) {
  state.appliances = await fetchJSON("/api/appliances");
  if (!state.applianceId && state.appliances.length) {
    state.applianceId = state.appliances[0].id;
  }
  if (state.applianceId && !state.appliances.find((a) => a.id === state.applianceId)) {
    state.applianceId = state.appliances[0]?.id || null;
  }
  // Skip forced tree rebuild on Auto ticks — signature check avoids sidebar flash.
  renderApplianceList(force);
  return state.appliances;
}

export async function submitEditForm(e) {
  e?.preventDefault?.();
  const { editForm, editFormError, btnEditSave } = getDom();
  if (!editForm) return;
  if (editFormError) {
    editFormError.hidden = true;
    editFormError.textContent = "";
  }
  const fd = new FormData(editForm);
  const id = Number(fd.get("appliance_id"));
  const target = String(fd.get("edit_target") || "appliance");
  if (!id) return;
  const body = {};
  if (target === "cluster") {
    body.cluster_display_name = String(fd.get("cluster_display_name") || "").trim();
  } else {
    body.display_name = String(fd.get("display_name") || "").trim();
    body.location = readLocationKey(editForm);
    body.cloud = String(fd.get("cloud") || "").trim();
  }
  if (btnEditSave) {
    btnEditSave.disabled = true;
    btnEditSave.textContent = "Saving…";
  }
  try {
    const updated = await fetchJSON(`/api/appliances/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const idx = state.appliances.findIndex((a) => a.id === id);
    if (idx >= 0) state.appliances[idx] = { ...state.appliances[idx], ...updated };
    state._applianceSig = null;
    closeEditModal();
    renderApplianceList(true);
    await loadAppliances();
    renderApplianceList(true);
    if (state.applianceId && state.viewMode === "dashboard") {
      await loadDashboard(state.dashboardId, { forceFull: true });
    }
  } catch (err) {
    if (editFormError) {
      editFormError.hidden = false;
      editFormError.textContent = err.message || "Failed to save changes";
    } else {
      window.alert(err.message || "Failed to save changes");
    }
  } finally {
    if (btnEditSave) {
      btnEditSave.disabled = false;
      btnEditSave.textContent = "Save";
    }
  }
}

export function showToast(message, { type = "ok", duration = 3200 } = {}) {
  let host = document.getElementById("toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-host";
    host.className = "toast-host";
    host.setAttribute("aria-live", "polite");
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  window.setTimeout(() => {
    el.classList.remove("show");
    window.setTimeout(() => el.remove(), 280);
  }, duration);
}

const _seenNotificationIds = new Set();

function ensureNotifyBannerHost() {
  let host = document.getElementById("notify-banner-host");
  if (host) return host;
  host = document.createElement("div");
  host.id = "notify-banner-host";
  host.className = "notify-banner-host";
  const shell = document.getElementById("app-shell");
  const tabs = document.getElementById("primary-tabs");
  if (shell && tabs) shell.insertBefore(host, tabs);
  else document.body.prepend(host);
  return host;
}

function renderCrdpBanner(note) {
  const host = ensureNotifyBannerHost();
  const existing = host.querySelector(`[data-note-id="${note.id}"]`);
  if (existing) return;
  const el = document.createElement("div");
  el.className = "notify-banner notify-banner-crdp";
  el.dataset.noteId = String(note.id);
  el.innerHTML = `
    <div class="notify-banner-body">
      <strong>${escapeHtml(note.title || "CRDP update")}</strong>
      <span>${escapeHtml(note.message || "")}</span>
    </div>
    <div class="notify-banner-actions">
      <button type="button" class="btn btn-sm" data-action="open-crdp">Open CRDP</button>
      <button type="button" class="btn btn-sm" data-action="dismiss">Dismiss</button>
    </div>
  `;
  el.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === "open-crdp") {
      try {
        const { openCrdpForAppliance } = await import("./dashboard.js");
        await openCrdpForAppliance(note.appliance_id);
      } catch (err) {
        console.warn("open CRDP failed", err);
      }
      try {
        await fetchJSON(`/api/notifications/${note.id}/dismiss`, { method: "POST" });
      } catch {
        /* ignore */
      }
      el.remove();
      return;
    }
    if (action === "dismiss") {
      try {
        await fetchJSON(`/api/notifications/${note.id}/dismiss`, { method: "POST" });
      } catch {
        /* ignore */
      }
      el.remove();
    }
  });
  host.appendChild(el);
}

/** Surface background appliance-delete failures and CRDP membership changes. */
export async function pollDeleteNotifications() {
  try {
    const notes = await fetchJSON("/api/notifications");
    if (!Array.isArray(notes) || !notes.length) return;
    for (const n of notes) {
      const id = Number(n.id);
      if (!id || _seenNotificationIds.has(id)) continue;
      _seenNotificationIds.add(id);
      const kind = String(n.kind || "");
      if (kind.startsWith("crdp_")) {
        renderCrdpBanner(n);
        showToast(n.message || n.title || "CRDP clients updated", {
          type: "err",
          duration: 10000,
        });
        // Keep notification until user opens CRDP or dismisses the banner.
        continue;
      }
      const text = n.message || n.title || "A background task failed";
      showToast(text, { type: "err", duration: 14000 });
      // Also alert once so it is hard to miss if the toast is overlooked.
      if (n.kind === "appliance_delete_failed") {
        window.setTimeout(() => {
          window.alert(text);
        }, 200);
      }
      try {
        await fetchJSON(`/api/notifications/${id}/dismiss`, { method: "POST" });
      } catch {
        /* keep trying next poll */
        _seenNotificationIds.delete(id);
      }
    }
    // If a delete failed, appliance may reappear — refresh list.
    if (notes.some((n) => n.kind === "appliance_delete_failed")) {
      await loadAppliances({ force: true }).catch(() => null);
      renderApplianceList(true);
      await refreshStatus().catch(() => null);
    }
  } catch (err) {
    console.warn("notification poll failed:", err);
  }
}

export async function handleApplianceAction(e) {
  const { panelsEl, descEl } = getDom();
  const overviewBtn = e.target.closest(".appliance-open-overview");
  if (overviewBtn) {
    e.preventDefault();
    e.stopPropagation();
    const id = Number(overviewBtn.dataset.id);
    if (!id) return true;
    state.applianceId = id;
    state.panelMeta = null;
    setApplianceMenuOpen(false);
    renderApplianceList(true);
    await openOverview();
    await refreshStatus().catch(() => null);
    return true;
  }

  const editBtn = e.target.closest(".appliance-edit");
  if (editBtn) {
    e.preventDefault();
    e.stopPropagation();
    const id = Number(editBtn.dataset.id);
    const appliance = state.appliances.find((a) => a.id === id);
    if (!appliance) return true;
    const target = editBtn.dataset.editTarget || "appliance";
    openEditModal(appliance, target);
    return true;
  }

  const delBtn = e.target.closest(".appliance-delete");
  if (delBtn) {
    e.preventDefault();
    e.stopPropagation();
    const id = Number(delBtn.dataset.id);
    const appliance = state.appliances.find((a) => a.id === id);
    const name = appliance?.display_name || appliance?.host || `#${id}`;
    if (!window.confirm(
      `Remove appliance "${name}"?\n\nThis removes it from the list and deletes its metric history immediately.`
    )) {
      return true;
    }
    delBtn.disabled = true;
    try {
      const res = await fetchJSON(`/api/appliances/${id}`, { method: "DELETE" });
      // Optimistic UI update so the tree refreshes even if a later poll is slow.
      state.appliances = (state.appliances || []).filter((a) => a.id !== id);
      state._applianceSig = null;
      if (state.applianceId === id) {
        state.applianceId = state.appliances[0]?.id || null;
        state.panelMeta = null;
        destroyCharts();
        if (panelsEl) panelsEl.innerHTML = "";
        if (descEl) {
          descEl.textContent = "Select or add a CipherTrust Manager appliance to begin.";
        }
      }
      renderApplianceList(true);
      await loadAppliances();
      renderApplianceList(true);
      if (state.viewMode === "appliances") {
        await renderFleetHealth();
      } else if (state.applianceId && state.viewMode === "dashboard") {
        await loadDashboard(state.dashboardId, { forceFull: true });
      }
      await refreshStatus();
      showToast(res?.message || `Removed "${name}" and its metric history.`, {
        type: "ok",
        duration: 4200,
      });
      void pollDeleteNotifications();
    } catch (err) {
      window.alert(err.message || "Failed to remove appliance");
      await loadAppliances();
      renderApplianceList(true);
    } finally {
      delBtn.disabled = false;
    }
    return true;
  }

  const retryBtn = e.target.closest(".appliance-retry");
  if (retryBtn) {
    e.preventDefault();
    e.stopPropagation();
    const id = Number(retryBtn.dataset.id);
    if (state.syncingApplianceIds.has(id)) return true;
    const appliance = state.appliances.find((a) => a.id === id);
    const wasOffline = appliance?.last_status === "offline";
    const label =
      (appliance?.display_name || "").trim() ||
      (appliance?.host || "").replace(/^https?:\/\//, "") ||
      `#${id}`;
    state.syncingApplianceIds.add(id);
    state.applianceId = id;
    state.panelMeta = null;
    renderApplianceList(true);
    try {
      await fetchJSON(`/api/appliances/${id}/scrape?force=1`, { method: "POST" });
      await loadAppliances();
      await refreshStatus();
      if (state.viewMode === "dashboard") {
        await loadDashboard(state.dashboardId, { forceFull: true });
      }
      showToast(
        wasOffline ? `Retry complete · ${label}` : `Sync complete · ${label}`,
        { type: "ok" }
      );
    } catch (err) {
      await loadAppliances();
      await refreshStatus();
      showToast(
        err.message || (wasOffline ? `Retry failed · ${label}` : `Sync failed · ${label}`),
        { type: "err", duration: 4500 }
      );
    } finally {
      state.syncingApplianceIds.delete(id);
      renderApplianceList(true);
    }
    return true;
  }
  return false;
}
