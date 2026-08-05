# Loom — design

- **Date:** 2026-08-03
- **Status:** approved, not yet planned
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing

## What Loom is

A local dashboard that shows, at a glance, what a fleet of coding agents is doing
across git worktrees: which agent is blocked, which pull requests are waiting on a
human, and which worktrees are about to collide.

It has two faces over one set of facts:

- a browser page left open while working, refreshing itself
- a Claude Code skill that reads the same data and answers "what should I pick up next"

The name is a metaphor that does work: parallel threads worked at the same time and
woven into one cloth, and a collisions panel that is literally warp crossing weft.

## Why it exists

Six agents currently run in parallel across six worktrees of one repository. Their
state is spread across `git`, the GitHub API, tmux, and six terminal windows. Answering
"is anything waiting on me" means visiting each window in turn, and an agent blocked on
a permission prompt is invisible until someone looks.

Loom makes the blocked ones loud and everything else quiet.

## Decisions

These were chosen explicitly and are not open for re-litigation during planning.

| Decision | Choice |
|---|---|
| Moment of use | Glance on return, live in a pane, **and** triage ranking |
| Scope | Current repository, with an `--all` flag widening to every Launchpad child |
| Form factor | Local browser dashboard **and** a Claude Code skill |
| Agent state source | Hooks say what an agent is doing; the process list corroborates that it exists — **the second half was found unsound during execution and replaced by timestamp freshness; see correction 7.** The decision is left as it was taken rather than rewritten, because a spec that quietly matches whatever got built teaches nobody anything |
| v1 slice | Everything `git` + `gh` + hooks can feed. Cost/telemetry and replay deferred |
| Home | Its own repository (`loom`); the skill lives in `serina-skills` and drives it |

## Architecture

Five units, one contract.

```
  git ─┐
  gh  ─┼──▶  collect  ──▶  snapshot  ──┬──▶  serve ──SSE──▶  page (browser)
hooks ─┘     (pure)       THE CONTRACT  └──▶  skill (Claude, in chat)
```

### `collect`

Shells to `git` and `gh`, reads the hook state directory, **returns** one snapshot object.
A library function, not a script: it does not print, serve, or render. All the logic that
can be wrong lives here, which is why it is the only unit with substantial tests.

Takes its repository root, state directory, and command runner **as arguments**. Nothing
is hardcoded, so absence can be tested — a hardcoded path cannot be negative-tested.

A thin CLI wraps it for the skill: `loom snapshot [--all]` prints the snapshot as JSON to
stdout and exits. The wrapper contains no logic beyond argument parsing.

**Which repository.** Run from a worktree, `collect` resolves to the common git directory,
so it reports the whole fleet rather than the single tree it was invoked from. With
`--all`, it discovers every immediate child of `~/Launchpad` containing a `.git` entry and
reports each as its own entry in `repos`.

### `serve`

Runs `collect` on a timer, pushes each snapshot to connected browsers over server-sent
events, serves the static page. Bound to `127.0.0.1` only. Knows nothing about git.
A foreground process: it lives in a tmux pane and stops when the pane closes. No daemon.

### `page`

Vanilla HTML, CSS and JavaScript. No build step. Consumes snapshots, renders panels.
Knows nothing about `git` or `gh` — only the snapshot shape.

### `hooks`

A small script installed into Claude Code settings. Each session writes its own state
file. Fully independent of the other units: if hooks are not installed, `collect`
degrades to `running · state unknown` rather than reporting something it cannot know.

### `skill`

Lives at `serina-skills/plugins/serina/skills/loom/`. Runs `collect` and reasons over the
snapshot. Because the page and the skill consume the same snapshot, they cannot drift
into telling different stories.

## The snapshot contract

The interface between every unit. Versioned, because two consumers parse it.

