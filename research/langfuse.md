# Langfuse

Researched 2026-08-10 · findings apply to Langfuse **v4** (the version the
self-hosting page documents) and to Claude Code's telemetry docs as of the same date.

**Two dates, deliberately.** Everything below is as of 2026-08-10 unless a passage carries
its own later date inline — one addition, about whether identity can be suppressed at
source, was checked 2026-08-12. Dated in place rather than by bumping this header, because
re-dating the whole note would silently claim the older claims were re-checked when they
were not.

**Read this caveat first.** Every quote below was retrieved by a fetch tool that
renders a page through a summarising model. The wording is therefore *reported* as
verbatim, not *proven* verbatim. Before depending on any exact string — an
environment variable, an endpoint path — open the cited URL and read it directly.
That is a real limitation of how this note was made, not a formality.

## What it is, and the problem it solves

Langfuse is an LLM observability backend: it stores traces of LLM calls, with token
usage, cost, latency and model, and gives you a UI to browse and chart them over
time. Self-hostable, or hosted by them.

The problem it solves *for Loom*: Loom is stateless by design — one snapshot, no
history. So it cannot answer "what did this cost yesterday" or "is this run getting
slower". Langfuse holds the datastore that Loom deliberately refuses to have.

## When to use it — and when not

**Use it for** history and trends across sessions: cost per day, tokens by model,
one run compared against another over time.

**Do not use it for** the question Loom already answers — *what needs me now*.
Loom's issue #11 makes this argument better than I can: *"Adding charts here makes
a worse Langfuse without making a better Loom."*

**Do not put it inside Loom.** Its SDK is a pip package, and `check_stdlib_only.py`
fails on any import it has never heard of. The pairing has to be
side-by-side — Claude Code exports to Langfuse directly, and Loom never imports it.

## How to start

**Claude Code's side.** Traces are behind a beta flag; without it you get metrics
and log events only, which Langfuse does not ingest (see Open questions). Reported
from the Claude Code docs:

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
export OTEL_TRACES_EXPORTER=otlp
```

The span hierarchy those produce, as reported by the same page:

```
claude_code.interaction
├── claude_code.llm_request
├── claude_code.hook
└── claude_code.tool
    ├── claude_code.tool.blocked_on_user
    ├── claude_code.tool.execution
    └── (subagent spans)
