# Audits

An audit judges the whole tree against reality, at one commit. A code review judges one
change against its intent. These are the former.

**Read an audit beside its remediation log**, or you are reading a list of problems that
have since been fixed.

## 2026-08-05 · Claude (Opus 5)

| | |
|---|---|
| **Findings** | [`audit-2026-08-05-claude.md`](audit-2026-08-05-claude.md) |
| **Remediation** | [`remediation-2026-08-05.md`](remediation-2026-08-05.md) |
| **Baseline** | `a4b4eea` — 200 tests, clean tree |
| **Result** | 0 Blocker · 8 High · 11 Medium · 13 Low |

Audited the whole tree plus its two external consumers (the `serina-skills` loom skill,
and the CI workflow). **All 32 findings are resolved.** Test count went from 200 to 283,
a pinned `mypy` job was added, and CI now runs on Python 3.10 through 3.13.

**The audit was written by the same model family that built much of the code, and no
third party has graded it.** Its most serious findings carry pasted execution output for
exactly that reason — so they can be checked without trusting the auditor. The
remediation log records three places where execution proved the audit itself wrong.

### Still open at the end of the Low tier

Not findings, but deliberately left for a human:

| | Why it is not fixed here |
|---|---|
| `CHANGES_REQUESTED` is invisible at every rank | A design decision: giving it a rank changes the spec's ranking table, which is not a bugfix |
| The loom skill's `hooks` constraint can never fire | The skill's wording is wrong, not the code — and it lives in `serina-skills`, a different repository, installed from GitHub |
| The `types` check is not required by the ruleset | Making it required is a gate change |
| Issues #3, #4, #6, #8 | Fixed on the branch, so they close on merge. Closing them now would claim `main` is fixed when it is not |
| Issue #11 (tokens-and-cost panel) | A legitimate deferred feature, matching the spec's own out-of-scope list |

## If you are running the next one

Do not re-run blind and do not grade an existing audit from its own text: verify each
finding against the code, then add what it missed. The remediation log is the honest
place to start — it records what was fixed, what was deliberately left, and which of
the original findings turned out to be wrong.