```jsonc
{
  "schema": 1,
  "generated_at": "2026-08-03T07:45:00+12:00",
  "duration_ms": 340,
  "repos": [{
    "name": "example-repo",
    "root": "/home/you/Projects/example-repo",
    "issue_repo": "you/example-repo",
    "default_branch": "main",

    "worktrees": [{
      "dir": "feature-b",
      "path": "/home/you/Projects/example-worktrees/feature-b",
      "branch": "fix/feature-b-silent-load",
      "head": "3f0d19c",
      "ahead": 3,
      "behind": 1,
      "dirty": { "staged": 0, "unstaged": 7, "untracked": 2 },
      "last_commit": { "sha": "3f0d19c", "when": "…", "subject": "…" },
      "agent": {
        "state": "waiting",
        "source": "hook",
        "since": "2026-08-03T07:41:00+12:00",
        "pid": 2176024,
        "tmux_window": "wm-feature-b"
      },
      "pr": 58
    }],

    "prs": [{
      "number": 58, "title": "…", "branch": "fix/feature-b-silent-load",
      "draft": false, "review": null, "checks": "passing",
      "worktree": "feature-b", "updated_at": "…"
    }],

    "issues": [{ "number": 55, "title": "…", "labels": ["bug","client"], "assignees": [] }],

    "collisions": [{ "file": "src/board.ts", "branches": ["feature-a","feature-c"] }],

    "commits": [{ "when": "…", "branch": "feature-c", "sha": "161948b",
                  "subject": "…", "files": 2, "add": 64, "del": 1 }],

    "flags": [{ "kind": "orphan_pr", "severity": "warn", "subject": "PR #56",
                "detail": "branch fix/feature-a-null-case has no worktree" }],

    "sources": [{ "name": "git", "ok": true },
                { "name": "gh:prs", "ok": true },
                { "name": "gh:issues", "ok": false, "error": "HTTP 403 rate limited",
                  "last_good": "2026-08-03T07:41:00+12:00" },
                { "name": "hooks", "ok": true },
                { "name": "tmux", "ok": true }]
  }]
}
```

### `agent.state` values

| Value | Meaning |
|---|---|
| `working` | A hook reported activity, uncontradicted by the process source |
| `waiting` | A `Notification` hook fired — blocked on a permission prompt or input |
| `idle` | Session alive, turn finished, awaiting a prompt |
| `stale` | Hook claims activity, but its timestamp has stopped advancing (see correction 7) |
| `unknown` | Process alive, no hook data — hooks not installed for this session |
| `stopped` | Session ended |

## Error honesty

**`sources` is part of the schema, not an afterthought.** This is the most important
decision in the design.

It comes from an observed failure. On 2026-08-03, `gh issue list` run inside
a repository with both an `origin` and an `upstream` remote returned **empty with exit
code 0**, because no default repository was set and `gh` resolved to the `upstream` fork
parent rather than the `origin` where the issues actually live. Four issues were open at
the time. A dashboard that trusted that output would have displayed "0 issues" in
confident green.

Therefore:

1. Every panel is backed by a named source. If the source failed, the panel renders
   `PRs unavailable — gh: HTTP 403, last good 4m ago`. It never renders an empty list.
2. `issue_repo` is derived from the `origin` remote URL and passed explicitly to **every**
   `gh` call. `gh` is never allowed to resolve the repository itself.
3. An empty panel and a broken panel must look different at a glance, always.

**The flag is not uniform, and assuming it is will break the build.** `gh pr list` and
`gh issue list` take `-R owner/repo`; `gh repo view` takes the repository as a positional
argument and rejects `-R` outright. Every `gh` command Loom uses must have its repo-pinning
form confirmed against `--help` before it is relied on.

### Stale state is caught, not trusted

A crashed agent leaves a state file reading `working` forever, so an uncorroborated claim
must eventually expire. **Staleness is decided by timestamp freshness, not by the process
list** — the hook rewrites `since` on every event, so a live session's timestamp keeps
advancing and a dead one's freezes. A dead process cannot update a clock.

`working` claims expire after 15 minutes; `waiting` and `idle` after 12 hours, because a
parked agent legitimately stops refreshing while it waits. A timestamp that cannot be read
at all — missing, timezone-naive, unparseable, or in the future — means **cannot tell**, and
never concludes death.

