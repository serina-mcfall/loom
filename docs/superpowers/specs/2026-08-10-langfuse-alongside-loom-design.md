# Loom and Langfuse — history beside the live board

Loom answers *what needs me now*. It is stateless by design: one snapshot, no history,
no datastore. That is why it is a stdlib-only project with zero dependencies.

So it cannot answer *what did this cost yesterday*, or *is this run getting slower*.
This spec pairs Loom with Langfuse to answer those, **without Loom gaining a single
dependency or storing a single prompt.**

Research it rests on: [`research/langfuse.md`](../../../research/langfuse.md), checked
2026-08-10 against `claude-code` v2.1.220 and Langfuse v4.

## The problem

Issue #11 already drew the line, and this spec does not move it:

> Loom answers "what needs me now". Langfuse answers "what happened and what did it
> cost". Adding charts here makes a worse Langfuse without making a better Loom.

The design doc deferred cost in v1 because it *"requires standing up OpenTelemetry from
Claude Code into a collector, and verifying what it actually emits per session before
depending on it."* That verification has now happened. This spec is what it found.

## Why not put Langfuse inside Loom

Three reasons, in increasing order of how much they matter.

**It would fail the build.** Langfuse's SDK is a pip package. `check_stdlib_only.py`
fails on any import it has never heard of, and the absence of a dependency file is the
evidence the README cites for "no third-party supply chain".

**It would make Loom stateful.** Trends need a datastore, a retention policy and a
query layer. Loom has none of those on purpose.

**It would break the promise in `hooks/loom_hook.py`.** *"Deliberately records no
prompt, no output, no tool input and no transcript path. A local web server must never
become a place a transcript can leak from."* Langfuse's usual value is storing exactly
that. The two designs are not compatible, so they stay separate processes with separate
jobs.

## Decision: a local collector between them, and nothing else

```
Claude Code  ──OTLP/HTTP──▶  otelcol-contrib (local)  ──OTLP/HTTP──▶  Langfuse Cloud
   spans                      · renames usage attrs                    traces, tokens,
   (beta flag)                · strips identity attrs                  cost, over time

Loom  ──reads hook state + transcripts──▶  live board (UNCHANGED)
```

The collector exists because of one measured fact: **Claude Code's spans carry token
counts under names Langfuse does not read.** Observed on a real span, verbatim:

```
input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
```

Langfuse reads usage from `gen_ai.usage.*`, `llm.token_count.*` or
`langfuse.observation.usage_details`. Claude Code emits some GenAI attributes
(`gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.id`) but not the usage ones.
A direct export would therefore land traces with **no tokens and no cost** — most of the
value, silently absent.

One thing needs no help: *"Any span with a `model` attribute is tracked as a
`generation`."* The `claude_code.llm_request` span has `model`, so classification is free.

## Langfuse Cloud, not self-hosted

| | |
|---|---|
| Self-hosted v4 needs | Postgres, Clickhouse, Redis/Valkey, an S3-compatible store |
| Recommended | *"at least 4 cores and 16 GiB of memory"* |
| Docker on this machine | **not installed** |
| Free tier | *"50k units / month included"*, *"30 days data access"*, *"2 users"* |

Self-hosting means installing Docker and running four services to evaluate a tool. The
collector removes the reason to fear hosting, because identity never leaves the machine.
**If the constraint later becomes "nothing leaves at all", self-hosting is the exit, and
nothing in this design has to change but the exporter endpoint.**

## The collector is the trust boundary

Spans carry `user.email`, `user.id`, `organization.id`, `user.account_uuid` and
`user.account_id`. All five are deleted before egress.

**`session.id` is deliberately kept.** It is the join key: issue #11 records that the
session id is already in Loom's hook state files, so that one attribute is what lets a
Langfuse trend be traced back to a worktree. Removing it would make the two tools
un-joinable and cost the pairing its point.

Prompt content needs no handling: the interaction span arrives as
`user_prompt: "<REDACTED>"` with a length beside it. **Redaction is the platform's
default, not something this design configures** — which is why no masking step appears
below.

## The configuration

Claude Code's side, env only:

```bash
CLAUDE_CODE_ENABLE_TELEMETRY=1
CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=none          # Langfuse ingests traces only
OTEL_LOGS_EXPORTER=none             # do not pay units for signals that get dropped
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
```

`http/protobuf` is not a preference. Langfuse's docs: *"`gRPC` is not supported yet."*
Claude Code's own examples default to gRPC on port 4317, so this is the one setting most
likely to be got wrong by following either doc alone.

The collector:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 127.0.0.1:4318      # localhost only

processors:
  transform/usage:
    error_mode: ignore                # a missing attribute must never drop a span
    trace_statements:
      - set(span.attributes["gen_ai.usage.input_tokens"],  span.attributes["input_tokens"])
      - set(span.attributes["gen_ai.usage.output_tokens"], span.attributes["output_tokens"])
      # cache buckets: see "The one open question" below

  attributes/strip_identity:
    actions:
      - { key: user.email,        action: delete }
      - { key: user.id,           action: delete }
      - { key: organization.id,   action: delete }
      - { key: user.account_uuid, action: delete }
      - { key: user.account_id,   action: delete }

