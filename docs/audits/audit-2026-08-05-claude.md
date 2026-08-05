# Loom — audit, 2026-08-05

- **Auditor:** Claude (Opus 5), dispatched by Serina
- **Commit:** `a4b4eea` (`main`, clean tree, up to date with `origin/main`)
- **Scope:** whole tree, plus the two external consumers of its contract
  (`serina-skills/.../skills/loom/SKILL.md`, `.github/workflows/checks.yml`)
- **Ask:** propose a refactor; what is broken; what is missing; what should be dropped;
  where are there other ways of doing something

**8 High · 11 Medium · 13 Low · 0 Blocker.**

No Blocker: nothing here loses data, leaks a credential, or leaves the tree broken.
The tree passes its own gates (200 tests, stdlib check, both required CI checks) and
those gates are real — see *Credit* below.

Every High is the same shape: **a fact Loom knows is not the fact Loom shows.** For a
tool whose founding document says *"an empty panel and a broken panel must look
different at a glance, always"*, that is the defect class that matters most, and it
has reappeared in five places the spec did not anticipate.

---

## High

### H1 · The "Needs you" strip loses every PR alert on 29 of every 30 ticks

*Severity: High · Not filed as an issue*

**Location** `loom_cli.py:101` (`repo["needs_you"] = needs_you(repo)`) against
`loom/serve.py:102` (`apply_gh_cache(...)` runs after it)

**Evidence** — executed:

```
=== EXP 3: does `needs_you` survive a FAST tick? ===
  repo['prs'] the page renders : [7, 8]
  repo['needs_you'] the strip renders: []

  -> PR #7's failing checks (rank 4) shown in 'Needs you'? False
  -> PR #8 awaiting review (rank 2) shown in 'Needs you'? False

  For comparison, needs_you recomputed AFTER the splice:
      {'rank': 2, 'kind': 'pr_awaiting_review', 'subject': 'PR #8', ...}
      {'rank': 4, 'kind': 'pr_failing', 'subject': 'PR #7', ...}

  FAST_SECONDS=2, SLOW_SECONDS=60 -> 29 of every 30 ticks are fast ticks.
```

`build_snapshot` computes `needs_you` from `collect()`'s output. On a fast tick
`include_gh=False`, so `collect()` returns `prs=[]` *by design*. `apply_gh_cache` then
splices the cached PRs back into `repo["prs"]` — but `needs_you` has already been
computed and is never recomputed.

**Consequence** The ranked triage strip is the entire product: *"Loom makes the blocked
ones loud and everything else quiet."* For 58 of every 60 seconds, ranks 2 and 4 are
absent from it, then blink into existence for one 2-second tick and vanish again. The
PR panel below simultaneously lists "PR #7 — checks failing", so the page contradicts
itself on screen. A human glancing at the strip sees a quiet fleet that is not quiet.

**Change** Ranking must be a projection over the *finished* snapshot, applied at the
serving and printing boundary — after any cache merge — not baked in mid-assembly.
See *Refactor R2*.

---

### H2 · Rank 2 never fires on any repository that requires reviews

*Severity: High · Filed as issue #4 — confirmed still live, and worse than the issue states*

**Location** `loom/rank.py:59` — `elif not p.get("review"):`

**Evidence** — executed:

```
=== EXP 1: rank 2 on a repo that REQUIRES reviews ===
   {'rank': 2, 'kind': 'pr_awaiting_review', 'subject': 'PR #2', ...}
  PR #1 (REVIEW_REQUIRED, genuinely awaiting review) present? False
  PR #4 (CHANGES_REQUESTED, blocked on the author) present? False
```

`reviewDecision` is a four-valued enum (`null`, `REVIEW_REQUIRED`, `APPROVED`,
`CHANGES_REQUESTED`), and the code tests it for truthiness. `REVIEW_REQUIRED` — the
exact state rank 2 exists to catch — is truthy, so it is read as "already reviewed".
Rank 2 fires *only* on `null`, which means only on repos with **no** review
requirement at all.

A mutation test confirms no test pins the current behaviour, so the field's four values
have no coverage in either direction:

```
  SURVIVED (suite green)  <- FIX rank 2 to fire on REVIEW_REQUIRED
```

**Consequence** This repo's own ruleset requires two approving checks. On any repo
configured the way Serina configures repos, the second-most-important alert in the
product is unreachable. `CHANGES_REQUESTED` — a PR actively blocked on the author —
also never surfaces at any rank.

**Change** Test the enum's values explicitly, not its truthiness. Decide deliberately
whether `CHANGES_REQUESTED` earns its own rank; it is currently invisible everywhere.

> **Note on the spec.** Correction #1 in the design doc fixed the *checks* half of this
> condition ("passing" → "not failing") after observing it could never fire. The
> *review* half has the identical defect and was not caught by the same pass.

---

### H3 · A failed git call is indistinguishable from a healthy worktree

*Severity: High · Not filed as an issue*

**Location** `loom/gitsrc.py:71` (`return (0, 0)`), `:82` (`return Dirty()`),
`:151-167` (`touched_files` returns a partial set on failure)

**Evidence** — executed:

```
=== EXP 5: every git call for a worktree FAILS. What does the page show? ===
  ahead_behind -> (0, 0)  (renders as "0" / "0")
  dirty_counts -> Dirty(staged=0, unstaged=0, untracked=0)  (renders as "0")
  touched_files -> set()  (renders as: no collisions)

=== and rank 5 (stopped agent with uncommitted work)? ===
  stopped agent, dirty counts zeroed by a git failure -> []
  -> rank 5 ("Work at risk of being lost") is silently suppressed.
```

`sources` reports at *subsystem* granularity — one `git` entry, hardcoded
`ok: True` at `loom/collect.py:177`. There is no per-worktree, per-fact status. A
worktree 12 ahead with 9 uncommitted files whose git calls failed renders identically
to one perfectly in sync and clean.

