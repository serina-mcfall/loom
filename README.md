# Loom

A local dashboard showing what a fleet of coding agents is doing across git worktrees:
who is blocked, which PRs are waiting on a human, and which worktrees are about to collide.

- **Design:** [`docs/superpowers/specs/2026-08-03-loom-design.md`](docs/superpowers/specs/2026-08-03-loom-design.md)
- **Audits and remediation:** [`docs/audits/`](docs/audits/README.md)

## Requirements

**Python 3.10 or newer. Nothing else — no pip install, no build step, no lockfile.**

Every import is standard library or first-party, enforced on every push by
`scripts/check_stdlib_only.py`, which fails on an import it has never heard of rather
than allowing it.

The floor was measured rather than assumed, by running the suite and a real
`loom snapshot` on each interpreter:

| Version | Result |
|---|---|
| 3.9 | Loom itself runs, but `check_stdlib_only.py` does not — `sys.stdlib_module_names` arrived in 3.10 |
| **3.10** | **everything works, including the project's own checks — the declared floor** |
| 3.11 · 3.12 · 3.13 | pass |

CI runs the suite on all four supported versions, so the floor is enforced rather
than claimed.

> There is deliberately **no `pyproject.toml`**. It would be the conventional home
> for `requires-python`, but the absence of any dependency file is itself the
> evidence the design cites for "no third-party supply chain" — a claim a reader can
> check in one `ls`. Trading that for one metadata line was not worth it, so the
> requirement is stated here and enforced in CI instead.

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
python3 -m unittest discover -s tests    # 285 tests, no network, no fixtures to fetch
python3 scripts/check_stdlib_only.py     # every import is stdlib or first-party
```

Both run on every push, across Python 3.10 through 3.13.

## Licence

[MIT](LICENSE) — © 2026 Serina McFall.

Chosen deliberately: the zero-dependency constraint exists so Loom can be dropped into
any repository, and without a licence nobody legally could.
