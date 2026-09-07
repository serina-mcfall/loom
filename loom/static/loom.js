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

// Display text for loom/cost.py's enumerated unknown_reason values -- a
// fixed, machine-shaped set (loom/cost.py's UNKNOWN_REASONS), same as
// STATE_LABEL above: the DECISION of what unknown_reason IS was already
// made in Python; this only formats it for reading, same as glyph+word
// does for a session state.
const REASON_LABEL = {
  "no-session": "no matching session",
  "transcript-missing": "transcript not found",
  "unreadable": "transcript could not be read",
  "no-usage-records": "no usage records yet",
  "missing-bucket": "a token bucket was missing",
  "unknown-model": "unrecognised model",
};

const BADGE_CLASS = {
  live: "src--ok", connecting: "", stale: "src--warn", error: "src--bad",
  disconnected: "src--bad", incompatible: "src--bad",
};

const el = (id) => document.getElementById(id);
const text = (tag, value, className) => {
  const n = document.createElement(tag);
  n.textContent = value;
  if (className) n.className = className;
  return n;
};

/** The same rendering `text()` always did, except when `url` is truthy: then
 *  it's a real `<a>` instead of a bare `tag`, opening in a new tab (this is a
 *  live, auto-refreshing dashboard -- navigating away in the same tab loses
 *  the SSE connection until you come back) with rel="noopener noreferrer",
 *  which is not optional on a target="_blank" link -- its absence is a real
 *  security hole (reverse tabnabbing). A trailing visually-hidden span warns
 *  assistive tech about the new tab BEFORE it opens, matching WCAG's own
 *  guidance for links that change context without asking. `url` is null for
 *  every "no GitHub remote" / "no matching PR" case already threaded through
 *  the Python side -- this function makes no decision about when a link
 *  should exist, it only renders the one it's handed. */
function linkOrText(tag, value, className, url) {
  if (!url) return text(tag, value, className);
  const a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.textContent = value;
  if (className) a.className = className;
  a.append(text("span", " (opens in a new tab)", "visually-hidden"));
  return a;
}

/** renderTrees/renderPrs/renderTicker/renderNeeds all call .replaceChildren()
 *  UNCONDITIONALLY on every SSE tick (every 2s) -- fine while their content
 *  held nothing focusable, but now that they render real links, a keyboard
 *  user who tabs onto one loses focus to <body> the moment the next tick
 *  fires, often well under the time it takes to actually read the link and
 *  press Enter. Confirmed live, 2026-09-07: a marked DOM node was a
 *  different object 3 seconds later.
 *  This wraps a render call to restore focus afterward, keyed by the link's
 *  own `href` -- a stable identity that survives the element being
 *  destroyed and recreated, unlike DOM position, which a reorder or
 *  insertion elsewhere in the same list would silently point at the wrong
 *  row. If nothing with that href exists in the fresh render (its PR
 *  merged, its commit aged out of the ticker), focus is not force-relocated
 *  -- it falls back to whatever the browser does by default for any
 *  element removed while focused, same as it always has.
 *  TRADE-OFF, stated plainly rather than hidden: the restored element is a
 *  NEW DOM node, not the same one, so a screen reader announces it again on
 *  every tick a focused link's row happens to re-render. Less disruptive
 *  than silently losing focus to <body>, but not free -- a full keyed-diff
 *  reconciliation (reusing the same DOM nodes across renders entirely)
 *  would avoid the re-announcement too, at the cost of restructuring all
 *  four render functions from wholesale rebuilds into field-level patches.
 *  Deliberately not attempted here: real, but separable engineering, not
 *  this fix's job. */