**Consequence** This is the spec's founding incident reproduced inside the Worktrees
panel — the same "empty with exit code 0" confusion that `sources` was invented to
prevent, one layer down where `sources` does not reach. It also silently suppresses
rank 5, whose stated rationale is *"Work at risk of being lost."*

**Change** A fact that could not be determined must be `None`, not `0`, and must render
as `?` rather than a number. See *Refactor R3*.

---

### H4 · One failed gh fetch destroys the cache it was meant to protect

*Severity: High · Not filed as an issue*

**Location** `loom/serve.py:68-73` — the `if include_gh:` branch caches
unconditionally, without consulting whether the fetch succeeded

**Evidence** — executed:

```
=== EXP 2: apply_gh_cache when a slow tick's gh fetch FAILS ===
  after a healthy slow tick, cache holds PRs: [{'number': 9}]
  after a FAILED slow tick, cache holds PRs: []
  what the page then shows for the next 60s: []
```

`apply_gh_cache` writes `repo["prs"]` into the cache on every gh-including tick. When
`gh` fails, `collect()` correctly returns `prs=[]` with `ok: False` — and that empty
list overwrites the good cache.

**Consequence** A single transient `gh` failure (rate limit, expired token, network
blip) discards known-good PR and issue data for at least 60 seconds. The `gh:prs`
source does carry `ok: False`, so the *panel* shows a banner — but `needs_you` was
computed from the empty list (see H1), so the triage strip goes quiet with no banner
above it. The mechanism named "cache" is the one thing guaranteed not to hold a cached
value when it is needed.

**Change** Cache only a successful fetch. Retain the previous value with its
`cached_at`, and let the source status carry the failure.

---

### H5 · `serve --all` collects every repository and displays only the first

*Severity: High · Filed as issue #6 — confirmed still live*

**Location** `loom/static/loom.js:125` — `const repo = snapshot.repos[0];`

**Evidence** `build_snapshot` (`loom_cli.py:98-102`) loops over every root and appends
each to `repos`. The page indexes `[0]` and returns early if absent. A mutation
changing it to render the *last* repo instead left the suite green:

```
  SURVIVED (suite green)  <- dashboard renders the LAST repo instead of the first
```

**Consequence** `--all` is documented in both `README.md` and the CLI `USAGE` string as
a supported flag for `serve`. It pays the full collection cost for every checkout under
`~/Launchpad` — 12 subprocess spawns per repo per tick, measured — and silently
discards all but one. A user watching a six-repo fleet sees one repo and no indication
the others exist.

**Change** Render every repo, or reject `--all` on `serve` until the page supports it.
Silently collecting and discarding is the worst of the three options.

---

### H6 · A green "live" badge sits over frozen data when collection fails

*Severity: High · Filed as issue #3 — confirmed still live*

**Location** `loom/static/loom.js:140-144` — `source.onmessage` sets `"● live"`
unconditionally

**Evidence** `refresh_error` is produced with care and read by nothing outside the
server's own loop and its tests:

```
=== refresh_error ===
tests/test_serve.py:208,220,221,223,225,229
loom/serve.py:113,116,117,120,133,137,152
```

No occurrence in `loom/static/`. Worse, the failure path *increases* SSE traffic:
`_refresh_step` returns the previous snapshot with `refresh_error` added, which changes
the serialised body, which triggers a send — so the page receives a message, and a
message is the only thing it uses to conclude "live".

**Consequence** The one condition under which the dashboard is lying is the condition
under which it most confidently claims to be live.

**Change** The page must read `refresh_error` and `generated_at` and degrade the badge.
The badge currently reports *connection* health and is labelled as though it reports
*data* health.

---

### H7 · The skill is instructed to check a field the CLI does not emit

*Severity: High · Not filed as an issue*