The process list takes no part in this, in either direction. See correction 7 for why the
original pane-corroboration rule was removed as unsound.

## Panels

```
┌─ LOOM ─ example-repo ───────────────── 6 trees · 4 PRs · 4 issues ─ ●live 3s ┐
│  NEEDS YOU                                                                   │
│  WORKTREES        │  COLLISIONS       │  TICKER                              │
│  PRS & ISSUES     │  LOOSE ENDS                                              │
└─ sources: git ✓  gh ✓  hooks ✓ (6/6)  tmux ✓ ────────────────────────────────┘
```

| Panel | Contents |
|---|---|
| Needs you | The ranked triage strip. Empty on a good day |
| Worktrees | Directory, branch, agent state, ahead/behind, dirty counts, last activity |
| Collisions | File × branch matrix of uncommitted and unmerged changes against the merge-base |
| Ticker | Recent commits across all worktrees, newest first |
| PRs & issues | Open PRs with review and check state; open issues |
| Loose ends | Orphan PRs, stale directories, branches with no issue |
| Sources | Which sources answered, which failed, how stale the cached ones are |

The collisions panel compares **uncommitted and unmerged** changes against the
merge-base. It catches "about to conflict", not "already conflicted".

## Ranking

The "needs you" strip is ordered by how much a human is the bottleneck.

| # | Condition | Rationale |
|---|---|---|
| 1 | Agent blocked on a permission prompt | Burning wall-clock doing nothing; only a human unblocks it |
| 2 | PR with no review, and checks **not failing** | Finished work, parked; only a human moves it |
| 3 | Two dirty worktrees touching one file | A conflict not yet paid for; cheapest to act now |
| 4 | PR with failing checks | An agent can fix it, but a human may want to redirect |
| 5 | Agent stopped with uncommitted work | Work at risk of being lost |
| 6 | Loose ends | Real, but nothing breaks today |

Everything else stays out of the strip and lives in the lower panels.

## Hooks

| Hook event | Writes |
|---|---|
| `SessionStart` | session id, cwd, `state: idle`, pid (a debugging aid only) |
| `UserPromptSubmit` | `state: working` |
| `PreToolUse` | `state: working`, current tool name |
| `Notification` | `state: waiting` — this powers rank #1 |
| `Stop` | `state: idle` |
| `SessionEnd` | `state: stopped` |

Written to `~/.loom/state/<session-id>.json`.

**Reaping.** `SessionEnd` writes `stopped` rather than deleting, because rank #5 needs to
report an agent that stopped and left uncommitted work behind. `collect` removes state
files that have been `stopped` for more than 24 hours, so the directory does not grow
without bound.

**The pid is not a liveness signal.** A command hook runs under `sh -c`, so
`os.getppid()` is a shell wrapper that exits within milliseconds — verified by execution
2026-08-03. Using it for staleness would mark every hooked agent `stale` immediately,
defeating the authoritative source entirely.

**Staleness comes from the timestamp, not from the process list.** Hooks say WHAT an agent
is doing, and the freshness of their own `since` field says WHETHER that claim is still
current. An active state expires when its timestamp stops advancing past the limit for that
state. A timestamp that cannot be read means cannot tell, and never concludes death —
declaring an agent dead on no evidence is the worse lie.

The process list still supplies the `unknown` state, for a worktree with a live agent
process and no hook data at all. It plays no part in staleness. Corrected 2026-08-03; see
correction 7.

**Privacy boundary.** The state file contains only: session id, working directory, state,
tool name, timestamp, pid. No prompts, no model output, no file contents, no environment.
A local web server must not become a place transcripts can leak from.

## Refresh

Two clocks, deliberately.

| Source | Interval | Reason |
|---|---|---|
| git, hooks, tmux | 2s | Local and cheap |
| `gh` | 60s, cached | Network and rate-limited; cached age is displayed |

A single clock would mean either a laggy dashboard or hammering the GitHub API all day.

## Accessibility

Requirements, not aspirations. Each is verifiable.

