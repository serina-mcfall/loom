# Loom — clickable PR, issue, and commit links (interactivity, round 1)

- **Date:** 2026-09-07
- **Status:** approved
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing. This is the "Spec 2 (interactivity)" work the
  2026-09-07 reskin design doc deferred — first round of it, not all of
  it. Adds `url` to the `PullRequest` and `Issue` dataclasses (additive;
  `SCHEMA_VERSION` unaffected, same reasoning as the tokens-and-cost
  design's OPEN-3) and a `pr_url` field to two `needs_you()` item
  kinds.

## The problem

Every number and sha on the dashboard is plain text. Serina asked for
the actual missing piece directly: *"jump straight to things"* — click a
PR number, a commit sha, or an issue and land on the real GitHub page,
instead of reading a number and switching tabs to look it up by hand.

## Constraints

- **Stays vanilla.** The 2026-09-07 reskin deferred React to "wherever
  it would actually earn its keep." A hyperlink is the simplest,
  most-accessible interactive element in HTML — native keyboard
  operability and screen-reader support for free, zero framework
  needed. Introducing React for this would add a build step for
  something `<a>` already does perfectly. Confirmed with Serina before
  writing this doc.
- **Decisions live in Python, not `loom.js`.** The file's own header
  comment states this outright: *"Every DECISION ... lives in
  loom/view.py ... If you find yourself deciding something here, it
  belongs in loom/view.py."* A URL is a decision (what it points to,
  whether it exists at all when there's no GitHub remote) — so it's
  computed server-side and shipped as a field, never assembled from
  parts in the browser.
- **Real URLs over reconstructed ones, where a real one is available.**
  `gh`'s own `--json url` field is the actual URL GitHub returned for a
  PR or issue — asking for it costs one string in an existing field
  list. Reconstructing `https://github.com/{owner}/{repo}/pull/{n}` by
  hand would work today (this codebase only recognizes `github.com`
  remotes at all — see `loom/ghsrc.py`'s `SSH_RE`/`HTTPS_RE`, both
  anchored to `github\.com`), but it's a guess where a real value is
  one field away for no extra cost. Commits have no such luxury —
  `git log` knows nothing about GitHub — so commit links are
  necessarily built, not fetched.

  **Correction (2026-09-07, found by an independent codex review, later
  closed the same day):** a built commit link is a *candidate*
  destination, not evidence the page exists on its own —
  `gitsrc.recent_commits()` runs `git log --all`, which includes commits
  on a branch that has never been pushed, and every one used to get a
  link regardless. Verifying each commit individually (`git merge-base
  --is-ancestor <sha> <ref>`) would cost one subprocess call per commit,
  up to 40 more per tick against this project's own measured, tested
  subprocess budget (audit finding M4) — rejected for exactly that
  reason. Closed instead with `ghsrc.remote_reachable_shas()`: ONE `git
  rev-list --remotes --since=<date>` call for the whole batch, bounded
  by the same recency window `recent_commits()` already implies, with
  membership checked in Python afterward at no further subprocess cost.
  `TestSubprocessBudget`'s budget moved from 9 to 10 to carry this,
  justified in that test itself, not slipped in silently. Verified live
  against this repo's own real history: every one of this session's
  (unpushed) commits correctly shows no link, and every already-pushed
  commit before them correctly does.

## Design

### Data model (Python)

**`loom/ghsrc.py`:** `PR_FIELDS` and `ISSUE_FIELDS` each gain `,url`;
`PullRequest` and `Issue` each gain a `url: str` field, populated
straight from `gh`'s JSON like every other field on both dataclasses
already is. No new logic — one field wider on two existing objects.

**A new `commit_url(issue_repo, sha)` helper** (`loom/ghsrc.py`, beside
`origin_repo` — same file already owns "what does a GitHub URL for
this repo look like"): returns `None` when `issue_repo` is `None` (no
GitHub remote — same honesty rule `t.pr` and every other
maybe-absent field on the snapshot already follows), else
`f"https://github.com/{issue_repo}/commit/{sha}"`. `git log` has no
notion of GitHub, so a commit's URL can only ever be built, never
fetched — this is the one link in this spec that isn't a real,
`gh`-provided value. Used in **one** place:

- **`loom/collect.py`**, building each commit dict for the `commits`
  list — adds a `url` key beside the existing `sha`.

**The worktree table's PR badge does NOT use `commit_url`'s shape.**
`by_branch` (`loom/collect.py:176`) already maps branch → PR **number**
for this exact lookup (`{p.branch: p.number for p in prs}`), discarding
the rest of the matched `PullRequest` object. Widening it to map branch
→ the whole `PullRequest` costs nothing new — the join already exists —
and means the worktree table's PR badge gets the same real `gh`-
provided `url` as the PRs & Issues panel, not a second, separately
constructed one.

**`loom/rank.py`'s `needs_you()`:** the `pr_failing` and
`pr_awaiting_review` branches already compute `pr_number = p.get(
"number", "?")` locally, from `p` — the full serialized PR dict
(`repo.get("prs", [])`, already carrying the real `url` this spec adds)
— before formatting it into the `subject` string (`f"PR #{pr_number}"`)
and discarding both `pr_number` and the rest of `p`. **Correction
(2026-09-07, caught while planning):** an earlier draft of this section
said `pr_number` survives as a new field, which would have left
`loom.js` to reconstruct a URL from it — exactly the "decision in JS"
this doc's own Constraints section rules out. Since `p` already has the
real `url` in hand, `needs_you()` carries `pr_url = p.get("url")`
through instead — the same real value, one hop earlier, no
reconstruction anywhere. `loom/view.py`'s `aggregate_needs()` needs
**no change** — it already spreads every original key through
(`{**item, "repo": ..., "show_repo": ..., "label": ...}`), confirmed by
reading the function, so a new key on the input dict reaches the
client automatically.

### Rendering (`loom.js`)

One small helper, alongside `text()` at the top of the file: given a
URL-or-`null`, the visible text, and a class name, returns either an
`<a href="..." target="_blank" rel="noopener noreferrer">` (URL
present) or the exact same plain element rendered today (URL absent).
`rel="noopener noreferrer"` is non-negotiable on every `target="_blank"`
link — omitting it lets the opened page's JavaScript reach back into
the tab that opened it (reverse tabnabbing).

Four existing call sites switch from a bare `text(...)` call to this
helper:

- `renderTrees` — the worktree table's PR cell (`t.pr`/`t.pr_url`)
- `renderPrs` — each PR's number (`p.number`/`p.url`) and each issue's
  number (`i.number`/`i.url`)
- `renderTicker` — each commit's sha (`c.sha`/`c.url`)
- `renderNeeds` — the `pr_failing`/`pr_awaiting_review` items' `subject`
  line, where the `PR #N` substring becomes a link when `item.pr_url`
  is present (the other four `needs_you` kinds — agent-waiting,
  collision, stopped-dirty, loose-end-flag — have no PR and stay
  exactly as they render today)

### Accessibility

No new ARIA, no new keyboard pattern, no new widget — `<a>` is natively
operable and announced correctly by every screen reader without any
help from this code.

**New-tab links get an accessible warning.** Opening a new tab without
telling an assistive-tech user is a real, well-documented trap (WCAG
technique G200/SC 3.2.5 territory) — a screen-reader user who activates
a link and doesn't hear a context change can be genuinely lost. Every
link this feature adds includes a `visually-hidden` trailing span
(reusing the class `loom.css` already defines) reading `(opens in a new
tab)` — sighted users see nothing extra, screen readers announce it as
part of the link's name.

Color stays exactly as today (`--num` for PR/issue numbers, `--dim` for
commit shas) — no new color decision.

**Correction (2026-09-07, found by an independent codex review, both
fixed the same day):**

1. This section originally said hover/focus-only underlining was
   sufficient for every link. It is not, for the two that carry no other
   non-color cue: `.issue-num` and `.c-sha` have normal font weight, so
   color was their *only* resting distinction from surrounding text —
   a WCAG 1.4.1 / G183 violation. `.pr-num` and `.needs-subject` are
   already bold in a context where nothing else is, which is itself a
   valid non-color cue, so those two correctly keep the hover-only
   underline. `.issue-num` and `.c-sha` now carry a permanent underline
   instead.
2. `.needs-subject`'s CSS set `font-weight: 700` but never `color` —
   `<strong>` always inherited the page's text color for free, and
   swapping the tag to `<a>` for a linked item meant the browser's own
   default link color took over instead, measuring as low as 1.24:1
   against the hero background. Now sets `color: var(--text)` explicitly
   (9.76:1, verified).

**Correction (2026-09-07, found by an independent codex review, fixed
the same day) — focus loss on every render tick.** `renderTrees`,
`renderPrs`, `renderTicker`, and `renderNeeds` all call
`.replaceChildren()` unconditionally on every SSE tick (every 2 seconds).
Before this feature, nothing inside that regenerated content was ever
focusable, so the churn was invisible. Once real links lived there, a
keyboard user who tabbed onto one lost focus to `<body>` before they
could realistically press Enter — confirmed live by marking a DOM node
and finding it a different object 3 seconds later. Fixed with a
`preservingFocus()` wrapper (`loom.js`) around each of the four render
calls: it remembers the focused link's `href` (a stable identity, not a
DOM position), lets the render proceed exactly as before, then restores
focus to whichever fresh link now carries that same `href`. A fuller
fix — reusing the same DOM nodes across renders entirely, so focus is
never even nominally lost — was considered and deliberately not built:
it means restructuring all four render functions from wholesale rebuilds
into field-level patches, real but separable engineering from closing
the immediate hole. The accepted residual cost: a screen reader
announces the restored link again, since it is a new DOM node: better
than silently losing focus to `<body>`, not free.

