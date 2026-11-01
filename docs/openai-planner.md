# OpenAI planner adapter

The Responses API adapter is implemented and tested with a fake client. No live
request has been verified. The `prepare-openai` CLI explicitly invokes the adapter
and connects its captured response to the durable preparation worker. Offline
commands remain available and never automatically switch to a paid provider.

The adapter follows the official [Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
It requests a strict ProjectPlan JSON schema, then validates the returned JSON
locally. PlanningService remains responsible for replaying the proposed changes,
checking secrets, and proving final-source equality. Structured output alone does
not establish that a plan is correct or meaningful.

## Configuration for the live entry point

Install the optional SDK dependency:

```bash
python -m pip install -e '.[openai]'
```

Supply `OPENAI_API_KEY` in the process environment. The factory uses the official
SDK and endpoint, and refuses to initialize without an explicit
`GIT_PROGRESSOR_OPENAI_MODEL`. Choose a model supporting Responses structured
outputs. The key is not a Settings field and is never serialized into project
artifacts. A key placed only in `.env` is not loaded by this factory.

Other settings:

| Setting | Default | Bound |
| --- | --- | --- |
| `GIT_PROGRESSOR_OPENAI_MAX_OUTPUT_TOKENS` | 8192 | 1–32768 |
| `GIT_PROGRESSOR_OPENAI_TIMEOUT_SECONDS` | 120 | Greater than zero, at most 600 |

The request JSON is limited to 512 KiB by default and response text to 2 MiB.
No tools are supplied, response storage is disabled, and automatic SDK retries
are disabled. A timeout can still incur usage on the provider side; it is not
evidence that no billable request occurred. Token/byte limits are not a dollar
budget. Budget reservations and retry reconciliation must be added before
unattended live processing; the ledger records reported token usage only.

Incomplete responses, refusals, malformed JSON, and schema violations fail closed.
SDK error messages are replaced by a generic error to avoid exposing credentials
or source text. Token usage, when provided, is captured by the durable handoff;
it is not a dollar-cost ledger. There are no paid model fallbacks.

## Durable handoff and commands

```bash
git-progressor prepare-openai PROJECT_ID --model YOUR_MODEL
git-progressor planning-status REQUEST_ID
git-progressor planning-resume REQUEST_ID
git-progressor planning-resume REQUEST_ID --retry
```

`prepare-openai` can incur API charges and transmit the bounded project context
and source excerpts. It prints the planning request ID before calling the provider.
No real API calls were made during implementation or automated tests.

Migration 6 adds `planning_requests`, which records source revision, context hash,
model, output token cap, prompt policy version, response hash, token usage when
available, and linked preparation job. Identical inputs reuse the saved request.
Changing the model or context creates a distinct request that can incur new costs.

An atomic PENDING-to-STARTED transition permits only one worker to call the API.
The response is saved as CAPTURED before deterministic generation starts. Recovery
from that point does not require credentials or another API call. The response
remains untrusted until preparation passes its integrity and secret checks.

STARTED means an API attempt may have happened. A crash in that state is not
automatically retried, even after a long wait. FAILED provider requests are also
not reissued. This avoids duplicate spending when the outcome is uncertain; it
does not provide exactly-once delivery or guarantee recovery of an unsaved response.
`--retry` retries only deterministic preparation, never the model request.
The separate `planning-retry REQUEST_ID` command explicitly permits one more
potentially billable attempt for a FAILED request, up to three total attempts.
It preserves the original source revision, context hash, model, and output cap,
and archives previous failure/usage evidence in `planning_retry_history`.
It refuses STARTED requests with uncertain outcomes and CAPTURED successful
responses. Migration 7 adds attempt counts and this retry history. Ordinary
resume and repeated prepare commands never authorize an API retry.
Other projects can proceed independently. No automatic reset of ambiguous API
attempts or provider reconciliation is implemented yet.

Token usage is saved when supplied by the adapter, including incomplete responses.
Timeouts and abrupt process termination can leave usage unknown. The ledger is
not a dollar budget or a complete billing record. Database access is trusted and
must remain private because captured responses contain project source material.

## Next integration milestone

Test a small calculator run with a configured key and selected model, add persistent
spending reservations and reconciliation, then connect planning to cloud queues.
The current offline tests do not prove SDK/server schema
compatibility or the quality of actual model-generated stages.
