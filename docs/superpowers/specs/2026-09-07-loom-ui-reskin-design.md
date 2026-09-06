# Loom — a vixenz-inspired reskin, no architecture change

- **Date:** 2026-09-07
- **Status:** approved
- **Author:** Serina McFall, with Claude
- **Supersedes:** nothing. Replaces `loom.css`'s `:root` token values and
  `loom.js`'s Data-sources render path; no schema, no snapshot change, and
  the only Python touch is one content-type table entry in `serve.py` (see
  "Fonts, self-hosted" below — caught during planning).

## The problem

The dashboard works — every panel is real, live, and accessibility-audited —
but it doesn't feel like Serina's. Every panel carries the same visual
weight, whether it's "Needs you" (the one thing worth acting on) or "Data
sources" (diagnostics, rarely of interest). And the palette is a generic
GitHub-dark-mode lookalike, not an aesthetic anyone chose on purpose.

This spec borrows the visual identity already built for
`vixenz-portfolio` (deep indigo backgrounds, warm/cool identity hues, a
disciplined type scale) and uses it to also fix the flatness: the one
actionable panel becomes visually first among equals, and the one
diagnostics-only panel becomes something you open on purpose instead of
scan past every time.

## Constraints

- **No architecture change.** Loom's page is deliberately zero-build vanilla
  JS/HTML/CSS, updated live over one `EventSource`. `loom.js`'s own docstring
  says every *decision* belongs in `loom/view.py`, not the page — this spec
  respects that boundary and touches only rendering, never what gets decided.
- **No accessibility regression.** Every color in the current palette carries
  a WCAG contrast ratio in a code comment, verified against both `--bg` and
  `--panel`. Any replacement token needs the same verification, computed
  against both backgrounds, not a by-eye guess.
- **`vixenz-portfolio`'s palette does not survive contact with a dense
  dashboard unmodified.** Its actual panel/border colors, dropped in as-is,
  measured 1.25:1 against its background — nearly invisible. That works on a
  portfolio, where whitespace and glow carry structure. It does not work
  here, where a reader needs to see where one data panel ends and the next
  begins. See "Palette & tokens" below for the fix.
- **21st.dev is a React/Tailwind component marketplace.** Loom has no
  React, no build step, and no bundler. Importing its components literally
  would mean adopting all three — a fork in scope, not a styling change. This
  spec instead re-implements the *visual ideas* (chip-shaped state badges,
  glow-accented hero cards) in the page's existing vanilla CSS. A real React
  migration, if wanted, is deliberately out of scope here — see below.

## Design

### Palette & tokens

Vixenz's five identity hues carry over unchanged — they're what makes this
recognizably Serina's, and all of them clear AA by a wide margin against a
Loom-style dark background:

| Token | Hex | vs background | vs panel |
|---|---|---|---|
| `--text` (moonlight) | `#F3EAD7` | 14.9:1 | 12.2:1 |
| `--dim` (mist) | `#B3BCD0` | 9.3:1 | 7.6:1 |
| `--warn` (lantern) | `#E6B870` | 9.7:1 | 7.9:1 |
| `--good` (lotus) | `#6FB3B8` | 7.5:1 | 6.1:1 |
| `--branch` (lavender, derived) | `#C7A8F0` | 8.7:1 | 7.1:1 |

Vixenz has no error/danger hue (a portfolio doesn't need one), so `--bad` is
a new rose derived from the same warm family, not borrowed from GitHub-dark's
red: `#F0919E`, 7.8:1 / 6.4:1.

**What had to change:** the portfolio's own panel and border colors
(`--surface-card`, a translucent overlay, and `--tile-border`) measured
1.25:1 and 1.09:1 against its background when flattened to solid colors —
below even Loom's *current* (already loose) 1.55:1 / 1.09:1. Panels here are
opaque, not translucent-over-a-blurred-atmosphere, because Loom has no
atmosphere to blur — just a flat page. Brightened, same-hue replacements:

| Token | Hex | vs background |
|---|---|---|
| `--bg` (midnight, unchanged) | `#16152E` | — |
| `--panel` | `#242648` | 1.22:1 |
| `--line` (border) | `#3A3F7A` | 1.84:1 |

1.84:1 is still well under the 3:1 WCAG 1.4.11 guideline for meaningful
graphical objects — but so is Loom's *current, shipped* 1.55:1, and in both
cases the border reinforces a boundary that heading text, spacing, and DOM
landmarks already convey; it's never the sole way a reader (sighted or
not) knows where a panel ends. This spec makes it better than today, not
perfect, and doesn't block on a redesign the current page doesn't have
either.

### Rank ramp

The six-step urgency ramp (`--rank1`..`--rank6`, warm-and-loud to
cool-and-quiet) gets the same treatment — re-hued into the vixenz family,
same warm→cool ordering, each value re-verified:

