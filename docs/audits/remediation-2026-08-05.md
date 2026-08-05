# Loom — remediation journey, from audit 2026-08-05

The paper trail for fixing what the audit found. One entry per finding, in the order
they were worked: **High → Medium → Low → second audit pass.**

- **Audit:** [`audit-2026-08-05-claude.md`](audit-2026-08-05-claude.md) — 8 High, 11 Medium, 13 Low, 0 Blocker
- **Baseline:** `a4b4eea` on `main` (200 tests, clean tree)
- **Branch:** `fix/audit-high`
- **Method:** TDD throughout — every fix has a test that was watched failing first, with
  the failure output pasted below. A fix whose test passed on first run is not recorded
  as fixed; it is recorded as a finding that was already false.

## How to read an entry

Each carries **RED** (the failing test and its actual output), **GREEN** (the change and
the passing run), and **Notes** where a decision was made that the audit did not dictate.
Where a fix changed an existing test, that is called out explicitly — a quietly edited
test is how a suite stops being evidence.

---

## Status

| ID | Finding | Tier | Status | Commit |
|---|---|---|---|---|
| H1 | `needs_you` ranked before the gh cache splice | High | **fixed** | `7831705` |
| H2 | Rank 2 never fires where reviews are required | High | **fixed** | `7bedcd8` |
| H3 | Failed git call indistinguishable from healthy | High | **fixed** | `96961c7` |
| H4 | Failed gh fetch destroys the cache | High | **fixed** | `59910bf` |
| H5 | `serve --all` displays only the first repo | High | **fixed** | `d21fd35` |
| H6 | Green "live" badge over frozen data | High | **fixed** | `d21fd35` |
| H7 | Skill checks a field the CLI never emits | High | **fixed (Loom side)** | `25974b0` |
| H8 | `loom.js` has no test coverage | High | **fixed** | `d21fd35` |
| M1 | Spec documents the abandoned staleness rule | Medium | **fixed** | `0aca7c5` |
| M2 | `origin_repo` accepts a leading `--` | Medium | **fixed** | `5404e46` |
| M3 | `stale_dir` flags silently disabled | Medium | **fixed** | `5404e46` |
| M4 | 12 subprocess spawns per worktree per tick | Medium | **fixed** | `04cd99d` |
| M5 | CI runs no lint, typecheck, JS test or coverage | Medium | **fixed (typecheck)** | `c70610a` |
| M6 | Verdict gate's remediation path does not exist | Medium | **fixed** | `c70610a` |
| M7 | `role="status"` rewritten every 2s | Medium | **fixed** | `d21fd35` |
| M8 | `aria-live` toggling is an unreliable debounce | Medium | **fixed** | `949c9da` |
| M9 | `serve` on a taken port raises a traceback | Medium | **fixed** | `d29a075` |
| M10 | SSE change-suppression can never suppress | Medium | **fixed** | `d29a075` |
| M11 | Refresh thread cannot be stopped | Medium | **fixed** | `d29a075` |
| L1 | Three dead declarations (**two**, corrected) | Low | **fixed** | `4a5f9de` |
| L2 | 15 snapshot fields read by nothing | Low | **fixed** | `5b32be6` |
| L3 | Spec status stale | Low | **fixed** | `ff56ba4` |
| L4 | Spec says `del`, code emits `dele` | Low | **fixed** | `ff56ba4` |
| L5 | Collapse-control a11y requirement is vacuous | Low | **fixed** | `ff56ba4` |
| L6 | "Loose ends" panel never built | Low | **fixed (built)** | `ff56ba4` |
| L7 | Cached gh age promised, never displayed | Low | **fixed** | `5b32be6` |
| L8 | Issues #5 and #7 fixed but open | Low | **awaiting Serina** | — |
| L9 | No LICENSE | Low | **awaiting Serina** | — |
| L10 | `--help` exits 2 | Low | **fixed** | `4a5f9de` |
| L11 | No declared Python floor | Low | **fixed (measured, 3.10)** | `ff56ba4` |
| L12 | Completed plan is the largest file | Low | **fixed (archived)** | `ff56ba4` |
| L13 | No index of decision records | Low | **fixed** | `ff56ba4` |

| — | Colour coding + compactness (requested live) | extra | **done** | `8d98887` |
| N4 | Static assets were cacheable | new | **fixed** | `8d98887` |

**All 8 High findings are fixed.** M7 landed early with H6 because it was the same
lines of code.