exporters:
  otlphttp/langfuse:
    endpoint: https://cloud.langfuse.com/api/public/otel
    headers:
      Authorization: "Basic ${env:LANGFUSE_AUTH}"
      x-langfuse-ingestion-version: "4"

service:
  pipelines:
    traces:
      receivers:  [otlp]
      processors: [transform/usage, attributes/strip_identity]
      exporters:  [otlphttp/langfuse]
```

`transform` is beta for traces and ships in the **contrib** distribution only, so the
binary is `otelcol-contrib`. It is a single Go binary from GitHub releases — no Docker.

**The key never appears in the config.** `${env:LANGFUSE_AUTH}` holds the base64 pair.
The config file may be committed; the environment file must not be, and goes in
`.gitignore` the moment it exists.

**The endpoint carries no `/v1/traces`.** The `otlphttp` exporter appends the signal
path, landing on Langfuse's documented `/api/public/otel/v1/traces`. Getting this wrong
produces silent 404s, so stage 4 below checks for exactly that.

## The one open question, and it is a spike not a guess

Whether `gen_ai.usage.*` understands **cache** buckets is unverified — Langfuse's docs
give the wildcard and never enumerate it. `langfuse.observation.usage_details` accepts
arbitrary keys as a JSON string and certainly would, but building JSON from four integer
attributes in OTTL is awkward.

**So: send one span mapped both ways and look at the UI.** Whichever renders all four
buckets becomes the config; the other is deleted. This is one step, before any of the
rest is trusted, because everything downstream of it inherits the answer.

## Cost is not money owed, here either

Claude Code puts **no cost attribute on the span at all** — cost exists only as the
`claude_code.cost.usage` metric, which Langfuse does not ingest. So any figure Langfuse
shows is computed from its own model pricing: **API list price, not subscription spend.**

Issue #11 refuses to tell that lie locally. This design must not tell it remotely: any
dashboard built on this carries the caveat in its name or description. A number that
looks like a bill and is not one is the failure this project exists to refuse.

## Verification — one hop at a time

An empty dashboard has four different causes with four different fixes, so each hop gets
its own observable signal.

```bash
# stage 0 — config valid, port listening
otelcol-contrib validate --config=collector.yaml
ss -ltn | grep 4318

# stage 3 — the negative check; anything but 0 is a leak
grep -cE 'user\.(email|id|account)|organization\.id' debug.log
```

| Stage | Method | Pass |
|---|---|---|
| 0 | the two commands above | config valid, port listening |
| 1–2 | add `debug` exporter with `verbosity: detailed` to the **same** pipeline | span printed, and `gen_ai.usage.input_tokens` present in it |
| 3 | the `grep` above, against the debug log | **0** |
| 4 | one real turn, then the Langfuse UI | trace present, tokens non-zero |

Stage 1–2 works because `debug` sits at the end of the pipeline, so what it prints is
**post-processing** — one look proves arrival and rename together.

**Stage 3 is the assertion that matters and it expects zero.** Without a check that
expects nothing, "identity is stripped" is a belief. This is the same reasoning as the
positive control in `tests/test_hook.py`: without it, a handler that always failed would
satisfy every other assertion.

Failure modes, separated so they cannot be confused:

| Symptom | Cause |
|---|---|
| no trace, no export errors | spans never reached the collector — check Claude Code's env |
| no trace, 401 or 404 in collector log | auth string or endpoint path wrong |
| trace present, tokens blank | the rename did not map — the spike's question |
| trace present, tokens populated | the chain works |

## Units: measure before filtering

*"Units = Count of Traces + Count of Observations + Count of Scores"*, and every
observation counts. `claude_code.hook` spans will be the high-volume, low-value ones —
Loom installs hooks on six events.

**Start without filtering and measure for a week.** A `filter` processor can drop hook
spans later if units run hot. Filtering first would be discarding the data that says
whether it was needed.

Recorded honestly: the estimate in the research note — roughly 1,500–2,000 turns per
month against 50k units — is arithmetic over a documented span hierarchy, not a
measurement. The turn actually measured emitted **two** spans, because it used no tools.

## Out of scope, deliberately

- **Any change to Loom.** No import, no field, no dependency, no panel. Rollback is
  unsetting env vars and killing the collector; Loom cannot carry a mark from this.
- **Replacing issue #11.** The local tokens-and-cost panel stays: it is offline, needs no
  key, and is the honest view. This spec adds history beside it, not instead of it.
- **Prompt or completion content.** Never sent, and no configuration here enables it.
- **Self-hosting.** The exit if the constraint changes, not the starting point.
- **Charts in Loom.** Still the wrong place, for the reason issue #11 gives.

## Ordering

Issue #11 says **after #3 and #9**, because *"a new panel on a dashboard that reports
live agents as `stale` makes the existing lie more convincing, not less."*

That constraint applies to Loom's own panel and **not** to this work, which changes
nothing in Loom and cannot make its board more convincing. This can proceed independently
of #3 and #9. Stated explicitly so nobody has to guess whether the ordering was
overlooked or considered.
