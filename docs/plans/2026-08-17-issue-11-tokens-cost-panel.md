Issue #11 — Add a tokens-and-cost panel, read from local transcripts
Stated size: no `Size` line on the issue → directed by Serina at planning time (2026-08-17) to treat as more than an hour → cap: 12 steps

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
    slug = "-" + cwd.replace("/", "-") — verified live: `ls ~/.claude/projects/`
    shows `-home-serina-Launchpad-loom` for cwd `/home/serina/Launchpad/loom`
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
        Builds the slug the same way Claude Code does and returns the
        expected .jsonl path only if it exists.
        done when: a test with a fake HOME dir and a planted .jsonl at the
        derived slug path gets that exact path back, and a session_id with
        no matching file gets None

STEP 2  cost.py: read_usage(transcript_path) -> list[(model, usage_dict)]   [needs 1]
        Streams the jsonl, pulling message.model + message.usage from lines
        where both are present. A malformed line is skipped, not raised,
        matching read_state_dir's tolerance (loom/agents.py:58-68).
        done when: a fixture .jsonl with 2 well-formed usage lines and 1
        malformed line returns exactly the 2 usage records, in order

STEP 3  cost.py: pricing table + sum_cost(usage_records) -> cost dict   [needs 2]
        Four per-token rates keyed by model name, plus a "prices_as_of" date
        constant beside the table (per Serina's OPEN-4 decision above).
        sum_cost() returns {"tokens": {4 buckets}, "model": <name, or None if
        records span >1 model>, "notional_cost_usd": float|None,
        "prices_as_of": <date string>}. An unrecognised model, or a bucket
        absent from every record, returns notional_cost_usd=None — never a
        number derived from a guess.
        done when: `python3 -c "from loom.cost import sum_cost; ..."` against
        a fixture record for a known model prints a numeric
        notional_cost_usd and a non-empty prices_as_of, and the same call
        with an unrecognised model name prints notional_cost_usd: None
                                                                      ← RUNS HERE

STEP 4  cost.py: worktree_cost(state_dir, worktree_path, home)   [needs 1,2,3]
        Matches every session whose cwd is the worktree or inside it (the
        same prefix rule as agent_for, loom/agents.py:129-147), resolves and
        reads each one's transcript, and combines them. If ANY matched
        session's transcript cannot be located or read, or a bucket is
        missing after combining, the WHOLE worktree result is {"tokens":
        None, "notional_cost_usd": None, "unknown_reason": <why>} — never a
        partial sum presented as complete.
        done when: three fixture cases (transcript found and complete;
        transcript missing for one of two matching sessions; a bucket absent
        from a summed record) each produce the shape the honesty requirement
        demands — populated only in the first case

STEP 5  Wire worktree_cost into collect()   [needs 4]
        Call it once per worktree beside the existing ahead/behind and
        status calls (loom/collect.py:141-151); attach the result under a
        new "cost" key on each worktree dict; add a "cost" SourceStatus
        entry to `sources` reporting ok=False with a reason only when a
        worktree's cost is unknown because a transcript was unreadable
        (never for a worktree with simply no active session — not an error).
        done when: `loom snapshot --json` run from this repo shows a
        non-null cost.tokens for at least one worktree, and every existing
        test in tests/test_collect.py still passes unmodified

STEP 6  view.py: fleet_total(repos), wired into finalise()   [needs 5]
        Follows the aggregate_needs/badge pattern (loom/view.py:122-147) —
        sums notional_cost_usd across every worktree with a known cost, and
        reports the unknown ones by count in the label text itself (per
        Serina's OPEN-2 decision above — "N worktrees excluded", never a
        silent gap), never folding an unknown into the sum as zero. Called
        from finalise() (loom/view.py:180-197) to attach snap["cost"] at the
        top level. The label also carries the "list-price equivalent, not a
        bill" caveat, so the frontend only paints it.
        done when: a test with two worktrees (one priced, one unknown)
        asserts the total equals only the priced one's figure, and the
        label text contains both the caveat and "1" (the excluded count);
        `loom snapshot --json` shows the same shape for real

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
          zero matching sessions, more than one matching session — is exactly
          the kind of case this project's own audit history (H3, M4, L2, H7
          in collect.py's comments) shows gets subtly wrong on a first pass.

OPEN      All four resolved by Serina, 2026-08-17 — recorded here rather than
          only in chat, so the decision survives past this conversation:

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
