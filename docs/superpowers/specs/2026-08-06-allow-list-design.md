# Loom — which repositories the board shows

- **Date:** 2026-08-06
- **Status:** approved
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing. Narrows `--all`, which the v1 design left unfiltered

## The problem

`--all` shows every immediate child of `~/Launchpad` containing a `.git` entry. Launchpad
is a 16-week course container, so it accumulates finished challenges and never sheds them.
Observed 2026-08-06: seven repositories, of which **three were completed challenges** —
`nextjs-project`, `nextjs-project-tucktuck`, `worktrees-challenge`. They occupy the board,
the triage strip, and 4 subprocess spawns per tick each, for work nobody intends to touch.

## Why not filter by activity

Considered and rejected on evidence, not taste. Last-commit ages on 2026-08-06:

| Repository | Last commit | Wanted on the board? |
|---|---|---|
| `loom` | 67 minutes | yes |
| `serina-learning` | 7 minutes | yes |
| `serina-skills` | 2 hours | yes |
| **`skills`** | **8 days** | **yes** |
| `worktrees-challenge` | 2 days | no |
| `nextjs-project` | 8 days | no |
| `nextjs-project-tucktuck` | 8 days | no |

`skills` is exactly as stale as the two `nextjs` repos and is wanted. `worktrees-challenge`
is fresher than `skills` and is not. **Recency cannot separate the two sets**, so any
automatic rule would have to be overridden by hand anyway — at which point the hand-written
list is the mechanism, and the inference is only a source of surprise.

## Decision: an allow list, not a deny list

Both were considered. The allow list wins on how it ages: by week 16 there may be twenty
repositories and four that matter, so the file stays four lines. A deny list grows with
every finished challenge, and forgetting an entry silently clutters the board.

Its cost is real and accepted: **a new project is invisible until it is added.**

Also rejected: a `.loomignore` marker inside each repository. Self-documenting, but
`nextjs-project-tucktuck` is another team's checkout, and opting it out would mean writing
a file into someone else's repository.

## The file

`~/.loom/repos` — beside the `~/.loom/state` directory Loom already owns.

```
# Loom shows only these. Delete this file to show every Launchpad repo again.
loom
serina-learning
serina-skills
skills
```

One repository name per line. `#` begins a comment; blank lines are ignored. Names, not
paths: `--all`'s documented scope is the immediate children of `~/Launchpad`, and accepting
paths would quietly widen it.

## Two absences, and what each means

This is the part worth getting right, because both are cases where a wrong default lies.

**No file → every repository, exactly as today.** A missing config must never produce an
empty board. That is the empty-versus-broken confusion the whole `sources` mechanism exists
to prevent, and it also keeps the change backwards-compatible for any checkout without the
file.

**An empty file, or one containing only comments → every repository.** Approved explicitly.
An empty file is far more likely to be a mistake — a truncated write, a half-finished
edit — than a deliberate request for a blank board. The generous reading is the safe one
here, because the failure it prevents (a board that silently shows nothing) is worse than
the one it allows (a board showing more than intended, which is visible immediately).

## A name that matches no repository is reported, never dropped

If the file says `serina-skils`, Loom must say so. Silently dropping it would remove a
repository the operator asked for and give no reason — the same failure as `gh` returning
empty with exit code 0, which is this project's founding incident.

The snapshot therefore carries one new top-level field:

```jsonc
"config": {
  "source": "/home/serina/.loom/repos",   // null when no file exists
  "listed": 4,                            // names read from the file
  "missing": ["serina-skils"]             // named but not found under ~/Launchpad
}
```

**Both consumers read it.** `render_text` prints a line when `missing` is non-empty; the
page shows it beside the summary. A producer with no consumer was the largest single defect
cluster in the 2026-08-05 audit (finding L2), and this field does not get to repeat it.

`config` is present on every snapshot, including single-repository runs without `--all`,
where `source` is null and `listed` is 0. One shape, always — a field that appears and
disappears is a field consumers get wrong.

## Where the code goes

`discover_repos` gains an optional allow list and applies it to its result. It still scans
`~/Launchpad` and still tests for a `.git` **entry** rather than a directory, because a
linked worktree's `.git` is a file — that rule and its OSError handling are untouched.

Reading the file is its own function taking an injectable reader, so **absence can be
tested**. The v1 design's rule stands: a hardcoded path cannot be negative-tested.

## Out of scope, deliberately

- Absolute paths, so repositories outside `~/Launchpad` stay out of `--all`'s scope
- Globs or patterns
- Per-repository marker files
- Any change to single-repository mode, which resolves via `git rev-parse` and never reads
  this file

## Tests

Every check gets a negative control, per the v1 design's testing rule.

| Check | Negative control | Positive control |
|---|---|---|
| No file | — | Absent file → every repository, not none |
| Empty file | A file with names → only those | Empty file → every repository |
| Comments only | — | `#`-only file → every repository |
| Filtering | A name not in the file → excluded | Four names → exactly those four |
| Bad name | A file whose names all exist → `missing` empty | `serina-skils` → in `missing`, and the four good ones still returned |
| Comment and blank handling | — | Inline `#`, blank lines and surrounding whitespace all ignored |
| `config` shape | Single-repo mode → `source` null, `listed` 0 | `--all` with a file → source path and count |