**Blocked on a decision from Serina:** L9 (which licence), L11 (declare the Python
floor in README vs add a `pyproject.toml`, which weakens the "no dependency file
exists" boundary the spec cites as evidence).

**Decisions taken during the High tier:**

| Question | Choice | Why |
|---|---|---|
| Commit gate could not stamp | Add `python3 -m unittest` to the hook's pattern | Fixes it for every Python stdlib project, not just Loom |
| H8 testing approach | Extract decisions to Python | Keeps zero-dependency purity; leaves only DOM plumbing untested |
| H5 scope | Render every repo | The flag is documented; collecting and discarding was the worst option |
| `CHANGES_REQUESTED` rank | Left unranked, recorded | Adding a tier changes the spec's ranking table — design, not bugfix |

**New findings raised during remediation** (for the second audit pass): see
[New findings](#new-findings-raised-during-remediation) at the end.

---

## H1 · `needs_you` was ranked before the gh cache splice

*High · fixed in `7831705`*

The most serious finding in the audit. The triage strip — the thing the whole product
rests on — lost every PR-derived alert on 29 of every 30 ticks.

### Preparation (not a fix)

`tests/test_serve.py` held its fast-tick `ReplayRunner` as a method on
`TestTickSkipsGhOnFastTick`, and a second test was already reaching for it as
`TestTickSkipsGhOnFastTick()._replay_runner()`. Promoted it to a module-level
`_fast_tick_runner()` so one fixture serves every fast-tick test.

That refactor was done **before** writing the failing test, verified green at 200 tests,
and changed no behaviour. It immediately exposed the awkward call site as an error:

```
AttributeError: 'TestTickSkipsGhOnFastTick' object has no attribute '_replay_runner'
  tests/test_serve.py:271  runner = TestTickSkipsGhOnFastTick()._replay_runner()
```

Two copies of a fast-tick fixture would have been free to drift, which is the same class
of defect as the one being fixed.

### RED

Added `TestNeedsYouIsRankedAfterTheGhCacheSplice` with two tests: one pinning the two
specific ranks, one pinning the general invariant — *whatever `prs` a consumer is shown,
`needs_you` was computed from exactly that list.*

```
FAIL: test_a_fast_tick_ranks_the_cached_prs_it_displays
AssertionError: 'pr_failing' not found in set()
  : PR #7's failing checks are displayed but not ranked

FAIL: test_the_strip_and_the_panel_never_disagree_about_which_prs_exist
AssertionError: Items in the second set but not the first:
'PR #8'
'PR #7' : every displayed PR here warrants an alert; the strip must not
          silently drop the ones the panel shows

Ran 2 tests — FAILED (failures=2)
```

The failure is the right one: `kinds` is `set()` while the panel holds `[7, 8]`.

### GREEN

Took the **structural** fix (audit R2), not the patch. The patch would have been to rank
a second time in `serve` after the splice — that fixes the symptom while keeping the
wrong shape, and leaves a trap for the next person who mutates a snapshot.

- `loom/rank.py` — new `rank_snapshot(snapshot)`: attaches `needs_you` to every repo in a
  **finished** snapshot and returns it.
- `loom_cli.py` — `build_snapshot` no longer ranks. Its docstring now says so and why.
- `loom_cli.py` — the `snapshot` command ranks last: `rank_snapshot(build_snapshot(...))`.
- `loom/serve.py` — `_tick` ranks **after** `apply_gh_cache`, with a comment stating the
  ordering is the invariant.

Ranking now happens exactly once, at the boundary that publishes the snapshot. Anything
inserted between collection and publication is automatically covered.

```
Ran 202 tests — OK
OK: 23 Python files, every import is stdlib or first-party
```

Re-run of the audit's original reproduction against the real fast-tick path:

```
=== H1 re-run against the REAL fast-tick path ===
  panel shows PRs: [7, 8]
  strip shows    : [(2, 'pr_awaiting_review', 'PR #8'), (4, 'pr_failing', 'PR #7')]

  BEFORE fix: strip was []  <- 29 of every 30 ticks
  AFTER  fix: strip and panel agree -> True
```

### Notes — one existing test was deliberately retargeted

`tests/test_cli.py::TestBuildSnapshot::test_attaches_needs_you_to_every_repo` asserted
that `build_snapshot` attaches `needs_you`. It passed before this change, and **that
placement was the defect** — so the test was pinning the bug in place. It failed as
expected once ranking moved:

```
FAIL: test_attaches_needs_you_to_every_repo
AssertionError: 'needs_you' not found in {...}
```

Retargeted, not deleted, into two assertions on the new contract:

1. `build_snapshot` must **not** rank — `assertNotIn("needs_you", ...)`, which is now a
   structural guarantee rather than an accident.
2. `rank_snapshot` attaches it, and it is a list.

**`needs_you` is absent rather than empty on an unranked snapshot**, deliberately. An
empty list would make "nobody ranked this" and "the fleet is quiet" identical — the exact
empty-versus-broken confusion this project exists to refuse. A consumer that forgets to
rank now gets a `KeyError`, loudly, instead of a reassuring blank strip.

### Incidental confirmation of H3

Running `./bin/loom snapshot` on this branch printed:

```
loom — 1 trees, 0 PRs, 7 issues
  ! git:default-branch unavailable — could not resolve origin/HEAD; falling back to a 'main' guess
  nothing needs you
```

`origin/HEAD` is unresolvable here, so `base` is a guess, so `ahead_behind` compares
against a ref that may not exist — and reports `0 / 0` regardless. Live, unprompted
evidence for H3, on the very first run after the fix.

---

## H2 · Rank 2 never fired where reviews are required

*High · issue #4 · fixed in `7bedcd8`*

### RED

Five tests, one per `reviewDecision` value. Only one failed:

```
FAIL: test_a_review_required_pr_ranks_as_awaiting_review
AssertionError: Lists differ: [] != ['pr_awaiting_review']
```

**Recorded honestly: the other four passed immediately.** They pin behaviour that
was already correct (`APPROVED`, `CHANGES_REQUESTED`, draft, unrecognised value)
and are regression guards on the enum, not drivers of the fix. Only the
`REVIEW_REQUIRED` test drove anything.

### GREEN

`not p.get("review")` → `p.get("review") in AWAITING_REVIEW`, an explicit whitelist
`{None, "", "REVIEW_REQUIRED"}` matching `derive_checks`'s existing rule: an
unrecognised value must not become an alert.

```
=== H2 re-run of the audit reproduction ===
  PR #1 REVIEW_REQUIRED  -> ranked? True (was False before the fix)
  PR #2 null             -> ranked? True
  PR #3 APPROVED         -> ranked? False (correctly not)
  PR #4 CHANGES_REQUESTED-> ranked? False (deliberately not)
```

Confirmed live afterwards: seven rank-2 items across five repos on the real fleet.

### Notes — one gap deliberately left open

`CHANGES_REQUESTED` is invisible at every rank. It fails rank 2's rationale ("only
a human moves it" — an agent can act on requested changes), and giving it a rank of
its own means **adding a tier to the spec's ranking table**. That is a design
decision, not a bug fix, so it is recorded rather than quietly invented.
**Serina's call.**

---

## H3 · A failed git call was indistinguishable from a healthy worktree

*High · fixed in `96961c7`*

### RED

Nine failures, all for the right reason. The most telling one is that
`test_failure_is_zero_zero` **already existed and asserted the defect** — a test
written to lock in the wrong answer:

```
FAIL: test_failure_is_none_not_zero_zero          AssertionError: (0, 0) is not None
FAIL: test_a_failed_status_is_none_not_a_clean_tree
                                     AssertionError: Dirty(0,0,0) is not None
FAIL: test_touched_files_is_none_when_the_merge_base_cannot_be_found
                                                  AssertionError: set() is not None
FAIL: test_a_stopped_agent_with_an_unmeasurable_tree_is_flagged_not_silenced
                                     AssertionError: [] != [(5, 'stopped_dirty')]
ERROR: test_a_worktree_whose_files_cannot_be_read_is_named_not_silently_skipped
```

### GREEN

`ahead_behind → tuple | None`, `dirty_counts → Dirty | None`, `touched_files → set |
None` (requiring **all four** git calls, since a partial set understates what a
worktree touched), and `collisions → (found, undetermined)`.

Two new `sources` entries carry the reason — routed through the existing honesty
mechanism rather than a new field, because that is what `sources` is for.

```
=== EXP 5 re-run: every git call for a worktree FAILS ===
  ahead_behind -> None (was (0,0) -> rendered "0")
  dirty_counts -> None (was Dirty(0,0,0) -> rendered "0")
  touched_files-> None (was set() -> "no collisions")
  collisions   -> ([], ['a', 'b'])

=== rank 5: stopped agent, tree unmeasurable ===
   {'rank': 5, 'kind': 'stopped_dirty', 'detail': 'agent stopped, and git could
    not be asked whether work was left behind'}
  (was [] -> work at risk silently suppressed)
```

### Notes

**Rank 5 is deliberately the one guard that speaks up when it cannot tell.**
Everywhere else in Loom, "cannot tell" means stay silent, because a false alarm
cries wolf. Rank 5's rationale is "work at risk of being lost", so a false alarm
costs one glance and a false silence costs someone's uncommitted work.

**The new sources were negative-controlled**, because on this repo they both read
OK — the `"main"` fallback guess happens to be correct here, so a green reading
proved nothing:

```
=== negative control: could the new sources ever report BAD? ===
  ok=False  git:worktree-facts
        could not measure ahead/behind or dirty counts for 1 worktree(s): loom
  ok=False  git:collisions
        could not enumerate changed files for 1 worktree(s)...: fix/audit-high
```

They name the worktree differently on purpose — `git:worktree-facts` uses the
directory (as the Worktrees table's first column does) and `git:collisions` uses the
branch (as the matrix's column headers do). Each names the thing the way its own
panel labels it; this is not a bug.

---

## H4 · One failed gh fetch destroyed the cache meant to protect against it

*High · fixed in `59910bf`*

### RED

```
FAIL: test_a_failed_slow_tick_does_not_overwrite_a_good_cache
AssertionError: Lists differ: [] != [{'number': 1}]
```

### GREEN

The cache now holds two facts separately: **data from the last SUCCESS, status from
the last ATTEMPT.** Only a success may replace the data.

Splitting them is not tidiness — it is what stops the page flapping. Cached
together, a failed slow tick shows the banner and the next fast tick splices the
stale `ok: True` status back in two seconds later, alternating indefinitely.

```
=== EXP 2 re-run ===
  after healthy slow tick, cache PRs: [{'number': 9}]
  after FAILED slow tick, cache PRs: [{'number': 9}] (was [] before the fix)
  banner source: {'name':'gh:prs','ok':False,'error':'HTTP 403 rate limit',
                  'last_good':'T1'}
  next FAST tick, does it flap back to ok=True? [False]
```

### Notes

This also **assigns `last_good` for the first time ever** (audit L1). The field has
been declared on `SourceStatus` since v1 and never once set, which made the spec's
own error-honesty example — *"PRs unavailable — gh: HTTP 403, last good 4m ago"* —
unimplementable. The page now renders it.

---

## H7 · The skill checked a field the CLI never emitted

*High · fixed in `25974b0` (Loom side)*

### RED

```
FAIL: test_the_snapshot_states_when_it_was_generated
AssertionError: 'generated_at' not found in {'schema': 1, 'repos': [...]}
ERROR: test_duration_ms_is_a_non_negative_integer     KeyError: 'duration_ms'
```

### GREEN

`build_snapshot` now stamps both for the whole build, timezone-aware.

```
  top-level keys: ['duration_ms', 'generated_at', 'repos', 'schema']
  generated_at  : 2026-08-05T16:14:32+12:00
  computed age  : 0.2s  -> the skill can now honour its 5-minute rule
```

### Notes — one half is NOT fixed and is not Loom's to fix

The skill's other unsatisfiable constraint — *"If `hooks` is not ok, agent states
are `unknown`"* — cannot fire, because `hooks` is hardcoded `ok: True` at
`loom/collect.py:184`. That is **correct** per spec correction #3: an empty state
directory is the expected condition before hooks are installed, not a breakage.

So the skill's wording is wrong, not the code. Fixing it means editing
`serina-skills`, a **different repository**, and that plugin is installed *from
GitHub* — local edits are inert until pushed. **Outstanding, and Serina's call**,
since it crosses a repo boundary.

---

## H5, H6, H8 · The page tier

*High · all three fixed in `d21fd35`*

Handled as one change because all three had the same root cause: every display
decision lived in `loom.js`, which no test could reach.

### RED

`tests/test_view.py`, 13 tests, module absent:

```
ModuleNotFoundError: No module named 'loom.view'
```

Then six more for `aggregate_needs`:

```
ImportError: cannot import name 'aggregate_needs' from 'loom.view'
```

### GREEN

New `loom/view.py` owns the decisions: `badge()` (data health), `aggregate_needs()`
(the fleet-wide strip), `finalise()` (the single publish boundary both consumers
call). `loom.js` became plumbing.

### Verified in a real browser, against a real 7-repo fleet

Not asserted — measured:

```
  sseFramesSeen: 3                      (refreshes really happened)
  connLiveRegionMutations: 0            (M7: was mutating every 2 seconds)
  focusStillOnSameElement: true         (focus survived 3 refreshes)
  activeElementLabel: "repo-0-trees-h"
```

```
  repoSections: [loom, nextjs-project, nextjs-project-tucktuck, serina-learning,
                 serina-skills, skills, worktrees-challenge]
  headingOrder: H1:Loom > H2:Needs you > H2:loom > H3:Worktrees > H3:Collisions ...
```

Seven repos rendered where one used to be.

### Notes

**The H6 integration guard passed on first run**, because the unit tests had already
driven the fix. Rather than trust it, the fix was reverted to prove the guard is not
vacuous:

```
=== with the H6 fix reverted, does the guard fail? ===
FAIL: test_a_failed_step_travels_with_an_error_badge_not_a_green_one
AssertionError: 'live' != 'error'
```

**Skeletons are rebuilt only when the set of repo names changes.** Rebuilding every
tick would throw focus to `<body>` every 2 seconds for anyone tabbed into a scroll
container — introducing an accessibility defect while fixing one. The measurement
above is what confirms it does not.

**One existing assertion was relaxed**, from whole-dict equality on `repos` to
comparing names, because `finalise` now attaches `needs_you` and a badge. Its intent
was "the good data replaced the stale data", not byte-identity. A second assertion I
added there was wrong and was corrected: I asserted the badge reads `live`, but the
stub snapshot never sets `collected`, so `connecting` is the correct reading — the
test now asserts it is not `error`, which is the actual claim.

---

## Extra · colour coding and compactness

*Requested live during review · `8d98887`*

Not an audit finding — Serina asked for it while watching the dashboard. Recorded
here because it changed the same files the findings did.

**The rule held: colour is never the only carrier of meaning.** The rank number is
printed in every chip, collisions cells still say "collides", review and check
states are spelled out, and an unmeasurable number renders `?` in italic.

Every ratio was **computed, not guessed**, against both backgrounds — and after the
zebra stripe was added, all nine foregrounds were re-checked against that third
background:

```
NEW background --zebra #1b212a — does every foreground still pass AA?
  --text 13.7:1  --dim 7.3:1  --warn 9.5:1  --bad 7.4:1  --good 10.3:1
  --time  9.8:1  --branch 8.3:1  --num 8.2:1  --rank6 6.3:1
  weakest combination: 6.3:1 -> all pass AA
```

Compactness came from `align-items: start` (grid rows default to equal height, so
one long Issues panel dragged its neighbours down), a 15rem cap with internal
scrolling on unbounded panels, and double width for the two table panels after the
`Dirty` column fell off the edge.

### A confusing round trip worth recording

After the CSS landed, the page appeared unchanged. Two separate causes, both real:

1. **Python is not reloaded per request.** Static files are read from disk on every
   request, so CSS and JS changes appear on reload — but `loom/view.py` was already
   imported, so `show_repo` was missing until the server was restarted. Static
   reloading masked the fact that the Python half had not.
2. **Static assets were cacheable** (N4). No build step and no fingerprinted names
   means an edited `loom.css` keeps its URL forever, and the browser served the old
   one. Indistinguishable from the edit having failed. Now fixed with `no-store` and
   pinned by a test verified to fail without it.

---

## The Medium tier

All 11 fixed. Grouped by the files they touched rather than by number, so each commit
stayed reviewable.

### M2 + M3 · `5404e46` — the data layer

**M2 RED** — three of four cases accepted an option-shaped remote:

```
AssertionError: '--upload-pack=evil/x' is not None
AssertionError: '-x/y' is not None
AssertionError: 'owner/-oProxyCommand=evil' is not None
```

**GREEN** — owner and repo must each begin with an alphanumeric. Verified that
legitimate names with inner hyphens, dots and underscores still parse
(`serina-mcfall/loom`, `some_org/my.dotted-repo`).

**M3** — `find_flags` took a single parent string, and that shape *was* the bug. Now
a list, with `_worktree_parents` returning all of them.

#### The most instructive moment of the whole tier

Changing that parameter from `str` to `list[str]` should have broken eight call sites.
**Seven of them kept passing.** `str` is iterable, so `"/t"` was looped over
character by character — `listdir("/")`, `listdir("t")` — which returned nothing
matching, so no flags were produced, and those seven tests assert an empty list.

They passed for entirely the wrong reason. Only the single test that expected a flag
caught it:

```
FAIL: test_a_directory_with_no_dot_git_is_still_flagged
AssertionError: Lists differ: [] != ['stale_dir']
```

A `TypeError` guard now makes that loud. This is the "could this pass if the thing
did not exist" rule catching a live instance in my own change.

### M9 + M10 + M11 · `d29a075` — the server

**RED** — raw `OSError` escaping the bind, and no way to stop the loop:

```
ERROR: test_a_taken_port_exits_cleanly_instead_of_raising   OSError: [Errno 98]
ERROR: test_an_already_set_stop_event_means_the_loop_never_runs
       TypeError: _refresh_loop() got an unexpected keyword argument 'stop'
```

**Verified live** against the running server:

```
$ ./bin/loom serve --port 8787
cannot serve on 127.0.0.1:8787 — Address already in use.
Port 8787 is already in use; a Loom may already be running there.
Try `loom serve --port 8788`, or stop the other one.
exit code: 2
```

**M10 note — the fix was deliberately NOT the obvious one.** The audit offered
"compare a digest that excludes the timestamps, or drop the comparison". Repairing
the digest would have *created* a hole: an EventSource whose server stopped
collecting stays OPEN and merely goes quiet, so `onerror` never fires. Suppressing
identical frames makes "nothing changed" and "the server died" indistinguishable.

So every tick is now a frame, deliberately, and the page watches for **silence** —
using `stale_after_seconds` carried on the badge rather than a constant of its own,
so the threshold cannot drift from `view.STALE_AFTER_SECONDS`.

**One test stub had to grow.** `FakeServer` gained `server_close`, because
`run_server` now closes the socket in a `finally`. A fake standing in for the real
thing has to model the interface it is asked for, or the test fails on the stub
instead of on the behaviour.

### M8 · `949c9da` — the accessibility mechanism

Flipping `aria-live` between `off` and `polite` on every render was the wrong
mechanism for a right intent. The visible list is no longer a live region at all; a
separate permanently-polite hidden region receives one sentence from
`view.announcement`, debounced to 15 seconds and only when the sentence changed.

**Measured in a browser over 8 seconds, against the real fleet:**

```
  visibleListMutations: 48      (repaints, for the eye)
  announcementMutations: 0      (debounced)
  ariaLiveToggles: 0            (the fragile mechanism is gone)
  visibleList aria-live: null   hiddenRegion aria-live: polite, role=status
```

48 repaints, 0 announcements. Every one of those 48 used to happen inside a live
region governed by the toggle.

### M5 + M6 · `c70610a` — CI

**mypy earned its place on its first run.** It found `body` used for both `str` and
`bytes` inside one function, where the f-string would have emitted `"b'...'"` if
anything were reordered — plus a missing return annotation and two unannotated empty
lists. Five errors, all fixed.

Deliberate configuration choices:

- **A separate job.** `tests and constraints` has no install step and that is its
  guarantee. A type checker is a *development* dependency, so putting it in its own
  job keeps both signals true: the tests job still proves Loom runs on a bare
  interpreter, and the code still gets checked.
- **`--strict --allow-any-generics`,** not full `--strict`. Bare `dict` is used
  idiomatically here and annotating 39 of them buys nothing; every check that finds
  defects stays on.
- **mypy pinned to 2.3.0.** An unpinned checker turns somebody else's release into a
  red build on a branch that changed nothing.

**M6** — the gate now names **no path at all**, deliberately. `verdict.sh` ships
inside the serina-skills plugin, whose cache directory is version-specific
(`serina/0.6.0/...` today, something else after the next update), so any literal path
would rot exactly as the old one did. The instruction is to invoke the skill, which
knows where its own script lives.

**Not made a required check in the ruleset** — that is a gate change and Serina's call.

### M1 · `0aca7c5` — the spec

Five sites described the pane-corroboration rule PR #12 removed as unsound. Now
correction 7, with the full reasoning including why the *first repair attempt* also
failed. Two further corrections recorded (8: rank 2's review half; 9: `sources`
needing per-fact granularity).

The obsolete threat-model row is **struck through rather than deleted**, and the
Decisions table entry is **annotated rather than rewritten** — the document's own
stated reason for keeping a corrections list is that a spec quietly matching whatever
got built teaches nobody anything.

### M4 · `04cd99d` — the subprocess cost

Measured against real repositories, before and after:

```
  1 worktree   12 -> 9  spawns  (360 -> 270 a minute)
  7 worktrees  54 -> 33 spawns (1620 -> 990 a minute)
```

Cost went from `5 + 7n` to `5 + 4n`. Three changes: one `git status` per worktree
serving both the counts and the collision paths; `_last_commit` deleted (one `git
log` per worktree per tick for a field nothing read); and `wait_seconds` so ticks
START every 2 seconds rather than being spaced 2 seconds apart.

**Equivalence proven, not assumed.** The risk in reusing status output is subtly
different collision detection, so both paths were run against the live 7-worktree
fleet:

```
  NEW (status reuse): 3 collisions, 0 undetermined
  OLD (4 git calls) : 3 collisions, 0 undetermined
  IDENTICAL RESULT: True
```

#### Two corrections to my own audit

1. **A3 was wrong.** It suggested `git status --porcelain=v2 --branch` to get
   ahead/behind and dirty in one call. Verified by execution: `branch.ab` is measured
   against the **upstream**, and Loom compares against the **default branch**. Not
   equivalent, and following it would have silently changed what ahead/behind means.
2. **`-z` is mandatory, which A3 did not mention.** `--porcelain=v1` quotes paths
   containing spaces or non-ASCII, so paths parsed from it would disagree with the
   ones `git diff -z` returns and the matrix would compare two spellings of one file.
   Rename entries also carry the original path as a **separate NUL token** — verified
   against real git output; missing that desynchronises every path after it.

A budget test now pins the spawn count with its breakdown written down, so adding a
per-worktree git call means justifying a raise rather than quietly costing every user
another 30 spawns a minute.

---

## The Low tier

Eleven of thirteen fixed. Two need a human and are listed at the end.

### L1 + L10 · `4a5f9de`

**L10 RED** — all three help forms exited 2:

```
FAIL: test_asking_for_help_succeeds (argv=['--help'])   AssertionError: 2 != 0
FAIL: test_asking_for_help_succeeds (argv=['-h'])       AssertionError: 2 != 0
FAIL: test_asking_for_help_succeeds (argv=['help'])     AssertionError: 2 != 0
```

Negative controls kept: bare `loom` and an unknown command still exit 2, because only
one of those three is an error.

**L1 — a correction to the audit.** It listed *three* dead declarations. Only two were
still dead by the time the Low tier began:

- `_pane_in_worktree` — dead. The last trace of the pane-corroboration rule PR #12
  removed as unsound, so it read as live code implementing an abandoned rule.
- `Dirty.total` — dead. Rank 5 sums the fields itself, because it must distinguish
  `None` from zero first.
- `SourceStatus.last_good` — **no longer dead.** H4 assigns it, and the page renders it
  in the banner. The audit was right when written and wrong by the time it was actioned.

### L2 + L7 · `5b32be6` — the fifteen unread fields

**A correction to my own measurement, twice.** The first pass counted 14 by substring
match, which is wrong in both directions: `head` matched `tHead` in the JS. The second
pass used property-access patterns and still counted 14, because **`os.path.join` in
`loom_cli.py` matched `\.path\b`** and hid `worktrees[].path`. Only after stripping
Python's own `os.path` did the count land on **15 — exactly what the audit claimed.**

That is the third time in this remediation that a grep matched my own tooling rather
than the thing I was measuring.

Each field was then resolved rather than counted:

| Resolution | Fields |
|---|---|
| **Rendered** | `duration_ms`, `issue_repo`, `default_branch`, `gh_cached_at` (L7), `worktree.pr`, `pr.updated_at`, commit `sha`/`files`/`add`/`dele` |
| **Validated** | `schema` |
| **Dropped** | worktree `head`, PR `worktree`, issue `assignees` |
| **Kept, documented as skill-facing** | `root`, `worktrees[].path` |

**The `schema` one matters most.** The spec's stated reason for versioning is that "two
consumers parse it and would otherwise drift silently" — and neither consumer ever read
the number. A version field nothing validates is decoration. A mismatch now outranks
every other badge state *including a refresh error*, because if the shape cannot be
trusted then no field read out of it can be either.

`root` and `path` were **kept**, against the audit's "render or drop" framing. Both are
unrendered, but an agent reporting "worktree X needs you" has to be able to say where X
is. The defect was never that they existed — it was that nothing recorded which consumer
they were for.

**SCHEMA_VERSION bumped to 2.** No consumer read the removed fields, so nothing broke —
but "probably nobody noticed" is how a version field becomes decoration.
`test_version_is_pinned` exists to make a bump deliberate, and it did exactly that.

**An accessibility improvement fell out of it.** Each repo section's `h2` carried the
tree/PR/issue counts, so the section's *accessible name changed every 2 seconds*. A
moving landmark label is disorienting to navigate by. The heading is now the bare repo
name and the counts moved to a plain paragraph.

### L11 · the Python floor, measured rather than guessed

`uv` made it possible to test real interpreters instead of reasoning about them:

```
  python3.9   PASS  (Ran 285 tests)      but check_stdlib_only.py FAILS
  python3.10  PASS  (Ran 285 tests)      everything works  <- declared floor
  python3.11  PASS  (Ran 285 tests)
  python3.13  PASS  (Ran 285 tests)
  ./bin/loom snapshot on python3.9  PASS (real end-to-end run)
```

So Loom's *runtime* reaches 3.9, and the project's floor is **3.10** — the lowest version
at which everything works, including its own checks. The checker's docstring claim of
3.12 was a guess and is corrected.

#### The matrix nearly broke the binding gate

Adding `strategy.matrix` to the `tests` job would have renamed its check run from
`tests and constraints` to `tests and constraints (3.10)`. The ruleset for `main`
requires the **bare** context, which would then never be published again — an
unsatisfiable gate, indistinguishable from a slow one.

Caught before committing. The matrix legs are named `py3.x`, and a separate aggregate
job carries the stable required name, with `if: always()` so a failed leg makes it
**fail** rather than skip — a skipped required check is not a failing one, and GitHub
would have read the gate as still-running forever.

Verified against the live ruleset afterwards: both required contexts
(`tests and constraints`, `reviewed for this commit`) are still published.

### L6 · the panel that was specified and never built

Built. Verified in the browser against the real fleet:

```
  panelsPerRepo: [Worktrees, Collisions, Pull requests & issues, Commits,
                  Loose ends, Data sources]
  looseEndsItems: ["stale dir wave1-apiclient — wave1-apiclient is not a git worktree"]
```

The spec's third flag kind, "branches with no issue", is produced by **no code path at
all** — removed from the description rather than left as a phantom feature.

### L3 · L4 · L5 · L12 · L13 · the documents

L5 is the interesting one. *"Every collapse control is a real `<button>`…"* sat in a list
headed **"Requirements, not aspirations. Each is verifiable."** The page has no
interactive controls, so it was trivially satisfied and verified nothing, while reading
as a passed check. It is now conditional, and the requirement the page *actually* has —
focusable, named scroll regions — is stated beside it.

L13's index is not cosmetic: nothing enumerated what the documents claimed, which is the
mechanism by which L3 through L7 all went unnoticed.

**One piece of drift was created and then fixed inside this tier:** the spec's contract
example still showed schema 1 with `head`, `last_commit`, PR `worktree` and `assignees`
after `5b32be6` removed them. Updating the code and leaving the document behind is the
exact failure the audit was about, so it was caught and corrected in `ff56ba4`.

---

## New findings raised during remediation

Not in the original audit. Recorded here for the second pass rather than fixed inline.

### N1 · The fast-tick `ReplayRunner` fixture is duplicated across two test modules

*Low · found while fixing H1*

`tests/test_cli.py::TestBuildSnapshot` and `tests/test_serve.py::_fast_tick_runner` carry
byte-similar recording dicts for the same fast tick. H1's preparation deduplicated the
copies **inside** `test_serve.py`, but the `test_cli.py` copy remains.

**Consequence** Two fixtures describing one scenario are free to drift, and a fast-tick
fixture that disagrees with itself would make one of the two suites test a tick that
cannot happen. No consequence today — they currently agree.

**Change** Move the recordings to a shared `tests/fixtures.py`. Deferred rather than done,
because widening H1's diff into a second test module is how a focused fix becomes an
unreviewable one. H7 did extract `test_cli.py`'s copy into a `_recordings()` helper, so
there are now two named fixtures instead of one named and one inline — still two.

### N2 · `/favicon.ico` 404s on every page load

*Low · found in the browser console while verifying H5*

**Evidence** Browser console, first load:

```
[ERROR] Failed to load resource: the server responded with a status of 404
        (Not Found) @ http://127.0.0.1:8787/favicon.ico
```

**Consequence** Cosmetic only, but it means the console is never clean, so a real
error has to be spotted among noise. Pre-existing, not introduced by this pass.

**Change** Serve a tiny inline favicon, or return 204 for that path.

### N3 · `HEAD` requests return 501

*Low · found while verifying the cache header*

**Evidence** `Handler` implements `do_GET` only:

```
=== HEAD ===
HTTP/1.1 501 Unsupported method ('HEAD')
```

**Consequence** Minor, but it cost a wrong conclusion during this session: `curl -I`
reported no `Cache-Control` header, which looked like the fix having failed when in
fact the request method was unsupported. Anything health-checking this server with
HEAD would see it as broken.

**Change** Add `do_HEAD = do_GET`-style handling, or accept it and note it.

### N4 · Static assets were cacheable — FIXED in this pass

*Medium when found · fixed in `8d98887`*

**Evidence** No `Cache-Control` header on any response, no build step, no
fingerprinted asset names. An edited `loom.css` keeps its URL, so a browser serves
the stale copy after a reload.

**Consequence** Observed live: a restyled page came back looking entirely unchanged,
which reads exactly like the edit having failed. Cost a confused round trip.

**Fixed** `no-store, must-revalidate` on every response, pinned by
`test_nothing_is_cacheable`, which was verified to fail without the header.

---

## Environment findings — not Loom, but they blocked or disrupted this work

Recorded because they cost real time during this session and are not visible from
the codebase.

### E1 · The commit gate could not see Loom's test command

`~/.claude/hooks/post-bash.sh` (a symlink into `serina-learning`) matched 12 test
runners and **not** `python3 -m unittest`, so a passing suite could never stamp
`.claude/.verified` and every commit was blocked. One alternative added to the
pattern, with Serina's approval, which fixes it for every Python stdlib project.

### E2 · That same hook treats an unknown exit code as a PASS

`post-bash.sh:30` — `if [ "$EXIT_CODE" = "0" ] || [ "$EXIT_CODE" = "unknown" ]`. If
those JSON field paths ever stop matching, a **failing** test run stamps as verified.
A fail-open default in the one mechanism whose job is to be closed. **Raised, not
changed — Serina's gate, Serina's call.**

Related: the stamp is written to `$CLAUDE_PROJECT_DIR`, which is the `~/Launchpad`
container, not the repo being worked in. So a passing suite in one child unlocks
commits in all of them. Also raised rather than changed.

### E3 · A broken `linkedin` MCP server was opening a browser on a loop

Not related to Loom at all, but it disrupted the session. `claude mcp list` showed:

```
linkedin: ... npx -y @pegasusheavy/linkedin-mcp
          ✘ Failed to connect — connection timed out after 30000ms
```

It failed on a 30s timeout every session, was respawned each time, and never exited
— **12 orphaned processes across 4 generations, the oldest running 7 days.** The
package opens a browser to authenticate, which was the recurring LinkedIn popup.

Removed at Serina's explicit request via `claude mcp remove linkedin`. The
`LINKEDIN_*` exports in `~/.secrets` were left untouched, and no credential file was
read at any point — `claude mcp list` and `claude mcp remove` are the tool's own
commands, which is the correct path for exactly this reason.

**I initially misattributed this to my own `wslview` call and said so; that was
wrong.** A single `wslview` invocation had run, but no Windows-facing process
survived it, and the real cause was the MCP server. Corrected in the moment because
it changed what needed fixing.

### E4 · `mempalace` MCP server is also dead

```
mempalace: ... ✘ Failed to connect — ENOENT: no such file or directory,
               posix_spawn '/home/serina/.local/pipx/venvs/mempalace/bin/python'
```

Its pipx virtualenv python is gone, so it fails on every session start. **Left
alone** — not asked to touch it.
