"use strict";

// PLUMBING ONLY. Every DECISION -- is this data stale, which repos to show, how
// to label a strip item -- lives in loom/view.py where the Python suite can reach
// it. This file paints what it is handed. Audit 2026-08-05, finding H8.
//
// If you find yourself deciding something here, it belongs in loom/view.py.

// Glyph AND word. Colour is never the only carrier of meaning.
const STATE_LABEL = {
  waiting: "⛔ waiting", working: "▶ working", idle: "○ idle",
  stale: "✕ stale", stopped: "■ stopped", unknown: "? unknown", none: "– none",
};

const BADGE_CLASS = {
  live: "src--ok", connecting: "", stale: "src--warn", error: "src--bad",
  disconnected: "src--bad",
};

const el = (id) => document.getElementById(id);
const text = (tag, value, className) => {
  const n = document.createElement(tag);
  n.textContent = value;
  if (className) n.className = className;
  return n;
};

// null/undefined in the snapshot means CANNOT TELL, never zero. Rendering it as
// "?" is the whole point of audit finding H3: `String(null)` gave "null", and
// `t.dirty || {}` quietly turned an unmeasurable tree back into a row of zeros,
// so a worktree 12 ahead with 9 dirty files whose git calls failed looked
// identical to one in perfect sync. Each repo's git:worktree-facts source says
// which trees and why.
const num = (v) => (v === null || v === undefined ? "?" : String(v));
const dirtyTotal = (d) =>
  d === null || d === undefined
    ? "?"
    : String((d.staged || 0) + (d.unstaged || 0) + (d.untracked || 0));

// The live region is debounced: a 2s region makes a screen reader unusable.
let lastAnnounce = 0;
const ANNOUNCE_EVERY_MS = 15000;

function renderNeeds(items) {
  const list = el("needs");
  const now = Date.now();
  const quiet = now - lastAnnounce < ANNOUNCE_EVERY_MS;
  list.setAttribute("aria-live", quiet ? "off" : "polite");
  if (!quiet) lastAnnounce = now;

  list.replaceChildren();
  if (items.length === 0) {
    list.append(text("li", "Nothing needs you.", "needs-item"));
    return;
  }
  for (const item of items) {
    const li = text("li", "", "needs-item");
    li.append(text("span", `[${item.rank}]`, "rank"));
    // `label` is decided in loom.view.aggregate_needs: the subject alone for one
    // repo, "repo · subject" when several, so two repos each holding a "PR #7"
    // do not read as a duplicate.
    li.append(text("strong", ` ${item.label || item.subject} `));
    li.append(text("span", `— ${item.detail}`));
    list.append(li);
  }
}

function renderTrees(body, trees) {
  body.replaceChildren();
  for (const t of trees) {
    const tr = document.createElement("tr");
    const th = text("th", t.dir);
    th.scope = "row";
    tr.append(th, text("td", t.branch || "detached"));
    const state = (t.agent && t.agent.state) || "none";
    tr.append(text("td", STATE_LABEL[state] || state, `state--${state}`));
    tr.append(text("td", num(t.ahead)), text("td", num(t.behind)));
    tr.append(text("td", dirtyTotal(t.dirty)));
    body.append(tr);
  }
}

function renderCollisions(table, collisions, trees) {
  const labels = trees.map((t) => t.branch || t.dir);
  const head = table.tHead.rows[0];
  head.replaceChildren(Object.assign(text("th", "File"), { scope: "col" }));
  for (const label of labels) {
    head.append(Object.assign(text("th", label), { scope: "col" }));
  }
  const body = table.tBodies[0];
  body.replaceChildren();
  if (collisions.length === 0) {
    const tr = document.createElement("tr");
    const td = text("td", "No two worktrees are editing the same file.");
    td.colSpan = labels.length + 1;
    tr.append(td);
    body.append(tr);
    return;
  }
  for (const c of collisions) {
    const tr = document.createElement("tr");
    const th = text("th", c.file);
    th.scope = "row";
    tr.append(th);
    for (const label of labels) {
      // Text, not a dot — a screen reader must hear the same thing an eye sees.
      tr.append(text("td", c.branches.includes(label) ? "collides" : "—"));
    }
    body.append(tr);
  }
}

