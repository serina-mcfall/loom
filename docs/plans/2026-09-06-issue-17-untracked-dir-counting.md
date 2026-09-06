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
  THE GENUINELY MISSED CASE, reproduced live with the SAME final path in
    both worktrees (CORRECTED — an earlier draft of this section used two
    DIFFERENT paths here, existingdir/thing.ts vs newdir/thing.ts, which
    can never collide under any -u mode and did not demonstrate the defect
    it claimed to; found by an independent review-plan pass, 2026-09-06):
    two worktrees on DIVERGENT branches, both adding the identical
    uncommitted file `shared/thing.ts`. On branch "has-shared-dir",
    shared/ is ALREADY a tracked directory (committed earlier on that
    branch), so git reports the specific filename: `?? shared/thing.ts`.
    On branch "wt-b-fresh", shared/ was never committed at all, so the
    entire directory is untracked and collapses: `?? shared/`. WITHOUT
    -uall these are two different strings — no collision detected, even
    though both worktrees hold the identical uncommitted file. WITH -uall
    both report `?? shared/thing.ts` — same string, correctly detected.
    This is the one case `-uall` is actually required to fix.
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
    a ReplayRunner fixture key in EIGHT call sites across FIVE test files —
    CORRECTED from an earlier draft's miscount ("seven across six"; the
    line-by-line list below was always correct, only the prose totals were
    wrong — found by an independent review-plan pass, 2026-09-06, and
    reconfirmed by `git grep -o "git status --porcelain=v1 -z" -- 'tests/*'
    | wc -l` = 8) — not just the tests that exercise worktree_status
    directly:
      tests/test_gitsrc.py:143, :191
      tests/test_view.py:437
      tests/test_collect.py:157, :289, :458
      tests/test_cli.py:459
      tests/test_serve.py:245
    ReplayRunner "raises on anything unrecorded, on purpose" (loom/runner.py:47) —
    a plain dict[key_for(argv)] lookup with no .get() fallback. Changing the
    real command to add `-uall` without updating every one of these eight
    breaks all of them with a KeyError far from the actual cause, in test
    files that have nothing to do with this issue on their face.
  Existing TestWorktreeStatus fixtures all key off a single helper,
    `_status(out)` (tests/test_gitsrc.py:140-144), so updating that one
    helper's fixture key fixes every test built on it (tests/test_gitsrc.py:
    146-196, the rest of TestWorktreeStatus — CORRECTED from an earlier
    draft's "146-401ish", which both exceeded this 316-line file's actual
    length and overstated the helper's real reach by 200+ lines; found by
    a third independent review-plan pass, 2026-09-06. TestCollisions
    starts at :197 and never calls git status at all, confirmed by grep)
    in one place — the eight-site list above is what's outside that
    helper's reach.
  Neither the issue nor loom/gitsrc.py's own docstrings currently document
    that `-uall` exists or why — this plan adds that comment as part of the
    fix, matching this codebase's own convention of recording the WHY next
    to the code it explains, not only in the issue.

STEP 1  loom/gitsrc.py: add -uall, update the eight fixture call sites      [independent]  ← RUNS HERE
        Change the invocation at loom/gitsrc.py:122 to
        `["git", "status", "--porcelain=v1", "-z", "-uall"]`. Add a comment
        stating WHY (untracked directories collapse to their own name
        without it, undercounting rank 5 and hiding collisions — cite this
        issue number) and the measured cost from ALREADY TRUE, so the next
        reader does not have to re-derive or re-measure it.
        Update the fixture key in ALL EIGHT call sites named in ALREADY TRUE
        to end in ` -uall`, including tests/test_gitsrc.py's shared
        `_status()` helper (which covers the bulk of TestWorktreeStatus by
        itself).
        done when: `python3 -m unittest discover -s tests` passes with ONLY
        the nine fixture-key edits (loom/gitsrc.py's real invocation plus
        the eight test call sites) and no other test content changed; a live
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
        FIXTURE DESIGN splits into two shapes, because ONE worktree and TWO
        worktrees need different constructions — conflating them was found
        broken by a second independent review-plan pass (2026-09-06).
        TEST 1 (single worktree, the undercount case) uses the ORIGINAL
        both-keys design: a ReplayRunner registering BOTH "git status
        --porcelain=v1 -z" (pre-fix key) AND "... -uall" (post-fix key),
        each with the REAL git output verified in ALREADY TRUE. Reverting
        step 1's code makes it request the pre-fix key again, and the SAME
        fixture returns the SAME real pre-fix data — a meaningful assertion
        failure (wrong count, collapsed path), never a KeyError. This part
        still works exactly as designed; only tests 2 and 3 below needed
        fixing.
        TESTS 2 AND 3 (two worktrees, asymmetric or false-positive) CANNOT
        use one shared ReplayRunner for both worktrees — found live:
        ReplayRunner's key is `key_for(argv) = " ".join(argv)`
        (loom/runner.py:42-43), which does NOT include `cwd`. One shared
        runner therefore returns the IDENTICAL stdout to both worktrees for
        the identical command, which cannot express "worktree A sees the
        specific filename, worktree B sees the collapsed directory" — the
        entire point of both tests. (This is also why the file's own
        existing test_two_trees_touching_the_same_files_collide shares one
        runner: it WANTS both worktrees to see the same thing. These two
        new tests want the opposite, so they cannot copy that pattern.)
        CORRECTED post-build, by an independent review-final pass
        (2026-09-06): this hand-built-Status design is what actually
        shipped in ce26e33, and review-code/review-tests then found it
        unfalsifiable -- both tests passed unchanged with step 1's -uall
        flag fully reverted, because neither called the real
        worktree_status() at all. Commit 8d605e7 replaced it: each
        worktree gets its OWN ReplayRunner carrying BOTH the pre-fix and
        post-fix command keys with real captured output, and Status is
        derived through the REAL worktree_status() (see
        tests/test_gitsrc.py:250,
        test_asymmetric_tracked_state_now_collides_through_the_real_matrix).
        The paragraph below is what this plan originally called for and is
        kept for its own record, but it is NOT what shipped -- read it as
        history, not as the current design.
        Instead: construct each worktree's Status object DIRECTLY —
        `Status(dirty=Dirty(...), paths=frozenset({...}))` — using the
        REAL per-worktree values verified live in ALREADY TRUE's divergent-
        branch repro (worktree A: `{"shared/thing.ts"}`; worktree B
        pre-fix: `{"shared/"}`, post-fix: `{"shared/thing.ts"}`), rather
        than deriving them through worktree_status() at all. Verified this
        construction actually produces the claimed collisions() results:
        passing both hand-built Status objects through the real
        `statuses` dict parameter, with one ordinary shared runner
        supplying only the merge-base/diff calls (identical across both
        worktrees, which is fine — only the untracked-status paths need to
        differ, and touched_files() skips re-deriving those when a `status`
        is already supplied) gives `[]` collisions for the pre-fix pair and
        one real collision for the post-fix pair, exactly as intended.
        done when: test 1 passes against the post-fix key's data, and with
        step 1's code reverted (same fixture, both keys present) fails on a
        real, specific assertion — never a KeyError. Tests 2 and 3, built
        from hand-constructed per-worktree Status objects (not a shared
        ReplayRunner), pass against the post-fix values. Substituting each
        test's PRE-fix Status values (also hand-constructed from the same
        ALREADY TRUE data, never re-derived) in place of the post-fix ones
        must flip BOTH: test 2 from one real collision found to zero (the
        missed-detection direction), and test 3 from zero to ONE FALSE
        collision found on "shared/" — verified live, pre-fix values
        collide on the collapsed directory name even though the real files
        (alpha.ts vs beta.ts) never do. Test 3 existing as a negative
        control does NOT mean it stays zero under both fixture states; it
        means it correctly reads zero post-fix and correctly reads a
        (false) one pre-fix — if it read zero under BOTH, it would not be
        exercising the fix at all.