function preservingFocus(container, render) {
  const active = document.activeElement;
  let focusedHref = null;
  let ordinal = 0;
  if (active && active.tagName === "A" && container.contains(active)) {
    focusedHref = active.href;
    // TWO REAL GAPS in a first draft, found by an independent codex
    // review, 2026-09-07, both fixed here:
    //  1. `href` alone is not always a unique identity -- two worktrees
    //     can share the same PR, so two links can share the same href.
    //     `.find()` always returned the FIRST one, silently moving focus
    //     to the wrong row when the SECOND was the one actually focused.
    //     Fixed by also recording this link's ORDINAL among same-href
    //     matches before the render, then restoring to the same ordinal
    //     after -- a much weaker, more reliable assumption than absolute
    //     DOM position, and correct even when multiple rows genuinely do
    //     share one href.
    //  2. `.focus()` scrolls its target into view by default. If a user
    //     focused a link, then scrolled elsewhere (in the page or inside
    //     a capped panel) WITHOUT changing focus, the next tick's
    //     restoration would silently yank the scroll position back.
    //     `preventScroll: true` (below) stops that.
    const matches = [...container.querySelectorAll("a")].filter((a) => a.href === focusedHref);
    ordinal = matches.indexOf(active);
  }
  render();
  if (focusedHref) {
    const matches = [...container.querySelectorAll("a")].filter((a) => a.href === focusedHref);
    const match = matches[ordinal] || matches[0];
    if (match) match.focus({ preventScroll: true });
  }
}

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

// The announcement is debounced: a region firing every 2s makes a screen reader
// unusable. It is a SEPARATE hidden region that stays permanently polite -- the
// visible list is no longer a live region at all, because toggling `aria-live` is
// not reliably honoured by readers. Audit finding M8.
let lastAnnounce = 0;
let lastAnnounced = "";
const ANNOUNCE_EVERY_MS = 15000;

/** Write the summary sentence only when it has changed AND enough time has passed.
 *  Both conditions matter: unchanged text should not be repeated at all, and text
 *  that changes every tick still must not be read out every tick. */
function announce(sentence) {
  if (!sentence || sentence === lastAnnounced) return;
  const now = Date.now();
  if (now - lastAnnounce < ANNOUNCE_EVERY_MS) return;
  lastAnnounce = now;
  lastAnnounced = sentence;
  el("needs-announce").textContent = sentence;
}

function renderNeeds(items) {
  const list = el("needs");
  // The hero glow is a signal of urgency, not decoration -- it must be OFF
  // whenever the fleet is genuinely quiet, so this toggles on the item count,
  // never on a fixed class. list.closest("section") is the `.panel--needs`
  // element itself (see index.html), not the <ul>.
  list.closest("section").classList.toggle("is-active", items.length > 0);
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
    // `item.subject` is already exactly "PR #N " for the two kinds that ever
    // carry `pr_url` (loom/rank.py's pr_failing/pr_awaiting_review) -- the
    // whole subject becomes the link, no substring parsing needed. Linking
    // swaps the tag from <strong> to <a>, so "needs-subject" carries the
    // bold weight in loom.css regardless of which one rendered.
    li.append(linkOrText("strong", item.subject.trimEnd(), "needs-subject", item.pr_url));
    li.append(text("span", ` — ${item.detail}`));
    list.append(li);
  }
}

/** Issue #11's per-worktree ask: the model, four token buckets, and a
 *  notional cost. `cost.unknown_reason` means every number in it is None
 *  (loom/cost.py's own contract -- one shape, only the numbers go missing),
 *  so this prints the reason IN WORDS (via REASON_LABEL) in one spanning
 *  cell, never a bare "?" or a raw developer-facing slug like
 *  "missing-bucket" that would say something is missing without saying
 *  why in a sentence a reader can act on. */
function appendCostCells(tr, cost) {
  if (!cost || cost.unknown_reason) {
    const reason = (cost && cost.unknown_reason) || "?";
    const label = REASON_LABEL[reason] || reason;
    const td = text("td", label, "n--unknown");
    td.colSpan = 6;
    tr.append(td);
    return;
  }
  // `models` carries every model a mixed-model session touched (OPEN-6),
  // each with its own notional_cost_usd share AND its token share
  // (loom/cost.py sum_cost()'s own docstring). More than one entry means
  // the row shows the breakdown rather than only the winning model, so a
  // mixed-model session is never reported as if it ran on a single one --
  // and the breakdown now reads both shares, not only the cost one, so
  // the token share that was already being computed reaches a reader.
  const fmt = (v) => (v === null || v === undefined ? "?" : `$${v.toFixed(2)}`);
  const modelText = cost.models && cost.models.length > 1
    ? cost.models.map((m) => {
        const mt = m.tokens || {};
        return `${m.model} (${fmt(m.notional_cost_usd)}; `
          + `input=${num(mt.input)} cache_write=${num(mt.cache_write)} `
          + `cache_read=${num(mt.cache_read)} output=${num(mt.output)})`;
      }).join(", ")
    : cost.model || "?";
  tr.append(text("td", modelText, "cost-model"));
  const t = cost.tokens || {};
  // The four DISPLAY buckets come straight off the tokens dict. cache_write
  // is ALREADY the 5m + 1h sum computed in loom/cost.py's sum_cost() -- read
  // here, never added. No arithmetic on token counts happens in this file.
  tr.append(cell(num(t.input), t.input, "n--tok"));
  tr.append(cell(num(t.cache_write), t.cache_write, "n--tok"));
  tr.append(cell(num(t.cache_read), t.cache_read, "n--tok"));
  tr.append(cell(num(t.output), t.output, "n--tok"));
  tr.append(text("td", fmt(cost.notional_cost_usd), "cost-figure"));
}

