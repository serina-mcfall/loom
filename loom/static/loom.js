"use strict";

// Glyph AND word. Colour is never the only carrier of meaning.
const STATE_LABEL = {
  waiting: "⛔ waiting", working: "▶ working", idle: "○ idle",
  stale: "✕ stale", stopped: "■ stopped", unknown: "? unknown", none: "– none",
};

const el = (id) => document.getElementById(id);

// null/undefined in the snapshot means CANNOT TELL, never zero. Rendering it as
// "?" is the whole point of audit finding H3: `String(null)` gave "null", and
// `t.dirty || {}` quietly turned an unmeasurable tree back into a row of zeros,
// so a worktree 12 ahead with 9 dirty files whose git calls failed looked
// identical to one in perfect sync. The footer's git:worktree-facts source says
// which trees and why.
const num = (v) => (v === null || v === undefined ? "?" : String(v));
const dirtyTotal = (d) =>
  d === null || d === undefined
    ? "?"
    : String((d.staged || 0) + (d.unstaged || 0) + (d.untracked || 0));
const text = (tag, value, className) => {
  const n = document.createElement(tag);
  n.textContent = value;
  if (className) n.className = className;
  return n;
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
    const li = text("li", "", "needs-item");
    li.append(text("span", `[${item.rank}]`, "rank"));
    li.append(text("strong", ` ${item.subject} `));
    li.append(text("span", `— ${item.detail}`));
    list.append(li);
  }
}

function renderTrees(trees) {
  const body = el("trees").tBodies[0];
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

function renderCollisions(collisions, trees) {
  const table = el("collisions");
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

function renderPrs(repo) {
  const box = el("prs");
  box.replaceChildren();
  // collect() emits gh:prs and gh:issues SEPARATELY — never a source named "gh".
  // Matching on "gh" meant this banner could never render, so a failed fetch showed
  // as an empty list with no explanation: the exact failure the spec forbids.
  const broken = repo.sources.filter((s) => s.name.startsWith("gh") && !s.ok);
  if (broken.length) {
    box.append(text("p", broken.map((s) => `${s.name} unavailable — ${s.error}`).join("; "),
                    "src--bad"));
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

function renderSources(sources) {
  const list = el("sources");
  list.replaceChildren();
  for (const s of sources) {
    list.append(text("li", s.ok ? `✓ ${s.name}` : `✕ ${s.name}: ${s.error}`,
                     s.ok ? "src--ok" : "src--bad"));
  }
}

function render(snapshot) {
  const repo = snapshot.repos[0];
  if (!repo) return;
  el("summary").textContent =
    `${repo.name} — ${repo.worktrees.length} trees, ${repo.prs.length} PRs, ${repo.issues.length} issues`;
  renderNeeds(repo.needs_you || []);
  renderTrees(repo.worktrees);
  renderCollisions(repo.collisions, repo.worktrees);
  renderPrs(repo);
  renderSources(repo.sources);
  el("ticker").replaceChildren(
    ...repo.commits.slice(0, 12).map((c) =>
      text("li", `${c.when.slice(11, 16)} ${c.branch} ${c.subject}`)));
}

const source = new EventSource("/events");
source.onmessage = (e) => {
  el("conn").textContent = "● live";
  el("conn").className = "conn src--ok";
  render(JSON.parse(e.data));
};
source.onerror = () => {
  el("conn").textContent = "✕ disconnected";
  el("conn").className = "conn src--bad";
};
