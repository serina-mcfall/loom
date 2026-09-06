Loom UI reskin — vixenz palette, needs-you hero, no React
Stated size: Focused Checklist  →  cap: 8 steps

ALREADY TRUE  (verified against git and the real files, not the design doc's prose)
  loom.css's `:root` (lines 1-28) defines the current GitHub-dark palette
    (`--bg:#0d1117` etc.) with a per-token WCAG ratio recorded in a comment
    beside each one (lines 3-27). This plan replaces the values; it keeps
    the pattern of documenting the ratio beside the token.
  Neither `.panel--needs` nor `.panel--cost` (referenced as classes in
    index.html:33 and :74) has a single CSS rule defined anywhere in
    loom.css today — confirmed by grep. Both currently render IDENTICALLY
    to plain `.panel` (loom.css:45-46). The hero treatment this plan adds
    is new CSS, not an override of an existing rule.
  renderNeeds() (loom.js:91-111) rewrites only the `<ul id="needs">`'s
    children; it never touches the ancestor `<section class="panel
    panel--needs">`. There is currently no hook anywhere for a
    "something needs attention" vs. "quiet" visual distinction.
  buildRepoSection's Data-sources panel (loom.js:430-434) is a plain `<ul>`
    inside the shared panel() helper, with its `<h3>` made
    `visually-hidden` (loom.js:433) so a sighted user never sees a label
    at all. There is no `<details>` element anywhere in loom/static/ today
    — confirmed by grep.
  renderTrees() (loom.js:168) colors each worktree's Agent cell by putting
    `state--${state}` directly on the `<td>`. There is no `.chip` class or
    badge wrapper anywhere in loom.css or loom.js today — confirmed by grep.
  loom/serve.py's `/static/` route (lines 312-323) resolves every request
    through `Path(self.path).name` (line 316) — the BASENAME ONLY, any
    directory component silently stripped — and its content-type table
    (lines 321-322) maps only `css` and `js`. There is no `loom/static/
    fonts/` directory today, and a request for one would 404 under this
    routing. THE DESIGN DOC ORIGINALLY SAID `loom/static/fonts/`; this was
    corrected in the design doc (2026-09-07, caught during this planning
    pass) to a flat path, and the one-line content-type addition this
    forces is recorded there too.
  `python3 -m unittest discover -s tests` passes 374 tests today (run live,
    this session, standalone — not piped, so the run is attributable).
    No test in tests/test_serve.py asserts on the BYTES of loom.css or
    loom.js — the three call sites that touch either path (lines 655-665,
    817, 897-911) check status codes and caching headers only.

STEP 1  Self-host three font files flat in loom/static/, teach serve.py     [independent]
        the woff2 content-type
        Add `Lexend-Regular.woff2`, `Lexend-SemiBold.woff2`, and
        `JetBrainsMono-Regular.woff2` (OFL-licensed, redistributable)
        directly under `loom/static/` — NOT a subfolder, per ALREADY TRUE's
        routing constraint — plus the license file(s) required by OFL
        attribution. Add one entry to serve.py's content-type table
        (loom/serve.py:321-322): `"woff2": "font/woff2"`.
        No `@font-face` yet — that is step 2, once the files this step
        adds actually exist to point at.
        done when: the three files and their license text exist under
        `loom/static/`; with `python3 loom_cli.py serve` running,
        `curl -sI http://127.0.0.1:8787/static/Lexend-Regular.woff2`
        returns `200` with `Content-Type: font/woff2` (repeat for the
        other two filenames); `python3 -m unittest discover -s tests`
        still shows 374 passed.

STEP 2  loom.css: replace the :root palette, rank ramp, and font stack      [needs 1]  ← RUNS HERE
        with the approved design's vixenz-derived tokens
        Replace `--bg`/`--panel`/`--line`/`--text`/`--dim`/`--warn`/
        `--bad`/`--good`/`--branch` and all six `--rank*` values with the
        hex values computed in the design doc's tables, each carrying its
        contrast ratio in a comment (same convention the current file
        already uses). Also set `--time: #7FD6E8` and `--num: #8FA8F0` —
        see OPEN below, these two weren't in the approved spec's table.
        Add three `@font-face` rules pointing at step 1's files; apply
        Lexend to `h1`/`h2`/`h3` and the needs-you hero's item text
        (added in step 3); leave the body's monospace-first stack
        (loom.css:30-31) as JetBrains Mono everywhere else, unchanged in
        spirit.
        done when: with `loom serve` running and the page loaded, browser
        devtools computed-style on `<body>` shows the new `--bg` hex, not
        `#0d1117`; re-running the contrast formula from the design doc
        against every text-bearing token actually checked into loom.css
        (not the design doc's copy) confirms each is ≥4.5:1 against both
        `--bg` and `--panel`; `python3 -m unittest discover -s tests`
        still shows 374 passed (a CSS-only change breaking a Python test
        would mean an unrelated edit crept in).

STEP 3  loom.css + loom.js: needs-you hero, glowing only when non-empty     [needs 2]
        Add CSS for `.panel--needs` (larger padding, larger item type) and
        a second, additive rule for `.panel--needs.is-active` (the static
        — no animation — radial glow in lantern, corrected from an earlier
        two-hue "lantern/magnolia" description: --magnolia went unused in
        what actually shipped and was removed rather than wired in, to
        avoid re-risking the contrast margin review-a11y found and fixed
        2026-09-07). Modify
        renderNeeds() (loom.js:91-111) to toggle `is-active` on the
        section ancestor: `list.closest("section").classList.toggle(
        "is-active", items.length > 0)`.
        done when: loading the real dashboard while the fleet is quiet
        (today's actual state — `needs_you: []`) shows the calm, flat
        variant with no glow; opening browser devtools and manually
        editing the DOM to add an `is-active` class (or briefly stopping
        a worktree's agent / simulating a snapshot with a non-empty
        `needs_you`, whichever is faster to hand) shows the glow appear;
        removing the class again removes it. `python3 -m unittest
        discover -s tests` still shows 374 passed.

STEP 4  loom.js: Data sources panel becomes a native <details>/<summary>    [needs 3]
        In buildRepoSection (loom.js:430-434), replace the panel()-wrapped
        `<ul>` with a `<details>` whose `<summary>` reads "Data sources"
        (dropping the `visually-hidden` h3 trick — the label is genuinely
        visible now, sitting in the summary itself). renderSources()
        (loom.js:286-292) is unchanged — it only ever mutated the inner
        `<ul>`, which still exists in the same place.
        CORRECTED (2026-09-07, review-final, after the fix round below):
        both of the previous paragraph's claims changed shape during the
        fix round that closed review-a11y's findings, and are false as a
        description of what actually shipped. The `<summary>` is not bare
        text — review-a11y found the bare version dropped this panel from
        heading navigation and the landmark rotor, so it now contains a
        real `<h3>`, itself wrapped in the same `<section aria-labelledby>`
        shape every other panel uses. And renderSources() is no longer
        unchanged: it now takes a third argument (the heading element) and
        writes a live failing-source count into it. See the design doc's
        own corrections in "Layout & hierarchy" and "Tests" for why.
        This is the one step that could conceptually run alongside step 3
        or step 5, but does not — see PARALLEL below.
        done when: loading the dashboard shows "Data sources" as a closed-
        by-default disclosure; clicking it with a mouse opens it; Tab-ing
        to it and pressing Enter or Space (keyboard only, no mouse) also
        opens and closes it — native `<details>` guarantees this, verify
        it actually does in a real browser rather than assuming; the real
        git/gh/tmux source list appears inside once open.

STEP 5  loom.css + loom.js: state badges become chips                      [needs 4]
        In renderTrees() (loom.js:168), wrap `STATE_LABEL[state]` in
        `<span class="chip chip--${state}">...</span>` instead of putting
        `state--${state}` on the `<td>` directly. Add matching
        `.chip`/`.chip--working`/`.chip--waiting`/etc. rules in loom.css —
        tinted, rounded background using the SAME colors `state--*`
        already uses today, so nothing here is a new color decision.
        done when: loading the dashboard shows each worktree's Agent cell
        as a small rounded, tinted pill; viewing the rendered HTML (browser
        inspector) confirms the glyph AND word are both still inside the
        chip's text content — nothing here changes what a screen reader
        announces, only adds a wrapper and a background.

STEP 6  Full-pass manual verification                                      [needs 3, 4, 5]
        No new automated coverage is added anywhere in this plan (the
        design doc's own Tests section says so, and ALREADY TRUE confirms
        no existing test touches either file's content) — this step IS
        the plan's verification, not a placeholder for one.
        done when: `python3 -m unittest discover -s tests` shows 374
        passed; a full keyboard-only pass (Tab, no mouse) reaches the
        needs-you hero, every existing scroll region, and the new
        `<details>`, in that order, with visible focus on each; toggling
        `prefers-reduced-motion: reduce` in devtools and reloading shows
        the hero's glow appear/disappear instantly (it was specified as
        static, never animated, so there is nothing to disable) and the
        existing reduced-motion rule (loom.css:144-146) still applies
        unchanged to whatever else on the page has motion.

PARALLEL  Step 1 is the only genuinely independent step — it touches
          loom/serve.py and adds new font files, never loom.css or
          loom.js. Steps 2 through 5 ALL touch loom.css and/or loom.js;
          two edits to the same file conflict regardless of how
          unrelated the changes look, so none of them may run as
          parallel subagents even though steps 3, 4, and 5 are
          conceptually independent of each other. This is a strictly
          sequential plan once step 1 is done.

GATES     review-code applies to the whole diff (loom.css, loom.js,
          loom/serve.py) once step 6 is done.
          review-a11y applies — this plan introduces a new native
          disclosure widget and a conditional visual state, and Serina's
          own accessibility rule requires every UI change to be audited
          as part of the build, not after.
          review-tests does NOT apply in its usual sense: this plan adds
          no new automated test coverage by design (manual verification
          only, per the design doc's own Tests section) — there is
          nothing for it to review.
          qa explore mode DOES apply: after step 6, drive the real
          dashboard through both fleet states (quiet and needs-you-non-
          empty, as already mocked during brainstorming), keyboard-only,
          and with reduced-motion toggled — exactly step 6's own
          done-when, run by a fresh pair of eyes.
          review-final applies once the above are clear, matching this
          repo's own convention of one whole-branch pass before merge.

BUDGET    Step 1 is the step most likely to overrun — not the code, but
          sourcing two correctly-licensed, appropriately-subset woff2
          files (not full variable-axis Google Fonts megafiles, which
          would be needlessly large for a three-weight local tool) and
          bundling the OFL attribution correctly. It is also the only
          step requiring an actual outbound fetch during implementation,
          everything after it is pure editing.

OPEN      None outstanding. Two gaps the approved design doc's palette
          left open were confirmed by Serina before build (2026-09-07):
          `--time` stays close to its current cyan (`#7FD6E8`, 10.7:1 /
          8.8:1) and `--num` becomes a new periwinkle-blue (`#8FA8F0`,
          7.6:1 / 6.2:1); font weights stay at three files (Lexend
          Regular + SemiBold, one JetBrains Mono Regular), with the
          existing `font-weight: 700` rules left as browser-synthesized
          bold rather than a fourth font file.

LEFT OUT  Any change to the rank ramp's underlying logic in loom/view.py
          — this plan only re-hues the CSS classes already keyed to it.
          Introducing a JS test harness for loom.js — the codebase has
          never had one; adding one is a far bigger decision than a
          reskin should carry, and every done-when above is written to
          be checkable by hand instead.
          Any change to how `/static/`'s routing itself works beyond the
          one content-type table entry — the flat-namespace behavior
          stays exactly as it is; this plan works inside it.
