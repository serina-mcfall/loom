Issue #14 — Every new branch inherits a stale READY verdict, and it reads as a broken gate
Stated size: no `Size` line → directed by Serina at planning time (2026-09-06), plan to pick a remediation option → cap: 8 steps

ALREADY TRUE  (verified against git and the real committed workflow, not notes)
  The verdict-checking logic lives ENTIRELY as inline Python inside
    .github/workflows/checks.yml's `verdict:` job (lines 256-380ish), not in
    a standalone script this repo's test suite can import. Confirmed by
    reading the file directly — no scripts/verdict_gate.py or equivalent
    exists anywhere in this repo today.
  The gate already distinguishes TWO cases when sha != head — added by
    commit 31106e3 ("ci: the verdict gate could never go green", 2026-08-03,
    TWO DAYS BEFORE this issue was filed): "verdict names X, which is not
    reachable from this PR's head" (sha unreachable at all) versus "verdict
    is for X but head is Y, and N file(s) changed since... The review does
    not cover this code" (sha reachable, but more than the verdict file
    changed). `git log -p --all -- .github/workflows/checks.yml` shows both
    message strings were added ONCE, in that one commit, and never touched
    since — including not touched by anything that would have closed this
    issue.
  THIS DOES NOT ALREADY FIX ISSUE #14. Both of the issue's named scenarios
    — "a verdict for an unrelated commit" and "a verdict for an earlier
    commit on this branch" — currently produce the SAME message ("N files
    changed since... review does not cover this code"), because the
    existing distinction is REACHABILITY, not RELEVANCE. Once a PR merges
    with a real merge commit (not squashed — verified: `git log --oneline
    --merges main` shows "Merge pull request #N" entries, and
    `git merge-base --is-ancestor 0a916fc main` exits 0), EVERY commit ever
    merged becomes a reachable ancestor of every future branch — so the
    "unreachable" message essentially never fires in this repo's own
    workflow, and the issue's real complaint (a fresh branch's first CI run
    reads like a misconfigured gate) still reproduces today, unchanged.
  main's currently-tracked .superpowers/verdict.json (verified live,
    `git show main:.superpowers/verdict.json`) reads READY for 0a916fc,
    issue #11's tokens-cost work — exactly the shape issue #14 describes:
    any brand-new branch cut from main right now inherits this, entirely
    unrelated to whatever that new branch will actually build.
  git merge-base --is-ancestor A B is the exact primitive this plan needs:
    exits 0 if A is an ancestor of (or equal to) B, non-zero otherwise, no
    output either way — confirmed live against this repo's own history.
  CORRECTION — an earlier draft claimed plain `git merge-base` was unused
    anywhere in this repo. FALSE, found by an independent review-plan pass
    (2026-09-06): loom/gitsrc.py:235 already runs
    `git merge-base <base> HEAD`, with an ESTABLISHED, AUDITED convention
    for its failure mode this plan must follow, not invent fresh —
    loom/gitsrc.py:236-239: "if not mb.ok or not mb.stdout.strip(): ...
    return None" (a failed or empty merge-base is a THIRD, distinguishable
    outcome — "cannot tell" — never silently folded into either the
    success or the failure branch). That convention exists because of
    audit finding H3, "Failed git call indistinguishable from healthy,"
    fixed in 96961c7 (docs/audits/remediation-2026-08-05.md:28). Step 2
    below must follow this same convention for `git merge-base` failing
    against origin/main, or it reproduces H3's exact defect class in new
    code: a `git merge-base` call that fails (disjoint histories, a
    corrupted/foreign sha, a shallow or partial fetch) would otherwise
    silently read as "not an ancestor" — the SAME branch as the legitimate
    "reviewed, then diverged" case — misclassifying an indeterminate
    situation as a known-good one. Reproduced live: `git merge-base
    <head> ""` (an empty/unresolvable ref, the shape of an unhandled
    failure) exits 128 with no stdout and does not raise in Python
    (subprocess.run only raises with check=True) — so an unguarded read of
    this result silently falls through unless explicitly checked.
  Locally, both `main` and `origin/main` resolve to the same sha right now
    (confirmed: `git rev-parse --verify main` and `--verify origin/main`
    both print 628a9dd). In a GitHub Actions PR run, the checked-out ref is
    the PR's head — often detached or on a differently-named local branch —
    so a bare `main` may not resolve there even though `origin/main` should,
    per actions/checkout's documented fetch-depth:0 behaviour (fetches all
    branches and tags, not only the checked-out ref's own history). NOT
    verified live in an actual GitHub Actions run — flagged as a real risk
    in BUDGET and step 3's own done-when, not assumed safe.
  scripts/check_stdlib_only.py is this repo's own established convention
    for "a standalone, type-checked, stdlib-only script CI invokes directly"
    (FIRST_PARTY already includes "scripts" and "tests", so a new script and
    its test module need no allow-list change). mypy --strict --allow-any-
    generics already runs against scripts/ (.github/workflows/checks.yml's
    `types` job) — a new script there is checked automatically, for free.
  No test in this repo exercises the verdict GATE's logic at all today —
    it is untested Python living inside a YAML string, the one piece of
    logic in this codebase's CI that isn't. CORRECTED — an earlier draft
    said grep found no "verdict" reference anywhere under tests/; found
    false by an independent review-plan pass (2026-09-06):
    tests/test_collect.py:377 has one hit, "every staleness verdict in the
    snapshot" — an unrelated docstring about a different feature (worktree
    staleness, not this gate), so the substantive conclusion (nothing
    exercises the CI gate itself) still holds, but the claim as stated was
    wrong.
  THE FULL, EXACT set of branches the real inline Python has today — not
    the six an earlier draft of this plan named, which omitted two —
    verified by reading .github/workflows/checks.yml:278-373 line by line:
      1. verdict.json absent                          -> block, exit 1
      2. verdict.json present but not valid JSON       -> block, exit 1
      3. state field is not "READY"                    -> block, exit 1
      4. sha != head AND the `git diff` subprocess call
         itself raises (not a git failure — a Python
         exception: timeout, git missing, etc.)         -> block, exit 1
      5. sha != head AND git diff returns non-zero
         (sha unreachable from head at all)              -> block, exit 1
      6. sha != head AND diff succeeds AND more than
         just the verdict file changed                   -> block, exit 1
      7. sha != head AND diff succeeds AND ONLY the
         verdict file changed since                       -> OPEN, exit 0
      8. sha == head exactly                              -> OPEN, exit 0
    Cases 2 and 4 are the two an earlier draft's "six existing cases" list
    omitted. Case 4 in particular matters for step 1's own refactor: moving
    from block()'s direct `sys.exit(1)` to a function that RETURNS
    (exit_code, message) means every call site needs an explicit `return`,
    and case 2's except-block currently has no code after it that would
    crash if the return were missing — `state, sha = v.get(...)` executes
    unconditionally right after, with `v` never assigned when the JSON load
    raised, which is a NameError waiting for exactly this refactor to
    introduce it if case 2's own return is forgotten.

