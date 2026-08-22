Issue #11 — Add a tokens-and-cost panel, read from local transcripts
Stated size: no `Size` line on the issue → directed by Serina at planning time (2026-08-17) to treat as more than an hour → cap: 12 steps
Reviewed 2026-08-23 (review-plan) → 1 Blocker, 4 High, 1 Medium, all in the plan and none yet built. Amended in place the same day; the corrections and the evidence behind them are recorded inline rather than only in the review, so a builder reading this file alone still sees why each rule is what it is.

ALREADY TRUE  (verified against git and a live run, not notes)
  collect() assembles each worktree dict from gitsrc + agents + ghsrc, one call
    per source per worktree (loom/collect.py:125-246)
  agents.read_state_dir() reads ~/.loom/state/*.json; each record carries
    session_id, cwd, state, since, pid — six fields, written by
    hooks/loom_hook.py:71-101 (confirmed: hooks/loom_hook.py:71 docstring,
    tests/test_agents.py:33-34)
  agents.agent_for() matches sessions to a worktree by realpath prefix on
    `cwd` (loom/agents.py:129-147) — the same match rule this plan reuses
  Claude Code transcripts live at ~/.claude/projects/<slug>/<session_id>.jsonl,
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd) — EVERY non-alphanumeric character
    becomes "-", and nothing is prepended, because cwd already begins with "/".
    Verified 2026-08-23 against all 42 project directories on this machine that
    carry a readable `cwd`: this rule matched 42 of 42.
    The rule this file carried until then, `"-" + cwd.replace("/", "-")`, was
    wrong for 42 of 42 — it doubled the leading dash and left "." and "_" alone.
    Recorded rather than quietly deleted, because the failure it would have
    shipped is silent: `/home/serina/.buzz-dev` derives `--home-serina-.buzz-dev`
    where the real directory is `-home-serina--buzz-dev`, no such file exists,
    locate_transcript returns None, and every worktree reports cost `unknown`
    forever with every honesty check passing
  a transcript line carries top-level `sessionId`, `cwd`, and
    `message.model` + `message.usage.{input_tokens, cache_creation_input_tokens,
    cache_read_input_tokens, output_tokens}` — verified live by reading key
    names off ~/.claude/projects/-home-serina-Launchpad-loom/7033de3a-*.jsonl
  view.py is the sole place display DECISIONS are made (badge, aggregate_needs,
    announcement); loom.js only paints what it is handed — stated as the
    module's own boundary rule (loom/view.py:1-18)
  render_text() in loom_cli.py:201-219 is the CLI's per-repo panel renderer;
    finalise() in view.py:180-197 is the one boundary both CLI and server call
  loom is stdlib-only, enforced on every push by scripts/check_stdlib_only.py
    — no new import may be added for this feature (README.md:11-15)
  the ordering dependency the issue names (#3, #9) is CLOSED — confirmed via
    `gh issue view 3` and `gh issue view 9`
  no docs/plans/ directory existed before this file — first plan under it

STEP 1  cost.py: locate_transcript(home, cwd, session_id) -> Path|None   [independent]
        Builds the slug the same way Claude Code does — every non-alphanumeric
        character to "-", nothing prepended — and returns the expected .jsonl
        path only if it exists.
        done when: a test plants a .jsonl at a HARDCODED LITERAL slug directory
        and gets that exact path back. Never at a path the test re-derives from
        the function's own rule — that asserts only self-consistency and passes
        under any rule at all, including the wrong one this plan carried. The
        fixture cwd must exercise all three characters where the right rule and
        the wrong one diverge: cwd "/tmp/x/.worktrees/a_b" must resolve under
        the literal directory name "-tmp-x--worktrees-a-b". A session_id with
        no matching file gets None.

STEP 2  cost.py: read_usage(transcript_path) -> list[(model, usage_dict)]   [needs 1]
        Streams the jsonl, pulling message.model + message.usage from lines
        where both are present. A malformed line is skipped, not raised,
        matching read_state_dir's tolerance (loom/agents.py:58-68).
        done when: a fixture .jsonl with 2 well-formed usage lines and 1
        malformed line returns exactly the 2 usage records, in order

STEP 3  cost.py: pricing table + sum_cost(usage_records) -> cost dict   [needs 2]
        FIVE per-token rates keyed by model name, not four: input, output,
        cache-read, and cache-write SPLIT BY TTL. A 5-minute cache write and a
        1-hour cache write are not the same price — 1.25x versus 2x base input —
        and the transcript reports them separately under usage.cache_creation as
        ephemeral_5m_input_tokens and ephemeral_1h_input_tokens. Read those two
        sub-keys, NOT the flat cache_creation_input_tokens, which collapses them
        into one number a single rate would then misprice.
        Measured 2026-08-23 on this repo's own transcripts: 6,757,319 tokens of
        1-hour cache writes and zero of 5-minute. Pricing every write at the
        5-minute rate would have printed ~$129 where the honest figure is ~$155,
        roughly 16% low — a wrong number, confidently, which is the one outcome
        #11 says this panel exists to refuse.
        Plus a "prices_as_of" date constant beside the table (per OPEN-4).
        Cost is summed PER RECORD at that record's own model's rates and then
        totalled — never one model's rate applied to a mixed-model list (OPEN-6).
        sum_cost() returns {"tokens": {5 buckets}, "model": <the model carrying
        the most tokens>, "models": <every model seen, with its token share>,
        "notional_cost_usd": float|None, "prices_as_of": <date string>}.
        An unrecognised model in ANY record, or a bucket absent from every
        record, returns notional_cost_usd=None — never a number from a guess.
        done when: `python3 -c "from loom.cost import sum_cost; ..."` against a
        fixture whose bucket values are known by hand prints the EXACT expected
        notional_cost_usd. Not merely a numeric one — "a number appeared" is
        true of every wrong rate as well as the right one. A second fixture
        mixing claude-opus-5 and claude-haiku-4-5 records prints a populated
        "model" and both entries in "models"; a third fixture with an
        unrecognised model name prints notional_cost_usd: None
                                                                      ← RUNS HERE

STEP 4  cost.py: worktree_cost(state_dir, worktree_path, home, now)   [needs 1,2,3]
        Matches every session whose cwd is the worktree or inside it (the
        same prefix rule as agent_for, loom/agents.py:129-147), resolves and
        reads each one's transcript, and combines them.
        STALE SESSIONS ARE INCLUDED IN THE SUM AND COUNTED — never dropped,
        and never folded in unlabelled (OPEN-5). A session is stale by the
        rule agent_for already uses: WORKING_STALE_SECONDS / PARKED_STALE_SECONDS
        against `since` (loom/agents.py:16-35, 177-196). That is why `now` is a
        REQUIRED argument here rather than defaulted, for the same reason
        agent_for requires it (loom/agents.py:133-137) — staleness must never
        depend on an invisible clock. The result carries "stale_sessions": <count>
        and "live_sessions": <count>, so the panel can say which part of a figure
        is history rather than current burn.
        If ANY matched session's transcript cannot be located or read, or a
        bucket is missing after combining, the WHOLE worktree result is {"tokens":
        None, "notional_cost_usd": None, "unknown_reason": <why>} — never a
        partial sum presented as complete.
        done when: five fixture cases (transcript found and complete; transcript
        missing for one of two matching sessions; a bucket absent from a summed
        record; one live session beside one stale session; zero matching
        sessions) each produce the shape the honesty requirement demands —
        populated only in the first and fourth, and the fourth additionally
        asserts the sum covers BOTH sessions and that stale_sessions == 1

STEP 5  Wire worktree_cost into collect()   [needs 4]
        Call it once per worktree beside the existing ahead/behind and
        status calls (loom/collect.py:141-151); attach the result under a
        new "cost" key on each worktree dict; add a "cost" SourceStatus
        entry to `sources` reporting ok=False with a reason only when a
        worktree's cost is unknown because a transcript was unreadable
        (never for a worktree with simply no active session — not an error).
        THIS IS THE STEP THAT PUTS A MULTI-MEGABYTE FILE READ INSIDE A TWO-
        SECOND LOOP. collect() is not only the CLI's one-shot path: `loom serve`
        calls it every FAST_SECONDS = 2 (loom/serve.py:16, 226-248), and
        serve.py:210-223 already records that collection is the expensive part
        and that stretching a tick is a real regression — audit finding M4.
        This repo's own largest transcript is 4.3 MB and 1,918 JSON-parsed
        lines, measured 2026-08-23, and transcripts only ever grow.
        So cache per transcript on (path, mtime, size) and re-read only what
        changed: an unchanged file must cost a stat, not a parse.
        done when: a `loom serve` TICK is timed, not a one-shot snapshot — the
        CLI path never enters the refresh loop and so structurally cannot see
        this regression, which is why the CLI-only check this step originally
        carried was not a check at all. Two consecutive ticks over an unchanged
        transcript show the second doing no re-parse; `loom snapshot --json` run
        from this repo still shows a non-null cost.tokens for at least one
        worktree; and every existing test in tests/test_collect.py still passes
        unmodified

STEP 6  view.py: fleet_total(repos), wired into finalise()   [needs 5]
        Follows the aggregate_needs/badge pattern (loom/view.py:122-147) —
        sums notional_cost_usd across every worktree with a known cost, and
        reports the unknown ones by count in the label text itself (per
        Serina's OPEN-2 decision above — "N worktrees excluded", never a
        silent gap), never folding an unknown into the sum as zero. It also
        carries the fleet-wide stale-session count through into the label
        (OPEN-5), so a total inflated by dead sessions says so rather than
        reading as live burn. Called from finalise() (loom/view.py:180-197) to
        attach snap["cost"] at the top level. The label also carries the
        "list-price equivalent, not a bill" caveat, so the frontend only paints.
        done when: a test with three worktrees (one priced and live, one priced
        but carrying a stale session, one unknown) asserts the total equals both
        priced figures, and the label text contains the caveat, "1" as the
        excluded count, and the stale-session count; `loom snapshot --json`
        shows the same shape for real

STEP 7  loom_cli.py: add the cost line to render_text()   [needs 5]
        loom_cli.py:201-219.
        done when: `loom snapshot` (no --json) prints a cost line per repo
        that has any worktree with a known cost

STEP 8  loom/static: render snap.cost on the dashboard   [needs 6]
        Paint-only per view.py's own boundary rule — the same way the badge
        and needs-you panels already render their view.py-computed fields.
        done when: `loom serve`, viewed in a browser, shows a cost panel
        whose text matches what view.py computed, and grep of loom.js for
        arithmetic on token counts finds none

STEP 9  Accessibility pass on the new panel   [needs 8]
        Keyboard reachability, and whether it needs its own live-region
        entry or folds into the existing announcement() sentence
        (loom/view.py:150-177) — decide explicitly rather than leaving it
        unannounced by omission.
        done when: the decision (folded in / separate / explicitly out of
        scope) is written down in the PR description, and a manual Tab-
        through of `loom serve` either reaches the panel (if interactive) or
        confirms it is non-interactive (if not)

STEP 10 tests/test_cost.py: full-module suite for cost.py   [needs 1,2,3,4]
        Covers the honesty cases named in the issue — missing bucket,
        unrecognised model, no matching session at all for a worktree —
        each asserting `unknown`, never a silently-partial number.
        Plus the four cases the 2026-08-23 review found would otherwise have
        shipped green, every one of them a test that could not fail:
          - a literal-path slug test over a cwd containing "." and "_" (step 1)
          - an exact-figure cost assertion that separates 5-minute from 1-hour
            cache writes, so a wrong rate fails rather than "a number" passing
            (step 3)
          - a session spanning claude-opus-5 and claude-haiku-4-5, asserting a
            populated "model" (step 3)
          - a stale session beside a live one, asserting both are summed and
            stale_sessions == 1 (step 4)
        done when: `python3 -m unittest tests.test_cost` passes and
        `python3 scripts/check_stdlib_only.py` still passes (no new import)

STEP 11 docs/superpowers/specs: design note for this panel   [needs 9]
        Matches the project's per-feature spec convention (2026-08-06-
        allow-list-design.md, 2026-08-10-langfuse-alongside-loom-design.md)
        — records the pricing table's source and staleness handling, the
        per-worktree vs fleet-total unknown rule, and the OPEN items below
        once Serina has resolved them.
        done when: docs/superpowers/specs/<date>-tokens-cost-design.md
        exists and README.md's Design bullet links it the way it links the
        other two specs

PARALLEL  Steps 1-4 all edit loom/cost.py and are sequential regardless of
          logical independence. Step 10 (tests/test_cost.py) touches a
          different file and can start as soon as step 4 lands, running
          alongside steps 5-9 rather than waiting for the dashboard work.
          Steps 6 (view.py) and 7 (loom_cli.py) both need only step 5, touch
          different files, and can run as parallel subagents once step 5 is
          done. Step 8 needs step 6 specifically (the label text), not step
          7, so it cannot start in that same parallel batch.

GATES     review-code and review-tests apply to the whole diff once step 10
          is done. review-a11y applies specifically to steps 8-9 (the new
          panel) before either is called finished. review-docs applies to
          step 11's spec file. If this PR is routed through Serina's
          review-pr pipeline, that gate supersedes running the four above by
          hand.

BUDGET    Step 4 (worktree_cost's honesty propagation) is the step most
          likely to eat the budget. Getting "unknown, never a partial sum"
          right across every combination — missing bucket, missing model,
          zero matching sessions, more than one matching session, live beside
          stale — is exactly the kind of case this project's own audit history
          (H3, M4, L2, H7 in collect.py's comments) shows gets subtly wrong on
          a first pass.
          Step 5 is the second risk, and a different KIND of risk: not
          wrongness but cost. A transcript re-read that looks free from the CLI
          is two thousand JSON parses a second under `loom serve`, and the
          CLI-only done-when this step originally carried could never have seen
          it. Budget for the mtime cache, not just the wiring.

OPEN      Six resolved by Serina — four on 2026-08-17, two more on 2026-08-23
          after this plan was reviewed — recorded here rather than only in
          chat, so the decisions survive past those conversations:

          1. RESOLVED — sum every matching session's transcript, not just the
             one agent_for() would report as "the" agent. Reasoning: "who is
             burning the most" must not go blind to a second live session in
             the same worktree, even though this breaks the singular-agent
             pattern every other per-worktree field uses. (Step 4 already
             matches this — no step text changes.)
          2. RESOLVED — the fleet total reports how many worktrees were
             excluded as unknown, not just the sum of the known ones.
             Reasoning: matches the project's existing SourceStatus
             convention (collect.py already says "could not measure N
             worktree(s)" rather than leaving a silent gap). (Step 6 done-when
             updated below.)
          3. RESOLVED — no SCHEMA_VERSION bump. Reasoning: the one precedent
             (collect.py:17-21) bumped it for fields LEAVING the contract; an
             additive field doesn't break a consumer that ignores unknown
             keys. Step 5 does not touch SCHEMA_VERSION.
          4. RESOLVED — pricing staleness is surfaced as a "prices as of
             <date>" field in the output, not just a code comment. Reasoning:
             visible to anyone reading the panel, matching the honesty-first
             framing of the rest of this feature. (Step 3 done-when updated
             below.)
          5. RESOLVED 2026-08-23 — stale sessions are INCLUDED in a worktree's
             sum and reported as a count, not excluded. Serina's reasoning, in
             her own words: it should be recorded. Dropping a dead session
             hides real spend, and this project's posture is that a gap must be
             visible rather than silent — the same rule collect.py already
             follows when it says "could not measure N worktree(s)" instead of
             leaving a hole. A labelled figure lets a reader see that a
             worktree's total is history rather than current burn; excluding it
             would answer #11's "right now" question by deleting evidence.
             (Steps 4 and 6 updated above.)
          6. RESOLVED 2026-08-23 — a session spanning more than one model is
             priced PER RECORD at that record's own rates, and reports the
             model carrying the most tokens plus a full "models" breakdown.
             Reasoning: the rule this plan carried until the review — "model is
             None if records span >1 model" — would have blanked the field on
             essentially every real session. This repo's own transcripts run
             623 claude-opus-5 records beside 2 claude-haiku-4-5 background
             calls, and two records out of 625 would have collapsed the field.
             #11 asks for the model explicitly, so None is not an answer.
             (Step 3 updated above.)

LEFT OUT  Any time-series or historical cost view, or the datastore/retention
          policy that would need — the issue says so explicitly, and it
          would break Loom's "one snapshot, no history, zero dependencies"
          design.
          A real "amount owed" dollar framing — the whole feature is scoped
          to a notional, comparative figure.
          Any live pricing lookup or third-party API — loom is stdlib-only,
          enforced by scripts/check_stdlib_only.py; pricing is a hardcoded
          table, not a network call.
          Cumulative cost beyond the currently-matched session(s) for a
          worktree — anything more would make Loom stateful, which is the
          thing #11 explicitly says not to build.
