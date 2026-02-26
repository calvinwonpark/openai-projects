# Offline RAG Evals

This suite validates that `/chat` follows the safe-RAG contract:

- language field correctness (`ko`/`en`)
- refusal behavior for out-of-scope queries
- citation presence for non-refusal answers
- required source citation checks

## Run locally

1. Start services:

```bash
docker compose up -d --build db server
docker compose run --rm indexer
```

2. Run evals:

```bash
python evals/run.py
```

Optionally point to another endpoint:

```bash
API_BASE_URL=http://localhost:8000 python evals/run.py
```