### Scope: what gets linked, what doesn't

**In scope:** worktree table's PR badge, the PRs & Issues panel's PR
and issue numbers, the commits ticker's sha, and the needs-you triage
list's PR references.

**Deliberately out, this round:** the "Loose ends" panel
(`loom/rank.py`'s flag-based items) can also name an orphaned PR by
number — the identical shape to needs-you's PR links — but Serina
scoped this round to the four sites above and asked to leave Loose
ends for later rather than expand silently. Easy follow-up, not
forgotten.

## Alternatives considered

- **Build all URLs client-side in `loom.js`** from `issue_repo` +
  number/sha, avoiding any Python change beyond the unavoidable
  `pr_url` threading in `rank.py`. Rejected: it works today (only
  `github.com` remotes are recognized at all), but it puts a decision
  — what a link points to, whether one exists — into the file whose
  own header comment says decisions don't belong there. The
  inconsistency this would introduce (some URLs decided in Python,
  this one decided in JS, for no reason but that it was easy) is worse
  than the small cost of doing it uniformly.
- **Link Loose ends' PR references in this same round.** Deferred, not
  rejected — see Scope above.

## Tests

Genuine new Python behavior this time (unlike the reskin, which was
presentation-only) — real coverage, not just manual verification:

- `tests/test_ghsrc.py`: a `PullRequest`/`Issue` built from mock `gh`
  JSON carries the `url` field through unchanged.
- `tests/test_rank.py`: `needs_you()`'s `pr_failing` and
  `pr_awaiting_review` items carry `pr_url` equal to the input PR
  dict's own `url` field — not reconstructed, not derived from the
  number embedded in `subject`.
- A new test (`tests/test_ghsrc.py`) for `commit_url`: `None` when
  `issue_repo` is `None`, the expected `github.com/.../commit/{sha}`
  string otherwise.
- `tests/test_collect.py`: a worktree whose branch matches an open PR
  gets `pr_url` equal to that PR's real `url`, not a separately
  constructed string — pins the `by_branch` widening actually reuses
  the `PullRequest` object rather than just its number.
- The rendering side (`loom.js`) stays manually verified, same as the
  reskin: load the dashboard, confirm each of the four link types
  opens the correct real GitHub page in a new tab, confirm the
  visually-hidden "(opens in a new tab)" text is present via the
  accessibility tree (not just assumed from the markup), confirm
  hover/focus shows the underline, confirm a worktree/commit/PR with no
  matching URL (no GitHub remote) still renders as plain text with no
  broken link.
