Loom interactivity round 1 — clickable PR, issue, and commit links
Stated size: Focused Checklist  →  cap: 8 steps

ALREADY TRUE  (verified against git and the real files, not the design doc's prose)
  loom/ghsrc.py's PR_FIELDS (line 26) and ISSUE_FIELDS (line 27) do not
    request `url` from `gh`; `PullRequest` (lines 40-48) and `Issue`
    (lines 51-56) have no `url` field. `origin_repo` (lines 59-69) is the
    only GitHub-URL-shaped logic in the file today — confirmed by
    `grep -rn "github.com" loom/`, which matches only font license text.
  loom/collect.py:176 builds `by_branch = {p.branch: p.number for p in
    prs}` — branch → bare PR NUMBER, discarding the rest of the matched
    `PullRequest` (including its future `url`). Used once, at
    loom/collect.py:204, to set a worktree dict's `"pr"` key.
  loom/gitsrc.py:186's `LOG_FORMAT` uses `%h` (abbreviated sha) only;
    there is no full sha anywhere in a commit record. GitHub resolves a
    short sha in a commit URL, so this is not a blocker — noted so a
    later step does not go looking for a full sha that was never
    collected.
  loom/rank.py:76,81 compute `pr_number = p.get("number", "?")` from
    `p` — the full serialized PR dict (`repo.get("prs", [])`, i.e. the
    dict this plan's step 1 widens to carry `url`) — then format it
    into `subject` (`f"PR #{pr_number}"`, lines 77,83) and discard both
    the variable and the rest of `p`. `p` already has everything this
    plan needs; nothing new has to reach `rank.py` from outside.
  loom/view.py's `aggregate_needs` (lines 143-146) spreads every
    original key through unchanged (`{**item, "repo": ..., "show_repo":
    ..., "label": ...}`) — confirmed by reading the function. A new key
    added to a `needs_you()` item reaches the client with no change
    here.
  EXACTLY TWO test call sites break if `PR_FIELDS`/`ISSUE_FIELDS` widen
    (confirmed by `grep -rn "number,title" tests/`, same class of trap
    as the earlier `-uall` fix's eight call sites, this time much
    smaller):
      tests/test_ghsrc.py:6-9 — `PR_ARGS`/`ISSUE_ARGS` module-level
        constants, each used across 9 call sites total but defined once.
      tests/test_collect.py:19-20 — `pr(number, branch)` helper,
        constructing a real `PullRequest(...)` POSITIONALLY with
        exactly 7 args, matching the dataclass's current 7 fields.
        Widening the dataclass to 8 fields breaks this call unless it's
        updated in the same step.
  No other test in the repo constructs `PullRequest` or `Issue`
    directly — confirmed by `grep -rn "PullRequest(\|Issue(" tests/
    loom/`: only the two real construction sites in loom/ghsrc.py and
    the one test helper above.
  `python3 -m unittest discover -s tests` passes 375 tests today (run
    live, this session, standalone).

STEP 1  loom/ghsrc.py: add `url` to PR_FIELDS/ISSUE_FIELDS and both      [independent]  ← RUNS HERE
        dataclasses; add commit_url(); fix the two broken fixtures
        Add `,url` to `PR_FIELDS` and `ISSUE_FIELDS` (loom/ghsrc.py:26-
        27); add `url: str` as the last field on `PullRequest` and
        `Issue`, populated from `gh`'s JSON exactly like every other
        field (`url=p["url"]` / `url=i["url"]`, following the existing
        `number=p["number"]` style — required, no default, matching
        every other field on both dataclasses). Add `commit_url(
        issue_repo: str | None, sha: str) -> str | None`, beside
        `origin_repo` in the same file: `None` when `issue_repo` is
        `None`, else `f"https://github.com/{issue_repo}/commit/{sha}"`.
        Fix both breaking fixtures from ALREADY TRUE: update
        `PR_ARGS`/`ISSUE_ARGS` in tests/test_ghsrc.py to end in `,url`;
        update tests/test_collect.py's `pr()` helper to pass a url
        (either append an 8th positional arg or convert the call to
        keywords — either is fine, keywords are less fragile against
        a future field reorder).
        Add new tests in tests/test_ghsrc.py: a `PullRequest`/`Issue`
        built from mock `gh` JSON carries `url` through unchanged;
        `commit_url` returns `None` for `issue_repo=None` and the
        exact expected string otherwise.
        done when: `python3 -m unittest tests.test_ghsrc -v` shows the
        new tests passing (real, running proof the url field survives
        a realistic gh-shaped JSON payload — this is the plan's
        demonstrable point, not the full feature); `python3 -m
        unittest discover -s tests` still shows 375+ passed with no
        regressions from the two fixture fixes.

STEP 2  loom/collect.py: widen by_branch to the full PullRequest,        [needs 1]
        add pr_url and commit url
        Change `by_branch` (loom/collect.py:176) from `{p.branch:
        p.number for p in prs}` to `{p.branch: p for p in prs}`; update
        the one call site (loom/collect.py:204) to derive both `"pr"`
        (the number) and a new `"pr_url"` key from the matched
        `PullRequest` object (`None` for both when no match, same
        shape `t.pr` already follows for "no PR"). Add a `"url"` key to
        each commit dict, via `ghsrc.commit_url(issue_repo, c.sha)` —
        find the exact spot commit dicts are built (this plan's
        ALREADY TRUE didn't need to cite it precisely since it's a
        single obvious insertion beside the existing `asdict(c)` call;
        confirm the real line when implementing).
        done when: a new tests/test_collect.py test builds a snapshot
        with a worktree whose branch matches an open PR and asserts
        the worktree dict's `pr_url` equals that PR's own `url` field
        exactly (not a separately constructed string — proves the
        `by_branch` widening actually reuses the object); a second new
        test asserts a commit dict's `url` matches `commit_url`'s own
        output for the same `issue_repo`/sha. `python3 -m unittest
        discover -s tests` still green.

STEP 3  loom/rank.py: needs_you()'s PR items carry the real pr_url       [needs 1]
        In the `pr_failing` and `pr_awaiting_review` branches
        (loom/rank.py:77-78, 82-83), add `"pr_url": p.get("url")` to
        each item dict — pulled from the same `p` that already
        provides `pr_number`, no new lookup. Widen tests/test_rank.py's
        `pr()` helper (line 19-21) to accept and pass through a `url`
        parameter (default a fixed test URL string, so every existing
        call site keeps working unchanged).
        This step and step 2 touch entirely different files
        (loom/rank.py + tests/test_rank.py vs loom/collect.py +
        tests/test_collect.py) — see PARALLEL.
        done when: a new tests/test_rank.py test asserts a
        `pr_failing`/`pr_awaiting_review` item's `pr_url` equals the
        input PR dict's own `url` — not derived from `pr_number`, not
        reconstructed. `python3 -m unittest discover -s tests` still
        green.

STEP 4  loom.js + loom.css: render real links wherever a PR/issue        [needs 2, 3]
        number or commit sha appears
        One new helper beside `text()` (loom.js:35-40): given a tag,
        visible text, class name, and a URL-or-`null`, returns an
        `<a href="..." target="_blank" rel="noopener noreferrer">`
        containing the visible text plus a trailing
        `<span class="visually-hidden"> (opens in a new tab)</span>`
        when the URL is truthy, else the exact same plain element
        `text()` already returns today. `rel="noopener noreferrer"` is
        not optional — its absence is a real security hole
        (reverse tabnabbing) on every `target="_blank"` link.
        Four call sites switch from `text(...)` to this helper:
          - renderTrees (loom.js:171) — the worktree PR cell, using
            `t.pr_url`
          - renderPrs (loom.js:240, 256) — each PR's `#{p.number}`
            using `p.url`, and each issue's `#{i.number}` using `i.url`
          - renderTicker (loom.js:329) — each commit's sha, using `c.url`
          - renderNeeds (loom.js:112) — for `pr_failing`/
            `pr_awaiting_review` items ONLY: `item.subject` is already
            exactly `"PR #N "` for these two kinds (loom/rank.py:77,83)
            — the whole `<strong>` becomes the link when `item.pr_url`
            is present, no substring parsing needed. The other four
            `needs_you` kinds (agent-waiting, collision, stopped-dirty,
            loose-end-flag) have no `pr_url` and render exactly as they
            do today.
        loom.css: `a.pr-num, a.issue-num, a.c-sha { text-decoration:
        none; }` plus a `:hover, :focus-visible` rule adding it back —
        scoped to the `a.` prefix specifically, so the plain (no-URL)
        `<span class="pr-num">` fallback is untouched. `:focus-visible`'s
        existing global outline rule already covers these links with no
        change.
        SUPERSEDED (2026-09-07, found by an independent codex review):
        hover/focus-only underlining for ALL FOUR classes shipped and then
        turned out to be a WCAG 1.4.1/G183 violation for the two that
        carry no other non-color cue -- `.issue-num` and `.c-sha` have
        normal font weight, so color was their only resting distinction
        from surrounding text. Those two now carry a PERMANENT underline.

        SUPERSEDED AGAIN (2026-09-07, found by an independent review-a11y +
        review-docs pass, confirmed Blocker by review-adjudicate): the
        paragraph above also claimed `.pr-num`/`.needs-subject` correctly
        kept hover-only underlining because their bold weight was "already
        a valid non-color cue." False for `.needs-subject` -- every
        needs-you item's subject renders through the same class whether or
        not it's linked (only two of six kinds ever carry a `pr_url`), so
        an unlinked sibling in the same list is equally bold and the cue
        distinguishes nothing. `.needs-subject` now carries the same
        permanent underline as `.issue-num`/`.c-sha`. `.pr-num` alone keeps
        hover-only underlining -- it has no unlinked-sibling problem, since
        it only ever renders on a worktree with a matched PR, whose `url`
        is a required field. Read the shipped CSS, not this paragraph, for
        the actual rule.
        done when: `python3 -m unittest discover -s tests` still green
        (this step touches only static assets); loading the dashboard
        in a real browser (`python3 loom_cli.py serve`) shows each of
        the four link types as a real `<a>` with the correct `href`
        (verify by inspecting the actual DOM, not by assuming the code
        is right) when the fleet has a GitHub remote with open PRs/
        issues, and shows the exact same plain text as before this
        step when it doesn't (a repo with no `origin` remote, or none
        matching `github.com`).

STEP 5  Full-pass manual verification                                   [needs 4]
        Genuine new Python behavior is covered by steps 1-3's real
        tests; this step is the rendering side's verification, same
        split the design doc's own Tests section describes.
        done when: `python3 -m unittest discover -s tests` shows all
        tests passed; in a real browser, clicking each of the four link
        types opens the correct real GitHub page in a new tab (verify
        the actual URL that opens, not just that a tab opened); the
        accessibility tree (not the visual page) shows "(opens in a new
        tab)" as part of each link's accessible name; Tab reaches every
        link and Enter activates it (keyboard-only, no mouse); a
        worktree/commit/PR/issue with no matching URL (simulate: a
        fleet with no GitHub remote, or a snapshot value with
        `pr_url`/`url` set to `null`) renders as plain, non-interactive
        text with no broken `href` and no console error.