- Status is **never** colour alone: a glyph and a word — `⛔ waiting`, `▶ working`,
  `○ idle`, `✕ stale`, `? unknown`.
- The collisions matrix is a real `<table>` with row and column headers. Every cell
  carries text, so a screen reader hears "board.ts, feature-c, collides" rather than silence.
- The "needs you" strip is `aria-live="polite"`, **debounced to ~15 seconds**. A 2-second
  live region would make a screen reader unusable.
- Every collapse control is a real `<button>`, keyboard reachable, `:focus-visible`
  styled, with an honest `aria-expanded`.
- `prefers-reduced-motion` disables every pulse and transition.
- Dark theme, with all text verified at 4.5:1 contrast or better.

## Testing

`collect` is the only unit with logic worth getting wrong. Fixtures are recorded from the
real repository, so tests run with no network and no GitHub.

Every check gets two tests: could it pass if the thing did not exist, and could the
measured value ever occur.

| Check | Negative control | Positive control |
|---|---|---|
| "gh unavailable" banner | Working `gh` returning genuinely zero issues must render `0 issues`, **not** the banner | `gh` exit 403 must render the banner |
| "waiting on you" row | Hook state with no waiting session — row absent | A `Notification` state file — row present |
| Stale agent | A `working` record refreshed seconds ago — reports `working` | A `working` record older than the 15-minute limit — reports `stale` |
| Unreadable timestamp | — | Missing, naive, unparseable or future `since` — reports the raw state, never `stale` |
| Collision detection | Two worktrees editing different files — no collision | Two worktrees editing one file — collision |
| Repo pinning | — | Every recorded `gh` command line names the resolved `issue_repo` explicitly |

## Out of scope for v1

Deferred deliberately, not forgotten:

- **Cost, tokens and model spend.** Requires standing up OpenTelemetry from Claude Code
  into a collector, and verifying what it actually emits per session before depending on it.
- **Replay and the history scrubber.** Requires a persisted event store and a recorded
  history format designed up front.
- **The animated centre-piece scene.** Decorative; costs nothing to add later.

## Known limitations

1. **Hooks only cover sessions started after installation.** The six agents running as of
   2026-08-03 will report `running · state unknown` until they are restarted, and rank #1
   cannot fire for them. This is a real v1 limitation, not a defect to chase.
2. `loom serve` is a foreground process. Closing its tmux pane stops it.
3. The snapshot schema is versioned because two consumers parse it and would otherwise
   drift silently.

## Threat model

Added 2026-08-03. Loom reads from sources other people can write to, and serves the result
over HTTP — so it needs this written down rather than assumed. The table's shape is
borrowed from the `agent-lockdown-challenge` common loop, whose central distinction applies
directly here: **a prompt is guidance; a harness or sandbox is containment.** The same
holds for a spec — a rule stated in prose is not a boundary until something enforces it.

| Area | Answer |
|---|---|
| **Useful task** | Report the true state of a worktree fleet to one local human |
| **Untrusted input** | Branch names, commit subjects, file paths, PR and issue titles, label and author names, tmux window names, and every hook state file |
| **Valuable access** | The full git history and working trees of every watched repo; `gh` running under the operator's authenticated credentials; `~/.loom/state/`; the ability to spawn subprocesses |
| **Exit paths** | The HTTP server; the CLI's stdout, which the skill pipes into a conversation transcript; the browser page |
| **Boundary** | Enforced in code and listed below — not in prose |

### Who controls the untrusted inputs

Worth stating plainly, because it is easy to assume this data is ours:

- **Anyone who can open a pull request or issue** controls PR titles, issue titles, labels
  and author names. On a public repository that is anyone at all.
- **Anyone who can push a branch** controls branch names, commit subjects and file paths.
- **Any agent** controls its own hook state file, including the `cwd` it claims.

### Boundaries that are enforced

Each was verified rather than assumed, on 2026-08-03:

