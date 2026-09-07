# Loom — clickable PR, issue, and commit links (interactivity, round 1)

- **Date:** 2026-09-07
- **Status:** approved
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing. This is the "Spec 2 (interactivity)" work the
  2026-09-07 reskin design doc deferred — first round of it, not all of
  it. Adds `url` to the `PullRequest` and `Issue` dataclasses (additive;
  `SCHEMA_VERSION` unaffected, same reasoning as the tokens-and-cost
  design's OPEN-3) and a `pr_number` field to two `needs_you()` item
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
`pr_awaiting_review` branches already compute `pr_number` locally
before formatting it into the `subject` string (`f"PR #{pr_number}"`)
and discarding the variable. It survives instead, as a `pr_number` key
on the item dict. `loom/view.py`'s `aggregate_needs()` needs **no
change** — it already spreads every original key through
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
  line, where the `PR #N` substring becomes a link when `item.pr_number`
  is present (the other four `needs_you` kinds — agent-waiting,
  collision, stopped-dirty, loose-end-flag — have no PR number and stay
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
commit shas) — no new color decision. `a:hover, a:focus-visible` gets a
text-underline, so the interactive affordance is visible on interaction
without changing how the page reads when it isn't being interacted
with. `:focus-visible`'s existing outline rule already covers these
links with zero changes.

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
  `pr_number` threading in `rank.py`. Rejected: it works today (only
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
  `pr_awaiting_review` items carry a real `pr_number` matching the
  number already embedded in their `subject` string.
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