STEP 3  tests/test_gitsrc.py: end-to-end collisions() proof, not just       [needs 1, 2]
        worktree_status() in isolation
        One new test on the existing collisions()-level test group (beside
        test_two_trees_touching_the_same_files_collide) using the
        asymmetric-tracked-state Status objects from step 2's test 2, run
        through the real collisions(runner, trees, base, statuses) function
        with two real Worktree entries — proving the fix reaches the actual
        matrix collect.py wires into a snapshot, not only the Status object
        one level down. The test's own docstring states what the PRE-fix
        code returned against this exact fixture (zero collisions), so the
        test's purpose survives after the fix looks unremarkable.
        CORRECTED post-build, same as step 2 above: this test's design was
        absorbed into step 2's rewrite rather than surviving as its own
        commit -- 8d605e7 deleted a byte-identical duplicate of it from
        TestCollisions and kept the rewritten version inside
        TestWorktreeStatus instead (see the note at step 2). There is no
        separate collisions()-level test in TestCollisions for this fix
        as a result; the coverage is real, but it does not live where this
        step originally said it would.
        FIXTURE, corrected the same way step 2's tests 2 and 3 were —
        found by a second independent review-plan pass (2026-09-06) that a
        SHARED ReplayRunner cannot give the two worktrees different status
        output (ReplayRunner keys on argv only, not cwd; verified live: a
        shared runner here collapses both worktrees to the SAME collapsed
        "shared/" pre-fix, which — unlike test 2's genuinely-missed case —
        actually DOES register as a collision on the directory name, the
        wrong result for the wrong reason, not the "zero collisions" the
        test needs). Pass the two hand-built Status objects (one per
        worktree, from step 2's test 2 data) through collisions()'s
        `statuses` parameter directly; a single ordinary runner supplies
        only the merge-base/diff calls, which are identical across both
        worktrees here and need no per-worktree variance. Verified live
        this construction gives [] for the pre-fix pair and one real
        collision for the post-fix pair.
        done when: the test passes against the post-fix Status pair, and
        its docstring's stated pre-fix behaviour is itself verified — with
        the SAME two hand-built Status objects swapped for their pre-fix
        values (never re-derived through a runner) — by confirming the
        assertion actually flips to zero collisions found.

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

BUDGET    Step 1 is A budget risk — not the one-line git-invocation change
          itself, but finding and correctly updating all eight fixture call
          sites. Missing even one produces a KeyError failure in a test file
          this issue has nothing else to do with, which reads as an
          unrelated regression rather than what it actually is.
          THE BIGGER RISK, found by a second independent review-plan pass
          (2026-09-06): ReplayRunner keys on argv alone — `key_for(argv) =
          " ".join(argv)` (loom/runner.py:42-43) — NOT on cwd, so one
          shared runner instance cannot give two different worktrees two
          different outputs for the identical git-status command. Steps 2
          and 3's multi-worktree tests must build each worktree's Status
          object from its OWN isolated runner (or construct Status directly
          by hand) and pass the results through collisions()'s `statuses`
          dict, never share one runner across worktrees that need to look
          different. See steps 2 and 3's own corrected fixture text.

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
