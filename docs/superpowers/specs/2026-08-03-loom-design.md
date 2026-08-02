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
| Agent state source | Hooks are authoritative; process liveness is the fallback |
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
      "draft": false, "review_decision": null, "checks": "passing",
      "worktree": "feature-b", "updated_at": "…"
    }],

    "issues": [{ "number": 55, "title": "…", "labels": ["bug","client"], "assignees": [] }],

    "collisions": [{ "file": "src/board.ts", "branches": ["feature-a","feature-c"] }],

    "commits": [{ "when": "…", "branch": "feature-c", "sha": "161948b",
                  "subject": "…", "files": 2, "add": 64, "del": 1 }],

    "flags": [{ "kind": "orphan_pr", "severity": "warn", "subject": "PR #56",
                "detail": "branch fix/feature-a-null-case has no worktree" }],

    "sources": [{ "name": "gh", "ok": false, "error": "HTTP 403 rate limited",
                  "last_good": "2026-08-03T07:41:00+12:00" }]
  }]
}
```

### `agent.state` values

| Value | Meaning |
|---|---|
| `working` | A hook reported activity and the process is alive |
| `waiting` | A `Notification` hook fired — blocked on a permission prompt or input |
| `idle` | Session alive, turn finished, awaiting a prompt |
| `stale` | State file claims activity but the recorded pid is gone |
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

A crashed agent leaves a state file reading `working` forever. `collect` cross-checks the
recorded pid against a live process. If the file claims activity and nothing is running,
the state is `stale` — never `working`.

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
| 2 | PR with passing checks and no review | Finished work, parked; only a human moves it |
| 3 | Two dirty worktrees touching one file | A conflict not yet paid for; cheapest to act now |
| 4 | PR with failing checks | An agent can fix it, but a human may want to redirect |
| 5 | Agent stopped with uncommitted work | Work at risk of being lost |
| 6 | Loose ends | Real, but nothing breaks today |

Everything else stays out of the strip and lives in the lower panels.

## Hooks

| Hook event | Writes |
|---|---|
| `SessionStart` | session id, cwd, `state: idle`, pid |
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
| Stale agent | Live pid with `working` — reports `working` | Dead pid with `working` — reports `stale` |
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
