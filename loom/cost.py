"""Tokens and notional cost, read from Claude Code's own local transcripts.

Loom never asks Claude Code for this — Claude Code already writes every
session's usage to ~/.claude/projects/<slug>/<session_id>.jsonl, and the hook
(hooks/loom_hook.py) deliberately does not record the transcript path itself
("A local web server must never become a place a transcript can leak from").
So this module re-derives the transcript's location from the same `cwd` and
`session_id` the hook already writes, and reads usage straight off disk.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def locate_transcript(home: str, cwd: str, session_id: str) -> Path | None:
    """The .jsonl transcript path for one session, or None if it isn't there.

    Builds the slug the same way Claude Code does: every character in `cwd`
    that isn't a-z, A-Z or 0-9 becomes "-", and nothing is prepended — `cwd`
    already begins with "/". Verified 2026-08-23 against all 42 project
    directories on this machine that carry a readable `cwd`: this rule
    matched 42 of 42 (see the plan's ALREADY TRUE section for the wrong rule
    this replaced and why its failure was silent).

    `cwd` MUST already be the session's resolved (realpath) cwd — measured
    2026-08-27 live against a real symlinked directory: Claude Code resolves
    cwd before slugifying, so a raw, unresolved cwd here would derive a slug
    that is never created and this would return None forever for every
    symlinked worktree. Resolving is the caller's job (worktree_cost, step
    4); this function only slugifies whatever string it is given.
    """
    slug = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    path = Path(home, ".claude", "projects", slug, f"{session_id}.jsonl")
    return path if path.is_file() else None


def read_usage(transcript_path: Path) -> list[tuple[str, dict]]:
    """Every (model, usage_dict) pair a transcript's assistant lines carry.

    A malformed LINE (bad JSON, or valid JSON missing `message.model` or
    `message.usage`) is skipped, not raised — matching read_state_dir's
    tolerance for a single bad line inside a file that opened fine
    (loom/agents.py:58-68).

    A FILE THAT CANNOT BE OPENED IS A DIFFERENT FAILURE. The open() below is
    deliberately NOT wrapped in try/except: an OSError (permissions, a
    directory where a file should be, a race with deletion) propagates to the
    caller. Step 4 (worktree_cost) is what turns that exception into
    `unknown_reason: "unreadable"` for the whole worktree — catching it here
    would silently turn "unreadable" into "empty transcript" one layer too
    early.
    """
    records: list[tuple[str, dict]] = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            model = message.get("model")
            usage = message.get("usage")
            if model is None or usage is None:
                continue
            records.append((model, usage))
    return records


# A local API-error message is tagged with this "model" id — it is not a
# model, carries no cost, and is skipped explicitly rather than falling
# through the unrecognised-model branch, which would blank a whole worktree
# over one transient error.
SYNTHETIC_MODEL = "<synthetic>"

# Every id-derivation rule in this table is stated against a count taken from
# disk (see the plan's step 3), never against a plausible-looking name — this
# plan carried two wrong claims of exactly that shape across five review
# rounds before both were caught.
#
# RESOLVE IDS THROUGH THIS EXPLICIT MAP, NOT A SUFFIX REGEX. Stripping a
# trailing "-\d{8}" was inferred from the one dated id below and does not
# generalise: a future dated id's stripped form need not be its real alias.
# An id this map does not name resolves to nothing — unknown-model, never a
# guessed rate.
#
# claude-opus-4-20250514 and claude-sonnet-4-20250514 deliberately have NO
# entry here: both were retired 2026-06-15 (confirmed live against
# platform.claude.com/docs on 2026-08-27), so a transcript carrying either id
# was necessarily written before the retirement and has no current rate to
# cite. Mapping a retired id to today's rate would itself be "a number from a
# guess" — the exact thing this module refuses.
ALIAS_MAP: dict[str, str] = {
    "claude-haiku-4-5-20251001": "claude-haiku-4-5",
}

# USD per million tokens, (input, output). Keyed on the canonical id ALIAS_MAP
# resolves to. From platform.claude.com pricing, re-verified 2026-08-27.
#
# claude-sonnet-5 is priced at its INTRODUCTORY rate (2 / 10), in effect
# through 2026-08-31 and reverting to the standard 3 / 15 on 2026-09-01. This
# table was built 2026-08-27, inside the introductory window — PRICES_AS_OF
# below records when someone looked, not when this number expires, so this
# entry must be re-checked and changed to 3 / 15 on or after 2026-09-01.
RATES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10, 50),
    "claude-opus-5": (5, 25),
    "claude-opus-4-7": (5, 25),
    "claude-opus-4-8": (5, 25),
    "claude-sonnet-5": (2, 10),
    "claude-haiku-4-5": (1, 5),
}

# Cache multipliers apply to a model's own INPUT rate.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0

# When these rates and the alias map above were last checked against
# published pricing (OPEN-4) — carried into the output so a stale table is
# visible on the panel itself, not just in this comment.
PRICES_AS_OF = "2026-08-27"

# The five raw usage buckets sum_cost combines, before the sixth (derived)
# "cache_write" key is added on top.
_BUCKET_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def resolve_model(model_id: str) -> str | None:
    """The rate-table key `model_id` prices at, or None if unrecognised.

    A SEVENTH invariant this module holds (no fixture needed, just true by
    construction): every value ALIAS_MAP resolves TO must be a key in RATES,
    checked once below at import time rather than left to drift the way the
    regex it replaced eventually would have.
    """
    canonical = ALIAS_MAP.get(model_id, model_id)
    return canonical if canonical in RATES else None


# Fails at import time, not at some later call site, if the map ever points
# at a table entry that does not exist -- "a map with a dead end is the same
# bug as the regex it replaced, spelled longhand."
assert all(target in RATES for target in ALIAS_MAP.values()), \
    "ALIAS_MAP resolves to a model id with no RATES entry"


def _extract_buckets(usage: dict) -> dict[str, int | None]:
    """One record's five raw buckets, or None per bucket when the KEY itself
    is missing from the usage object -- not when its value is 0. On disk every
    usage-bearing line carries all four flat keys plus the nested
    cache_creation object with both TTL sub-keys; a missing key is what a
    record looks like when Anthropic changes the shape, not the ordinary case.
    """
    cache_creation = usage.get("cache_creation")
    cache_creation = cache_creation if isinstance(cache_creation, dict) else {}
    return {
        "input": usage.get("input_tokens") if "input_tokens" in usage else None,
        "output": usage.get("output_tokens") if "output_tokens" in usage else None,
        "cache_read": (usage.get("cache_read_input_tokens")
                       if "cache_read_input_tokens" in usage else None),
        "cache_write_5m": (cache_creation.get("ephemeral_5m_input_tokens")
                           if "ephemeral_5m_input_tokens" in cache_creation else None),
        "cache_write_1h": (cache_creation.get("ephemeral_1h_input_tokens")
                           if "ephemeral_1h_input_tokens" in cache_creation else None),
    }


def _price(canonical_model: str, bucket_totals: dict[str, int]) -> float:
    """One model's notional cost from its own five bucket totals, at its own rate.

    Cost is summed PER RECORD at that record's own model's rates and then
    totalled -- never one model's rate applied to a mixed-model list. Callers
    achieve that by grouping records to ONE model before calling this, so this
    function only ever sees totals that already share one rate.
    """
    input_rate, output_rate = RATES[canonical_model]
    total = (
        bucket_totals["input"] * input_rate
        + bucket_totals["output"] * output_rate
        + bucket_totals["cache_read"] * input_rate * CACHE_READ_MULTIPLIER
        + bucket_totals["cache_write_5m"] * input_rate * CACHE_WRITE_5M_MULTIPLIER
        + bucket_totals["cache_write_1h"] * input_rate * CACHE_WRITE_1H_MULTIPLIER
    )
    return total / 1_000_000


def sum_cost(usage_records: list[tuple[str, dict]]) -> dict:
    """Price every (model, usage) record and total them, honestly.

    Returns {"tokens": {input, cache_write_5m, cache_write_1h, cache_write,
    cache_read, output}, "model": <the model with the highest per-model
    notional_cost_usd>, "models": <every model seen, each with its own
    notional_cost_usd share and its token share>, "notional_cost_usd":
    float|None, "prices_as_of": PRICES_AS_OF}.

    `tokens` ALWAYS carries plain observed counts -- treating a genuinely
    missing bucket key as a 0 contribution to the COUNT is not a guess, it is
    "we saw nothing here." `notional_cost_usd` is the one field the honesty
    rule protects, and it goes None -- never a partial number -- when:
      * usage_records is empty, or every record is <synthetic> (nothing
        priceable was measured yet — a brand-new session, or an all-error
        turn — the same "nothing was measured" case either way)
      * any record's model does not resolve through resolve_model()
      * a bucket is present in some records combined here and absent (key
        missing) in others, or absent from every one of them -- summing it
        as though the missing ones were 0 would be a number from a guess,
        not an observation
    `<synthetic>` records are skipped entirely, before any of the above --
    they are not a model and must never trip the unrecognised-model branch.
    """
    tokens = {k: 0 for k in _BUCKET_KEYS}
    priced_records = [(m, u) for m, u in usage_records if m != SYNTHETIC_MODEL]

    if not priced_records:
        tokens["cache_write"] = 0
        return {"tokens": tokens, "model": None, "models": [],
               "notional_cost_usd": None, "prices_as_of": PRICES_AS_OF}

    bucket_present_everywhere = {k: True for k in _BUCKET_KEYS}
    # Grouped by CANONICAL id when the raw id resolves, so
    # claude-haiku-4-5-20251001 and any future alias to the same table entry
    # combine into one breakdown row rather than fragmenting the display by
    # a dated id nobody asked to see. An id that does NOT resolve is grouped
    # under its own raw id -- there is no canonical form to fold it into.
    per_model_tokens: dict[str, dict[str, int]] = {}
    unresolved_models: set[str] = set()

    for model, usage in priced_records:
        canonical = resolve_model(model)
        group_key = canonical if canonical is not None else model
        if canonical is None:
            unresolved_models.add(model)
        buckets = _extract_buckets(usage)
        mt = per_model_tokens.setdefault(group_key, {k: 0 for k in _BUCKET_KEYS})
        for k in _BUCKET_KEYS:
            v = buckets[k]
            if v is None:
                bucket_present_everywhere[k] = False
                v = 0
            tokens[k] += v
            mt[k] += v

    tokens["cache_write"] = tokens["cache_write_5m"] + tokens["cache_write_1h"]

    any_bucket_missing = not all(bucket_present_everywhere.values())
    any_unresolved = bool(unresolved_models)
    fully_priceable = not any_bucket_missing and not any_unresolved

    models_out = []
    per_model_costs: dict[str, float] = {}
    for group_key, mt in per_model_tokens.items():
        resolved = group_key not in unresolved_models  # unresolved kept under raw id
        if resolved and not any_bucket_missing:
            cost = _price(group_key, mt)
            per_model_costs[group_key] = cost
        else:
            cost = None
        models_out.append({
            "model": group_key,
            "notional_cost_usd": cost,
            "tokens": dict(mt, cache_write=mt["cache_write_5m"] + mt["cache_write_1h"]),
        })

    if fully_priceable:
        notional_cost_usd = sum(per_model_costs.values())
        winner = max(per_model_costs, key=lambda m: per_model_costs[m])
    else:
        # At least one model's cost, or one bucket's total, cannot be
        # honestly known -- so neither a total nor a "which model spent
        # most" answer can be either. Naming a winner from an incomplete
        # comparison would be exactly the guess this module refuses.
        notional_cost_usd = None
        winner = None

    return {
        "tokens": tokens,
        "model": winner,
        "models": models_out,
        "notional_cost_usd": notional_cost_usd,
        "prices_as_of": PRICES_AS_OF,
    }
