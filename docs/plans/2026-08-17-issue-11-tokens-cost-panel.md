Issue #11 — Add a tokens-and-cost panel, read from local transcripts
Stated size: no `Size` line on the issue → directed by Serina at planning time (2026-08-17) to treat as more than an hour → cap: 12 steps
Reviewed 2026-08-23 (review-plan) → 1 Blocker, 4 High, 1 Medium, all in the plan and none yet built. Amended in place the same day; the corrections and the evidence behind them are recorded inline rather than only in the review, so a builder reading this file alone still sees why each rule is what it is.
Reviewed a third time 2026-08-24 (review-final, clean session, genuinely independent) → 2 Blocker, 4 High, 5 Medium, 2 Low, all fixed here. One of its Blockers was a GATES paragraph asserting that check-ledger.sh could not parse this plan. It parses it fine — check-ledger.sh:54 accepts `STEP N` explicitly and prints PASS. That claim came from the previous review, was quoted into this file truncated at the clause disproving it, and was never checked against the script. A finding taken on trust from another agent and written into a permanent document is the same defect class as a rule taken on trust from a plausible name: verify, then record.
Reviewed again 2026-08-23 (review-final, on the amendment) → 2 Blocker, 7 High, 5 Medium, 2 Low. The first amendment had reintroduced its own Blocker in a new place: it keyed a test fixture on the model id `claude-haiku-4-5`, which exists nowhere on disk — the real id is `claude-haiku-4-5-20251001` — so a pricing table built to pass that test would have blanked loom's own worktree forever. Twice now the same failure class: a rule derived from a plausible NAME rather than from what is actually written, wrong against real data, failing silently to `unknown`, guarded by a test built from the same wrong assumption. Every id-derivation rule in this plan is now stated against a count taken from disk, and no fixture takes its expected value from the rule under test.