```

**Langfuse's side.** The OTLP endpoint path is `/api/public/otel`, with
`/api/public/otel/v1/traces` for signal-specific configuration. Auth is Basic, and
the token is built by base64-encoding the key pair:

```bash
echo -n "pk-lf-1234567890:sk-lf-1234567890" | base64
```

```
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ${AUTH_STRING},x-langfuse-ingestion-version=4"
```

**The one config trap found so far.** Langfuse's OTLP is HTTP only — *"Langfuse
currently supports OTLP over HTTP with both `HTTP/JSON` and `HTTP/protobuf`. `gRPC`
is not supported yet."* Claude Code's own examples use
`OTEL_EXPORTER_OTLP_PROTOCOL=grpc` and port 4317. So the protocol must be set to
`http/protobuf` and the endpoint pointed at Langfuse's path, or nothing arrives.

**Self-hosting cost.** v4 requires four backing services — *"Postgres - OLTP
(Transactional Data)"*, *"Clickhouse - OLAP (Observability Data)"*, a
*"Redis/Valkey cache"*, and an *"S3/Blob Store"* — started with `docker compose up`.
The deployment page recommends *"at least 4 cores and 16 GiB of memory, e.g. a
t3.xlarge on AWS"*, and warns the compose setup *"lacks high-availability, scaling
capabilities, and backup functionality."*

**Cloud free tier:** *"50k units / month included"*, *"30 days data access"*,
*"2 users"*. Paid tiers: Core $29/mo, Pro $199/mo, Enterprise $2,499/mo.

## What surprised me

**1. Claude Code exports real spans, not just metrics.** I expected metrics and log
events only, which would have made the whole pairing a non-starter, since Langfuse
takes traces only. The `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` flag changes the
answer. This is the single finding the design hinges on.

**2. Billing counts spans, not calls.** *"Units = Count of Traces + Count of
Observations + Count of Scores"*, and every observation in a trace counts. Claude
Code emits a span per tool call **and per hook firing** — and Loom installs hooks on
six event types, so hooks fire constantly. Arithmetic, not a source: at ~25–35
observations per turn, 50k units is roughly 1,500–2,000 turns per month. For a fleet
that is weeks, not a year.

**3. The self-hosting floor is 16 GiB.** Four services for a personal dashboard is
much heavier than "run a container".

## Open questions

1. **Do Claude Code's spans actually carry the attributes Langfuse maps to usage and
   cost?** Langfuse reads `langfuse.observation.usage_details`, `gen_ai.usage.*` or
   `llm.token_count.*` for tokens, and `langfuse.observation.cost_details` or
   `gen_ai.usage.cost` for cost. Claude Code documents its *metric* names (`claude_code.token.usage`,
   `claude_code.cost.usage`) but the span attribute names were not on the page I
   read. **This is the load-bearing unknown** — if the spans carry usage under other
   names, Langfuse will show traces with no tokens and no cost, which is most of the
   value gone.
   *Method — an experiment, not more reading:* enable the beta flags, export to a
   local collector, and read the actual attribute keys off one `claude_code.llm_request`
   span. RepoQL's `watch` collects OTEL into queryable tables locally, so this can be
   done without standing up Langfuse at all.

2. **Can a trace carry usage and cost with input and output omitted entirely?**
   Needed for the "no prompt content leaves the machine" constraint. The masking docs
   describe redacting content via a `mask` callback, but *"does not address whether
   inputs and outputs can be completely omitted or fully redacted while preserving
   token usage and cost tracking."* Unresolved.
   *Method:* read the ingestion API reference for whether `input`/`output` are
   optional fields; then confirm by sending one span with usage and no content and
   checking the UI still shows tokens and cost.

3. **Does the OTLP path apply pricing to arrive at a cost, or only pass one
   through?** Matters because Claude Code reports API-list-price cost while Serina is
   on a subscription — the same honesty problem issue #11 already names. Unverified.
   *Method:* Langfuse's token-and-cost-tracking docs, then confirm on a real trace.

4. **What does 30-day retention mean for trend work?** A free-tier chart cannot show
   a quarter. Unverified; *method:* the pricing page's retention wording plus one
   test query after 30 days, or accept it as a known ceiling.

## Sources

- OpenTelemetry Integration with Langfuse — https://langfuse.com/integrations/native/opentelemetry — undated
- Self-hosting (v4) — https://langfuse.com/self-hosting — undated
- Docker Compose deployment — https://langfuse.com/self-hosting/deployment/docker-compose — undated
- Pricing — https://langfuse.com/pricing — undated
- Billable Units — https://langfuse.com/docs/administration/billable-units — undated
- Masking — https://langfuse.com/docs/observability/features/masking — undated
- Claude Code, Monitoring usage — https://code.claude.com/docs/en/monitoring-usage — undated
- Loom issue #11, "Add a tokens-and-cost panel, read from local transcripts" — local repository — 2026-08

Every Langfuse page carried no visible publication date, so none of them can support
a claim about how the product behaves *now* on their own. The v4 label on the
self-hosting page is the only version anchor found.

## Checked — 2026-08-10

Method: ran one real Claude Code turn with the console span exporter, no collector and
no Langfuse involved, and read the emitted spans directly.

```bash
CLAUDE_CODE_ENABLE_TELEMETRY=1 CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1 \
OTEL_TRACES_EXPORTER=console OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none \
claude -p --model claude-haiku-4-5-20251001 "Reply with exactly the word: ok"
```

**The beta flag works, on `claude-code` v2.1.220.** Two spans were emitted —
`claude_code.interaction` (root) and a child `claude_code.llm_request` — under
instrumentation scope `com.anthropic.claude_code.tracing` v1.0.0.

**Token usage IS on the span — under bare names, not `gen_ai.usage.*`.** The keys below
are a **selection** of what `claude_code.llm_request` carried, not an exhaustive dump —
it also carried `span.type`, `speed`, `duration_ms`, `stop_reason`, `request_id`,
`ttft_ms`, `attempt` and `client_request_id`. Quoted verbatim, the ones that matter here:

```
input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
model, gen_ai.system, gen_ai.request.model, gen_ai.response.id,
gen_ai.response.finish_reasons
session.id
```

**`session.id` is on the list because the design depends on it.** It appeared on *both*
spans, the same UUID on each, and it is the join key back to Loom's hook state files. The
first version of this block omitted it — having been rewritten specifically to stop reading
as exhaustive, it enumerated eight incidental attributes and left out the one load-bearing
one. Verified in shape only: both are UUIDs and `session.id` is stable across the run, but
no hook state file from that same run was captured, so the join has not been demonstrated
end to end.

All four of the buckets issue #11 needs, priced differently from each other, plus a
*partial* GenAI semantic-convention set.

**Note `model` and `gen_ai.request.model` are BOTH present**, carrying the same value.
That matters: Langfuse's mapping page says *"Any span with a `model` attribute is tracked
as a `generation`"*, so classification needs no rename. Recorded explicitly because an
earlier version of this section listed only `gen_ai.request.model` and read as if it were
the complete set — which led a reviewer to file a Blocker on the reasonable inference that
no bare `model` key existed. The list was a selection; the wording did not say so.

**There is no cost attribute on the span at all.** No `gen_ai.usage.cost`, no
`langfuse.observation.cost_details`. Cost appears only as the separate
`claude_code.cost.usage` *metric*, which Langfuse does not ingest.

**Prompt content is redacted by default.** The interaction span carried
`user_prompt: "<REDACTED>"` with `user_prompt_length` beside it. Content omission is
the default, not something to configure — which satisfies the no-content constraint
without a masking callback.

**New finding the note did not anticipate: spans carry identity.** Every span
included `user.email`, `user.id`, `organization.id`, `user.account_uuid` and
`user.account_id` as attributes (values deliberately not reproduced in this note).
Anything shipped to a hosted Langfuse carries those with it.

**And the emitter cannot be asked to withhold them.** `OTEL_METRICS_INCLUDE_ACCOUNT_UUID`
and `OTEL_METRICS_INCLUDE_SESSION_ID` exist, but the docs scope them to **metrics, not
spans**, and say `organization.id`, `user.id` and `user.email` are *"always included"* —
not controlled by any flag. The `OTEL_LOG_*` switches do reach spans, but they govern
prompt, response and tool **content**, which is already off by default. So identity can
only be removed downstream, which is what makes a collector a trust boundary rather than a
convenience. Checked 2026-08-12 against the Claude Code monitoring docs.

## Corrections — what this note got wrong

**Nothing in the note was false.** The rules held. Three things were incomplete:

1. **Open question 1 is now answered, and the answer is "not natively".** The note
   framed it as unknown whether spans carry usage. They do — but under
   `input_tokens`/`output_tokens`, which are *not* the `gen_ai.usage.*` keys Langfuse
   documents reading. So a direct export very likely lands traces with no tokens and
   no cost. **Still unverified on the receiving side:** Langfuse may accept bare names
   by heuristic. Only sending one span to a real instance settles that.
2. **Open question 2 was aimed at the wrong end.** It asked whether Langfuse can
   store usage without content. The emitter never sends content in the first place,
   so the question mostly dissolves.
3. **The units arithmetic assumed tool and hook spans.** This turn used no tools and
   produced two spans, not thirty. The 1,500–2,000-turns estimate holds only for
   tool-heavy work; a quiet session is far cheaper. Incomplete, not wrong.

4. **The usage-mapping list dropped one key, and the attribute dump read as exhaustive.**
   Both found by the `review-docs` pass on PR #22, and both fixed above: the fetch
   returned three usage sources and this note recorded two, and the observed-attributes
   block did not say it was a selection. Neither made a false claim — but the second one
   cost a competent reviewer a Blocker filed on a true statement, which is a real cost
   even when the document is technically correct.

## Check these first

1. **`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` is what turns spans on.** The entire
   design rests on it, it is labelled beta, and beta flags get renamed or promoted.
   *Method:* run `claude` with it set plus `OTEL_TRACES_EXPORTER=console` and confirm
   spans print to the terminal. If nothing prints, the flag has moved.
2. **The header string
   `"Authorization=Basic ${AUTH_STRING},x-langfuse-ingestion-version=4"`.** Copied
   through a summarising fetch, and one wrong character means silent 401s.
   *Method:* open the integration page and read the code block directly before use.
3. **"gRPC is not supported yet."** A "not yet" is the sentence most likely to be
   stale, and it dictates the protocol setting.
   *Method:* same page; or just try `http/protobuf` first, which works either way.
