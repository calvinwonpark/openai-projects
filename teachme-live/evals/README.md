# TeachMe Live Offline Evals

This eval suite validates transcript-only safety behavior through `POST /chat_text` (no microphone required).

## Run locally

```bash
# from teachme-live/
uvicorn app:app --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
python evals/run.py
```

If your server runs on a different port:

```bash
API_BASE_URL=http://localhost:8010 python evals/run.py
```

## Dataset

`evals/datasets/transcript_eval.jsonl` includes 25+ rows covering:
- High-risk refusal routing
- Ambiguous prompts requiring clarifying questions
- Korean and English handling