| Boundary | Mechanism | How it was checked |
|---|---|---|
| No shell interpretation of any command | `subprocess.run` with an argv list; **no `shell=True` anywhere**, no `os.system` | grepped the whole package |
| Untrusted strings never become markup | the page sets `textContent` only; **zero uses of `innerHTML`** | grepped the page source |
| The server is not reachable off-host | bound to `127.0.0.1`, never `0.0.0.0` | stated in `serve`; verify with `ss -ltnp` |
| No conversation content leaves a session | the hook records six fields; `transcript_path` is deliberately not among them | asserted by a test that passes a payload containing a prompt and a credentials path |
| `gh` cannot act, only read | only `pr list` and `issue list` are ever invoked | no write subcommand exists in the code |
| No third-party supply chain | standard library only | no dependency file exists |

### Gaps, with honest severity

| Gap | Severity | Why |
|---|---|---|
| ~~A sandboxed agent may be reported `stale`~~ | **obsolete** | Withdrawn 2026-08-05. This described staleness corroborating against `pane_current_command ∈ {claude, node}`, which correction 7 removed: the process list plays no part in staleness. A sandboxed agent presenting as `bwrap` or `docker` now only affects the `unknown` fallback, which is informational. Kept struck through rather than deleted so the reasoning is not silently lost |
| **A live agent can still be reported `stale`** | **Low** | Timestamp expiry is what replaced pane corroboration, and the 15-minute `working` limit only bounds what the harness bounds. An MCP call has no cap, and neither does a long generation with no tool call, so a genuinely live agent CAN read `stale`. That is the acceptable direction — a false `stale` costs a glance, a false `working` is the lie the module exists to prevent — but it is a real false-positive source |
| A hook state file is trusted absolutely | Low | Any agent can claim any state, or a `cwd` belonging to another worktree, masking a real agent there. Writing the file already requires local access |
| `origin_repo` accepts a leading `--` | Low | `git@github.com:--upload-pack=evil/x.git` yields `--upload-pack=evil/x`, which is then passed as a `-R` value. Requires write access to `.git/config` first. GitHub names cannot start with `-`, so the regex should reject it |
| The snapshot contains `$HOME` paths | Low | The CLI's output names the operator's home directory and repository layout, and the skill pipes that into a conversation transcript |
| The local server has no origin check or CSP | Low | Any process on the host can read the snapshot. Browsers block cross-origin reads without CORS headers, and none are set, but DNS rebinding against a loopback service is a known class |

### The rule these gaps share

Every one is an instance of the same principle this document already applies to error
reporting: **a boundary that is true by accident is not a boundary.** The page is
XSS-safe because of how it happened to be written, not because a rule requires it. That is
now a stated requirement, and any future change that reaches for `innerHTML` is a defect.

## Corrections made during execution

Recorded rather than silently rewritten, because a spec that quietly matches whatever got
built teaches nobody anything. Each was forced by evidence, and each is dated 2026-08-03.

**1. Rank 2 asked for the impossible.** It read "PR with passing checks and no review".
Observed on the watched repository: every open PR has `statusCheckRollup: []` because no CI
is configured, so `checks` is `"none"` and a condition requiring `"passing"` could never
fire once. The second-most-important alert in the product was unreachable. Corrected above
to "no review, and checks not failing", where `"none"` counts as not failing.

**2. One `gh` source became two.** The `sources` example below shows a single `gh` entry.
PRs and issues are two independent `gh` calls that can fail independently — the shipped
snapshot therefore carries `gh:prs` and `gh:issues` separately. A single entry meant a
failed issue fetch could hide behind a successful PR fetch, which is this document's
founding incident reproduced inside the mechanism written to prevent it.

**3. `hooks` is never a failed source.** An empty state directory is the expected condition
before hooks are installed, not a breakage. Reporting it as `ok: false` was the same
empty-versus-broken confusion the `sources` list exists to prevent. How many agents
actually have hook data is derivable from each worktree's `agent.source`.

**4. The field is `review`, not `review_decision`.** The snapshot example below uses
`review_decision`; the implementation and both its consumers use `review`. The shorter name
won because it was already threaded through the code when the drift was noticed. Named here
so the example is not read as authoritative.

