Issue #17 — Untracked directories count as one file, so rank 5 understates what is at risk and new files never collide
Stated size: no `Size` line → directed by Serina at planning time (2026-09-06) to treat as 30-60 minutes → cap: 8 steps

ALREADY TRUE  (verified against git and real repro, not notes)
  worktree_status() runs `git status --porcelain=v1 -z` with no `-u` mode
    (loom/gitsrc.py:122), so git defaults to `-unormal`, which reports a
    wholly-new untracked directory as one line naming the directory, never
    the files inside it.
  status.paths feeds BOTH the dirty count (rank 5's "at risk" number) and,
    via touched_files() (loom/gitsrc.py:211-262), the collisions() matrix
    (loom/gitsrc.py:265-292) — confirmed by reading the call chain, not
    inferred: collect.py:140 builds one `statuses` dict per tick, passed to
    BOTH gitsrc.collisions() (collect.py:215) and rank.py's dirty-count path.
  REPRODUCED LIVE (two real git worktrees, temp repo, this session):
    two worktrees each creating a brand-new `newfeature/thing.ts` both
    report `?? newfeature/` — the SAME collapsed string — so today's code
    actually DOES flag this as a "collision" already, just mislabelled on
    the directory name rather than the real file. The issue's literal claim
    ("will not appear... at all") is the OUTCOME for the harder case below,
    not this one.
  A SECOND, NOT-IN-THE-ISSUE DEFECT, found by this plan's own live repro:
    two worktrees each creating a brand-new, SAME-NAMED directory but with
    DIFFERENT files inside (`shared/alpha.ts` vs `shared/beta.ts`) BOTH
    report `?? shared/` — so today's code reports a FALSE-POSITIVE collision
    on "shared/" even though the two files never actually collide. `-uall`
    fixes this in the same stroke as the undercount, because both defects
    share one root cause: a directory-name string standing in for the files
    inside it.
  THE GENUINELY MISSED CASE, reproduced live: worktree A has an
    ALREADY-TRACKED directory (some committed file already lives there) and
    adds an untracked file to it → git reports the SPECIFIC filename
    (`?? existingdir/thing.ts`), because git only collapses to a directory
    name when the ENTIRE directory is untracked. Worktree B creates the
    SAME logical file inside a BRAND-NEW directory → collapses to
    `?? newdir/`. Two different strings, no collision detected, even though
    both worktrees hold the same uncommitted file. This is the one case
    `-uall` is actually required to fix, not merely "probably right."
  `-uall` PERFORMANCE, MEASURED rather than guessed (the issue's own open
    question): timed `git status --porcelain=v1 -z` with and without
    `-uall` on ~/Launchpad/buzz, the largest real checkout on this machine
    (4.6M files under its worktree, per `find | wc -l`). Three runs each:
    without -uall: 0.11s cold, 0.02s / 0.02s warm. With -uall: 0.42s cold,
    0.03s / 0.05s warm. The warm-cache steady state — which is what a
    2-second refresh loop actually sees between ticks — costs roughly 1-3
    hundredths of a second more per worktree. This settles the issue's own
    "worth measuring before committing to it": the cost is real but small,
    and does not justify diverging the count path from the collision path
    (which finding M4 deliberately unified into one call).
  The literal command string "git status --porcelain=v1 -z" is hardcoded as
    a ReplayRunner fixture key in SEVEN call sites across SIX test files —
    not just the tests that exercise worktree_status directly:
      tests/test_gitsrc.py:143, :191
      tests/test_view.py:437
      tests/test_collect.py:157, :289, :458
      tests/test_cli.py:459
      tests/test_serve.py:245
    ReplayRunner "raises on anything unrecorded, on purpose" (loom/runner.py:47) —
    a plain dict[key_for(argv)] lookup with no .get() fallback. Changing the
    real command to add `-uall` without updating every one of these seven
    breaks all of them with a KeyError far from the actual cause, in test
    files that have nothing to do with this issue on their face.
  Existing TestWorktreeStatus fixtures all key off a single helper,
    `_status(out)` (tests/test_gitsrc.py:140-144), so updating that one
    helper's fixture key fixes every test built on it (tests/test_gitsrc.py:
    146-401ish) in one place — the seven-site list above is what's outside
    that helper's reach.
  Neither the issue nor loom/gitsrc.py's own docstrings currently document
    that `-uall` exists or why — this plan adds that comment as part of the
    fix, matching this codebase's own convention of recording the WHY next
    to the code it explains, not only in the issue.

