import { fetchJSON } from "./api.js";

let catalog = null;
let loadPromise = null;

export async function loadLocationCatalog() {
  if (catalog) return catalog;
  if (!loadPromise) {
    loadPromise = fetchJSON("/api/locations")
      .then((data) => {
        catalog = data || { suggestions: [], locations: [] };
        return catalog;
      })
      .catch((err) => {
        loadPromise = null;
        throw err;
      });
  }
  return loadPromise;
}

export function getLocationCatalog() {
  return catalog;
}

export function resetLocationCatalog() {
  catalog = null;
  loadPromise = null;
}

function suggestionHaystack(s) {
  return [s.label, s.country, s.region, s.continent, ...(s.aliases || [])]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function filterSuggestions(suggestions, query, limit = 12) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) {
    // Light default list when focused with empty query.
    return suggestions.slice(0, limit);
  }
  const scored = [];
  for (const s of suggestions) {
    const hay = suggestionHaystack(s);
    const label = String(s.label || "").toLowerCase();
    let score = -1;
    if (label.startsWith(q)) score = 100;
    else if (label.includes(q)) score = 80;
    else if (hay.includes(q)) score = 50;
    else {
      // Match all tokens (e.g. "us oregon", "california")
      const tokens = q.split(/\s+/).filter(Boolean);
      if (tokens.length && tokens.every((t) => hay.includes(t))) score = 40;
    }
    if (score >= 0) scored.push({ s, score });
  }
  scored.sort((a, b) => b.score - a.score || a.s.label.localeCompare(b.s.label));
  return scored.slice(0, limit).map((x) => x.s);
}

/**
 * Optional location autocomplete. Picks a catalog key into hidden input[name=location].
 * Free text that doesn't match a suggestion clears the key on blur (location stays optional).
 */
export async function initLocationFields(root, { selectedKey = "", previousLabel = "" } = {}) {
  if (!root) return;
  const hidden = root.querySelector("input[name=location]");
  const search = root.querySelector("input[name=location_search]");
  const list = root.querySelector(".location-suggestions");
  const prevNote = root.querySelector(".location-previous-note");
  if (!hidden || !search || !list) return;

  const data = await loadLocationCatalog();
  const suggestions = data.suggestions || data.locations || [];

  let currentKey = suggestions.some((s) => s.key === selectedKey) ? selectedKey : "";
  const known = Boolean(currentKey);
  const selected = suggestions.find((s) => s.key === currentKey);

  hidden.value = currentKey;
  search.value = selected ? selected.label : "";

  if (prevNote) {
    if (!known && previousLabel) {
      prevNote.hidden = false;
      prevNote.textContent = `Previous location: ${previousLabel} — type to pick a suggestion.`;
    } else {
      prevNote.hidden = true;
      prevNote.textContent = "";
    }
  }

  let activeIndex = -1;
  let visible = [];

  const hideList = () => {
    list.hidden = true;
    list.innerHTML = "";
    activeIndex = -1;
    visible = [];
  };

  const applyChoice = (item) => {
    if (!item) return;
    currentKey = item.key;
    hidden.value = item.key;
    search.value = item.label;
    hideList();
  };

  const clearChoice = () => {
    currentKey = "";
    hidden.value = "";
  };

  const renderList = (items) => {
    visible = items;
    activeIndex = items.length ? 0 : -1;
    if (!items.length) {
      list.innerHTML = `<li class="location-suggestion-empty">No matches — leave blank or try another search</li>`;
      list.hidden = false;
      return;
    }
    list.innerHTML = items
      .map(
        (s, i) =>
          `<li role="option" class="location-suggestion${i === activeIndex ? " is-active" : ""}" data-key="${escapeAttr(
            s.key
          )}" data-index="${i}">${escapeHtml(s.label)}</li>`
      )
      .join("");
    list.hidden = false;
  };

  const refresh = () => {
    renderList(filterSuggestions(suggestions, search.value));
  };

  search.onfocus = () => refresh();
  search.oninput = () => {
    // Typing invalidates prior selection until a suggestion is chosen.
    const current = suggestions.find((s) => s.key === currentKey);
    if (!current || search.value !== current.label) {
      clearChoice();
    }
    refresh();
  };

  search.onkeydown = (e) => {
    if (list.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      refresh();
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!visible.length) return;
      activeIndex = (activeIndex + 1) % visible.length;
      renderList(visible);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!visible.length) return;
      activeIndex = (activeIndex - 1 + visible.length) % visible.length;
      renderList(visible);
    } else if (e.key === "Enter") {
      if (!list.hidden && activeIndex >= 0 && visible[activeIndex]) {
        e.preventDefault();
        applyChoice(visible[activeIndex]);
      }
    } else if (e.key === "Escape") {
      hideList();
    }
  };

  search.onblur = () => {
    // Delay so suggestion mousedown/click can run first.
    setTimeout(() => {
      const exact = suggestions.find(
        (s) => s.label.toLowerCase() === String(search.value || "").trim().toLowerCase()
      );
      if (exact) {
        applyChoice(exact);
      } else if (!hidden.value) {
        // Optional: unmatched text is cleared so we never store free-text.
        search.value = "";
        clearChoice();
      } else {
        const keep = suggestions.find((s) => s.key === hidden.value);
        search.value = keep ? keep.label : "";
      }
      hideList();
    }, 120);
  };

  list.onmousedown = (e) => {
    const li = e.target.closest("[data-key]");
    if (!li) return;
    e.preventDefault();
    const item = suggestions.find((s) => s.key === li.getAttribute("data-key"));
    applyChoice(item);
  };
}

export function readLocationKey(root) {
  const hidden = root?.querySelector("input[name=location]");
  return String(hidden?.value || "").trim();
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}
