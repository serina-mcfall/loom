# Loom

A local dashboard showing what a fleet of coding agents is doing across git worktrees:
who is blocked, which PRs are waiting on a human, and which worktrees are about to collide.

Design: `docs/superpowers/specs/2026-08-03-loom-design.md`

## Usage

Run everything through the `bin/loom` shim (it lives at `bin/loom`, not at the repo
root — a shim named `loom` at the top level would collide with the `loom/` package
every module imports):

```bash
./bin/loom snapshot            # human-readable fleet report for the current repo
./bin/loom snapshot --json     # the same, as JSON — what the skill and dashboard consume
./bin/loom serve                # dashboard on http://127.0.0.1:8787, refreshing itself
./bin/loom serve --port 9000    # same, on a different port
./bin/loom install-hooks        # write Loom's hooks into ~/.claude/settings.json
```

Add `--all` to `snapshot` or `serve` to widen scope from the current repository to
every git checkout under `~/Launchpad`. Without it, Loom reports only the repo you're
standing in (found via `git rev-parse --git-common-dir`).

### `install-hooks`

`./bin/loom install-hooks` merges Loom's hook commands into
`~/.claude/settings.json`, alongside whatever is already there.

**It only affects sessions started after it runs.** A Claude Code session already
running has already read its settings for this run — it will not pick up the new
hooks retroactively, and needs to be restarted to report real state. Until
`install-hooks` is run, nothing is installed: Loom does not write to your settings
file on its own, at import time, or as a side effect of `snapshot` or `serve`. It only
happens when you run that command deliberately.

An agent whose session was never hooked (or was hooked before an install) shows up
as `unknown`, not as idle or blocked — Loom reports what the hooks actually told it,
and says so plainly when they told it nothing.

## Running the tests

```bash
python3 -m unittest discover -s tests
```