ALREADY TRUE  (verified against git and a live run, not notes)
  collect() assembles each worktree dict from gitsrc + agents + ghsrc, one call
    per source per worktree (loom/collect.py:125-246)
  agents.read_state_dir() reads ~/.loom/state/*.json; each record carries
    session_id, cwd, state, tool, since, pid — six fields, written by
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
  the hook DELIBERATELY does not record the transcript path, and must not start
    — hooks/loom_hook.py:3-4: "Deliberately records no prompt, no output, no
    tool input and no transcript path. A local web server must never become a
    place a transcript can leak from." The Claude Code hook payload carries
    `transcript_path` verbatim, so every bit of slug-derivation machinery in
    step 1 exists ONLY because that rule says no. Recorded here because the
    shortcut is obvious and looks like a simplification: the hook writes six
    fields (loom_hook.py:71-101) and it must not gain a seventh.
  a transcript line carries top-level `sessionId`, `cwd`, and
    `message.model` + `message.usage.{input_tokens, cache_creation_input_tokens,
    cache_read_input_tokens, output_tokens}` — verified live by reading key
    names off ~/.claude/projects/-home-serina-Launchpad-loom/7033de3a-*.jsonl
  `message.usage` ALSO carries a nested `cache_creation` object splitting the
    cache-write total by TTL: {ephemeral_5m_input_tokens,
    ephemeral_1h_input_tokens}. Present on 699 of 699 usage-bearing lines
    checked 2026-08-23. Step 3 prices from these two sub-keys, not from the
    flat cache_creation_input_tokens, so the evidence is recorded here rather
    than left implicit in the step
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
        THE TABLE IS KEYED ON THE MODEL IDS THAT ACTUALLY APPEAR ON DISK, NOT
        ON THE FRIENDLY ALIASES. Counted 2026-08-23 across every transcript in
        ~/.claude/projects/, on usage-bearing lines only — seven distinct ids,
        not two:
            claude-opus-5              x36670      claude-fable-5     x257
            claude-sonnet-5            x19278      claude-opus-4-8    x79
            claude-opus-4-7             x8569      <synthetic>        x62
            claude-haiku-4-5-20251001    x477
        Note `claude-haiku-4-5-20251001`, dated. An earlier draft of this step
        keyed its fixture on the bare `claude-haiku-4-5`, which exists nowhere
        on disk — the same class of defect as the slug rule above, and it would
        have failed the same silent way.
        RESOLVE IDS THROUGH AN EXPLICIT ALIAS MAP, NOT A SUFFIX REGEX. The
        obvious repair — strip a trailing `-\d{8}` — was inferred from the one
        dated id on disk and does not generalise. Two currently-active models
        break it: `claude-opus-4-20250514` strips to `claude-opus-4` whose
        real alias is `claude-opus-4-0`, and `claude-sonnet-4-20250514` strips
        to `claude-sonnet-4` whose alias is `claude-sonnet-4-0`. Neither
        stripped form is in the rate table, so both would fall through to the
        unrecognised-model branch and blank a whole worktree.
        Neither appears on this machine today, which is exactly why the
        on-disk-today assertion below cannot catch it: that test asserts a
        snapshot of the present population, while a regex makes a claim about
        every population. Write the map, not the rule.
        `<synthetic>` is NOT a model and carries no cost — it is what a local
        API-error message is tagged with. Skip those records explicitly rather
        than letting them fall through the unrecognised-model branch, which
        would blank a whole worktree over one transient error.
        RATES, from platform.claude.com pricing as of 2026-08-23, USD per
        million tokens, input/output. Keyed on the canonical id the alias map
        resolves to — the table says `claude-haiku-4-5`, and the map sends
        `claude-haiku-4-5-20251001` there:
            claude-fable-5   10 / 50     claude-opus-4-8    5 / 25
            claude-opus-5     5 / 25     claude-opus-4-7    5 / 25
            claude-sonnet-5   3 / 15     claude-haiku-4-5   1 /  5
        Cache multipliers apply to that model's INPUT rate: read 0.1x,
        5-minute write 1.25x, 1-hour write 2x.
        claude-sonnet-5 carries INTRODUCTORY pricing of 2 / 10 through
        2026-08-31, reverting to the 3 / 15 above on 2026-09-01. It is the
        second-largest population on this machine (19,278 records), so this is
        not a footnote. `prices_as_of` records when someone last looked, which
        is not the same as when a number expires — a table stamped 2026-08-23
        still reads fresh the day sonnet-5 gets 50% more expensive. If the
        build crosses 2026-08-31, re-check before shipping the table.
        PRICE FIVE BUCKETS, DISPLAY FOUR. The two cache-write TTLs are priced
        separately and then presented as a single `cache_write` figure equal to
        5m + 1h. Steps 7 and 8 render that combined bucket, so "all four
        buckets" there means input / cache-write / cache-read / output. Without
        this rule a builder rendering "four buckets" picks one TTL arbitrarily:
        on this machine 5-minute writes are zero, so picking that one displays
        the largest real bucket as 0 while the row's own cost figure — computed
        from all five — silently disagrees with the numbers beside it.
        These live in the plan rather than only in the code so step 3's test can
        assert against a figure with a stated source. `prices_as_of` is the
        constant beside the table holding that date (OPEN-4), and it is carried
        all the way to the label in step 6 — a date that stops at the module
        boundary implements nothing.
        Cost is summed PER RECORD at that record's own model's rates and then
        totalled — never one model's rate applied to a mixed-model list (OPEN-6).
        sum_cost() returns {"tokens": {5 buckets}, "model": <the model carrying
        the most tokens>, "models": <every model seen, with its token share>,
        "notional_cost_usd": float|None, "prices_as_of": <date string>}.
        An unrecognised model in ANY record, or a bucket absent from every
        record, returns notional_cost_usd=None — never a number from a guess.
        done when: a fixture of 1,000,000 output tokens on claude-opus-5 prints
        notional_cost_usd 25.00 exactly, and 1,000,000 1-hour cache-write tokens
        on the same model prints 10.00 (2x the 5/MTok input rate) where the
        5-minute rate would print 6.25 — an assertion tied to the published
        rates above, not re-derived from whatever table the code happens to
        hold. A second fixture mixing claude-opus-5 with the DATED
        claude-haiku-4-5-20251001 prints a populated "model" and both entries
        in "models". A third containing a `<synthetic>` record prices the rest
        and still returns a number. A fourth with a genuinely unknown model id
        prints notional_cost_usd: None. And every distinct model id present in
        ~/.claude/projects/ today resolves to a rate — assert that list, so a
        new model shows up as a failing test rather than a blank panel
                                                                      ← RUNS HERE

STEP 4  cost.py: worktree_cost(state_dir, worktree_path, home, now)   [needs 1,2,3]
        Matches every session whose cwd is the worktree or inside it (the
        same prefix rule as agent_for, loom/agents.py:129-147), resolves and
        reads each one's transcript, and combines them.
        Match on realpath (agent_for does, at loom/agents.py:139 and :145) but
        build the slug from the session's RAW `cwd`.
        UNVERIFIED — MEASURE THIS BEFORE STEP 1. Every other id-derivation rule
        in this plan is stated against a count taken from disk; this one is
        reasoning alone, and reasoning is what produced the two Blockers this
        plan has already had. The 42/42 slug sample contains no symlinked
        worktree, so it cannot distinguish whether Claude Code slugifies the
        raw cwd or a resolved one. If it resolves first, this rule is exactly
        backwards and every symlinked worktree reports transcript-missing
        forever, with every honesty check passing.
        The measurement is one observation: create a symlinked worktree, start
        a session inside it, and read which directory name appears under
        ~/.claude/projects/. Do that before writing locate_transcript, and
        record the result here. A test cannot settle it — planting a fixture
        proves only that loom's code agrees with itself.
        STALE SESSIONS ARE INCLUDED IN THE SUM AND COUNTED — never dropped,
        and never folded in unlabelled (OPEN-5). Staleness here is THREE-WAY,
        not two, because that is what agent_for actually does:
          - terminal: state not in ACTIVE_STATES (agents.py:180-182 — "stopped/
            unknown are already terminal"). reap() keeps stopped records for 24h
            (collect.py:101-121), so without this branch a session that ended ten
            minutes ago counts as live and its whole history reads as current
            burn — precisely what OPEN-5 exists to prevent.
          - stale: active, but aged out by WORKING_STALE_SECONDS /
            PARKED_STALE_SECONDS against `since` (agents.py:16-35, 183-187).
          - live: active and fresh.
        A fourth outcome is NOT a state but the absence of one: `_age_seconds`
        returns None when the timestamp is missing, unreadable, naive or in the
        future, and agents.py:183-185 says "cannot tell: never conclude death".
        Carry it as its own count, never silently as live — this module's whole
        convention is that cannot-tell is never folded into a number.
        That is why `now` is a REQUIRED argument here rather than defaulted, for
        the same reason agent_for requires it (agents.py:133-137).
        The result carries "live_sessions", "stale_sessions", "stopped_sessions"
        and "undated_sessions" as counts, plus "model" and "models" passed
        through from sum_cost — WITHOUT those two, issue #11's first-named
        per-worktree field never reaches a renderer at all.
        If ANY matched session's transcript cannot be located or read, or a
        bucket is missing after combining, the WHOLE worktree result is
        {"tokens": None, "notional_cost_usd": None, "model": None,
        "models": [], "prices_as_of": <date string>,
        "unknown_reason": <one of the enumerated values below>,
        plus the four session counts} — never a partial sum presented as
        complete.
        THE UNKNOWN SHAPE CARRIES EVERY KEY THE POPULATED ONE DOES. Only the
        numbers go None; no key disappears. Step 6 reads the session counts and
        `prices_as_of` off every worktree including unknown ones, and a shape
        that drops keys on the unknown branch either raises or silently
        omits them.
        This matters more than it looks: "no-session" is the NORMAL state of
        most worktrees most of the time, so all-worktrees-unknown is not an
        edge case, it is the ordinary reading of a quiet fleet. A field that
        only survives the populated branch is a field missing exactly when the
        panel is most often looked at.
        `unknown_reason` is an ENUMERATED value, not free prose, because two
        later steps must discriminate on it rather than pattern-match English:
            "no-session"          no matching session — NOT an error
            "transcript-missing"  matched a session, found no transcript file
            "unreadable"          transcript exists but could not be read
            "missing-bucket"      a token bucket absent after combining
            "unknown-model"       a model id with no rate
        done when: six fixture cases (transcript found and complete; transcript
        missing for one of two matching sessions; a bucket absent from a summed
        record; one live session beside one stale session; one stopped session
        eight hours old, asserting stopped_sessions == 1 and live_sessions == 0;
        zero matching sessions returning unknown_reason "no-session") each
        produce the shape the honesty requirement demands — populated only in
        the first and fourth, the fourth additionally asserting the sum covers
        BOTH sessions and that stale_sessions == 1, and every unknown case
        still carrying all four counts

STEP 5  Wire worktree_cost into collect()   [needs 4]
        Call it once per worktree and attach the result under a new "cost" key
        on each worktree dict.
        CALL IT IN THE LOOP AT collect.py:179-183, NOT THE ONE AT :141-151.
        Step 4 now requires `now`, and collect() does not create one until
        line 178 — a call placed at :141-151 is a NameError, and the obvious
        local fix (a second datetime.now()) breaks the invariant stated at
        collect.py:180: "One clock for the whole snapshot: two worktrees must
        never be aged against different instants." Reuse that clock; do not
        make a second one.
        Add a "cost" SourceStatus entry to `sources` reporting ok=False only
        for unknown_reason in {"transcript-missing", "unreadable"} — the two
        that mean something broke. "no-session" is NOT an error and must never
        set ok=False: most worktrees have no agent most of the time, and a
        source that reports failure for the normal case is a source nobody
        reads.
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

STEP 6  view.py: fleet_total(snap), wired into finalise()   [needs 5]
        Takes the SNAPSHOT, not a repo list — every other decision function in
        this module does (aggregate_needs(snap) at view.py:122, badge(snap, now)
        at view.py:66, finalise(snap, now) at view.py:180). A lone signature
        here is a thing the next reader has to check.
        Follows the aggregate_needs/badge pattern (loom/view.py:122-147) —
        sums notional_cost_usd across every worktree with a known cost, and
        reports the unknown ones by count in the label text itself (per
        Serina's OPEN-2 decision above — "N worktrees excluded", never a
        silent gap), never folding an unknown into the sum as zero.
        COUNT AS EXCLUDED ONLY unknown_reason in {"transcript-missing",
        "unreadable", "missing-bucket", "unknown-model"}. "no-session" is the
        normal state of most worktrees most of the time; counting it would put
        a permanent "18 worktrees excluded" on the label and drown the signal
        the count exists to give.
        It also carries the fleet-wide stale-session count through into the
        label (OPEN-5), so a total inflated by dead sessions says so rather
        than reading as live burn, and the `prices_as_of` date (OPEN-4) — a
        date that reaches the module boundary and stops has implemented
        nothing.
        Called from finalise() (loom/view.py:180-197) to attach snap["cost"]
        at the top level. Note finalise() runs on BOTH CLI paths
        (loom_cli.py:241) and in serve (serve.py:164, 198, 207), so a
        single-repo `loom snapshot` also gets this. #11 scopes the fleet total
        to `--all`; label it for what it covers rather than saying "fleet" over
        one repo. The label also carries the "list-price equivalent, not a
        bill" caveat, so the frontend only paints.
        done when: a test with four worktrees (one priced and live; one priced
        but carrying a stale session; one unknown for "unreadable"; one unknown
        for "no-session") asserts the total equals both priced figures, the
        label's excluded count is "1" and NOT "2", and the label text contains
        the caveat, the stale-session count and the prices_as_of date;
        `loom snapshot --json` shows the same shape for real

STEP 7  loom_cli.py: add the cost line to render_text()   [needs 5]
        loom_cli.py:201-219. render_text() currently emits a per-repo header
        and needs-you rows and NO per-worktree rows at all, so this step is
        where issue #11's per-worktree ask lands: "input / cache-write /
        cache-read / output tokens, the model, and a notional cost".
        THE TOTAL IS PRINTED ONCE, AFTER THE REPO LOOP — not inside it.
        Step 6 attaches it at snap["cost"], top level, while render_text()
        iterates `for repo in snapshot["repos"]`. A top-level value read from
        inside that loop prints once per repo and reads as that repo's spend,
        so `loom snapshot --all` over two repos would show the same fleet
        figure twice, each time attached to the wrong thing — under `--all`,
        which is the case #11 scopes the total to.
        Per-worktree rows go inside the loop; the total goes after it.
        Alongside the total, print ALL FOUR session counts — live, stale,
        stopped and cannot-tell. Step 4 computes four; step 6's label carries
        only the stale one; without this the other three are produced with care
        and read by nothing. `undated_sessions` is the sharpest case: a
        cannot-tell that reaches no display is cannot-tell folded into nothing,
        which is the exact failure agents.py:183-185 exists to refuse.
        done when: `loom snapshot` (no --json) prints, for each worktree with a
        known cost, a row naming the four DISPLAY buckets (cache-write being
        5m + 1h combined per step 3), the model, and the notional figure; the
        total appears exactly once per invocation, after the last repo, even
        with `--all` over two repos; the session counts appear beside it; and a
        worktree whose cost is unknown prints its unknown_reason rather than
        being omitted

STEP 8  loom/static: render snap.cost on the dashboard   [needs 6]
        Paint-only per view.py's own boundary rule — the same way the badge
        and needs-you panels already render their view.py-computed fields.
        Renders BOTH the top-level total from step 6 and the per-worktree
        breakdown attached by step 5 — the per-worktree model and buckets are
        what #11 asks for first, and a panel showing only a fleet dollar figure
        does not answer "which agent is burning the most".
        Where a worktree's `models` list holds more than one entry, the row
        shows the breakdown rather than only the winning model — that list was
        created by OPEN-6 precisely so a mixed-model session is not reported as
        if it ran on one model, and a breakdown no renderer reads would leave
        OPEN-6 resolved in prose and unimplemented in fact.
        done when: `loom serve`, viewed in a browser, shows the total AND a
        per-worktree row carrying the four DISPLAY buckets and the model, with
        a multi-model worktree showing every entry in `models`; the text
        matches what view.py computed; and grep of loom.js for arithmetic on
        token counts finds none

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
          - an exact-figure cost assertion tied to the published rates recorded
            in step 3, separating 5-minute from 1-hour cache writes, so a wrong
            rate fails rather than "a number" passing (step 3)
          - a session spanning claude-opus-5 and the DATED
            claude-haiku-4-5-20251001, asserting a populated "model" (step 3)
          - a stale session beside a live one, asserting both are summed and
            stale_sessions == 1 (step 4)
        And the four the 2026-08-23 review of the amendment found, all of them
        the same shape — a rule derived from a name, wrong against real data,
        failing silently to unknown:
          - every model id present in ~/.claude/projects/ today resolves to a
            rate; a new one fails this test rather than blanking a panel (step 3)
          - a `<synthetic>` record does not blank the worktree it appears in
            (step 3)
          - a session stopped eight hours ago counts as stopped, not live, so a
            reaped-but-not-yet-removed record cannot read as current burn (step 4)
          - a symlinked worktree still resolves its transcript, ONCE step 4's
            measurement has established which way Claude Code actually builds
            the slug. This test locks in the answer; it cannot discover it,
            because a planted fixture only ever proves loom agrees with itself
            (steps 1 and 4)
        done when: `python3 -m unittest tests.test_cost` passes and
        `python3 scripts/check_stdlib_only.py` still passes (no new import)

STEP 11 docs/superpowers/specs: design note for this panel   [needs 9]
        Matches the project's per-feature spec convention (2026-08-06-
        allow-list-design.md, 2026-08-10-langfuse-alongside-loom-design.md)
        — records the pricing table's source and staleness handling, the
        per-worktree vs fleet-total unknown rule, and the OPEN items below
        once Serina has resolved them.
        done when: docs/superpowers/specs/<date>-tokens-cost-design.md exists
        and is listed in docs/README.md's spec table — a row in the same shape
        as the existing entries at docs/README.md:15-16, path link plus a prose
        description of what the spec decides.
        NOT README.md. The root README's Design bullet (README.md:6) links
        exactly ONE spec, the 2026-08-03 loom design, and is not the index; the
        allow-list and Langfuse specs this step cites as precedent are not
        there. A builder who satisfies an earlier draft of this done-when by
        adding a root-README bullet marks the step complete while the project's
        actual spec index stays wrong.

PARALLEL  Steps 1-4 all edit loom/cost.py and are sequential regardless of
          logical independence. Step 10 (tests/test_cost.py) touches a
          different file and can start as soon as step 4 lands, running
          alongside steps 5-9 rather than waiting for the dashboard work.
          Steps 6 (view.py) and 7 (loom_cli.py) both need only step 5, touch
          different files, and can run as parallel subagents once step 5 is
          done. Step 8 needs step 6 specifically (the label text), not step
          7, so it cannot start in that same parallel batch.

GATES     Both gates parse this plan as written. check-ledger.sh:54 accepts
          `STEP N` alongside `### Task N:` by design, and prints "PASS plan
          declares 11 task(s)". The ledger itself appears once step 1 is built.
          Keep the `STEP N` headings: check-plan.sh:81 counts steps with
          `grep '^STEP '` and fails without them, so renaming would break the
          checker that passes to satisfy one that already passes.

          review-code and review-tests apply to the whole diff once step 10
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
          it. Budget for the mtime cache, not just the wiring. The cache needs
          a stated home — module-level in cost.py — and a reset hook, or it
          leaks between tests and the suite starts depending on run order.
          Step 3 is the third, and it is the one this plan has now got wrong
          twice: every identifier it derives — slug, model id — has been wrong
          against real data on a first pass, and wrong in a way tests written
          alongside it could not see. Before writing the table, run the counts
          in step 3 again AND re-check the rates themselves. The population
          changes as new models ship, and the prices change on their own
          schedule: claude-sonnet-5's introductory rate expires 2026-08-31.
          Re-running the id counts but trusting a week-old price is the same
          mistake wearing the other face.

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
             623 claude-opus-5 records beside 2 claude-haiku-4-5-20251001
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