| Rank | Meaning | Hex | vs panel (worst case) |
|---|---|---|---|
| 1 | blocked on a human right now | `#F0919E` | 6.4:1 |
| 2 | parked, awaiting review | `#E6B870` | 7.9:1 |
| 3 | collision brewing | `#E8CE7E` | 9.4:1 |
| 4 | failing checks | `#CBBF95` | 7.9:1 |
| 5 | stopped with work behind | `#9FB4D9` | 6.9:1 |
| 6 | loose ends | `#B3BCD0` | 7.6:1 |

Same rule as today: color reinforces the rank number and detail text
already printed in words; it never carries meaning alone.

### Fonts, self-hosted

Vixenz loads Lexend (headings/prose) and JetBrains Mono (code/data) from
Google's CDN. Loom is a loopback-only local tool — Serina chose to
self-host both families instead, so the dashboard renders correctly with
zero network access. Existing fallback stacks (`system-ui` / `ui-monospace`)
stay as the safety net if a font file is ever missing.

**Correction (2026-09-07, caught during planning):** the font files live
flat in `loom/static/`, not `loom/static/fonts/`. `serve.py`'s `/static/`
route resolves every request through `Path(self.path).name` — the
basename only, any directory component silently stripped — so a nested
path would 404. That same route's content-type table currently maps only
`css`/`js`; a `.woff2` extension needs to be added there too (one new
entry, `{"woff2": "font/woff2"}`), which makes this the one place the
"no Python change" framing above was wrong. The change is one line in an
existing lookup table, not new routing logic, so the architectural
boundary this spec cares about (no new decisions moving into `loom.js`
or `loom/view.py`) still holds.

Loom's data-heavy panels (tables, token counts, commit shas) keep
JetBrains Mono throughout, matching the current monospace-first design;
Lexend is reserved for headings and the needs-you hero's prose line, mirroring
how vixenz itself splits body text from code.

### Layout & hierarchy

Two structural changes, both scoped to stay inside the current DOM shape:

**Needs-you becomes a hero.** It's already a distinct element
(`section.panel--needs`, already first in the DOM and in reading order) —
no reordering needed, no reworked landmark structure. The change is CSS
only: larger padding and type for the item text, and a **static** (no
motion) radial glow in lantern that appears only when
`needs_you` is non-empty. When the fleet is quiet, the panel stays calm and
flat — the glow is a signal of urgency, not decoration, so it must not be
always-on.

**Correction (2026-09-07, caught by review-a11y during the review gate):**
this originally described a two-hue "lantern/magnolia" glow. Only lantern
shipped — `--magnolia` was defined but never referenced. Rather than wire
the second hue in after the fact, it was removed: the review that caught
this also found the chip badges (see "Layout & hierarchy" below) shipped a
real WCAG AA failure from an under-verified composited color, and adding a
second translucent hue to the hero's own composited gradient risked the
same class of mistake for a purely cosmetic gain.

**Data sources collapses into a native `<details>`/`<summary>`.** This is
the one panel that's pure diagnostics (git/gh/tmux health) — rarely
useful unless something's broken, unlike every other panel. The native
HTML disclosure element is keyboard-operable and correctly announced by
screen readers with zero custom ARIA — it already *is* the W3C APG
disclosure pattern, for free. This is a small, contained change to
`buildRepoSection` in `loom.js`: the `sources` `<ul>` moves inside a
`<details>`, the visually-hidden `<h3>` becomes the `<summary>`'s
accessible label.

**Correction (2026-09-07, caught by review-a11y then re-shaped by
review-final):** a first draft implemented this literally — a bare
`<summary>Data sources</summary>` with no heading and no landmark
region at all. review-a11y found that dropped this panel from both
heading navigation and the landmark rotor (`panel()`'s normal shape
gives every other panel both). What shipped instead, and is the actual
current shape: `<section class="panel" aria-labelledby>` — the same
wrapper every other panel uses — containing `<details><summary><h3
id="...">Data sources</h3></summary><ul>...</ul></details>`. The
heading is now genuinely visible (inside the summary, not hidden) *and*
still reachable by heading navigation and the landmark rotor, which the
"visually-hidden `<h3>` becomes the label" text above got half right:
the visually-hidden trick is gone, but a real `<h3>` survives rather
than being flattened into plain summary text.

**Loose ends stays visible, not collapsed.** Unlike Data sources, it's
occasionally user-actionable (an orphaned PR, a directory that stopped
being a worktree) even though the common case is "No loose ends" — hiding
it behind a click would bury the rare case it exists to catch.

**State badges become chips.** `STATE_LABEL`'s existing glyph-and-word
values (`▶ working`, `⛔ waiting`, …) get a small rounded, tinted
background — a chip shape borrowed from 21st.dev's visual style, hand-rolled
in CSS. The glyph and word both stay exactly as they are today; the chip is
a background treatment, not a new way of conveying state.