function renderTrees(body, trees) {
  body.replaceChildren();
  for (const t of trees) {
    const tr = document.createElement("tr");
    const th = text("th", t.dir);
    th.scope = "row";
    tr.append(th, text("td", t.branch || "detached"));
    // `pr` links this tree to the review waiting on it. Em dash, not blank, so an
    // empty cell is never mistaken for a rendering failure.
    const prTd = document.createElement("td");
    prTd.append(t.pr
      ? linkOrText("span", `#${t.pr}`, "pr-num", t.pr_url)
      : text("span", "—", "st--dim"));
    tr.append(prTd);
    const state = (t.agent && t.agent.state) || "none";
    // A tinted, rounded chip -- visual only. The glyph and word inside are
    // exactly what STATE_LABEL always printed; nothing here changes what a
    // screen reader announces, only adds a background.
    const stateTd = document.createElement("td");
    stateTd.append(text("span", STATE_LABEL[state] || state, `chip chip--${state}`));
    tr.append(stateTd);
    // Colour only reinforces the number that is already printed. An unmeasurable
    // fact reads "?" in italic dim, which no number could be mistaken for.
    tr.append(cell(num(t.ahead), t.ahead, "n--ahead"));
    tr.append(cell(num(t.behind), t.behind, "n--behind"));
    const dt = dirtyTotal(t.dirty);
    tr.append(cell(dt, dt === "?" ? null : Number(dt), "n--dirty"));
    appendCostCells(tr, t.cost);
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
    li.append(linkOrText("span", `#${p.number}`, "pr-num", p.url));
    li.append(text("span", ` ${p.branch}`, "pr-branch"));
    li.append(text("span", " — "));
    const review = p.review || "no review";
    li.append(text("span", review, REVIEW_CLASS[p.review] || "st--warn"));
    li.append(text("span", ", checks "));
    li.append(text("span", p.checks, CHECK_CLASS[p.checks] || "st--dim"));
    // `updated_at` was fetched from gh and rendered nowhere (L2). Date only: the
    // exact minute is noise next to "which of these has gone quiet".
    if (p.updated_at) {
      li.append(text("span", `, updated ${p.updated_at.slice(0, 10)}`, "c-time"));
    }
    list.append(li);
  }
  for (const i of repo.issues) {
    const li = document.createElement("li");
    li.append(linkOrText("span", `#${i.number}`, "issue-num", i.url));
    li.append(text("span", ` ${i.title}`));
    if (i.labels && i.labels.length) {
      li.append(text("span", ` [${i.labels.join(", ")}]`, "issue-label"));
    }
    list.append(li);
  }
  if (repo.prs.length === 0 && repo.issues.length === 0) {
    list.append(text("li", "No open pull requests or issues."));
  }
  box.append(list);
  // L7: the spec's Refresh table says "cached age is displayed" and its Panels table
  // says "how stale the cached ones are". `gh_cached_at` was produced by
  // apply_gh_cache and displayed nowhere, so both promises were unkept.
  if (repo.gh_cached_at) {
    box.append(text("p", `gh data cached at ${repo.gh_cached_at}`, "cached-at"));
  }
}

/** L6: orphan PRs and directories that are no longer worktrees.
 *
 *  These were only ever visible as rank 6 in the triage strip, so the strip had to
 *  explain them with no panel behind it. `severity` is carried in the data and
 *  reinforced with colour, but the `kind` is always spelled out in words. */
