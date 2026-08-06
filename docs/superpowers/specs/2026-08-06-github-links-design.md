# Loom — links from the board to GitHub

- **Date:** 2026-08-06
- **Status:** approved
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing

## What was asked for, and what is being built instead

The request was a button in the Needs you strip that, once a PR has been reviewed and looks
good, approves the human review and merges it — in one click.

**A link is being built instead, and the reasoning belongs in the record.**

### Why not the button

**It would invert Loom's security posture.** The v1 threat model promises `gh` cannot act,
only read — verified: the only two invocations are `pr list` and `issue list`. The server
implements `do_GET` and nothing else. That is why this row of the gap table reads *Low*:

> The local server has no origin check or CSP · **Low** · Any process on the host can read
> the snapshot … DNS rebinding against a loopback service is a known class

**The Low rating is contingent on read-only.** Today the worst case is that something reads
fleet state. With a merge endpoint, the worst case becomes any local process — or a
malicious page via DNS rebinding — merging arbitrary pull requests using the operator's
authenticated `gh` credentials. Closing that properly means a CSRF token, `Origin` and
`Host` validation, and a rewritten threat model. The security work would be most of the
feature, not a detail of it.

**GitHub will not let the author approve their own pull request.** That deadlock is why the
`.superpowers/verdict.json` mechanism exists at all, so the button could not do what was
literally described. It would instead have to run `verdict.sh record ready`, commit, push,
poll for the gate, then merge — five steps, five failure modes.

**And the affordance works against the gate.** A control reading "looks good, merge" sits
beside a pull request TITLE, not a diff. `verdict.sh`'s own comments warn about this shape:
*"That is exactly how verify-gate.sh's escape hatch became its normal path."* The friction
of opening the diff is doing real work.

### What the link gets instead

Most of the actual annoyance — *which one, and where is it* — for about five percent of the
cost, no new server behaviour, and no boundary broken. Clicking the link puts the operator
on the diff, which is where the review happens anyway.

## The design

Each `needs_you` item and each pull request and issue in the panel gains a `url`.

```jsonc
{ "rank": 2, "label": "serina-learning · PR #16", "detail": "no review yet",
  "url": "https://github.com/launchpad-26/serina-learning/pull/16" }
```

**Built in Python, not in the page.** The page would otherwise have to scrape `"PR #16"` for
digits and cross-reference the repo list to find `owner/repo` — string handling that finding
H8 deliberately moved out of `loom.js`. The URL is built from `issue_repo`, which is the
value already passed to every `gh` call, so the link and the data agree by construction.

**`issue_repo` is not the directory name.** `launchpad-26/serina-learning` against a
directory called `serina-learning`. Using the directory name would produce a plausible URL
pointing at a repository that does not exist, which is worse than no link.

### Which rows get one

| Rank | Links to |
|---|---|
| 2 · PR awaiting review | the pull request |
| 4 · PR with failing checks | the pull request |
| 6 · `orphan_pr` flag | the pull request it names |
| 1 · agent blocked on a prompt | nothing — no GitHub page exists for a local agent |
| 3 · collision | nothing — a file across two branches has no single URL |
| 5 · agent stopped with dirty work | nothing |
| 6 · `stale_dir` flag | nothing |

### `url` is null, never a guess

Null when the item is not PR-derived, and null when `issue_repo` could not be resolved from
the origin remote. The page renders no link rather than a broken one.

Same rule as `ahead: null` from finding H3: **a value that could not be determined is
absent, not blanked.** A link to a 404 is the confident-wrong-answer failure this project
exists to refuse.

## Accessibility

This is the page's **first interactive control**, so the requirements are new rather than
inherited.

- A real `<a href>`. Keyboard access, middle-click and ctrl-click all work for free; an
  `onclick` handler would silently break all three.
- **`↗` is decorative.** The accessible name is full text — `"Open PR #16 in
  serina-learning on GitHub"` — supplied as visually-hidden content inside the link. Not an
  `aria-label` on a glyph, because an icon-only link whose label drifts from its icon is a
  standing a11y trap.
- `target="_blank"` with `rel="noopener noreferrer"`, since the dashboard is left open.
- Focus indication is already covered by the existing `:focus-visible` rule.

**This activates a spec requirement that was vacuous until now.** Finding L5 made the
collapse-control requirement conditional because the page had no interactive elements. It
now has one, and the v1 design's claim that the page carries no controls must stop being
true by accident.

## Unchanged, deliberately

No `do_GET` sibling, no POST, no `gh` write subcommand, no threat-model change. The
`Low` rating stays `Low`.

## Tests

| Check | Negative control | Positive control |
|---|---|---|
| PR item gets a URL | A collision item gets `null` | Rank 2 item → `.../pull/16` |
| `issue_repo` is used, not the directory | — | `serina-learning` → `launchpad-26/serina-learning` in the URL |
| Unresolvable origin | — | `issue_repo` null → item `url` null, no link rendered |
| `orphan_pr` flag | A `stale_dir` flag gets `null` | An orphan PR flag → the PR's URL |
| Accessible name | — | The link's text contains the PR number and repo, not only the glyph |
| Issues in the panel | — | Issue #11 → `.../issues/11`, not `/pull/11` |