STEP 1  scripts/verdict_gate.py: extract the inline Python unchanged        [independent]  ← RUNS HERE
        Move checks.yml's inline Python verbatim into scripts/verdict_gate.py
        as a callable function, e.g. check(repo_root: str, head_sha: str,
        verdict_path: str = ".superpowers/verdict.json") -> tuple[int, str]
        returning (exit_code, message) rather than printing-and-exiting
        directly, so tests can assert on the message without capturing
        stdout. A thin main(argv: list[str]) -> int wraps it for CI: reads
        HEAD_SHA from the environment exactly as the current YAML does,
        prints the message, returns the exit code. checks.yml's verdict job
        now runs `python3 scripts/verdict_gate.py` with HEAD_SHA still set
        the same way (env, not a new mechanism).
        THIS STEP CHANGES NO BEHAVIOUR. Every message string, every exit
        code, and ALL EIGHT existing cases enumerated in ALREADY TRUE
        (not six — an earlier draft missed the malformed-JSON case and the
        diff-subprocess-raises case) are preserved byte-for-byte. EVERY
        call site converted from block()'s direct `sys.exit(1)` to the new
        `return (exit_code, message)` shape gets an explicit `return`
        immediately — including the malformed-JSON except-block, where
        ALREADY TRUE names the exact NameError this refactor would
        introduce if that one return were missed. This step exists to make
        the NEXT step's fix testable, not to fix anything itself.
        done when: tests/test_verdict_gate.py, using REAL git repositories
        built in temporary directories (not mocked — this issue is about
        real git topology, and a mock would just assert this plan's own
        assumptions back at itself), covers ALL EIGHT cases from ALREADY
        TRUE: absent (block, "no ... in this branch"); malformed JSON
        (block, "not readable JSON", NOT a NameError or any other
        exception); state not READY (block, names the reason); diff
        subprocess itself raising (block, "could not diff"); sha
        unreachable from head (block, "not reachable from this PR's
        head"); sha reachable but N files changed beyond the verdict file
        (block, "N file(s) changed since... The review does not cover this
        code"); sha equals head exactly (open); sha reachable and ONLY the
        verdict file changed since (open). Also: running
        `python3 scripts/verdict_gate.py` against THIS repo's own
        real current state (real HEAD, real .superpowers/verdict.json)
        prints the identical message the inline YAML version would have —
        checked once, side by side, before the inline copy is deleted.

STEP 2  scripts/verdict_gate.py: distinguish "never reviewed" from          [needs 1]
        "reviewed, then diverged"
        Inside the existing "sha reachable but N files changed" branch, add
        one more check: is `sha` an ancestor of (or equal to)
        `merge_base(head, origin/main)` — the point THIS branch diverged
        from main? If yes, the recorded verdict predates this branch's own
        first commit entirely; every one of the "N files changed" is
        everything this branch has ever done, not new work since a stale
        review. New message, distinct from the existing one: "This branch
        has never been reviewed. The recorded verdict (<sha>) predates this
        branch's own commits — it is inherited from whatever main's
        verdict.json happened to say when this branch was cut, not a review
        of anything here." If NO — sha is somewhere in this branch's OWN
        unique history, after the divergence point — keep the EXISTING
        message unchanged ("N files changed since... review does not cover
        this code"), because this is issue #14's own carved-out legitimate
        case: a branch reviewed once, then genuinely built on further.
        Resolve main as `origin/main` first, falling back to bare `main` if
        that ref does not exist (keeps local/manual runs working exactly as
        they do today, per ALREADY TRUE's note that both currently resolve
        identically here).
        A THIRD, INDETERMINATE OUTCOME IS REQUIRED, matching loom/gitsrc.py's
        OWN established convention for this exact primitive — found missing
        by an independent review-plan pass (2026-09-06). Computing
        merge_base(head, origin/main) is itself a git call that can fail
        (disjoint histories, a corrupted or foreign sha, a shallow or
        partial fetch) — reproduced live: `git merge-base <head> ""` exits
        128 with empty stdout and raises nothing in Python. loom/gitsrc.py:
        236-239 already treats exactly this shape ("not ok, or empty
        stdout") as a THIRD state, distinct from both "yes" and "no" —
        never silently folded into either. If this new code instead lets a
        failed merge-base fall through to "not an ancestor," it silently
        reuses the EXISTING "review does not cover this code" message for a
        case that is genuinely indeterminate, not "reviewed then
        diverged" — reproducing audit finding H3 ("failed git call
        indistinguishable from healthy") in brand-new code, in the same
        repository that already paid to fix it once elsewhere. So: if the
        merge-base call itself fails or returns empty, block with a
        message distinct from BOTH existing ones — e.g. "could not
        determine this branch's divergence point from main (<git's own
        stderr>) — treating as indeterminate, not as reviewed." — rather
        than guessing either way.
        done when: three new real-git-repo fixtures, not two. (a) A fresh
        branch cut from a "main" whose OWN tracked verdict.json already
        names some OTHER, unrelated commit (mirroring the issue's own
        example almost exactly: "main carries READY for ec65092 (issue
        #3)") — the new branch has never itself been reviewed, and the
        check now prints the NEW "has never been reviewed" message, not the
        old generic one. (b) A branch that recorded ITS OWN verdict earlier
        in its own unique history (mirroring this exact session's real #11
        experience: a verdict recorded mid-branch, then more commits landed
        on the SAME branch afterward) still prints the EXISTING "review
        does not cover this code" message, completely unchanged — proving
        the new distinction adds coverage without breaking the one case the
        issue itself says must keep working. (c) A repository where
        merge-base against origin/main genuinely cannot be computed
        (disjoint histories, built the same way loom/gitsrc.py's own
        test_touched_files_is_none_when_the_merge_base_cannot_be_found
        fixture does) prints the NEW "could not determine this branch's
        divergence point" message — never silently falling into case (b)'s
        message.

STEP 3  .github/workflows/checks.yml: wire the extracted script, confirm    [needs 1, 2]
        origin/main resolves in a real PR run
        Replace the inline Python block in the verdict job with a call to
        `python3 scripts/verdict_gate.py`, HEAD_SHA passed exactly as today.
        Delete the now-dead inline copy.
        THE ONE THING THIS PLAN CANNOT PROVE LOCALLY: whether
        `git rev-parse origin/main` resolves inside the actions/checkout@v4
        + fetch-depth:0 environment without an extra explicit fetch step.
        ALREADY TRUE states this is DOCUMENTED behaviour, not verified live.
        If the first real CI run of this PR shows origin/main failing to
        resolve, add an explicit `git fetch origin main` step before the
        Python call runs, and record that as a correction here rather than
        silently patching it.
        done when: the FIRST real CI run of this PR's own commits shows the
        `verdict` job either (a) correctly produce the current
        "reviewed for this commit" gate behaviour with no ref-resolution
        error, proving origin/main was reachable as assumed, or (b) fail
        with a ref-resolution error, in which case the fetch step above is
        added and this line updated to say so before the step is called
        done. This is real infrastructure, not something a local unit test
        can settle either way.

PARALLEL  None of these three can run as independent subagents. Step 2
          extends the exact function step 1 extracts; step 3 needs both the
          extraction and the new distinction in place before there is
          anything real to wire into CI. Strictly sequential.

GATES     review-code and review-tests apply to the whole diff once step 3
          is done. review-a11y does not apply — no UI. qa explore mode DOES
          apply, and is the ONLY way step 3's own done-when can actually be
          checked: this PR's own first CI run against a genuinely fresh
          branch (this one) is the live test of the exact scenario issue #14
          describes. Watch it, don't just trust that it will work.

BUDGET    Step 3's origin/main resolution is the single biggest risk in this
          plan, and it is explicitly NOT something more planning or more
          local testing can close — only a real CI run against this actual
          PR settles it. Do not let step 1 or step 2's more familiar,
          locally-testable work create false confidence that step 3 is
          equally safe.

OPEN      None. The issue names three options in rough order of size; this
          plan builds a version of the middle one (distinguish the two cases
          in the gate's message) but arrives at it through git topology
          (merge-base ancestry) rather than guessing from file lists alone,
          because that is the mechanical signal that actually answers "has
          this branch, this specific line of work, ever been reviewed" —
          which is the real question underneath both of the issue's named
          scenarios.

LEFT OUT  The issue's third, largest option — stop tracking verdict.json on
          main entirely, read it from somewhere per-branch instead. Left out
          because it is a bigger structural change than this issue asks for
          on its own merits (the gate already fails safe, per the issue's
          own words — this plan is about the MESSAGE, not the mechanism),
          and because moving where the verdict lives is exactly the kind of
          change that wants its own issue and its own plan, not a rider on
          a presentation fix.
