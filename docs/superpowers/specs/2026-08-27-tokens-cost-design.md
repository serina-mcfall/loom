# Loom — a tokens-and-cost panel, read from local transcripts

- **Date:** 2026-08-27
- **Status:** approved
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing. Adds a new `cost` field to the worktree shape and a
  new top-level `cost` field to the snapshot; both are additive, so
  `SCHEMA_VERSION` is not bumped (OPEN-3 below)

## The problem

Issue #11: nothing in Loom answers "which agent is burning the most tokens
right now, and roughly what has that cost". `#11` asks for, per worktree,
"input / cache-write / cache-read / output tokens, the model, and a notional
cost", plus a fleet-wide total under `--all`.

## Where the data comes from

Loom never asks Claude Code for this. Claude Code already writes every
session's usage to `~/.claude/projects/<slug>/<session_id>.jsonl`, and the
hook (`hooks/loom_hook.py`) deliberately records no prompt, no output, no
tool input and no transcript path — *"A local web server must never become a
place a transcript can leak from."* So `loom/cost.py` re-derives the
transcript's location from the same `cwd` and `session_id` the hook already
writes, and reads usage straight off disk.

**The slug rule**, verified live 2026-08-23 against all 42 project
directories on this machine that carry a readable `cwd`: every character in
`cwd` that is not `a-zA-Z0-9` becomes `-`, and nothing is prepended (`cwd`
already begins with `/`).

**Raw vs. resolved cwd**, measured live 2026-08-27, specifically because the
42-directory sample above contained no symlinked worktree and could not
settle it: created a real symlinked directory, ran a live `claude -p` session
from inside it, and read back both the resulting project directory name and
the transcript's own top-level `cwd` field. Both are the **resolved**
(`realpath`) path. `cost.worktree_cost` therefore matches sessions and builds
the slug from `realpath(cwd)` throughout — building it from the raw cwd, as
an earlier draft of this design assumed, would slugify every symlinked
worktree to a directory that is never created, and it would report
transcript-missing forever with every honesty check passing.

## The pricing table's source and staleness