PARALLEL  Step 1 is independent — touches only loom/ghsrc.py and its
          own test file. Steps 2 and 3 both depend on step 1 (they read
          `PullRequest`/`Issue`'s new `url` field) but are independent
          OF EACH OTHER — step 2 touches loom/collect.py +
          tests/test_collect.py, step 3 touches loom/rank.py +
          tests/test_rank.py, no file in common — so they may run as
          parallel subagents once step 1 lands. Step 4 needs both 2 and
          3 (loom.js reads `t.pr_url` from step 2 and `item.pr_url`
          from step 3) and step 5 needs step 4 — both strictly
          sequential after the steps 2/3 fan-in.

GATES     review-code applies to the whole diff once step 4 is done.
          review-tests applies this time — unlike the reskin, this plan
          adds genuine new Python test coverage (steps 1-3), and it
          should be checked for real assertions, not tautologies.
          review-a11y applies — new-tab links need their accessible
          warning verified as actually present in the accessibility
          tree, not just written in the markup.
          qa explore mode DOES apply: after step 5, drive the real
          dashboard against a real fleet with actual open PRs/issues
          (not just the mocked/simulated cases step 5's own done-when
          covers) and click through to confirm the destination pages
          are the intended ones.
          review-final applies once the above are clear, matching this
          repo's own convention of one whole-branch pass before merge.

BUDGET    Step 1 is the step most likely to eat the budget — not the
          field additions themselves, but making sure both broken test
          fixtures are actually found and fixed together (ALREADY TRUE
          names exactly two: tests/test_ghsrc.py's two constants and
          tests/test_collect.py's one helper). Missing either produces
          a test failure that reads as unrelated to this change.

OPEN      None. Every design decision (real gh url vs. reconstructed,
          new tab with an accessible warning, needs-you in scope,
          Loose ends out of scope, vanilla JS) was settled and
          confirmed with Serina before this plan was written — see the
          design doc's own resolution of each.

LEFT OUT  Linking the "Loose ends" panel's orphaned-PR references
          (loom/rank.py's `orphan_pr` flag, collect.py:61-63) — the
          identical shape to needs-you's PR links, deliberately
          deferred by Serina rather than expanded silently. Easy
          follow-up plan if wanted.
          Any change to how the commits ticker collects a sha — it
          stays the abbreviated `%h` it always was; GitHub resolves a
          short sha in a commit URL, so there is no reason to collect
          a full 40-character sha just for this.
          Sortable columns, expandable rows, or any other interactive
          widget beyond a plain link — out of scope for this round of
          "interactivity," per the design doc's own Scope section.
