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

/** A numeric table cell: colour reinforces the printed number, never replaces it.
 *  `value === null` means unmeasurable, and gets "?" in dim italic -- a rendering
 *  no actual count could be confused with, even in greyscale. */
function cell(display, value, classWhenNonZero) {
  if (value === null || value === undefined) return text("td", display, "n--unknown");
  return text("td", display, value ? classWhenNonZero : "n--zero");
}

// Which colour a PR's review or check state earns. A lookup, not a decision about
// what matters -- the state word itself is always printed next to it.
const REVIEW_CLASS = {
  APPROVED: "st--good", CHANGES_REQUESTED: "st--bad", REVIEW_REQUIRED: "st--warn",
};
const CHECK_CLASS = {
  passing: "st--good", failing: "st--bad", pending: "st--warn", none: "st--dim",
};

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
    // The rank class only colours what the text already says. `[3]` is printed in
    // the chip and the reason is spelled out in `detail`, so a viewer who cannot
    // distinguish the ramp loses nothing.
    const li = text("li", "", `needs-item rank--${item.rank}`);
    li.append(text("span", `[${item.rank}]`, "rank"));
    // `show_repo` is decided in loom.view.aggregate_needs -- the page does not
    // work out whether the repo name is worth the clutter.
    if (item.show_repo) li.append(text("span", `${item.repo} · `, "repo-tag"));
    li.append(text("strong", `${item.subject} `));
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
    // Colour only reinforces the number that is already printed. An unmeasurable
    // fact reads "?" in italic dim, which no number could be mistaken for.
    tr.append(cell(num(t.ahead), t.ahead, "n--ahead"));
    tr.append(cell(num(t.behind), t.behind, "n--behind"));
    const dt = dirtyTotal(t.dirty);
    tr.append(cell(dt, dt === "?" ? null : Number(dt), "n--dirty"));
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
      // The colour is layered on top of the word, never instead of it.
      const hit = c.branches.includes(label);
      tr.append(text("td", hit ? "collides" : "—", hit ? "collide" : "collide--no"));
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
    const li = document.createElement("li");
    li.append(text("span", `#${p.number} `, "pr-num"));
    li.append(text("span", p.branch, "pr-branch"));
    li.append(text("span", " — "));
    const review = p.review || "no review";
    li.append(text("span", review, REVIEW_CLASS[p.review] || "st--warn"));
    li.append(text("span", ", checks "));
    li.append(text("span", p.checks, CHECK_CLASS[p.checks] || "st--dim"));
    list.append(li);
  }
  for (const i of repo.issues) {
    const li = document.createElement("li");
    li.append(text("span", `#${i.number} `, "issue-num"));
    li.append(text("span", i.title));
    if (i.labels && i.labels.length) {
      li.append(text("span", ` [${i.labels.join(", ")}]`, "issue-label"));
    }
    list.append(li);
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
  ol.replaceChildren();
  for (const c of (commits || []).slice(0, 12)) {
    const li = document.createElement("li");
    // Time first and tinted, so the eye can walk the column vertically instead of
    // re-reading each line to find where it starts.
    li.append(text("span", c.when.slice(11, 16) + " ", "c-time"));
    if (c.branch) li.append(text("span", c.branch + " ", "c-branch"));
    li.append(text("span", c.subject));
    ol.append(li);
  }
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

/** A height-capped, vertically scrollable region. Focusable and named for the same
 *  reason `scrollBox` is: if it scrolls, a keyboard user must be able to reach and
 *  scroll it, and a screen reader must not announce an unlabelled group. */
function capBox(labelledBy, child) {
  const div = document.createElement("div");
  div.className = "capped";
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

  // Both tables get double width: six columns, and one column per branch, do not
  // fit a 20rem cell. Widening beats abbreviating the headers to glyphs.
  const treesTable = tableWith(["Tree", "Branch", "Agent", "Ahead", "Behind", "Dirty"]);
  const treesPanel = panel(`repo-${i}-trees-h`, "Worktrees", "h3",
                           scrollBox(`repo-${i}-trees-h`, treesTable));
  treesPanel.classList.add("panel--wide");
  panels.append(treesPanel);

  const collTable = tableWith(["File"], "Files changed by more than one worktree");
  const collPanel = panel(`repo-${i}-coll-h`, "Collisions", "h3",
                          scrollBox(`repo-${i}-coll-h`, collTable));
  collPanel.classList.add("panel--wide");
  panels.append(collPanel);

  // Capped and scrollable: a repo with 34 open issues would otherwise stretch its
  // panel far past everything beside it. `capBox` makes the scroll region
  // focusable, because a region that scrolls must be operable without a mouse.
  const prsBox = document.createElement("div");
  panels.append(panel(`repo-${i}-prs-h`, "Pull requests & issues", "h3",
                      capBox(`repo-${i}-prs-h`, prsBox)));

  const ticker = document.createElement("ol");
  ticker.className = "ticker";
  panels.append(panel(`repo-${i}-ticker-h`, "Commits", "h3",
                      capBox(`repo-${i}-ticker-h`, ticker)));

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
