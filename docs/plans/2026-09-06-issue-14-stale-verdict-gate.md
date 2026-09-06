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
    `git merge-base HEAD main` (the point a branch diverged from main) is
    already implicitly relied on by nothing in this repo today; this plan
    is the first thing to use it.
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
  No test in this repo exercises the verdict gate's logic at all today —
    it is untested Python living inside a YAML string, the one piece of
    logic in this codebase's CI that isn't. Confirmed by grep: no
    "verdict" reference anywhere under tests/.

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
        code, every existing distinction (absence, non-READY state,
        unreachable sha, reachable-but-N-files-changed, exact match, verdict-
        file-only-changed) is preserved byte-for-byte. It exists to make the
        NEXT step's fix testable, not to fix anything itself.
        done when: tests/test_verdict_gate.py, using REAL git repositories
        built in temporary directories (not mocked — this issue is about
        real git topology, and a mock would just assert this plan's own
        assumptions back at itself), covers all six existing cases: no
        verdict file (block, "no ... in this branch"); state not READY
        (block, names the reason); sha unreachable from head (block, "not
        reachable from this PR's head"); sha reachable but N files changed
        beyond the verdict file (block, "N file(s) changed since... The
        review does not cover this code"); sha equals head exactly (open);
        sha reachable and ONLY the verdict file changed since (open). Also:
        running `python3 scripts/verdict_gate.py` against THIS repo's own
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
        done when: two new real-git-repo fixtures. (a) A fresh branch cut
        from a "main" whose OWN tracked verdict.json already names some
        OTHER, unrelated commit (mirroring the issue's own example almost
        exactly: "main carries READY for ec65092 (issue #3)") — the new
        branch has never itself been reviewed, and the check now prints the
        NEW "has never been reviewed" message, not the old generic one. (b)
        A branch that recorded ITS OWN verdict earlier in its own unique
        history (mirroring this exact session's real #11 experience: a
        verdict recorded mid-branch, then more commits landed on the SAME
        branch afterward) still prints the EXISTING "review does not cover
        this code" message, completely unchanged — proving the new
        distinction adds coverage without breaking the one case the issue
        itself says must keep working.

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