function renderLoose(list, flags) {
  list.replaceChildren();
  if (!flags || flags.length === 0) {
    list.append(text("li", "No loose ends.", "st--dim"));
    return;
  }
  for (const f of flags) {
    const li = document.createElement("li");
    li.append(text("span", f.kind.replace(/_/g, " ") + " ",
                   f.severity === "warn" ? "st--warn" : "st--dim"));
    li.append(text("strong", f.subject));
    if (f.detail) li.append(text("span", ` — ${f.detail}`));
    list.append(li);
  }
}

/** `heading` is the closed-by-default <details>'s visible <h3>, inside its
 *  <summary>. A failing source used to be a Python-side "honesty channel"
 *  (loom/collect.py, audit finding H3): a per-worktree failure must never
 *  render as a confident number with no explanation nearby. Folding this
 *  panel shut (this reskin) re-created exactly that hole -- a real failure
 *  sat inside collapsed content, invisible until a manual click. Appending
 *  the failing count to the heading restores the signal WITHOUT forcing
 *  `open`, which would fight a user who closed it on purpose and could
 *  steal focus. Found by review-a11y, 2026-09-07. */
function renderSources(list, sources, heading) {
  list.replaceChildren();
  let failing = 0;
  for (const s of sources) {
    if (!s.ok) failing++;
    list.append(text("li", s.ok ? `✓ ${s.name}` : `✕ ${s.name}: ${s.error}`,
                     s.ok ? "src--ok" : "src--bad"));
  }
  heading.textContent = failing > 0
    ? `Data sources — ${failing} failing`
    : "Data sources";
}