**Correction (2026-09-07, found by review-code/review-a11y):** this claim
is true for six of the seven states, not all seven. `idle` had no prior
`.state--idle` rule at all — it inherited plain `--text` at full
brightness — so grouping it under the same dim tint as `unknown`/`none`
*is* a new color decision for that one state, kept deliberately (a
neutral idle reads correctly next to working/waiting/stopped's urgency
colors) rather than reverted. The other six states' colors are unchanged
from what `state--*` already used.

**Correction (2026-09-07, found by review-final):** the Data-sources
heading described above is not static text. `renderSources()` now
appends a live failing-source count — `Data sources — N failing` — so a
real `git`/`gh`/`tmux` failure is signaled without forcing the panel
open (which would fight a user who closed it on purpose) or leaving it
silently invisible inside collapsed content (which a first draft did,
re-creating the exact hole `loom/collect.py`'s "honesty channel", audit
finding H3, exists to close). This was added during the fix round for
review-a11y's findings, not in the original build steps, and is the one
place `renderSources()` is no longer purely a rendering function of its
`sources` argument — it also reads the section's own heading element.

### Cross-cutting: accessibility

No new interactive semantics beyond the native `<details>` disclosure,
which needs none. No live region changes: the hero's glow is a CSS-only
reaction to data already driving `renderNeeds`, not a new announcement
path. `:focus-visible` styling and the `prefers-reduced-motion` media
query in `loom.css` carry over unchanged and continue to apply to
whatever's added. Every new or changed color is contrast-verified above,
same discipline as the file's existing comments.

## Trade-offs

- The border/panel definition (1.22:1 / 1.84:1) is a real, if small,
  improvement over the current 1.09:1 / 1.55:1 — but it is still soft by
  general UI convention. The alternative (push panel/border brightness up
  to a hard 3:1) was rejected: at the swatches tested, hitting 3:1 against
  this background meant a noticeably lighter, more lavender-gray tone that
  broke the "deep midnight" identity vixenz is known for. Structure here
  leans on headings and spacing more than on border contrast, same as
  today.
- Self-hosting fonts is one extra asset-management concern (two font files
  to keep in the repo) in exchange for the tool never depending on network
  access to render as intended — judged worth it for a local-first tool.

## Alternatives considered

- **Full re-theme + panel count reduction** (also merging "Loose ends" into
  "Needs you", reworking the header bar): rejected for this round as too
  much simultaneous change to review at once. The current scope (palette +
  needs-you hero + one collapse) is the smallest change that fixes the
  three complaints (flat weight, density, no personality) without
  re-deciding the whole information architecture in one pass.
- **A user-toggleable compact/spacious layout setting:** rejected — a real
  toggle control needs its own APG pattern and persisted state, which is
  interactivity, not polish. Belongs in Spec 2 if wanted at all.
- **React migration now, reskin as part of it:** rejected — see
  Constraints. Validating the *look* first, in the medium that's fastest to
  iterate in (plain CSS, no build step), was proven out live during
  brainstorming: two full mockup variants were built and compared in
  minutes. Doing that inside a React scaffold would have been slower for
  no benefit, and would have coupled two decisions (design direction,
  framework adoption) that are cleaner made separately.

## Out of scope, deliberately

- React, any build step, any bundler — deferred to a future Spec 2
  (interactivity), where a framework would actually be earning its keep
  instead of being bolted onto a page that today has none
- Any new interactive widget beyond the native `<details>` disclosure —
  sortable columns, clickable commits, expandable rows all wait for Spec 2
- Panel reordering — Needs-you is already first; nothing else moves
- Any change to `loom/view.py`, `loom/collect.py`, or the snapshot schema —
  this spec is presentation-only

## Tests

**Correction (2026-09-07, found by review-final):** this section
originally claimed "no new Python behavior, so no new `tests/test_*.py`
coverage" — contradicted by this same document's own "Fonts,
self-hosted" section, which requires a `serve.py` content-type change.
What shipped is more than a static table entry: a conditional
(`content_type = ctype if ctype == "font/woff2" else f"{ctype};
charset=utf-8"`) that is genuine new branching behavior. `tests/
test_serve.py::test_a_woff2_font_is_served_with_no_charset_parameter`
now pins it — added specifically because review-final noted the exemption
above rested on a premise this document itself refuted, and the
untested branch was exactly the one review-code had just caught being
wrong once already.

Everything else in this spec is still presentation-only with no
Python-side decision logic added, so it stays manually verified: load
the dashboard in a real browser in both the quiet and
needs-you-non-empty states (as mocked during brainstorming), confirm
the hero glow only appears in the latter, confirm `<details>`
opens/closes with both mouse and keyboard, and re-run the contrast
computation above against the actual shipped hex values before merge —
all done live during the build and fix rounds; see the plan's own
`STEP 6` and the fix commit for what was actually run.
