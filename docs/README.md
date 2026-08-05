# Loom — documentation index

Every document in this repository, what it is for, and whether it is authoritative.

Audit finding L13: there was no index. With one spec and one plan that was cosmetic —
but it is also the mechanism by which findings L3 through L7 all went unnoticed.
Nothing enumerated what the documents claimed, so nothing could be checked against
what the code did. This is that enumeration.

## Authoritative — describes the code as it is

| Document | What it is |
|---|---|
| [`../README.md`](../README.md) | How to run Loom, and its one requirement (Python 3.10+) |
| [`superpowers/specs/2026-08-03-loom-design.md`](superpowers/specs/2026-08-03-loom-design.md) | The design: architecture, the snapshot contract, error honesty, ranking, accessibility requirements, threat model — **and a corrections list recording every place execution proved the original wrong** |

**The corrections list is the load-bearing part.** A spec that quietly matches whatever
got built teaches nobody anything, so when the code and the document disagree the
document records *why* rather than being rewritten to match. Nine corrections so far;
three were added by the 2026-08-05 audit.

## Findings — a snapshot in time, not a description of the code

| Document | What it is |
|---|---|
| [`audits/README.md`](audits/README.md) | Index of audits and their remediation |
| [`audits/audit-2026-08-05-claude.md`](audits/audit-2026-08-05-claude.md) | 8 High, 11 Medium, 13 Low, 0 Blocker, plus a proposed refactor and nine alternatives with verdicts |
| [`audits/remediation-2026-08-05.md`](audits/remediation-2026-08-05.md) | The fix journey: per finding, the failing test that drove it and the evidence that closed it |

An audit describes the tree **at the commit it was run against**. Read the remediation
log beside it, or you will be reading a list of problems that have since been fixed.

## Archived — history, not documentation

| Document | What it is |
|---|---|
| [`archive/2026-08-03-loom-v1-plan.md`](archive/2026-08-03-loom-v1-plan.md) | The task-by-task execution plan for v1, built and merged as PR #2. **Superseded in several places** — see its own header |

## The rule this index exists to serve

For any claim a document makes about behaviour, it should be possible to find the code
that makes it true. When it is not, that is a finding, and it belongs in an audit
rather than being quietly reconciled.
