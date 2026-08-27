Issue #11 — Add a tokens-and-cost panel, read from local transcripts
Stated size: no `Size` line on the issue → directed by Serina at planning time (2026-08-17) to treat as more than an hour → cap: 12 steps
Reviewed a fifth and sixth time 2026-08-27 against 4b08770 → round five (review-plan + review-adjudicate) found no Blockers, 3 Medium and 1 Low, all confirmed by an independent adjudicator that re-verified every citation itself and downgraded two severities with stated reasons; fixed here. Round six, an independent pass after Codex was unavailable (out of credits — recorded rather than silently substituted), found 3 Blocker and 3 High that five prior rounds had missed, fixed here. The three Blockers: nested worktrees double-counted into their own ancestor's sum (live today — `buzz`, on this machine's own allow list, has 16 of 41 worktrees nested under its own root); this plan's OWN alias-map rationale named two models "currently-active" that were in fact retired 2026-06-15, before the plan's first draft — the exact defect class the map exists to prevent, reproduced inside the map's own justification and unchecked across five reviews; and an absent-bucket rule that, read literally, made every one of step 3's own single-bucket fixtures return None instead of the number the fixture asserted. The three Highs: a stopped-session's spend reaching the fleet total unlabelled (OPEN-5 was scoped to stale sessions only, before stopped sessions were made to count); an enumerated `unreadable` value consumed by two steps and produced by none; and a confident $0.00 for zero usage records or a zero-worktree fleet, indistinguishable from a fleet that was actually measured and spent nothing.
Reviewed 2026-08-23 (review-plan) → 1 Blocker, 4 High, 1 Medium, all in the plan and none yet built. Amended in place the same day; the corrections and the evidence behind them are recorded inline rather than only in the review, so a builder reading this file alone still sees why each rule is what it is.
Reviewed a fourth time 2026-08-24 against 302cdc4 → 3 Blocker, 1 High, 4 Medium; the three Blockers fixed here on 2026-08-27, and the recorded verdict names only those four in detail, so the Mediums must be re-surfaced by re-running the gate rather than assumed closed. All three Blockers were the SAME defect class this file has now recorded four times, and this round it appeared as a test that could not fail (an assertion over `~/.claude/projects/` that is empty on CI, so vacuously true), a rule with no owner (5m+1h cache-write addition described in prose and assigned to no step), and a done-when contradicting its own step's rule (a stopped session asserted unknown where the rule includes it in the sum). Recorded because the pattern is now the finding: prose that states a rule is not the same as a step that owns it, and a test written the way this project reads directories (agents.py:58-68 returns [] when absent) passes hardest exactly where nobody is watching.
Re-measured 2026-08-27 before fixing, and the measurement is itself the evidence: the id corpus went from seven ids to six in four days — `claude-opus-4-7` fell from 8,569 records to absent entirely, `claude-haiku-4-5-20251001` 477→408, `claude-opus-4-8` 79→7, while `claude-opus-5` grew 36,670→44,116. Counts move in BOTH directions because transcripts are rotated and deleted, so the on-disk population is not a stable basis for any assertion. The rates and cache multipliers in step 3 were re-checked the same day against current published pricing and are correct as written.
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
        where both are present. A malformed LINE is skipped, not raised,
        matching read_state_dir's tolerance (loom/agents.py:58-68) — that
        tolerance is for a single bad JSON line inside a file that opened
        fine, not for the file itself.
        A FILE THAT CANNOT BE OPENED IS A DIFFERENT FAILURE AND MUST BE
        DISTINGUISHABLE FROM ONE THAT OPENS AND HAS NO USAGE LINES. Step 4
        enumerates "unreadable" as a distinct unknown_reason from
        "transcript-missing", and step 5 keys a SourceStatus on it, but
        nothing in this step produces that signal — an OSError on open()
        (permissions, a directory where a file should be, a race with
        deletion) is otherwise indistinguishable from an empty transcript.
        LET THE OSError PROPAGATE — do not catch it here. Step 4 is the step
        that owns turning "one session's transcript raised" into
        `unknown_reason: "unreadable"` for the whole worktree, the same way
        it already owns turning transcript-missing and unknown-model into
        their own enumerated values; catching it in step 2 would silently
        turn "unreadable" into "empty" one layer too early, and step 5's only
        ok=False branch tied to it would never fire.
        done when: a fixture .jsonl with 2 well-formed usage lines and 1
        malformed LINE returns exactly the 2 usage records, in order — the
        file itself opened fine. A second fixture — a path with mode 0o000,
        or any other genuinely unreadable stand-in — raises OSError rather
        than returning an empty list, so step 4 has something to catch

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
        dated id on disk and does not generalise: a future model can ship a
        dated id whose stripped form is not its real alias, and the map is
        what keeps that case honest — unknown-model, never a guessed rate —
        instead of silently wrong.
        AN EARLIER DRAFT OF THIS PARAGRAPH CITED `claude-opus-4-20250514` and
        `claude-sonnet-4-20250514` AS "TWO CURRENTLY-ACTIVE MODELS" THAT BREAK
        THE REGEX. Checked live against platform.claude.com/docs on
        2026-08-27: both were RETIRED 2026-06-15 — before this plan was even
        first written on 2026-08-17. Requests naming either now return 404.
        That claim was wrong from the first draft and repeated across five
        review rounds unchecked — the same defect class the map exists to
        prevent, sitting inside the map's own justification.
        A retired model has no current per-token rate to cite, so a
        transcript carrying either id — necessarily written before the
        retirement date — is correctly priced as unrecognised-model → None.
        That is not a gap to route around: mapping a retired id to a rate
        would itself be "a number from a guess," the exact thing the
        absent-bucket rule below forbids. NEITHER ID GETS A MAP ENTRY OR A
        TABLE ROW.
        The map's actual required entry, today, is the one already named
        below — `claude-haiku-4-5-20251001` → `claude-haiku-4-5`. Add a new
        entry only for an id VERIFIED — against a live rate, not inferred —
        to resolve to a real table key. An id the map doesn't name, like
        these two retired ones, blanks honestly rather than guesses.
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
        second-largest population on this machine (23,983 records as of
        2026-08-27), so this is not a footnote. `prices_as_of` records when
        someone last looked, which is not the same as when a number expires — a
        table stamped 2026-08-27 still reads fresh the day sonnet-5 gets 50%
        more expensive.
        THAT DATE IS NOW DAYS AWAY. This plan was written 2026-08-17 and
        re-checked 2026-08-27; the intro rate expires 2026-08-31. Any build
        starting after that date ships a table that is wrong on its second-
        largest population from the moment it lands, and wrong in the quiet
        direction — a plausible number, 33% low, with every honesty check
        passing. Re-read the rate before writing the table, not after.
        The rates and the cache multipliers below were verified 2026-08-27
        against current published pricing and are correct as written; it is
        only the expiry that moves.
        PRICE FIVE BUCKETS, DISPLAY FOUR — AND THIS STEP OWNS THE ADDITION.
        The two cache-write TTLs are priced separately and then presented as a
        single `cache_write` figure equal to 5m + 1h. sum_cost() PERFORMS that
        addition and returns `cache_write` as a SIXTH key in the tokens dict
        alongside the five it prices from. Steps 7 and 8 read that key; neither
        adds anything, which is what makes step 8's no-arithmetic-in-loom.js
        gate satisfiable rather than contradictory.
        This ownership is stated because the previous three revisions of this
        plan all described the combined figure in prose and assigned it to no
        step. A rule with no owner is not a rule: the builder either violates
        step 8's done-when or picks one TTL, and on this machine 5-minute
        writes are zero, so picking that one displays the largest real bucket
        as 0 while the row's own cost figure — computed from all five —
        silently disagrees with the numbers beside it.
        The derived key is redundant by design. Deriving it in two renderers
        instead is how the two displays drift apart, and deriving it in
        loom.js is the thing step 8 forbids outright.
        These live in the plan rather than only in the code so step 3's test can
        assert against a figure with a stated source. `prices_as_of` is the
        constant beside the table holding that date (OPEN-4), and it is carried
        all the way to the label in step 6 — a date that stops at the module
        boundary implements nothing.
        Cost is summed PER RECORD at that record's own model's rates and then
        totalled — never one model's rate applied to a mixed-model list (OPEN-6).
        "model" IS THE MODEL WITH THE HIGHEST PER-MODEL NOTIONAL COST, NOT THE
        MOST TOKENS. "Most tokens" was never stated against a dimension, and
        summed across all six buckets it usually means "did the most
        cache-reading" — measured on this repo's own transcripts, cache-read
        tokens outweigh output tokens by roughly 213x for claude-opus-5
        (253,713,753 vs 1,190,779), so a session where one model does the
        actual work and another merely re-reads a large cached prefix would
        have its "model" field answer the wrong question. #11 asks this field
        to answer "who is burning the most", and this panel already computes
        that in dollars per record — reuse it rather than inventing a second,
        disagreeing answer in tokens. Since "model" is only read on the
        POPULATED branch, every record's cost is already computable when this
        picks a winner, so there is no case where the cost comparison itself
        is undefined.
        sum_cost() returns {"tokens": {input, cache_write_5m, cache_write_1h,
        cache_write, cache_read, output}, "model": <the model with the
        highest per-model notional_cost_usd>, "models": <every model seen,
        each with its own notional_cost_usd share AND its token share>,
        "notional_cost_usd": float|None, "prices_as_of": <date string>}.
        SIX token keys: the five that carry rates, plus the derived
        `cache_write` = cache_write_5m + cache_write_1h that steps 7 and 8
        render. Both TTL keys survive into the output rather than being
        collapsed, so a reader can still see which TTL the spend came from.
        sum_cost([]) — ZERO USAGE RECORDS — RETURNS notional_cost_usd=None,
        NOT 0.0. A brand-new session has a transcript with a user line and no
        assistant `usage` line yet — common, not an edge case — and skipping
        every `<synthetic>` record can leave an otherwise-matched session with
        nothing left to price. Both are "nothing was measured", the same
        cannot-measure category as an unrecognised model, not "measured and
        the answer is zero". A confident $0.00 for a session that hasn't
        produced a priceable turn yet is exactly the wrong-number-confidently
        outcome #11 exists to refuse. Reported through step 4 as
        unknown_reason "no-usage-records" — the sixth enumerated value below.
        An unrecognised model in ANY record, or a bucket absent from every
        record, returns notional_cost_usd=None — never a number from a guess.
        ABSENT MEANS THE KEY IS MISSING FROM THE USAGE OBJECT, NOT THAT ITS
        VALUE IS ZERO. On disk every usage-bearing line carries all four flat
        keys plus the nested cache_creation object with both TTL sub-keys —
        absent is what a record looks like when Anthropic changes the shape,
        not the ordinary case. EVERY FIXTURE BELOW SETS EVERY BUCKET IT IS NOT
        EXERCISING TO AN EXPLICIT 0, PRESENT IN THE RECORD — never by omitting
        the key. Written the other way, each of the single-bucket fixtures
        immediately below would trip its own rule: a record naming only
        output_tokens has every other key absent BY OMISSION, which the rule
        just above reads as "absent from every record" and returns None,
        failing the fixture that is supposed to assert a number. If two
        records in the same combined sum disagree — one carries a key, the
        other genuinely omits it — that is `missing-bucket` in step 4's
        vocabulary, never a partial sum that reads the omission as zero.
        done when: a fixture of 1,000,000 output tokens on claude-opus-5,
        every other bucket present at 0, prints notional_cost_usd 25.00
        exactly, and 1,000,000 1-hour cache-write tokens on the same model,
        every other bucket present at 0, prints 10.00 (2x the 5/MTok input
        rate) where the 5-minute rate would print 6.25 — an assertion tied to
        the published rates above, not re-derived from whatever table the
        code happens to hold. A second fixture mixing claude-opus-5 with the
        DATED claude-haiku-4-5-20251001 prints a populated "model" and both
        entries in "models". A third containing a `<synthetic>` record prices the rest
        and still returns a number. A fourth with a genuinely unknown model id
        prints notional_cost_usd: None.
        A fifth fixture carries BOTH cache-write TTLs non-zero — 400,000
        five-minute and 600,000 one-hour tokens on claude-opus-5 — and asserts
        tokens["cache_write"] == 1,000,000 while both TTL keys survive at their
        own values, and notional_cost_usd == 8.50 (400k at 1.25x plus 600k at
        2x of the 5/MTok input rate).
        BOTH TTLs MUST BE NON-ZERO IN THIS FIXTURE. With either at zero the
        assertion passes under "pick one TTL" as readily as under addition,
        which is precisely the bug it exists to catch — and zero is the real
        value on this machine, so a fixture copied from live data would be the
        broken one.
        A SIXTH asserts every id in a FROZEN LITERAL LIST written into the test
        resolves to a rate: claude-opus-5, claude-sonnet-5, claude-opus-4-7,
        claude-haiku-4-5-20251001, claude-fable-5, claude-opus-4-8. That list is
        the union of every id observed on disk on 2026-08-23 and 2026-08-27, and
        it is a CONSTANT — never re-derived from ~/.claude/projects/ at run time.
        A test that reads that directory finds nothing on CI, where it does not
        exist and this project's own idiom returns [] rather than raising
        (agents.py:58-68), so the assertion is vacuously true on the one machine
        that gates every PR. It is also non-deterministic where it does run: the
        corpus lost claude-opus-4-7 entirely between those two dates. The live
        check still exists, as a separate and explicitly-skipping test — step 10.
        claude-opus-4-7 stays in both the list and the rate table though it is
        absent from disk today. A rate for a model nobody is running costs
        nothing; a missing rate blanks a worktree.
        A SEVENTH is pure consistency with no fixture at all: every canonical id
        the alias map resolves TO is a key in the rate table. Trivially true
        today — the map's one entry points at a real table key — but it is
        what stops the NEXT entry from being added the way the retired-id
        rationale above almost was: a map with a dead end is the same bug as
        the regex it replaced, spelled longhand. This one needs no corpus and
        fails the moment the two structures disagree.
        AN EIGHTH fixture makes the retired-id case concrete rather than only
        correct in prose: a record with model id claude-opus-4-20250514
        (confirmed retired 2026-06-15, unmapped by design) prints
        notional_cost_usd: None — the fourth fixture's assertion, now pinned
        to the specific id that motivated writing the alias map, rather than
        a synthetic placeholder unrelated to it.
        A NINTH asserts sum_cost([]) — zero usage records — returns
        notional_cost_usd: None, not 0.0. This is the case a session with no
        assistant turn yet, or an all-`<synthetic>` record set, reduces to,
        and it is the one place in this step where the honest answer is a
        function argument nobody has to construct wrong: the empty list is
        the fixture.
        A TENTH is what makes "model" mean cost rather than tokens: two
        records on DIFFERENT models where the token-heaviest model is NOT the
        cost-heaviest one — claude-haiku-4-5-20251001 with 100,000,000
        cache-read tokens (its only bucket; cost 1/5 the input rate x 0.1,
        i.e. $10.00) beside claude-opus-5 with 500,000 output tokens (cost
        $12.50). Total tokens favour haiku by two orders of magnitude; total
        cost favours opus-5. Asserts "model" == "claude-opus-5" — the
        dimension named in the rule above, proven by a case where "most
        tokens" would have picked the other model.
                                                                      ← RUNS HERE

