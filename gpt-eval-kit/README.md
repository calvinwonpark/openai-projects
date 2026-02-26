# gpt-eval-kit

OpenAI-first, deployment-grade evaluation framework for AI systems.

## What it includes

- Offline + online execution modes (`offline`, `http_app`, `openai`)
- Adapter architecture for local simulation, HTTP app integration, and OpenAI Responses
- Deterministic scoring (schema/refusal/grounding/tool/routing)
- Baseline regression gates for latency/cost/tokens
- CI-friendly CLI with run/report/diff commands
- Markdown + JSON run artifacts

## CLI

```bash
evalkit run --suite cases/suites/routing_core.jsonl --mode offline
evalkit report --run runs/<run_id> --format md
evalkit diff --baseline baselines/routing_core --run runs/<run_id>
```

Run with your app:

```bash
evalkit run --suite cases/suites/routing_core.jsonl --mode http_app --app-url http://localhost:8000
```

Run directly with OpenAI Responses:

```bash
export OPENAI_API_KEY=...
evalkit run --suite cases/suites/routing_core.jsonl --mode openai --model gpt-4o-mini
```

Update baseline intentionally:

```bash
evalkit run --suite cases/suites/routing_core.jsonl --mode offline --update-baseline
```

Explicit suite baseline folder:

```bash
evalkit run --suite cases/suites/tool_use.jsonl --mode offline --baseline baselines/tool_use
```

## Directory layout

```
cases/suites/*.jsonl
evalkit/runners/runner.py
evalkit/adapters/{offline.py,http_app.py,openai_responses.py}
evalkit/scoring/*.py
evalkit/rubrics/*.yaml
evalkit/reporting/*.py
baselines/<suite_name>/summary.json
runs/<run_id>/{manifest.json,results.jsonl,summary.json,report.md,diff.md}
```

## Notes

- `openai_responses` adapter calls `client.responses.create()`.
- Suite cases can provide `_suite_config` defaults (`requires_structured_output`, `response_schema`, `model`, `temperature`, `perf_gates`).
- In OpenAI mode, route/refusal checks auto-enable strict structured output using a routing schema.
- Regression thresholds are enforced against suite-specific baseline summaries.
