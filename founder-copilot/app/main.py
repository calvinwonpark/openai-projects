import os
import time
from fastapi import FastAPI, Request, Depends, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Optional
from dotenv import load_dotenv

from app.openai_client import create_thread, add_message, run_assistant_structured, upload_file
from app.storage import get_ids
from app.metrics import metrics

import redis.asyncio as redis
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

THREADS = {}  # per-session demo (in-memory)

async def client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    cf = req.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    return req.client.host if req.client else "unknown"

redis_client = None

@app.on_event("startup")
async def startup():
    global redis_client
    redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                                  encoding="utf-8", decode_responses=True)
    await FastAPILimiter.init(redis_client, identifier=client_ip)

@app.on_event("shutdown")
async def shutdown():
    global redis_client
    if redis_client:
        await redis_client.aclose()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/reset", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
def reset():
    th = create_thread()
    THREADS["thread_id"] = th.id
    return {"thread_id": th.id}

# main costed endpoint: 3 req / 60s per IP
@app.post("/chat", dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def chat(
    message: str = Form(...),
    files: Optional[List[UploadFile]] = File(None)
):
    start_time = time.time()
    user_msg = message.strip()
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
        # Upload files if provided
        file_ids = []
        if files:
            for file in files:
                if file.filename:
                    file_content = await file.read()
                    uploaded_file = upload_file(file_content, file.filename)
                    file_ids.append(uploaded_file.id)
        
        # Add message with file attachments if any
        add_message(thread_id, "user", user_msg, file_ids=file_ids if file_ids else None)
        result = run_assistant_structured(thread_id, assistant_id)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Extract usage from structured response
        usage = result.get("usage", {})
        
        # Record metrics
        metrics.record_request(
            latency_ms=latency_ms,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            total_tokens=usage.get("total_tokens"),
            error=False
        )
        
        # Return structured response with answer, sources, images, and other fields
        return {
            "thread_id": thread_id,
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "raw_text": result.get("raw_text", ""),
            "bullets": result.get("bullets"),  # Optional, if present
            "images": result.get("images", []),  # Images from code_interpreter
            "usage": usage
        }
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
