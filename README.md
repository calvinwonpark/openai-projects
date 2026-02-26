# OpenAI Projects

Monorepo of deployment-focused OpenAI application patterns. Each project emphasizes production concerns: safety controls, structured outputs, observability, eval gating, and CI automation.

## Repository Layout

- `founder-copilot/`
- `founder-copilot-response/`
- `gpt-eval-kit/`
- `k-food-helpdesk/`
- `teachme-live/`
- `gir-caddie-mvp/`

## Project Details

### `gpt-eval-kit` (OpenAI-first evaluation framework)

Deployment-grade eval framework for OpenAI systems with both offline and online execution.

- **Core architecture:** adapter-based execution (`offline`, `http_app`, `openai_responses`), deterministic scoring, baseline diff gating, markdown/json reporting.
- **CLI:** `evalkit run`, `evalkit report`, `evalkit diff`; supports suite-specific baselines and `--update-baseline`.
- **Scoring:** schema validation, refusal correctness, citation grounding, tool precision/recall, routing accuracy + confusion matrix.
- **Performance gates:** non-refusal/non-failure-injection aggregates (`latency`, `cost`, `tokens`) compared against baseline with configurable thresholds.
- **OpenAI integration:** `client.responses.create()` with strict `response_format.json_schema` when suite requires structured outputs; tool calls parsed directly from `response.output`.
- **CI:** offline evals on PR, gated online evals when `OPENAI_API_KEY` is available and PR is non-fork.
- **OpenAI APIs:** Responses API.

### `founder-copilot-response` (Responses API production migration)

Production version of a multi-assistant founder copilot migrated from Assistants to Responses.

- **Routing + strategy:** route classification across `tech`, `marketing`, `investor`, with strategies like winner-take-all / consult-then-decide / ensemble / data-analysis flow.
- **Tooling:** schema-validated tool arguments, retry/timeout handling, partial-response warning paths.
- **State + tenancy:** tenant-scoped conversation keys and analysis conversations; supports `/chat_text` JSON pipeline for evalability.
- **Streaming UX:** SSE chat stream with incremental rendering and structured extras (bullets/sources/images).
- **Observability:** structured telemetry logs with latency, token usage, cost estimates, schema validity, tool success.
- **Evals:** offline suite with confusion matrix, baseline/perf regression gates, CI workflow.
- **OpenAI APIs:** Responses API (+ code interpreter/file search tools through Responses), optional container file retrieval patterns.

### `founder-copilot` (Assistants API reference implementation)

Original Assistants API implementation of the founder copilot system.

- **Capabilities:** multi-assistant specialization, vector retrieval, tool use, streaming chat UX, dashboard-style metrics.
- **Value in repo:** baseline architecture for comparing Assistants-era patterns vs Responses-first implementations.
- **OpenAI APIs:** Assistants API, Threads, Vector Stores, File Search, Code Interpreter.

### `k-food-helpdesk` (Safe RAG template)

Interview-ready safe RAG system template designed for deployment engineering discussions.

- **Backend:** FastAPI + PostgreSQL/pgvector retrieval with deterministic post-validation.
- **Safety + trust:** strict structured output contract, citation verification (quotes must match source chunks), prompt-injection-resistant reference handling, PII redaction hooks.
- **Ops:** request-level tracing/debug endpoints, JSON logs, offline eval dataset + CI gating.
- **OpenAI APIs:** Embeddings (`text-embedding-3-small`) + chat model inference (model configurable; default mini class).

### `teachme-live` (Realtime voice tutor)

Realtime conversational tutoring app with safety and observability controls.

- **Realtime stack:** browser mic/WebRTC pipeline + backend policy gate.
- **Safety router:** risk classification and refusal templates for sensitive categories.
- **Robustness:** degraded modes for low STT confidence, latency pressure, and TTS failure.
- **Tracing:** session/turn/request IDs, structured turn logs, bounded in-memory trace store.
- **Evals:** transcript-based offline eval suite and CI workflow.
- **OpenAI APIs:** Realtime API + Responses/Chat pipeline for policy/tutor orchestration.

### `gir-caddie-mvp` (Multimodal strategy assistant)

Golf strategy assistant that combines image understanding with domain-specific planning.

- **Core function:** parse course-related visuals and context to generate shot-planning recommendations.
- **Pattern demonstrated:** multimodal input handling + structured decision support generation.
- **OpenAI APIs:** GPT-4o multimodal inference (vision + text reasoning).

## Common Engineering Themes

- Structured outputs with schema enforcement
- Safety routing/refusal controls
- Tool-call validation and failure-mode handling
- Evals + baseline regression gates in CI
- Cost/latency/token telemetry for deployment decisions