STEP 1  loom/gitsrc.py: add -uall, update the seven fixture call sites      [independent]  ← RUNS HERE
        Change the invocation at loom/gitsrc.py:122 to
        `["git", "status", "--porcelain=v1", "-z", "-uall"]`. Add a comment
        stating WHY (untracked directories collapse to their own name
        without it, undercounting rank 5 and hiding collisions — cite this
        issue number) and the measured cost from ALREADY TRUE, so the next
        reader does not have to re-derive or re-measure it.
        Update the fixture key in ALL SEVEN call sites named in ALREADY TRUE
        to end in ` -uall`, including tests/test_gitsrc.py's shared
        `_status()` helper (which covers the bulk of TestWorktreeStatus by
        itself).
        done when: `python3 -m unittest discover -s tests` passes with ONLY
        the eight fixture-key edits (loom/gitsrc.py's real invocation plus
        the seven test call sites) and no other test content changed; a live
        two-worktree repro (recreating the "asymmetric tracked state" case
        from ALREADY TRUE, real git, real temp worktrees, not a fixture)
        run through the REAL worktree_status() now reports `paths` containing
        the specific filename in both worktrees, not a collapsed directory
        name in either.

STEP 2  tests/test_gitsrc.py: worktree_status-level tests for the three     [needs 1]
        real behaviours this issue and this plan found
        Three new test methods on TestWorktreeStatus, each using a fixture
        string taken from real `-uall` output verified in this plan's own
        repro (ALREADY TRUE), never a synthesised guess at git's format:
          - a brand-new directory containing SEVERAL files reports the TRUE
            untracked count (e.g. 3, not 1) and paths containing each real
            file, not the directory name — issue's stated Consequence 1
          - two worktrees' statuses, fed through touched_files() and
            collisions(), now DO detect a real shared file when one
            worktree's copy sits in an already-tracked directory (specific
            filename) and the other's sits in a brand-new one (previously
            collapsed) — issue's stated Consequence 2, and the case ALREADY
            TRUE marks as "the one -uall is actually required for"
          - two worktrees creating DIFFERENT files inside a same-named new
            directory do NOT collide — the negative control this plan's own
            live repro found (the false-positive defect), proving the fix
            does not trade an undercount for an over-report
        done when: all three pass, and reverting step 1's `-uall` flag alone
        (leaving everything else in place) makes at least the first and
        second fail — proving they exercise the actual fix, not merely the
        existing parsing logic.

STEP 3  tests/test_gitsrc.py: end-to-end collisions() proof, not just       [needs 1, 2]
        worktree_status() in isolation
        One new test on the existing collisions()-level test group (beside
        test_two_trees_touching_the_same_files_collide) using the
        asymmetric-tracked-state fixture from step 2's second case, run
        through the real collisions(runner, trees, base, statuses) function
        with two real Worktree entries — proving the fix reaches the actual
        matrix collect.py wires into a snapshot, not only the Status object
        one level down. The test's own docstring states what the PRE-fix
        code returned against this exact fixture (zero collisions), so the
        test's purpose survives after the fix looks unremarkable.
        done when: the test passes, and its docstring's stated pre-fix
        behaviour is itself verified by temporarily reverting step 1's flag
        and confirming the assertion flips to zero collisions found.

PARALLEL  None of these three can be dispatched as independent subagents.
          Step 2 and step 3 both depend on step 1's flag existing before
          their done-when checks mean anything, and step 3 specifically
          needs step 2's fixture data to already be verified real (not
          re-deriving it). This is a strictly sequential 3-step plan, same
          shape as issue #15's.

GATES     review-code and review-tests apply to the whole diff once step 3
          is done. review-a11y does not apply — no UI touched.
          qa explore mode DOES apply: after building, run
          `./bin/loom snapshot --all` against this machine's real
          ~/Launchpad fleet (which has genuinely dirty, multi-worktree repos
          like buzz) and manually compare the reported dirty counts and
          collisions against `git status -uall` run by hand in a couple of
          those worktrees — a real-world sanity check no unit test fixture
          can substitute for.

BUDGET    Step 1 is the step most likely to eat the budget — not the
          one-line git-invocation change itself, but finding and correctly
          updating all seven fixture call sites. Missing even one produces a
          KeyError failure in a test file this issue has nothing else to do
          with, which reads as an unrelated regression rather than what it
          actually is.

OPEN      None. The issue's own open question — whether `-uall`'s cost
          justifies diverging the count path from the collision path — is
          closed by this plan's measurement: warm-cache cost on the largest
          real checkout on this machine is 1-3 hundredths of a second extra
          per worktree, which does not justify undoing finding M4's
          single-call consolidation.

LEFT OUT  A per-worktree timeout or fallback for a hypothetical repository
          with an enormous number of individually-untracked, non-ignored
          loose files (as opposed to files inside one collapsible new
          directory, which is the shape `-uall`'s cost actually scales
          with). No evidence today — including the buzz measurement above,
          the largest real checkout available — suggests this is a real
          problem worth guarding against pre-emptively, and Loom's existing
          honesty model (a worktree can already report as `unknown` when a
          git call fails, per Status | None) already has a place for this to
          land if it is ever observed, without new machinery.