Five per-token rates, not four: input, output, cache-read, and cache-write
**split by TTL** — a 5-minute cache write and a 1-hour cache write are priced
differently (1.25x and 2x the model's own input rate), and pricing every
write at the 5-minute rate would have understated this repo's own spend by
roughly 16% on 2026-08-23's measurement.

Rates are a hardcoded table in `loom/cost.py`, sourced from
platform.claude.com and re-verified 2026-08-27:

| Model | Input | Output |
|---|---|---|
| `claude-fable-5` | 10 | 50 |
| `claude-opus-5` | 5 | 25 |
| `claude-opus-4-7` | 5 | 25 |
| `claude-opus-4-8` | 5 | 25 |
| `claude-sonnet-5` | 2 (introductory, through 2026-08-31) | 10 |
| `claude-haiku-4-5` | 1 | 5 |

USD per million tokens. `claude-sonnet-5` reverts to 3 / 15 on 2026-09-01 —
this table must be re-checked and changed on or after that date, or the
figure for this machine's second-largest model population goes quietly 33%
low. `PRICES_AS_OF` (`"2026-08-27"`) is a constant beside the table and
travels all the way to the label a viewer reads — it records **when someone
last looked**, not when the number expires, so a table stamped fresh still
reads fresh the day a rate changes underneath it. That gap is accepted, not
solved: `#11` scopes this feature to `stdlib`-only, no network calls, so
there is no live pricing lookup to close it.

## Ids are resolved through an alias map, never a suffix regex

The obvious shortcut — strip a trailing `-\d{8}` off a dated id — was
inferred from the one dated id this table has ever needed
(`claude-haiku-4-5-20251001` → `claude-haiku-4-5`) and does not generalise: a
future dated id's stripped form need not be its real alias. `ALIAS_MAP` is an
explicit `{raw_id: canonical_id}` table instead, and an id it does not name
resolves to nothing — `unknown-model`, never a guessed rate.

Two retired model ids (`claude-opus-4-20250514`, `claude-sonnet-4-20250514`,
both retired 2026-06-15) deliberately have **no** entry: a transcript
carrying either was necessarily written before the retirement and has no
current rate to cite. Mapping a retired id to today's rate would itself be a
guess — the exact thing this table exists to refuse.

## Five buckets priced, six displayed

`sum_cost()` prices five buckets (`input`, `output`, `cache_read`,
`cache_write_5m`, `cache_write_1h`) and adds a **sixth, derived** key,
`cache_write` = `cache_write_5m + cache_write_1h`. This addition happens
exactly once, in `loom/cost.py`; the CLI (`loom_cli.py`) and the dashboard
(`loom/static/loom.js`) both **read** `tokens["cache_write"]` and never
recompute it. Both TTL keys still survive in the output, so a reader can see
which TTL the spend came from.

## Honesty: `notional_cost_usd` is `None`, never a guessed number

`sum_cost([])` — and a worktree with zero priceable records — returns
`notional_cost_usd: None`, not `0.0`. A brand-new session's transcript can
have a user line and no assistant `usage` line yet; that is "nothing was
measured", the same category as an unrecognised model, not "measured and the
answer is zero". Likewise, a token bucket that is present in some records and
absent (the **key itself missing**, not zero) in others cannot be summed
honestly and also returns `None`.

## Per-worktree honesty: one shape, unknown numbers

`worktree_cost()` (`loom/cost.py`) returns one of two shapes with the **same
keys** — only the numbers go `None` on the unknown branch, no key
disappears:

```jsonc
// populated
{"tokens": {...}, "notional_cost_usd": 70.99, "model": "claude-opus-5",
 "models": [...], "prices_as_of": "2026-08-27", "unknown_reason": null,
 "live_sessions": 1, "stale_sessions": 0, "stopped_sessions": 2, "undated_sessions": 0}

// unknown
{"tokens": null, "notional_cost_usd": null, "model": null, "models": [],
 "prices_as_of": "2026-08-27", "unknown_reason": "transcript-missing",
 "live_sessions": 0, "stale_sessions": 0, "stopped_sessions": 0, "undated_sessions": 1}
```

`unknown_reason` is one of six enumerated values, never free prose, because
two later steps (the CLI and the fleet total) discriminate on it:

| Reason | Meaning |
|---|---|
| `no-session` | no matching session — **not** an error |
| `transcript-missing` | matched a session, found no transcript file |
| `unreadable` | transcript exists but could not be read (`OSError` on open) |
| `no-usage-records` | matched session(s), zero priceable records |
| `missing-bucket` | a token bucket absent after combining |
| `unknown-model` | a model id with no rate |

`no-session` is the **normal** state of most worktrees most of the time, so
it is never treated as an error anywhere this reason is consumed.

**Every matching session's transcript is summed**, including stale and
stopped ones — dropping a dead session would hide real spend, and this
project's posture is that a gap must be visible rather than silent. A stopped
session with a readable transcript is **populated**, not unknown: only a
transcript that cannot be located or read makes the whole worktree unknown.
Four session counts (`live`, `stale`, `stopped`, `undated`) travel alongside
the cost figure either way, reusing `agents.py`'s own staleness rule and
`_age_seconds` directly rather than re-implementing it.

## Nested worktrees: nearest enclosing, never every ancestor

`agent_for`'s prefix-match rule (`loom/agents.py`) is correct for picking the
one agent that owns a worktree's badge, but reused naively for a **sum** it
double-counts: a session inside `buzz/__worktrees/<name>` matches both that
nested worktree's path prefix and `buzz`'s own. `worktree_cost` takes a
`sibling_paths` argument — every worktree path in the snapshot — and a
session belongs to the worktree only if no sibling is both a prefix match for
its cwd and strictly longer (by `realpath`) than the worktree's own path.
This is live on this machine's own fleet today: `buzz` has 16 of its 41
worktrees nested under its own root.

## Fleet total: excluded count, never a silent gap

`fleet_total()` (`loom/view.py`) sums `notional_cost_usd` across every
worktree with a known cost and reports the unknown ones **by count** in the
label — "N worktrees excluded" — rather than folding them into the sum as
zero (OPEN-2). Only `transcript-missing`, `unreadable`, `missing-bucket` and
`unknown-model` count as excluded; `no-session` and `no-usage-records` are
the normal shape of a quiet or just-started worktree, and counting them would
put a permanent, noisy "18 worktrees excluded" on the label.

Zero worktrees is **cannot-measure**, not measured-and-zero: a persistently
failing collector and a genuinely empty fleet both hand `fleet_total` zero
worktrees, so the total is `None` with every count at 0 in that case — a
confident `$0.00` can only ever mean a fleet that was actually measured and
actually spent nothing.

## Cost under `loom serve`'s refresh loop

`collect()` now calls `worktree_cost` once per worktree, every `FAST_SECONDS`
(2s). This repo's own largest transcript is 4.3 MB / 1,918 JSON-parsed lines
and transcripts only ever grow, so `cost.py` caches each transcript's parsed
usage records keyed on `(path, mtime, size)`: an unchanged file costs a
`stat`, not a re-parse. `cost.reset_cache()` clears it; tests call it in
`setUp`/`tearDown`.

## The six OPEN decisions, resolved

| # | Decision |
|---|---|
| 1 | Sum every matching session's transcript, not just the one `agent_for()` would report as "the" agent |
| 2 | The fleet total reports how many worktrees were excluded as unknown, not just the sum of the known ones |
| 3 | No `SCHEMA_VERSION` bump — additive fields only |
| 4 | Pricing staleness is a `prices_as_of` field in the output, not just a code comment |
| 5 | Stale sessions are included in a worktree's sum and reported as a count, not excluded |
| 6 | A session spanning more than one model is priced per record at that record's own rates, reports the model with the highest per-model notional cost, and a full `models` breakdown |

## Accessibility

The "Token cost" panel is discoverable via its own heading landmark but is
**not** a live region — neither its own `aria-live` entry nor folded into the
existing `#needs-announce` sentence. That region's 15-second debounce is
built around discrete, actionable state changes (a PR starting to fail); the
cost figure has no such event, drifting upward on nearly every tick, so a
periodic read-out would announce "the number changed" with nothing to act
on. No new interactive control was added, so the page's keyboard order is
unaffected.

## Out of scope, deliberately

- Any time-series or historical cost view, or the retention policy that would
  need — `#11` says so explicitly, and it would break Loom's "one snapshot,
  no history, zero dependencies" design
- A real "amount owed" dollar framing — the whole feature is a notional,
  comparative figure, stated as such in every label
- Any live pricing lookup or third-party API — Loom is `stdlib`-only
- Cumulative cost beyond the currently-matched session(s) for a worktree —
  anything more would make Loom stateful

## Tests

`tests/test_cost.py` covers `locate_transcript`, `read_usage`, `sum_cost` and
`worktree_cost` directly, including the raw-vs-resolved symlink case, the
alias map, the retired-id case, and a live (skipped-on-CI) check that every
model id actually on disk resolves to a rate. `tests/test_collect.py` and
`tests/test_view.py` cover the wiring into `collect()` and `fleet_total()`
end to end, including a real nested-worktree pair proving the fleet total
counts each session once, not the parent's cost twice.