function renderPrs(box, repo) {
  box.replaceChildren();
  // collect() emits gh:prs and gh:issues SEPARATELY — never a source named "gh".
  // Matching on "gh" meant this banner could never render, so a failed fetch showed
  // as an empty list with no explanation: the exact failure the spec forbids.
  const broken = repo.sources.filter((s) => s.name.startsWith("gh") && !s.ok);
  if (broken.length) {
    box.append(text("p", broken.map((s) =>
      // last_good is stamped by apply_gh_cache when a fetch fails but earlier data
      // survives, which is what makes the spec's own error-honesty example
      // ("last good 4m ago") expressible at all.
      `${s.name} unavailable — ${s.error}` +
      (s.last_good ? ` (last good ${s.last_good})` : "")).join("; "), "src--bad"));
    return;
  }
  const list = document.createElement("ul");
  for (const p of repo.prs) {
    list.append(text("li", `#${p.number} ${p.branch} — ${p.review || "no review"}, checks ${p.checks}`));
  }
  for (const i of repo.issues) {
    list.append(text("li", `issue #${i.number} ${i.title}`));
  }
  if (repo.prs.length === 0 && repo.issues.length === 0) {
    list.append(text("li", "No open pull requests or issues."));
  }
  box.append(list);
}

function renderSources(list, sources) {
  list.replaceChildren();
  for (const s of sources) {
    list.append(text("li", s.ok ? `✓ ${s.name}` : `✕ ${s.name}: ${s.error}`,
                     s.ok ? "src--ok" : "src--bad"));
  }
}

function renderTicker(ol, commits) {
  ol.replaceChildren(
    ...(commits || []).slice(0, 12).map((c) =>
      text("li", `${c.when.slice(11, 16)} ${c.branch} ${c.subject}`)));
}

// ---------------------------------------------------------------- repo sections

// A scrollable region needs to be focusable so a keyboard user can scroll it, and
// needs an accessible name so it is not announced as an unlabelled group.
function scrollBox(labelledBy, child) {
  const div = document.createElement("div");
  div.className = "scroll";
  div.tabIndex = 0;
  div.setAttribute("role", "group");
  div.setAttribute("aria-labelledby", labelledBy);
  div.append(child);
  return div;
}

function panel(headingId, headingText, level, body) {
  const section = document.createElement("section");
  section.className = "panel";
  section.setAttribute("aria-labelledby", headingId);
  const h = text(level, headingText);
  h.id = headingId;
  section.append(h, body);
  return section;
}

function tableWith(headers, caption) {
  const table = document.createElement("table");
  if (caption) {
    const cap = text("caption", caption, "visually-hidden");
    table.append(cap);
  }
  const thead = document.createElement("thead");
  const row = document.createElement("tr");
  for (const label of headers) {
    row.append(Object.assign(text("th", label), { scope: "col" }));
  }
  thead.append(row);
  table.append(thead, document.createElement("tbody"));
  return table;
}