**5. Check states are whitelisted, not blacklisted.** Not in the original text, but it
belongs with this document's other honesty rules: `checks` is reported as `"passing"` only
for states known to be good — `SUCCESS`, `NEUTRAL`, `SKIPPED`. Anything unrecognised,
including states GitHub has not invented yet, degrades to `"pending"`. A blacklist fails
open, and a dashboard that calls an unknown state green is lying in the one direction that
matters.

**6. Task 0 needed a second mechanism.** Silencing the tooling artefacts took both a
committed `.gitignore` and the shared `.git/info/exclude`. A `.gitignore` on `main` reaches
no other branch's checkout, so on its own it changed nothing across six worktrees.

**7. Pane corroboration was unsound and is gone.** *Added 2026-08-05, from PR #12 — the
largest behavioural change in the project, and it was missing from this list for two days,
which is exactly what this section exists to prevent.*

The original rule read: tmux has panes somewhere but none in this worktree, therefore the
agent here is gone. **That inference does not hold.** tmux running proves nothing about where
agents live — an agent in a plain terminal, a VS Code terminal, or a pane whose cwd differs
has zero panes "here" while being entirely alive. On 2026-08-03 this reported the very
session that was reading the snapshot as `stale`.

It cannot work in principle either: pane count cannot bound how many agents are alive when
agents need no pane at all. So the surplus variant (`panes_here < active` → stale the rest)
was unsound for the same reason and went with it.

The signal that does work was already in the data. The hook rewrites `since` on every event,
so a live session's timestamp keeps advancing and a dead one's freezes. A dead process cannot
update a clock.

A first repair attempt let a pane in the worktree exempt sessions from ageing, and that
failed too: a pane cannot be attributed to a particular session, because the recorded pid is
the hook's own transient `sh -c` wrapper. One pane therefore exempted every session there,
and a dead session beside a live one kept reporting `working` — the forbidden direction. So
panes take no part in staleness now, in either direction.

**8. Rank 2 had a second unreachable condition.** *Added 2026-08-05.* Correction 1 fixed the
checks half of rank 2 and missed the review half. `reviewDecision` is a four-valued enum
(`null`, `REVIEW_REQUIRED`, `APPROVED`, `CHANGES_REQUESTED`) and the code tested it for
truthiness, so `REVIEW_REQUIRED` — the exact state rank 2 exists to catch — read as "already
reviewed". Rank 2 fired only on `null`, meaning only on repositories with no review
requirement at all. It is now an explicit whitelist. `CHANGES_REQUESTED` remains unranked
and undecided: it is blocked on the author, so it fails rank 2's rationale, and giving it a
tier of its own is a change to the ranking table above rather than a bug fix.

**9. `sources` needed per-fact granularity, not just per-subsystem.** *Added 2026-08-05.*
The error-honesty rule above was written for `gh` and enforced at subsystem granularity — one
`git` entry, hardcoded `ok: true`. That left a gap one layer down: a failed `git rev-list` or
`git status` for a single worktree returned `(0, 0)` and `Dirty(0,0,0)`, so a worktree 12
ahead with 9 uncommitted files rendered identically to one in perfect sync. This document's
founding incident, reproduced inside the Worktrees panel. Facts that cannot be determined are
now `null` rather than `0`, render as `?`, and are named by two new sources,
`git:worktree-facts` and `git:collisions`.

## Grounding

Observed on 2026-08-03 in a private repository running a live agent fleet, and used to
shape this design. Specifics are generalised here because that repository is private.

- 6 worktrees in a sibling directory, every one with uncommitted changes
- 6 live `claude` processes, one per worktree, in a single tmux session
- 4 open pull requests and 4 open issues
- 2 pull requests whose branch had no corresponding worktree
- 1 directory left behind that was no longer a git worktree
- `gh` resolving to the wrong remote and returning empty results with **exit code 0**

That last observation is the origin of the error-honesty requirement above, and it is the
single most load-bearing fact in this design.
