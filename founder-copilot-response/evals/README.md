# Founder Copilot Response Evals

Offline eval suite for deployment workflow checks:
- routing behavior
- tool selection
- tool schema validation failures
- refusal behavior
- baseline latency/cost/token regression checks

## Run locally

```bash
# Terminal 1
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2
# compare mode (default)
python evals/run.py

# update baseline intentionally after approved performance changes
python evals/run.py --update-baseline
```

Override endpoint:

```bash
API_BASE_URL=http://localhost:8010 python evals/run.py
```

Outputs:
- per-case results: `evals/out/last_run_results.json`
- baseline: `evals/baselines/workflow_baseline.json`
