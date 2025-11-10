import os
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from dotenv import load_dotenv

from app.openai_client import create_thread, add_message, run_assistant
from app.storage import get_ids
from app.metrics import metrics

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

THREADS = {}  # per-session demo (in-memory)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/reset")
def reset():
    th = create_thread()
    THREADS["thread_id"] = th.id
    return {"thread_id": th.id}

@app.post("/chat")
async def chat(req: Request):
    start_time = time.time()
    body = await req.json()
    user_msg = body.get("message", "").strip()
    if not user_msg:
        return JSONResponse({"error": "message required"}, status_code=400)

    assistant_id, _ = get_ids()
    if not assistant_id:
        return JSONResponse({"error": "Seed first: python scripts/seed_knowledge.py"}, status_code=500)

    thread_id = THREADS.get("thread_id")
    if not thread_id:
        th = create_thread()
        thread_id = th.id
        THREADS["thread_id"] = thread_id

    try:
        add_message(thread_id, "user", user_msg)
        m, usage = run_assistant(thread_id, assistant_id)
        
        latency_ms = (time.time() - start_time) * 1000
        
        content = ""
        if m and m.content:
            # concatenate text parts
            parts = []
            for p in m.content:
                if p.type == "text":
                    parts.append(p.text.value)
            content = "\n".join(parts)
        
        # Record metrics
        metrics.record_request(
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens") if usage else None,
            output_tokens=usage.get("output_tokens") if usage else None,
            total_tokens=usage.get("total_tokens") if usage else None,
            error=False
        )
        
        return {"thread_id": thread_id, "answer": content}
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        metrics.record_request(latency_ms=latency_ms, error=True)
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/")
def root():
    return FileResponse("app/static/index.html")

@app.get("/api/metrics")
def get_metrics():
    """Get metrics data as JSON."""
    return metrics.get_stats()

@app.post("/api/metrics/reset")
def reset_metrics():
    """Reset all metrics."""
    metrics.reset()
    return {"status": "reset"}

@app.get("/metrics")
def metrics_page():
    """Serve the metrics dashboard page."""
    return FileResponse("app/static/metrics.html")