**Location** `serina-skills/plugins/serina/skills/loom/SKILL.md` ("If the snapshot is
older than 5 minutes, say so.") against `loom_cli.py:103`
(`return {"schema": 1, "repos": repos}`)

**Evidence** — executed, from the cwd the skill actually runs in:

```
  ran OK from /home/serina/Launchpad/worktrees-challenge
  top-level keys: ['repos', 'schema']
  can the skill honour "if older than 5 minutes"? -> False
```

`collect()` computes `generated_at` and `duration_ms` at `loom/collect.py:163-164`;
`build_snapshot` discards both when it merges repos. `serve` re-stamps its own
`generated_at`, so the *page* has one and the *CLI* does not.

A second instruction in the same file is also unsatisfiable: *"If `hooks` is not ok,
agent states are `unknown`"* — `hooks` is hardcoded `ok: True`:

```
184:                asdict(ghsrc.SourceStatus("hooks", True)),
```

**Consequence** Two of the skill's four constraints cannot fire. The staleness rule is
the one that matters: the skill pipes this snapshot into a conversation and asserts
freshness it has no way to check, so an agent can confidently report a fleet state
minutes out of date. The spec's stated reason for versioning the schema was *"two
consumers parse it and would otherwise drift silently"* — they have.

**Change** Emit `generated_at` (and `duration_ms`) from `build_snapshot`. Either give
`hooks` a real failure condition or drop that constraint from the skill.

---

### H8 · `loom.js` has no test coverage, and two live defects are in it

*Severity: High · Not filed as an issue*

**Location** `loom/static/loom.js` (148 lines), and the absence of any JS runner

**Evidence** — the search came up empty:

```
=== any JS/browser test runner or JS test file? ===
   (NO MATCHES — loom.js is untested)
```

```
  what do the serve tests assert about static assets?
  391: test_a_missing_static_file_404s_cleanly_instead_of_raising
  404: # Task 11 built loom/static/index.html; "/" is a live route now
```

The suite asserts the files are *served*, never that they are *correct*. Confirmed by
mutation: rendering the wrong repo left the suite green.

**Consequence** The spec says *"`collect` is the only unit with logic worth getting
wrong."* That was true when written and is no longer: H5 and H6 both live in
`loom.js`, and 148 lines of rendering logic — including the aria-live debounce the
accessibility section depends on — has no falsifiable check of any kind. The Python
suite's strength (see *Credit*) makes this gap easy to mistake for coverage.

**Change** Either extract the rendering decisions into pure functions that Python can
test through the contract, or accept a dev-only JS runner. The zero-dependency
constraint applies to Loom's *runtime*, not to its test tooling — worth deciding
deliberately rather than by default.

---

## Medium

### M1 · The spec documents a staleness rule the code deliberately abandoned

**Location** `docs/superpowers/specs/2026-08-03-loom-design.md` — the `agent.state`
table, *"Stale state is caught, not trusted"*, *"Staleness comes from corroboration"*,
the Testing table, and the Threat-model gap row — against `loom/agents.py:155-181`

**Evidence** The spec states in three places that `stale` means *"the process source
sees agents and none for this tree."* `loom/agents.py:181` records that this rule was
removed as unsound: *"Panes take NO part in staleness now, in either direction."*
Staleness is decided by timestamp freshness alone. The spec's Testing table prescribes
a control — *"Live pid with `working` — reports `working`"* — that cannot exist, since
pid is documented as not a liveness signal.

**Consequence** The largest behavioural change in the project is absent from a section
titled *"Corrections made during execution"* that has six entries and exists precisely
to prevent this. The spec now describes a Loom that was replaced. The Threat-model gap
*"A sandboxed agent may be reported `stale` — staleness corroborates against
`pane_current_command`"* is obsolete for the same reason, so a genuine risk register
entry is now misleading.

**Change** Add correction #7. Rewrite the three staleness passages and retire the
obsolete threat row.

---

### M2 · `origin_repo` still accepts a leading `--`, as the spec's own gap table predicts

**Location** `loom/ghsrc.py:10-11`

**Evidence** — executed:

```
  git@github.com:--upload-pack=evil/x.git       -> '--upload-pack=evil/x'
  https://github.com/-x/y.git                   -> '-x/y'
  git@github.com:owner/repo.git                 -> 'owner/repo'
```

**Consequence** The value is passed as `-R`'s argument to `gh`. The spec rates this Low
and states *"GitHub names cannot start with `-`, so the regex should reject it"* — a
stated intention that nothing enforces. Requires prior write access to `.git/config`,
which is why it stays Medium rather than High, but a repo cloned from an untrusted
source is not an exotic scenario for this tool.

**Change** Anchor the character class to reject a leading `-` in both patterns.

---

### M3 · `stale_dir` flags are silently disabled whenever worktrees span two parents

**Location** `loom/collect.py:60-63` — `return sorted(parents)[0] if len(parents) == 1 else None`

**Evidence** `_worktree_parent` returns `None` unless *exactly one* parent directory is
found, and `find_flags` skips the entire `stale_dir` scan when it is `None`
(`loom/collect.py:37`).

**Consequence** The spec's grounding observation lists *"1 directory left behind that
was no longer a git worktree"* as a motivating fact. A fleet whose worktrees live in
two sibling directories — or one worktree placed elsewhere — loses that detection with
no entry in `sources` and no flag. Absence of a warning reads as absence of a problem.

**Change** Scan every distinct parent, or report that the scan was skipped and why.

---

### M4 · 12 subprocess spawns per worktree per tick, for a tool meant to stay open all day

**Location** `loom/collect.py:102-152`, `loom/gitsrc.py:151-167`, `loom/serve.py:156`

**Evidence** — measured:

```
  12 subprocess spawns for a 1-worktree repo, include_gh=False: {'git': 11, 'tmux': 1}
  at FAST_SECONDS=2 that is 360 spawns/minute for ONE worktree
```

The cost is `5 + 7n` per tick (`touched_files` alone is 3 git calls per worktree, plus
`ahead_behind`, `dirty_counts`, `_last_commit`, and the merge-base). For the
six-worktree fleet the design was built against: **47 spawns per tick, ~1,410 per
minute.**

**Consequence** Not correctness, but the spec positions this as *"a browser page left
open while working"* on a laptop. `time.sleep(FAST_SECONDS)` also sits *after* the work,
so the real period is 2s + collection time and drifts under load.

**Change** Cache per-worktree facts against `HEAD` sha plus index mtime; `--porcelain=v2
--branch` returns ahead/behind and dirty state in one call. See *Alternatives A3*.

---

### M5 · CI runs no lint, no type check, no JS test, no coverage, and no advisory scan

**Location** `.github/workflows/checks.yml`

**Evidence** — each absence searched:

```
  ruff|flake8|pylint|lint:                 ABSENT from CI
  mypy|pyright|typecheck:                  ABSENT from CI
  coverage:                                ABSENT from CI
  node|npm|jest|vitest|playwright:         ABSENT from CI
  pip-audit|safety|bandit:                 ABSENT from CI
  schedule:|cron:                          ABSENT from CI
```

**Consequence** The codebase is fully annotated and `from __future__ import
annotations` is used throughout, so a type checker would pay for itself immediately —
and would have caught the `SourceStatus.last_good` field that is never assigned. No
advisory scan is defensible (zero dependencies, verified) but should be stated as a
decision rather than left as a gap.

**Change** Add `mypy --strict` on `loom/` first; it has the best ratio of findings to
noise here. Record the "no advisory scan because no dependencies" decision explicitly.

---

### M6 · The verdict gate's own remediation instructions point at a path that does not exist

**Location** `.github/workflows/checks.yml`, the `block()` message

**Evidence** — the search came up empty:

```
--- verdict.sh ---
ls: cannot access '.claude/skills/review-final/verdict.sh': No such file or directory
--- pr-gate.sh / verify-gate.sh / verdict.sh anywhere ---
   (NO MATCHES)
```

`.claude/` in this repo contains one file, `.verified` (empty, gitignored). The
workflow tells a blocked contributor to run
`.claude/skills/review-final/verdict.sh record ready <PLAN_FILE>`. `.gitignore` also
references a `verify-gate.sh` that is not in the tree.

**Consequence** The gate is genuinely binding — ruleset `20329458` requires both
`tests and constraints` and `reviewed for this commit`, and PRs #10 and #12 show both
green. So a real contributor will hit this message and follow instructions to a path
that isn't there. A gate whose escape hatch is undocumented is a gate people work
around.

**Change** Point at the real command, or state that the script lives outside this repo
and where.

---

### M7 · A `role="status"` region is rewritten every 2 seconds

*Accessibility · on Serina's a11y scale this is a **Blocker** for screen-reader users*

**Location** `loom/static/index.html:13` (`<p id="conn" role="status">`) against
`loom/static/loom.js:141-142`

**Evidence** `role="status"` is an implicit `aria-live="polite"` region.
`source.onmessage` assigns `el("conn").textContent = "● live"` on every message, and
messages arrive every `FAST_SECONDS` (2s). Assigning `textContent` replaces the child
text node even when the string is identical, so the live region mutates on every tick.

**Consequence** A polite live region that mutates every 2 seconds produces a
continuous, unstoppable announcement queue. The spec anticipated exactly this failure
for the *other* live region — *"A 2-second live region would make a screen reader
unusable"* — and debounced it to 15s in `renderNeeds`. The same reasoning was not
applied to `#conn`, which has no debounce at all.

I could not confirm actual announcement behaviour with a real screen reader in this
environment (see *Coverage*), and dedup behaviour varies between NVDA, JAWS and
VoiceOver. The mutation is certain; the announcement is highly likely and untested.

**Change** Write to `#conn` only when the state actually changes. That is a one-line
guard and removes the risk entirely regardless of which reader is used.

---

### M8 · Toggling `aria-live` between `off` and `polite` is an unreliable debounce

*Accessibility*

**Location** `loom/static/loom.js:25` — `list.setAttribute("aria-live", quiet ? "off" : "polite")`

**Evidence** `index.html:19` declares `aria-live="polite"` statically; `renderNeeds`
then flips the attribute on every render to implement the 15s debounce.

**Consequence** Screen readers register live regions when they are added to the
accessibility tree and do not uniformly re-read a changed `aria-live` value. The
debounce may therefore silence the region permanently for some readers, or not at all
for others. The *intent* is correct and well-reasoned; the mechanism is the fragile
way to express it. This is the spec's own warning — *"fake accessibility is worse than
no accessibility"* — in a subtler form: the attribute promises a behaviour the browser
may not deliver.

**Change** Keep `aria-live="polite"` fixed and debounce the *content*: write into the
region only when an announcement is due.

---

### M9 · `serve` on an occupied port dies with an uncaught traceback

**Location** `loom/serve.py:231` — `ThreadingHTTPServer((host, port), Handler)`

**Evidence** — executed:

```
  UNCAUGHT OSError -> OSError [Errno 98] Address already in use
```

**Consequence** The default port is fixed at 8787, and the most likely reason it is
taken is a Loom already running — the single most probable user error produces a
Python traceback instead of "Loom is already running on 8787". `parse_port` goes to
real trouble to avoid exactly this for a bad `--port` value; the socket path was
missed.

**Change** Catch `OSError` around the bind and print the same class of message
`parse_port` produces.

---

### M10 · The SSE change-suppression can never suppress anything

**Location** `loom/serve.py:218` (`if body != last`) against `:132`
(`snap["generated_at"] = _now_iso()`)

**Evidence** `_refresh_step` stamps `generated_at` with wall-clock time on every
successful tick, so the serialised body differs every 2 seconds regardless of whether
any fleet fact changed. `body != last` is therefore always true.

**Consequence** The optimisation is dead code that reads as live. Every connected
browser receives a full snapshot every 2 seconds and re-renders every panel — which is
also what drives M7. Harmless at one client; the comment implies a guarantee that does
not hold.

**Change** Compare a digest that excludes the timestamp fields, or drop the comparison
and document that every tick is a frame.

---

### M11 · The refresh thread cannot be stopped, and its failure mode is silent by design

**Location** `loom/serve.py:141-156`, `:230`

**Evidence** `_refresh_loop` is `while True` with no exit condition, started as a
daemon thread. `_refresh_step` is documented as never raising — deliberately, and
correctly, to stop a `KeyError` killing the daemon silently.

**Consequence** The remaining gap is the other direction: there is no way to stop the
loop for a clean shutdown or a test, so `serve`'s only exit is process death. Combined
with H6 (the page never reads `refresh_error`), a permanently-failing collector
produces a server that serves `collected: true` and a frozen snapshot forever, with a
green badge. Each half is individually defended; together they are not.

**Change** A `threading.Event` for both the sleep and the stop condition — same call
site, gives clean shutdown and testable timing.

---

## Low

### L1 · Three declarations are dead — deletable with the suite green

**Location** `loom/agents.py:85-87` (`_pane_in_worktree`), `loom/ghsrc.py:24`
(`SourceStatus.last_good`), `loom/gitsrc.py:16-18` (`Dirty.total`)

**Evidence** — searched, then confirmed by deletion:

```
=== _pane_in_worktree ===
loom/agents.py:85:def _pane_in_worktree(...)     <- sole occurrence, tests included
=== last_good ===
loom/ghsrc.py:24:    last_good: str | None = None  <- sole occurrence; never assigned
=== \.total ===
(only datetime.total_seconds() — Dirty.total is never read)
```

```
  SURVIVED (suite green)  <- delete the unused _pane_in_worktree helper
  SURVIVED (suite green)  <- delete the never-set last_good field
```

**Consequence** `_pane_in_worktree` is the residue of the pane-based staleness rule
that PR #12 removed — it is the *only* remaining trace of the abandoned design, and it
looks live. `last_good` is worse than dead: it is the field the spec's error-honesty
example depends on (*"PRs unavailable — gh: HTTP 403, last good 4m ago"*), so its
presence in the dataclass makes an unimplemented feature look implemented.

**Change** Drop all three. Implement `last_good` or remove it and correct the spec
example — leaving it declared-but-never-set is the one option that misleads.

---

### L2 · At least thirteen snapshot fields are produced and read by nothing

**Location** `loom/collect.py:147-152, 163-172`; `loom/ghsrc.py:28-43`

**Evidence** — searched each name across `loom/`, `loom_cli.py`, `hooks/`, and
`loom/static/`, excluding tests. Produced and never read: `duration_ms`,
`generated_at` (in the CLI path), `issue_repo`, `default_branch`, `last_commit`,
worktree `head`, worktree `path`, worktree `pr`, `agent.tmux_window`, PR `title`
(the page renders `branch` instead), PR `updated_at`, PR `worktree`, issue `labels`,
issue `assignees`, `gh_cached_at`.

`last_commit` is the expensive one — it costs one `git log` per worktree per tick.
Deleting it left the suite green:

```
  SURVIVED (suite green)  <- delete last_commit entirely
```

**Consequence** Filed as issue #8, which says *seven* fields. **The real count is at
least fifteen** — the issue undercounts by more than half, so anyone scoping from it
will under-scope. Two are load-bearing for documented behaviour: `gh_cached_at` is the
"how stale the cached ones are" the spec and README both promise, and `generated_at` is
H7's contract break.

**Change** Render or drop, field by field. This is the symptom that most argues for
*Refactor R1*: with no single owner of the contract, a field costs nothing to add and
nothing warns when it is read by no one.

---

### L3 · Spec status says "not yet planned" for work that is built and merged

**Location** `docs/superpowers/specs/2026-08-03-loom-design.md:4`

**Evidence** `- **Status:** approved, not yet planned`, against
`docs/superpowers/plans/2026-08-03-loom-v1.md` (2,721 lines) and PR #2 merged
2026-08-03.

**Change** Update to reflect that it is planned, built and merged.

---

### L4 · The spec's snapshot example says `del`; the code emits `dele`

**Location** spec commits block, against `loom/gitsrc.py:109`

**Evidence** — executed:

```
  Commit fields: ['when', 'branch', 'sha', 'subject', 'files', 'add', 'dele']
  spec says "del", code emits: dele
```

**Consequence** `del` is a Python keyword, so `dele` is a forced rename, not a slip.
Correction #4 in the spec records exactly this class of drift for `review` vs
`review_decision`; this instance was missed.

**Change** Fix the example, or add it to the corrections list.

---

### L5 · The spec's accessibility requirement for collapse controls is vacuous

**Location** spec, Accessibility section

**Evidence** — the search came up empty:

```
-- buttons / aria-expanded / collapse controls --
   (NONE — the spec's collapse-control requirement is vacuous)
```

**Consequence** *"Every collapse control is a real `<button>`, keyboard reachable,
`:focus-visible` styled, with an honest `aria-expanded`"* is listed under
*"Requirements, not aspirations. Each is verifiable."* There are no interactive
controls in the page at all, so this one is trivially satisfied and verifies nothing —
it reads as a met requirement while testing nothing. It becomes live the moment anyone
adds a panel toggle.

**Change** Mark it conditional ("if any collapse control is added…") so it cannot be
mistaken for a passed check.

---

### L6 · The "Loose ends" panel is specified and never built

**Location** spec Panels table, against `loom/static/index.html:16-50`

**Evidence** — the search came up empty:

```
-- 'Loose ends' panel (spec lists it) --
   (NONE — panel never built)
```

Panels present: Needs you, Worktrees, Collisions, PRs & issues, Commits, sources.

**Consequence** `flags` reach the page only via `needs_you` rank 6, so orphan PRs and
stale directories appear in the triage strip with no home panel. The spec's third flag
kind — *"branches with no issue"* — is never produced by any code path.

**Change** Build the panel or remove it from the table and drop the unimplemented flag
kind from the description.

---

### L7 · Cached gh age is promised in two documents and displayed nowhere

**Location** spec Refresh table (*"cached age is displayed"*) and Panels table
(*"how stale the cached ones are"*), against `loom/serve.py:79`

**Evidence** `gh_cached_at` is set on the repo dict and appears in the live snapshot
(confirmed by `curl`), but has no occurrence in `loom/static/`.

**Change** Render it, or correct both documents.

---

### L8 · Issues #5 and #7 are fixed but still open

**Location** GitHub issues #5, #7

**Evidence** — both tested against current code:

```
=== ISSUE #7: does a node process keep a crashed agent reporting 'working'? ===
  crashed 3h-old working session + a node pane in the tree -> stale
  ISSUE #7 still live? False

=== ISSUE #5: does a malformed gh record kill the snapshot? ===
  parsed PRs: [1] | status: SourceStatus(name='gh', ok=False,
                            error="malformed PR record: missing 'number'")
  ISSUE #5 first half (kills snapshot) still live? False
```

Issue #5's second half ("makes serve hammer gh every 2s") is also resolved:
`_degrade` returns a status rather than raising, so `refresh_error` stays `None` and
`loom/serve.py:152-153` advances `last_slow` normally.

**Consequence** PR #12's timestamp-based staleness fixed #7 as a side effect without
closing it. Two of seven open issues are stale, so the backlog overstates outstanding
work by 29%.

**Change** Close #5 and #7, citing the commits. Note that #4, #3, #6, #8 are confirmed
live (H2, H6, H5, L2) and #11 is a legitimate deferred feature, matching the spec's
out-of-scope list.

---

### L9 · No LICENSE

**Evidence** `ls LICENSE*` → no matches.

**Consequence** The stdlib-only constraint exists so Loom *"can be dropped into any
repo with a Python 3.12 interpreter"* — i.e. the project intends to be reused. Without
a licence, nobody can.

---

### L10 · `--help` exits 2

**Evidence** — executed:

```
  loom --help -> exit 2
  loom -h -> exit 2
  loom help -> exit 2
```

**Consequence** An explicit help request is a successful invocation. Exit 2 makes
`loom --help` fail in any script or `Makefile` that checks status.

---

### L11 · No minimum Python version is declared anywhere

**Evidence** — searched `README.md`, the workflow, and the spec:

```
.github/workflows/checks.yml:45:      - name: Set up Python 3.12
.github/workflows/checks.yml:48:          python-version: "3.12"
```

That is the only statement of a version, and it is a CI choice rather than a declared
floor. No `pyproject.toml` exists, so there is no `requires-python`, and CI tests
exactly one interpreter.

**Consequence** `scripts/check_stdlib_only.py` needs `sys.stdlib_module_names` (3.10+)
and its docstring asserts 3.12; the runtime code appears to need only 3.8+. Nobody
knows which, because nothing states or tests it. A user on 3.9 gets a confusing
failure from a project whose selling point is dropping in anywhere.

**Change** State the floor in `README.md` and test it in CI, or add a minimal
`pyproject.toml` for `requires-python` alone. Note the tension: adding one weakens the
"no dependency file exists" boundary the spec relies on as evidence — worth deciding
deliberately.

---

### L12 · The completed plan is the largest file in the repository

**Evidence** — measured:

```
  100K  docs/superpowers/plans/2026-08-03-loom-v1.md   (2,721 lines)
   80K  loom/         (all production code)
  372K  total tracked
```

**Consequence** The execution plan for merged work is 27% of the repository and larger
than everything it produced. It is valuable history, not current documentation, and its
task-by-task prose is now a fourth place the snapshot shape is described — a drift
surface.

**Change** Archive under `docs/archive/` with a header stating it is superseded by the
code, so nobody reads it as current.

---

### L13 · Decision records have no index

**Evidence** `docs/` holds one spec and one plan, discoverable only via a single
`README.md` link to the spec. There is no index enumerating decision records, so the
set cannot be diffed against anything.

**Consequence** With one spec this is cosmetic. It is the mechanism by which L3, L4,
L5, L6 and L7 all went unnoticed: nothing enumerates what the documents claim so it
can be checked against what the code does.

---

## Credit — what is genuinely strong

An audit that lists only faults misrepresents this tree. These were tested, not assumed.

**The test suite is falsifiable.** Six mutations of real invariants, six killed:

```
  killed  rank 1 no longer requires a fresh claim              (failures=4)
  killed  naive timestamp adopts now's zone (the reverted bug) (failures=2)
  killed  a future timestamp reads as its raw negative age
  killed  unknown check states report passing                  (failures=4)
  killed  not-yet-collected returns 200 instead of 503         (failures=1)
  killed  ahead/behind swapped                                 (failures=1)
```

That is unusual. Most suites this size survive at least half of these. The suite
covers what it covers *for real* — which is exactly why H8 (zero JS coverage) is worth
raising rather than assuming the page is covered too.

**Every security boundary the spec claims still holds.** Each verified independently:

```
-- shell=True / os.system --          (NONE — boundary holds)
-- innerHTML / eval --                (NONE — boundary holds)
-- 0.0.0.0 --                         (NONE — boundary holds)
```

Path traversal is blocked, and the bind is loopback-only:

```
  200  /static/loom.js
  404  /static/../../../etc/passwd
  404  /static/..%2f..%2f..%2fetc%2fpasswd
  404  /static/%2e%2e%2f%2e%2e%2fetc%2fpasswd
  LISTEN 127.0.0.1:18899
```

No credential patterns in any tracked file; no `.env`, key or token files tracked.

**The stdlib checker is not vacuous.** `scripts/check_stdlib_only.py:67-71` fails on an
empty file list, so it cannot pass by finding nothing — the two-tests-for-a-vacuous-check
rule, applied unprompted.

**The CI gate is real and binding.** Ruleset `20329458` requires both
`tests and constraints` and `reviewed for this commit`; PRs #10 and #12 show both
green. The `0.0.0.0` grep is a deliberate second, independent guard that reads the
source rather than trusting a test to still exist. The verdict job's chicken-and-egg
solution — head may differ from the reviewed sha *only* if the sole change is the
verdict file — is genuinely well reasoned.

**The CSS meets the accessibility bar it sets.** `:focus-visible` (not `:focus`),
`prefers-reduced-motion`, a real `visually-hidden`, contrast ratios computed and
recorded per token. The collisions matrix uses real `<th scope>` and text in every
cell. M7 and M8 are gaps in an otherwise carefully built page — which is why they are
worth fixing rather than starting over.

**The comments carry rationale, including reversals.** `loom/agents.py:105-131` and
`:155-181` record what was tried, why it was wrong, and which direction of error is
acceptable. That is why this audit could distinguish deliberate decisions from
accidents at all.

---

## Proposed refactor

Not a rewrite. Five moves, each fixing findings above rather than tidying for its own
sake. The current eight modules are well chosen; the problem is that two of them own
things they should not.

### R1 · One module owns the contract — `loom/snapshot.py`

**Fixes** L2, L4, H7, and the drift class behind L3–L7.

The snapshot is currently assembled as raw dicts inline in `loom/collect.py:161-188`
and described in four other places: the spec's JSONC block, `loom.js`'s field access,
`SKILL.md`'s instructions, and the plan. Five descriptions, zero enforcement. Every
doc-drift finding and every dead field is a symptom of that.

```
loom/snapshot.py     Snapshot / Repo / WorktreeView / PRView / IssueView / SourceStatus
                     to_dict()  — the ONLY place a snapshot key is spelled
                     validate() — every consumer runs it
```

`SourceStatus` moves here from `loom/ghsrc.py`, where it does not belong: it already
describes `git`, `hooks` and `tmux` as well as `gh`.

The payoff is not tidiness — it is that "produced and read by nothing" becomes a
*check* instead of an invisible cost, and adding a field to the contract becomes a
deliberate act.

### R2 · Ranking becomes a projection applied last

**Fixes H1** — the most serious finding.

`needs_you` currently runs inside `build_snapshot` (`loom_cli.py:101`), mid-assembly,
which is why the gh cache splice invalidates it. Move it to the boundary:

```
serve:  collect → merge cache → rank → publish
cli:    collect → rank → print
```

One move, and the strip can no longer disagree with the panel below it. It also makes
the invariant testable: *rank over a snapshot, and rank over that same snapshot after
any merge, must agree.*

### R3 · A determined fact and an undetermined one have different types

**Fixes H3**, and generalises `loom/agents.py`'s own hard-won rule.

`_age_seconds` already gets this right: `None` means *cannot tell* and callers must
never read it as zero — the docstring says so explicitly. `gitsrc` does the opposite:
`ahead_behind` returns `(0, 0)` and `dirty_counts` returns `Dirty()` on failure,
producing a confident wrong answer.

Make the return types `int | None` and `Dirty | None`, render `None` as `?`, and let
rank 5 refuse to conclude from an undetermined dirty count. This is the spec's
founding rule pushed down to per-fact granularity, where H3 shows it is actually
needed.

### R4 · Fleet assembly leaves the CLI — `loom/fleet.py`

**Fixes** a real dependency inversion: `loom/serve.py:100` does
`from loom_cli import build_snapshot`. The package imports its own CLI script.

`loom_cli.py`'s docstring says *"Argument parsing only — the logic lives in the
package"*, but it holds `discover_repos`, `repo_roots`, `build_snapshot` and
`render_text`. Move the first three to `loom/fleet.py`; the CLI keeps parsing and
rendering. `LAUNCHPAD = os.path.expanduser("~/Launchpad")` becomes a parameter — the
spec's own rule is *"a hardcoded path cannot be negative-tested"*, and this one is
hardcoded.

### R5 · gh caching becomes a merge policy on the contract

**Fixes H4.**

`apply_gh_cache` lives in `loom/serve.py`, where nothing knows what a *successful*
fetch means — which is precisely why it caches failures. Move it beside the contract
and give it the rule it is missing: **only a successful fetch updates the cache;
otherwise retain the previous value and let the source status carry the failure.**

### Target module map

```
loom/snapshot.py   the contract: dataclasses, to_dict, validate   [new]
loom/fleet.py      repo discovery, build_snapshot, cache merge    [new, from loom_cli + serve]
loom/collect.py    orchestration only                             [shrinks]
loom/gitsrc.py     git facts, None for undetermined               [R3]
loom/ghsrc.py      gh facts                                       [SourceStatus moves out]
loom/agents.py     hook state + staleness                         [drop _pane_in_worktree]
loom/rank.py       projection over a finished snapshot            [unchanged logic]
loom/serve.py      HTTP + SSE + scheduling only                   [shrinks]
loom_cli.py        argument parsing + text rendering              [shrinks]
```

**Sequencing.** R2 first — it is the smallest change with the largest correctness win
and needs nothing else. Then R3 (behavioural, needs new tests). Then R1, R4, R5
together as one structural pass, since R1's contract is what R4 and R5 move things
onto. Do not start with R1: it touches everything and fixes nothing on its own.

---

## Other ways of doing things

Alternatives worth *considering*, not recommendations. Several are worse than what is
here and are listed with that verdict, because "we chose this over that" is the useful
record.

**A1 · SSE → long-poll or plain poll.** SSE's change-suppression cannot suppress (M10),
so the current design pays SSE's costs — a thread per client, no cap, a hand-rolled
idle timeout — for a frame every 2 seconds. `fetch('/snapshot.json')` on a timer would
be simpler, need no `Handler` special case, and lose nothing measurable at this scale.
**Verdict:** SSE is fine *if* M10 is fixed; if it is not, polling is strictly simpler.

**A2 · Threads → `asyncio`.** One refresh task plus N SSE clients on one event loop
removes the unbounded thread-per-connection model and the `settimeout` workaround.
Still stdlib. **Verdict:** correct fit on paper, but it rewrites `serve.py` to fix a
problem that has not bitten at one-to-two clients. Revisit only if the thread model
actually hurts.

**A3 · Fewer git invocations.** `git status --porcelain=v2 --branch` returns
ahead/behind *and* dirty state in one call, replacing two. `git worktree list
--porcelain` already gives each HEAD, so `_last_commit`'s per-worktree `git log` is
avoidable via one repo-wide `git log --no-walk` over the collected shas. Cache
per-worktree facts against HEAD sha plus index mtime, since nothing changes between
ticks on an idle worktree. **Verdict:** worth doing — M4's `5 + 7n` becomes roughly
`3 + 2n`, and the change is local to `gitsrc`.

**A4 · `git` plumbing via `--git-dir`/`--work-tree` instead of `cwd=`.** Would let one
process serve several worktrees. **Verdict:** rejected — it breaks `ReplayRunner`'s
argv-keyed fixtures, and the record/replay harness is the reason this codebase is
testable at all. Not worth trading.

**A5 · A file watcher instead of a 2-second poll.** `inotify` on each `.git` plus the
state dir would make updates event-driven and near-instant. **Verdict:** rejected for
now — stdlib has no inotify binding, so it means a dependency or `ctypes`, and the
zero-dependency constraint is load-bearing here.

**A6 · Long-lived `gh` process or the REST API via `urllib`.** Dropping the `gh`
dependency would remove the auth-degradation path CI carefully tests. **Verdict:**
rejected — `gh` carries the operator's auth, and re-implementing that is strictly worse
than shelling to it.

**A7 · `id(s)` → `enumerate` index for staleness identity.** `loom/agents.py:182-202`
tracks stale sessions by `id(dict)`. It is correct today because the objects stay
alive, but it is identity-by-accident and reads as a hack. `for i, s in
enumerate(matching_sessions)` with a set of indices is the same code, obviously
correct. **Verdict:** do it — free.

**A8 · A JSON Schema file for the contract instead of dataclasses.** Would let the JS
side validate too. **Verdict:** dataclasses are better here — one language owns the
contract, and R1 needs a producer anyway. A schema file becomes attractive only if a
non-Python producer ever appears.

**A9 · Extract render decisions into pure functions.** For H8, the cheaper half of the
fix: move *what to display* (which repo, which badge state, whether data is stale) out
of DOM manipulation and into functions the Python contract tests can exercise. Leaves
only DOM plumbing untested. **Verdict:** the pragmatic option if a JS runner is
unwanted.

---

## Coverage

Every dimension, marked — because "not mentioned" and "checked and clean" are
indistinguishable to the next reader.

| # | Dimension | Status | Notes |
|---|---|---|---|
| 1 | **Invariants, adversarially** | **checked** | Five constructed forbidden states: rank 2 against all four `reviewDecision` values; a failed gh fetch against a warm cache; `needs_you` across a fast/slow tick boundary; all-git-calls-fail against a dirty worktree; a crashed session beside a `node` pane. Yielded H1–H4 and confirmed H2. |
| 2 | **Tests** | **checked** | 200 pass. Six mutations of real invariants, six killed. Five mutations of suspected-dead code, five survived — used as evidence for L1/L2, not as a defect in itself. One mutation anchor initially missed and was re-run; see *Corrections*. |
| 3 | **Accessibility** | **checked, with one hole** | CSS, ARIA, table semantics, live regions and reduced-motion all reviewed against the W3C APG. M7 and M8 raised. **Hole:** no real screen reader available in this environment, so M7's announcement behaviour is reasoned from the DOM-mutation mechanism, not observed. NVDA/JAWS/VoiceOver differ on identical-content dedup. The mutation is certain; the announcement is untested. |
| 4 | **Dependencies & security** | **checked** | Zero third-party dependencies, verified by `check_stdlib_only.py` (23 files) and by the absence of any manifest. Production tree = full tree; there is no separate dev tree. No advisory scan run and none needed — nothing to scan; recorded as M5 so the reasoning is on the record. Secrets scan clean over all tracked files. Boundaries re-verified: no `shell=True`, no `innerHTML`, no `0.0.0.0`, traversal blocked, loopback bind. |
| 5 | **Build & CI** | **checked** | Both required checks confirmed binding via the ruleset API. What CI does *not* run is M5; the broken remediation path is M6. No build step exists (by design — no bundler, no transpile). |
| 6 | **Docs vs reality** | **checked** | Every value stated in the spec traced to code: staleness rule (M1), `del`/`dele` (L4), collapse controls (L5), Loose ends panel (L6), cached age (L7), status line (L3), `last_good` (L1). Decision records enumerated (2) against their index (none exists) — L13. |
| 7 | **Process & automation** | **checked** | `bin/loom` shim, `check_stdlib_only.py`, the hook installer, both CI jobs, the verdict mechanism. `LAUNCHPAD` is the one hardcoded identity (R4). `.gitignore` references a `verify-gate.sh` not in the tree (M6). |
| 8 | **Live project state** | **checked** | `gh` authenticated as `serina-mcfall`. 7 open issues each tested against current code: #3/#4/#6/#8 confirmed live, #5/#7 fixed-but-open (L8), #11 a legitimate deferred feature. 3 PRs, all merged with required checks green. No stale branches — `main` only, local and remote in sync. |

**Not reached, and why:** a real screen reader (dimension 3, detailed above) — the only
hole in this report. M7 is stated with that limit named rather than asserted as
observed.

---

## Corrections

**To my own working method during this audit.** One mutation test reported
`SURVIVED (suite green)` for "a future timestamp reads as age zero" when its anchor
string had not matched the file's actual indentation — the mutation never applied, so
the green suite proved nothing. Caught in the same output, re-run with a matching
anchor, and the mutation was **killed**. `loom/agents.py:125-130`'s negative-age guard
is genuinely covered. The harness now exits non-zero on a missed anchor rather than
silently reporting a survival — a mutation test that cannot apply its mutation always
reports the reassuring answer.

**To issue #8.** It states *"Seven snapshot fields are produced with care and read by
nothing."* Verified count is **at least fifteen** (L2). Anyone scoping from the issue
title will under-scope by more than half.

**To issues #5 and #7.** Both are fixed in current `main` and both are open (L8).
Issue #7 was resolved as a side effect of PR #12's staleness rewrite rather than by a
change aimed at it, which is why it was never closed.

**To the design spec.** Its `agent.state` definition of `stale`, its
*"Staleness comes from corroboration"* passage, its Testing table's stale-agent row,
and its Threat-model gap on sandboxed agents all describe a pane-corroboration rule
that `loom/agents.py:155-181` documents as removed for being unsound (M1). The spec's
*"Corrections made during execution"* section — six entries, written for exactly this
purpose — does not record it. This is the single largest doc-vs-code gap in the tree.

**No prior audit of this tree exists**, so nothing here revises an earlier report. This
audit was written by the same model family that built much of the code, and no third
party has graded it — findings should be read with that in mind. H1, H3 and H4 are
supported by pasted execution output specifically so they can be checked without
trusting the auditor.

---

## Handoff

Findings only. Nothing was fixed, no issue was opened, no decision was recorded — all
five mutation-tested files were restored and verified:

```
=== restore verified ===
(git status --short: empty)
OK  (200 tests)
```

The tree is exactly as found at `a4b4eea`. What becomes work is Serina's call.

**If only three things get done:** H1 (via R2 — smallest change, largest correctness
win), H7 (one line: emit `generated_at`), and M7 (one line: only write `#conn` on
change). Those three cost almost nothing and remove the two lies the tool currently
tells its two consumers, plus the one that makes the page unusable with a screen
reader.