STEP 4  cost.py: worktree_cost(state_dir, worktree_path, sibling_paths, home, now)   [needs 1,2,3]
        Matches every session whose cwd is the worktree or inside it (the
        same prefix rule as agent_for, loom/agents.py:129-147), resolves and
        reads each one's transcript, and combines them.
        Match on realpath (agent_for does, at loom/agents.py:139 and :145) but
        build the slug from the session's RAW `cwd`.
        A SESSION BELONGS TO THE NEAREST ENCLOSING WORKTREE, NOT EVERY
        ENCLOSING ONE. `agent_for`'s prefix rule is correct for what it does —
        pick the one agent that owns a worktree's badge — because a session
        matching two worktree paths at once still contributes to only one
        badge each. Reused here for a SUM, the same rule double-counts:
        real Launchpad worktrees nest (`buzz`'s own worktrees live at
        `buzz/__worktrees/<name>`, inside `buzz`'s own repo root, and `buzz`
        is on loom's own allow list at ~/.loom/repos), so a session inside a
        nested worktree matches BOTH the nested worktree's path prefix AND
        its parent's. Summed naively, the parent's `worktree_cost` absorbs
        every nested worktree's spend on top of its own, then step 6 adds the
        parent row AND every nested row again — the fleet total is inflated
        by the double-counted spend, and the parent worktree permanently
        "wins" #11's own question, who is burning the most, by construction
        rather than by actually burning the most.
        `sibling_paths` is the full list of every worktree path in this
        snapshot, passed so a session can be excluded when it belongs to a
        MORE SPECIFIC match: for cwd C, this worktree owns C only if no path
        in `sibling_paths` is both a prefix-match for C and strictly longer
        (by realpath) than `worktree_path` itself. A session inside a nested
        worktree is therefore counted once, by the nested worktree, and
        excluded from every ancestor's sum.
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
            "no-usage-records"    matched session(s), zero priceable records
            "missing-bucket"      a token bucket absent after combining
            "unknown-model"       a model id with no rate
        `unknown_reason` IS PRESENT AND None ON THE POPULATED BRANCH, NEVER
        OMITTED — one shape, not two. THE UNKNOWN SHAPE CARRIES EVERY KEY THE
        POPULATED ONE DOES states the rule in one direction; this states it in
        the other, because a step-6 implementation written as
        `cost["unknown_reason"]` raises KeyError on every priced worktree if
        the populated branch is allowed to omit the key, and nothing catches
        that choice being made either way without this line.
        STEP 2's read_usage RAISES OSError WHEN A TRANSCRIPT FILE CANNOT BE
        OPENED, rather than returning an empty list — this step is what turns
        that exception into `unknown_reason: "unreadable"` for the whole
        worktree. Catch it around each session's read, not around the loop:
        one unreadable transcript among several matching sessions must not
        also swallow the others' honesty branches.
        A STOPPED SESSION WITH A READABLE TRANSCRIPT IS POPULATED, NOT UNKNOWN.
        This is stated because the done-when below asserted the opposite for
        three revisions: it listed the stopped-session case among the unknown
        ones, while the rule above includes every matched session in the sum and
        no enumerated unknown_reason fits a session whose transcript reads fine.
        Reconciled the other way it silently drops real spend and locks that in
        with a test — the exact outcome OPEN-5 was resolved to prevent, since a
        stopped session is where most of a quiet fleet's history lives. The
        `stopped_sessions` count is what marks it as history; the None shape is
        for cannot-measure, never for did-not-like-the-state.
        done when: eight fixture cases (transcript found and complete;
        transcript missing for one of two matching sessions; a transcript that
        RAISES on open (mode 0o000 or equivalent) for one of two matching
        sessions; a bucket absent from a summed record; one live session
        beside one stale session; one stopped session eight hours old; zero
        matching sessions returning unknown_reason "no-session"; a NESTED
        WORKTREE PAIR) each produce the shape the honesty requirement
        demands — POPULATED IN THE FIRST, FIFTH, SIXTH AND EIGHTH, unknown in
        the second, third, fourth and seventh.
        The fifth additionally asserts the sum covers BOTH sessions and that
        stale_sessions == 1. The third asserts unknown_reason == "unreadable"
        specifically, distinct from the second's "transcript-missing" — the
        two enumerated values this step exists to keep separable. The sixth
        asserts a POPULATED tokens dict and a non-None notional_cost_usd drawn
        from that stopped session's transcript, with stopped_sessions == 1,
        live_sessions == 0 and unknown_reason == None (present, not omitted)
        — a case that would pass just as well if the sum were empty, so
        assert the figure, not merely the shape.
        THE EIGHTH IS THE NESTING FIXTURE, tied directly to the sibling_paths
        rule above: worktree paths `/r` and `/r/__worktrees/a`, one session in
        each, `sibling_paths = ["/r", "/r/__worktrees/a"]`. Calling
        worktree_cost for `/r` must sum ONLY its own session — asserted by
        comparing against the known single-session token count, not merely by
        checking the total changed — and calling it for `/r/__worktrees/a`
        must sum only that session too. Neither call may see the other's
        session. Every unknown case still carries all four counts.

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
        PASS `sibling_paths = [t.path for t in trees]` — the full worktree
        list this same loop is iterating — TO EVERY CALL. Without it step 4's
        nearest-enclosing rule has nothing to compare against and degrades
        back to the double-counting it exists to prevent; the loop already
        holds this list, so this is a read, not new state.
        `home`'s PRODUCTION VALUE IS `cost.DEFAULT_HOME = os.path.expanduser(
        "~")`, a module-level constant in cost.py — the same pattern as
        `agents.DEFAULT_STATE_DIR` (agents.py:37) and every other bare-
        filesystem-root this codebase needs (loom_cli.py:25,29,
        hookinstall.py:17, hooks/loom_hook.py:53). Named here because nothing
        else in this plan says where the call site's `home` argument comes
        from, and every sibling argument at this same call site is otherwise
        pinned to the line.
        Add a "cost" SourceStatus entry to `sources` reporting ok=False only
        for unknown_reason in {"transcript-missing", "unreadable"} — the two
        that mean something broke. "no-session" is NOT an error and must never
        set ok=False: most worktrees have no agent most of the time, and a
        source that reports failure for the normal case is a source nobody
        reads.
        THE MESSAGE FOLLOWS THE SAME CONVENTION collect.py's OWN OTHER
        SourceStatus ENTRIES ALREADY USE (collect.py:228-232, :233-238): name
        the count and the affected worktree directories, e.g. "could not
        measure token cost for N worktree(s): {names}" — never a bare
        ok=False with no detail of which worktrees failed or why. Combine
        across worktrees the same way those two entries do: ok=False if ANY
        worktree's unknown_reason is in the error set, message naming all of
        them.
        THIS IS THE STEP THAT PUTS A MULTI-MEGABYTE FILE READ INSIDE A TWO-
        SECOND LOOP. collect() is not only the CLI's one-shot path: `loom serve`
        calls it every FAST_SECONDS = 2 (loom/serve.py:16, 226-248), and
        serve.py:210-223 already records that collection is the expensive part
        and that stretching a tick is a real regression — audit finding M4.
        This repo's own largest transcript is 4.3 MB and 1,918 JSON-parsed
        lines, measured 2026-08-23, and transcripts only ever grow.
        So cache per transcript on (path, mtime, size) and re-read only what
        changed: an unchanged file must cost a stat, not a parse.
        THE CACHE IS MODULE-LEVEL IN cost.py AND NEEDS A RESET FUNCTION,
        cost.reset_cache() (or equivalent), CALLED FROM tests/test_cost.py's
        setUp/tearDown. Named here rather than left in BUDGET prose because a
        rule that only lives in an advisory section is a rule with no owning
        step — the same defect class this plan has fixed twice elsewhere.
        Real risk is small today (this project's own test idiom uses a fresh
        tempfile.mkdtemp()/TemporaryDirectory() per test, so two tests
        colliding on the same literal (path, mtime, size) key is unlikely)
        but a cache with no reset and no eviction is also unaddressed for a
        long-running `loom serve`, where transcripts accumulate for the life
        of the process. Add the reset function now, while it is one function,
        rather than after a flaky test makes it load-bearing.
        done when: a `loom serve` TICK is timed, not a one-shot snapshot — the
        CLI path never enters the refresh loop and so structurally cannot see
        this regression, which is why the CLI-only check this step originally
        carried was not a check at all. Two consecutive ticks over an unchanged
        transcript show the second doing no re-parse; `loom snapshot --json` run
        from this repo still shows a non-null cost.tokens for at least one
        worktree; every existing test in tests/test_collect.py still passes
        unmodified; a fixture with one worktree whose cost is "unreadable"
        asserts the "cost" SourceStatus message names that worktree by
        directory, not a bare ok=False; a fixture over two REAL nested
        paths (mirroring step 4's seventh fixture) asserts collect() passes
        the full sibling list to every call, not a partial one; and
        cost.reset_cache() exists, is called in tests/test_cost.py's own
        setUp, and a test that mutates a cached transcript's content without
        changing its mtime/size — then calls reset_cache() — sees the new
        content, proving the reset actually clears state rather than being a
        no-op function that merely exists to satisfy this line

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
        the count exists to give. "no-usage-records" is excluded from the
        excluded-count for the same reason: a session that has started but
        not yet produced a priced turn is the normal shape of an agent that
        just began, not a measurement failure, and treating it as broken
        would put the same permanent noise on the label that "no-session"
        was carved out to avoid.
        THIS STEP OWNS AGGREGATING ALL FOUR SESSION COUNTS TO FLEET LEVEL, not
        just the stale one. Step 4 produces live / stale / stopped / undated per
        worktree and step 7 prints four at fleet level; without an owner in
        between, three of them are computed with care and read by nothing, and
        step 7 has no fleet-level value to print. So snap["cost"] carries all
        four summed across every worktree — including the unknown ones, whose
        counts survive precisely because the unknown shape keeps every key.
        `undated_sessions` is the one that matters most and is easiest to drop:
        a cannot-tell that reaches no display is cannot-tell folded into
        nothing, which is the failure agents.py:183-185 exists to refuse.
        THE LABEL CARRIES BOTH THE STALE AND THE STOPPED COUNT, NOT STALE
        ALONE. OPEN-5 was written 2026-08-23 about stale sessions only, before
        step 4 was changed to make a stopped session's spend populated rather
        than unknown. `reap()` keeps stopped records for 24h (collect.py:
        101-121), so a worktree's total can be dominated by a session that
        died 23 hours ago — the larger and longer-lived of the two "history,
        not current burn" cases OPEN-5's own reasoning names — and it would
        reach the label unlabelled if only stale were carried. At hour 25 the
        record is reaped and the same total quietly drops with no signal it
        ever had one. Fold both counts into the same "history, not current
        burn" clause whenever either is non-zero.
        The other two — live and undated — are attached as fields for step 7
        and step 8 to render, not folded into the label prose. The label also
        carries the `prices_as_of` date (OPEN-4) — a date that reaches the
        module boundary and stops has implemented nothing.
        Called from finalise() (loom/view.py:180-197) to attach snap["cost"]
        at the top level. Note finalise() runs on BOTH CLI paths
        (loom_cli.py:241) and in serve (serve.py:164, 198, 207), so a
        single-repo `loom snapshot` also gets this. #11 scopes the fleet total
        to `--all`; label it for what it covers rather than saying "fleet" over
        one repo. The label also carries the "list-price equivalent, not a
        bill" caveat, so the frontend only paints.
        ZERO WORKTREES IS ALSO CANNOT-MEASURE, NOT MEASURED-AND-ZERO. `snap[
        "repos"]` starts `[]` before the first successful collection
        (serve.py:30), and `_refresh_step` calls `finalise(stale)` on every
        collection failure — so a persistently failing collector and a
        genuinely empty fleet both hand fleet_total zero worktrees, and both
        must not read as "$0.00, nothing excluded". Return the notional total
        as None with zero excluded and zero of every session count, so a
        confident $0.00 can only ever mean a fleet that was actually measured
        and actually spent nothing.
        done when: a test with five worktrees (one priced and live; one priced
        but carrying a stale session; one priced but carrying only a stopped
        session; one unknown for "unreadable" and carrying an undated session;
        one unknown for "no-session") asserts the total equals every priced
        figure, the label's excluded count is "1" and NOT "2", and the label
        text contains the caveat, BOTH the stale- and stopped-session counts,
        and the prices_as_of date. It further asserts all FOUR fleet-level
        counts are present and correct, with undated_sessions == 1 — a count
        sourced from an UNKNOWN worktree, so the test fails if the unknown
        branch drops keys or the aggregation skips unknown worktrees.
        A SECOND fixture reuses step 4's nested-worktree pair (`/r` and
        `/r/__worktrees/a`, one session each) through the real collect() →
        fleet_total() path and asserts the total equals the sum of the two
        sessions' own costs exactly once each — not the parent's cost
        appearing twice, which is what step 4's rule existing but step 5
        failing to wire `sibling_paths` through would produce. This is the
        one fixture in the plan that would have caught B1 end to end rather
        than only at the unit the rule was written into.
        A THIRD fixture calls fleet_total on a snapshot with an EMPTY repos
        list and asserts notional_cost_usd is None, excluded count is 0, and
        every session count is 0 — never a bare "$0.00, 0 worktrees excluded"
        that reads identically whether the fleet spent nothing or was never
        measured at all.
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
        stopped and cannot-tell — reading the fleet-level figures step 6
        aggregated onto snap["cost"]. This step does not sum them itself; step 6
        owns that, and two places summing the same counts is how the CLI and the
        dashboard come to disagree.
        The per-worktree cache-write figure is likewise READ, not computed:
        tokens["cache_write"] already holds 5m + 1h from step 3. This step adds
        nothing up.
        done when: `loom snapshot` (no --json) prints, for each worktree with a
        known cost, a row naming the four DISPLAY buckets (reading
        tokens["cache_write"] for the combined one, per step 3), the model, and
        the notional figure; the
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
        The four DISPLAY buckets come straight off the tokens dict — input,
        cache_write, cache_read, output. `cache_write` is already the 5m + 1h
        sum computed in step 3, so this step reads one key rather than adding
        two, which is what makes the no-arithmetic gate below satisfiable.
        Render the fleet-level session counts step 6 attached, so the four
        counts reach the dashboard and not only the CLI.
        done when: `loom serve`, viewed in a browser, shows the total AND a
        per-worktree row carrying the four DISPLAY buckets and the model, with
        a multi-model worktree showing every entry in `models`; the fleet-level
        session counts appear; the text matches what view.py computed; and grep
        of loom.js for arithmetic on token counts finds none — which passes
        because step 3 already did the one addition this feature needs, not
        because the combined bucket was quietly dropped

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
          - every id in step 3's FROZEN LITERAL list resolves to a rate, and
            every id the alias map resolves to is a table key (step 3)
          - the live-corpus check, as a test that ANNOUNCES when it did not run.
            Guard it with unittest.skipUnless(~/.claude/projects exists), and on
            the machines where it does run, assert the id set is NON-EMPTY
            before asserting every member resolves. Both halves are load-bearing:
            the skip stops it passing green on CI where the directory is absent,
            and the non-empty assertion stops it passing where the directory
            exists but holds nothing readable. This is a local alarm for a new
            model id, not a CI gate — a gate over a corpus that lost an entire
            model in four days would fail for reasons no PR caused
          - a `<synthetic>` record does not blank the worktree it appears in
            (step 3)
          - a session stopped eight hours ago counts as stopped, not live, so a
            reaped-but-not-yet-removed record cannot read as current burn — AND
            its spend is still summed, since a stopped session with a readable
            transcript is populated, not unknown (step 4)
          - a fixture with BOTH cache-write TTLs non-zero, asserting the
            combined `cache_write` equals their sum. Zero in either TTL makes
            the test pass under "pick one", and zero is the real value on this
            machine (step 3)
          - all four session counts survive to fleet level, with the undated
            count sourced from a worktree whose cost is unknown (step 6)
          - a symlinked worktree still resolves its transcript, ONCE step 4's
            measurement has established which way Claude Code actually builds
            the slug. This test locks in the answer; it cannot discover it,
            because a planted fixture only ever proves loom agrees with itself
            (steps 1 and 4)
        Plus what the 2026-08-27 independent pass found — three Blockers and
        three Highs, none of them shape-of-a-name defects but each one a real
        gap a builder would otherwise have to guess at, guarded by no
        prescribed test:
          - NESTED WORKTREES ARE COUNTED ONCE, NOT ONCE PER ANCESTOR. A
            session inside `/r/__worktrees/a` must not also appear in `/r`'s
            sum; the fleet total over both must equal the sum of their own
            costs, not double the nested one's. This is live in this
            machine's own fleet today — `buzz`, on loom's own allow list, has
            16 of 41 worktrees nested under its own root (steps 4 and 6)
          - the retired-id case is a real fixture, not only a corrected
            claim: claude-opus-4-20250514 prints notional_cost_usd: None,
            proving the alias map's absence of an entry for it is honest
            rather than an oversight (step 3)
          - a transcript that raises OSError on open resolves to
            unknown_reason "unreadable", distinct from "transcript-missing"
            — the enumerated value five prior rounds cited as existing but
            none had a step produce (steps 2 and 4)
          - sum_cost([]) and a zero-worktree fleet both return None, never a
            confident $0.00 — the same cannot-measure-versus-measured-zero
            distinction this plan already applies to buckets, extended to
            record counts and worktree counts (steps 3 and 6)
          - `unknown_reason` is present and None on the populated branch in
            every fixture, never omitted — one shape, asserted the same way
            everywhere (step 4)
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
          it. Budget for the mtime cache, not just the wiring — step 5's own
          text now owns the cache's home and its reset function; this is a
          time-budget flag, not a second copy of that requirement.
          Step 3 is the third, and it is the one this plan has now got wrong
          twice: every identifier it derives — slug, model id — has been wrong
          against real data on a first pass, and wrong in a way tests written
          alongside it could not see. Before writing the table, run the counts
          in step 3 again AND re-check the rates themselves. The population
          changes as new models ship, and the prices change on their own
          schedule: claude-sonnet-5's introductory rate expires 2026-08-31.
          Re-running the id counts but trusting a week-old price is the same
          mistake wearing the other face.
          Note what the re-count on 2026-08-27 actually showed: the corpus went
          from seven ids to six in four days, losing claude-opus-4-7's 8,569
          records entirely, and every other count moved. So re-running the
          counts is for discovering NEW ids to add — never for deriving the
          frozen test list, and never for deciding which rates to drop. Ids
          only ever get added to that list; a model absent from disk today is
          one an agent could run tomorrow.

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