/** Build one repo's section, returning the mutable parts for later in-place updates. */
function buildRepoSection(repo, i) {
  const section = document.createElement("section");
  section.className = "repo";
  const headId = `repo-${i}-h`;
  section.setAttribute("aria-labelledby", headId);

  // h1 Loom > h2 repo name > h3 panels. One heading per repo, as agreed.
  const heading = text("h2", repo.name);
  heading.id = headId;
  section.append(heading);

  const panels = document.createElement("div");
  panels.className = "panels";

  const treesTable = tableWith(["Tree", "Branch", "Agent", "Ahead", "Behind", "Dirty"]);
  panels.append(panel(`repo-${i}-trees-h`, "Worktrees", "h3",
                      scrollBox(`repo-${i}-trees-h`, treesTable)));

  const collTable = tableWith(["File"], "Files changed by more than one worktree");
  panels.append(panel(`repo-${i}-coll-h`, "Collisions", "h3",
                      scrollBox(`repo-${i}-coll-h`, collTable)));

  const prsBox = document.createElement("div");
  panels.append(panel(`repo-${i}-prs-h`, "Pull requests & issues", "h3", prsBox));

  const ticker = document.createElement("ol");
  ticker.className = "ticker";
  panels.append(panel(`repo-${i}-ticker-h`, "Commits", "h3", ticker));

  const sources = document.createElement("ul");
  sources.className = "sources";
  const srcPanel = panel(`repo-${i}-src-h`, "Data sources", "h3", sources);
  srcPanel.querySelector("h3").classList.add("visually-hidden");
  panels.append(srcPanel);

  section.append(panels);
  return {
    section,
    refs: { heading, treesBody: treesTable.tBodies[0], collTable, prsBox, ticker, sources },
  };
}

// Skeletons are rebuilt ONLY when the set of repo names changes. Rebuilding every
// tick would move focus to <body> every 2 seconds for anyone tabbed into a scroll
// container -- introducing an accessibility defect while fixing one.
let renderedKey = null;
let repoRefs = new Map();

function syncRepos(repos) {
  const key = repos.map((r) => r.name).join(" ");
  if (key !== renderedKey) {
    const host = el("repos");
    host.replaceChildren();
    repoRefs = new Map();
    repos.forEach((repo, i) => {
      const { section, refs } = buildRepoSection(repo, i);
      host.append(section);
      repoRefs.set(repo.name, refs);
    });
    renderedKey = key;
  }
  for (const repo of repos) {
    const r = repoRefs.get(repo.name);
    if (!r) continue;
    r.heading.textContent =
      `${repo.name} — ${repo.worktrees.length} trees, ${repo.prs.length} PRs, ` +
      `${repo.issues.length} issues`;
    renderTrees(r.treesBody, repo.worktrees);
    renderCollisions(r.collTable, repo.collisions, repo.worktrees);
    renderPrs(r.prsBox, repo);
    renderTicker(r.ticker, repo.commits);
    renderSources(r.sources, repo.sources);
  }
}

// ---------------------------------------------------------------------- badge

// #conn is role="status", an implicit polite live region. Writing it only when the
// STATE changes is what stops an endless announcement queue: it used to be
// reassigned on every SSE message, i.e. every 2 seconds. The changing detail text
// goes to #summary, which is not a live region. Audit findings M7 and H6.
let lastBadgeState = null;

function renderBadge(state, label) {
  if (state === lastBadgeState) return;
  lastBadgeState = state;
  const conn = el("conn");
  conn.textContent = label;
  conn.className = `conn ${BADGE_CLASS[state] || ""}`;
}

function render(snapshot) {
  // DATA health comes from the snapshot's own badge, decided in loom/view.py.
  // It is NOT inferred from the arrival of a message: a failed refresh is exactly
  // what produces one, because adding `refresh_error` changes the serialised body.
  // That is why a green badge used to sit over frozen data. Audit finding H6.
  const badge = snapshot.badge || { state: "connecting", label: "● connecting", detail: "" };
  renderBadge(badge.state, badge.label);

  const repos = snapshot.repos || [];
  const trees = repos.reduce((n, r) => n + r.worktrees.length, 0);
  const parts = [`${repos.length} repo${repos.length === 1 ? "" : "s"}`,
                 `${trees} tree${trees === 1 ? "" : "s"}`];
  if (badge.detail) parts.push(badge.detail);
  el("summary").textContent = parts.join(" · ");

  renderNeeds(snapshot.needs_you || []);
  syncRepos(repos);
}

const source = new EventSource("/events");
source.onmessage = (e) => render(JSON.parse(e.data));
source.onerror = () => {
  // CONNECTION health, which is genuinely the page's to know -- distinct from
  // whether the data itself is fresh.
  renderBadge("disconnected", "✕ disconnected");
};