function renderTicker(ol, commits) {
  ol.replaceChildren();
  for (const c of (commits || []).slice(0, 12)) {
    const li = document.createElement("li");
    // Time first and tinted, so the eye can walk the column vertically instead of
    // re-reading each line to find where it starts.
    li.append(text("span", c.when.slice(11, 16) + " ", "c-time"));
    if (c.branch) li.append(text("span", c.branch + " ", "c-branch"));
    li.append(text("span", `${c.subject} `));
    // sha, files and the +/- totals were all collected and rendered nowhere (L2).
    // The sha is what you need to `git show` the thing you just read about.
    li.append(linkOrText("span", c.sha, "c-sha", c.url));
    if (c.files) {
      li.append(text("span", ` ${c.files}f `, "st--dim"));
      li.append(text("span", `+${c.add}`, "st--good"));
      li.append(text("span", ` \u2212${c.dele}`, "st--bad"));
    }
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

  // h1 Loom > h2 repo name > h3 panels. One heading per repo.
  //
  // The heading is the repo NAME ONLY. It used to also carry the tree/PR/issue
  // counts, which meant the section's accessible name changed every 2 seconds --
  // a moving landmark label, which is disorienting to navigate by. The counts and
  // the repo's identity live in a plain paragraph below instead.
  const heading = text("h2", repo.name);
  heading.id = headId;
  const meta = text("p", "", "repo-meta");
  section.append(heading, meta);

  const panels = document.createElement("div");
  panels.className = "panels";

  // Both tables get double width: thirteen columns now (seven git-state
  // columns plus issue #11's six cost columns), and one column per branch
  // do not fit a 20rem cell. Widening beats abbreviating the headers to
  // glyphs.
  // The last six columns are issue #11's per-worktree ask (step 8): model,
  // the four DISPLAY token buckets, and a notional cost. "tokens" is named
  // in the caption, not repeated per header, because a screen reader
  // announces the caption once for the table and then every header on
  // every cell -- "Input tokens" on every row would be read as often as
  // there are rows.
  const treesTable = tableWith(
      ["Tree", "Branch", "PR", "Agent", "Ahead", "Behind", "Dirty",
       "Model", "Input", "Cache write", "Cache read", "Output", "Cost"],
      "Worktrees — git state, plus notional token cost from local transcripts");
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

  const loose = document.createElement("ul");
  panels.append(panel(`repo-${i}-loose-h`, "Loose ends", "h3",
                      capBox(`repo-${i}-loose-h`, loose)));

  // Native <details>/<summary> for the toggle, inside the SAME
  // <section aria-labelledby>+<h3> shape every other panel uses -- a first
  // draft dropped both the heading and the landmark region entirely (found
  // by review-a11y, 2026-09-07: heading navigation and the landmark rotor
  // both lost this panel, even though it stayed in reading/Tab order). The
  // <details>/<summary> still is the disclosure: keyboard-operable and
  // correctly announced with zero custom ARIA, the W3C APG pattern for
  // free. "Data sources" now lives in a real, visible <h3> inside
  // <summary>, so the old visually-hidden-heading trick is gone -- the
  // landmark region holds regardless, but heading navigation finding the
  // nested <h3> is NOT guaranteed across every browser/AT combination
  // (some flatten a <summary>'s descendant roles); not re-verified against
  // a real matrix, disclosed rather than claimed. Found by an independent
  // codex review, 2026-09-07 -- this comment previously stated the
  // opposite as fact.
  // Mirrors panel() (above, this file) by hand rather than calling it: the
  // heading has to live INSIDE <summary>, which panel()'s fixed
  // section+heading+body shape can't express. If panel() ever changes
  // (a new class, a new attribute, a different landmark role), this block
  // needs the same change made twice -- noted here on purpose, since a
  // silently-skipped panel is exactly the class of bug review-a11y just
  // found on this one. Found by review-final, 2026-09-07.
  const sources = document.createElement("ul");
  sources.className = "sources";
  const srcHeadingId = `repo-${i}-src-h`;
  const srcHeading = text("h3", "Data sources");
  srcHeading.id = srcHeadingId;
  const srcSummary = document.createElement("summary");
  srcSummary.append(srcHeading);
  const srcDetails = document.createElement("details");
  srcDetails.append(srcSummary, sources);
  const srcSection = document.createElement("section");
  srcSection.className = "panel";
  srcSection.setAttribute("aria-labelledby", srcHeadingId);
  srcSection.append(srcDetails);
  panels.append(srcSection);

  section.append(panels);
  return {
    section,
    refs: { heading, meta, treesBody: treesTable.tBodies[0], collTable, prsBox,
            ticker, loose, sources, srcHeading },
  };
}

// Skeletons are rebuilt ONLY when the set of repo names changes. Rebuilding every
// tick would move focus to <body> every 2 seconds for anyone tabbed into a scroll
// container -- introducing an accessibility defect while fixing one. This is a
// narrow, already-accepted limitation, not a new one: a rebuild already resets
// scroll position in the capped/scroll regions, and now also resets the Data
// sources <details> to closed and drops focus if it was on the summary --
// found by review-a11y, 2026-09-07, and left as-is: it fires only when a repo
// appears, disappears, or is renamed in config, the same rare trigger the
// scroll-position loss already accepted.
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
    // `issue_repo` is which GitHub repository every `gh` call was pinned to, and
    // `default_branch` is what ahead/behind is measured against -- both were
    // produced and rendered nowhere (L2). Shown here because when
    // `git:default-branch` degrades to a guess, seeing WHICH branch it guessed is
    // the difference between a warning and an actionable one.
    const n = (c, one, many) => `${c} ${c === 1 ? one : many}`;
    r.meta.replaceChildren();
    if (repo.issue_repo) r.meta.append(text("span", repo.issue_repo, "pr-branch"));
    r.meta.append(text("span", ` · ${repo.default_branch || "?"} · `, "c-branch"));
    r.meta.append(text("span",
      [n(repo.worktrees.length, "tree", "trees"),
       n(repo.prs.length, "PR", "PRs"),
       n(repo.issues.length, "issue", "issues")].join(" · ")));
    preservingFocus(r.treesBody, () => renderTrees(r.treesBody, repo.worktrees));
    // renderCollisions/renderLoose/renderSources are NOT wrapped in preservingFocus:
    // none of the three renders a focusable node today (renderSources' <details>
    // summary lives outside the list this rebuilds). CORRECTED (found by
    // review-a11y, confirmed by review-adjudicate, 2026-09-07): the plan's own
    // LEFT OUT section names linking Loose ends' orphaned-PR references as an
    // easy follow-up, "the identical shape to needs-you's PR links" -- the moment
    // renderLoose renders a link, it MUST be wrapped the same way renderNeeds is,
    // or focus is lost to <body> on every 2-second tick, same as before this fix.
    renderCollisions(r.collTable, repo.collisions, repo.worktrees);
    preservingFocus(r.prsBox, () => renderPrs(r.prsBox, repo));
    preservingFocus(r.ticker, () => renderTicker(r.ticker, repo.commits));
    renderLoose(r.loose, repo.flags);
    renderSources(r.sources, repo.sources, r.srcHeading);
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

let lastConfigWarning = null;

function renderConfigWarning(config) {
  const missing = (config && config.missing) || [];
  const text = missing.length
    ? `${missing.join(", ")} named in ${config.source} but no such repo was found — ` +
      "check the spelling"
    : "";
  if (text === lastConfigWarning) return;
  lastConfigWarning = text;
  const el_ = el("config-warning");
  el_.textContent = text;
  el_.hidden = !text;
}

/** The fleet-wide total loom.view.fleet_total computed, its four session
 *  counts, and the excluded-worktree count. Plain text, deliberately no
 *  live-region behaviour -- step 9 decided against one; see index.html's
 *  comment on #cost-h for why. */
function renderCostTotal(cost) {
  const section = el("cost-h").closest("section");
  const totalEl = el("cost-total");
  const sessionsEl = el("cost-sessions");
  if (!cost) {
    // Hide rather than leave a named region holding an empty heading and
    // two empty paragraphs -- a landmark a reader enters to nothing looks
    // like a rendering failure, not an unmeasured state.
    section.hidden = true;
    return;
  }
  section.hidden = false;
  totalEl.textContent = cost.label || "";
  // Read straight off snap["cost"] -- loom.view.fleet_total already summed
  // these across every worktree. This file does not sum them again.
  // "sessions:" names the subject of the four bare numbers that follow --
  // matching loom_cli.py's own "  sessions: live=... " line, which a
  // screen-reader user hears the same way a terminal reader does.
  // excluded_count is ALSO already folded into cost.label's prose (OPEN-2)
  // -- printed again here as its own bare figure is the same duplication
  // the four session counts already have between the label and this line,
  // not a new pattern, and it is the only place excluded_count reaches a
  // reader as a number rather than only inside a sentence.
  sessionsEl.textContent =
    `sessions: live ${cost.live_sessions}, stale ${cost.stale_sessions}, ` +
    `stopped ${cost.stopped_sessions}, undated ${cost.undated_sessions}; ` +
    `excluded ${cost.excluded_count} worktree(s) (unknown cost)`;
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
  // duration_ms was produced every tick and rendered nowhere (L2). It is the
  // only visible feedback on collection cost, which finding M4 was about.
  if (snapshot.duration_ms !== undefined) {
    parts.push(`${snapshot.duration_ms}ms`);
  }
  el("summary").textContent = parts.join(" · ");

  // config.missing -- a repo named in the allow list that does not exist. Written only
  // when it changes: role="alert" is assertive, and rewriting it every 2s would talk
  // over a screen reader continuously, the same defect M7 fixed on #conn.
  renderConfigWarning(snapshot.config);

  preservingFocus(el("needs"), () => renderNeeds(snapshot.needs_you || []));
  // The sentence is decided in loom.view.announcement; the page only decides WHEN,
  // which is a timing concern it genuinely owns.
  announce(snapshot.announcement);
  renderCostTotal(snapshot.cost);
  syncRepos(repos);
}

// SILENCE IS A SIGNAL now that /events sends a frame every tick (M10).
//
// An EventSource whose server has stopped collecting -- a wedged refresh loop, a
// killed thread -- stays OPEN and simply goes quiet, so `onerror` never fires and
// the last badge would sit there reading "live" forever. This is the same hole H6
// closed from the server side, approached from the other end: the server can only
// tell the page what it knew when it last spoke.
//
// The threshold comes from the snapshot, not from a constant here, so it cannot
// drift from loom/view.py's STALE_AFTER_SECONDS.
let lastFrameAt = Date.now();
let staleAfterMs = 10000;

function checkForSilence() {
  if (Date.now() - lastFrameAt > staleAfterMs) {
    renderBadge("stale", "⚠ no update");
    el("summary").textContent =
      `no update for ${Math.round((Date.now() - lastFrameAt) / 1000)}s — ` +
      "the server may have stopped collecting";
  }
}
setInterval(checkForSilence, 1000);

const source = new EventSource("/events");
source.onmessage = (e) => {
  lastFrameAt = Date.now();
  const snapshot = JSON.parse(e.data);
  const after = snapshot.badge && snapshot.badge.stale_after_seconds;
  if (after) staleAfterMs = after * 1000;
  render(snapshot);
};
source.onerror = () => {
  // CONNECTION health, which is genuinely the page's to know -- distinct from
  // whether the data itself is fresh.
  renderBadge("disconnected", "✕ disconnected");
};
