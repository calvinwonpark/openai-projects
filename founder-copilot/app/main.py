import os
import time
from fastapi import FastAPI, Request, Depends, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from typing import List, Optional
from dotenv import load_dotenv

from app.openai_client import create_thread, add_message, run_assistant_structured, upload_file
from app.storage import get_ids, get_assistant_ids, get_all_assistant_ids
from app.router import route_query
from app.metrics import metrics

import redis.asyncio as redis
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

THREADS = {}  # per-session demo (in-memory) - stores thread_id per session
THREADS_BY_ASSISTANT = {}  # Stores thread_id per assistant label per session

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
    """Reset conversation threads (both legacy and multi-assistant)."""
    th = create_thread()
    THREADS["thread_id"] = th.id
    THREADS_BY_ASSISTANT.clear()  # Clear all assistant-specific threads
    return {"thread_id": th.id, "message": "All threads reset"}

def _has_grounded_content(result: dict) -> bool:
    """Check if assistant retrieved grounded content (sources or substantial answer)."""
    sources = result.get("sources", [])
    answer = result.get("answer", "").strip()
    # Consider it grounded if there are sources or a substantial answer (>50 chars)
    return len(sources) > 0 or len(answer) > 50

def _get_or_create_thread(label: str) -> str:
    """Get or create a thread for a specific assistant label."""
    if label not in THREADS_BY_ASSISTANT:
        th = create_thread()
        THREADS_BY_ASSISTANT[label] = th.id
    return THREADS_BY_ASSISTANT[label]

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

    # Check if multi-assistant setup exists, fallback to legacy single assistant
    all_assistants = get_all_assistant_ids()
    if not all_assistants:
        # Legacy single assistant mode
        assistant_id, _ = get_ids()
        if not assistant_id:
            return JSONResponse({"error": "Seed first: python scripts/seed_multi_assistants.py"}, status_code=500)
        
        thread_id = THREADS.get("thread_id")
        if not thread_id:
            th = create_thread()
            thread_id = th.id
            THREADS["thread_id"] = thread_id
        
        try:
            file_ids = []
            if files:
                for file in files:
                    if file.filename:
                        file_content = await file.read()
                        uploaded_file = upload_file(file_content, file.filename)
                        file_ids.append(uploaded_file.id)
            
            add_message(thread_id, "user", user_msg, file_ids=file_ids if file_ids else None)
            result = run_assistant_structured(thread_id, assistant_id)
            
            latency_ms = (time.time() - start_time) * 1000
            usage = result.get("usage", {})
            
            metrics.record_request(
                latency_ms=latency_ms,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                error=False
            )
            
            return {
                "thread_id": thread_id,
                "answer": result.get("answer", ""),
                "sources": result.get("sources", []),
                "raw_text": result.get("raw_text", ""),
                "bullets": result.get("bullets"),
                "images": result.get("images", []),
                "usage": usage
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_request(latency_ms=latency_ms, error=True)
            return JSONResponse({"error": str(e)}, status_code=500)
    
    # Multi-assistant routing mode
    try:
        # Step 1: Route the query
        routing = route_query(user_msg)
        label = routing["label"]
        confidence = routing["confidence"]
        top2_label = routing["top2_label"]
        margin = routing["margin"]
        is_high_risk = routing["is_high_risk"]
        
        # Step 2: Upload files if provided
        file_ids = []
        if files:
            for file in files:
                if file.filename:
                    file_content = await file.read()
                    uploaded_file = upload_file(file_content, file.filename)
                    file_ids.append(uploaded_file.id)
        
        # Step 3: Determine routing strategy
        primary_assistant_id, _ = get_assistant_ids(label)
        reviewer_assistant_id, _ = get_assistant_ids(top2_label)
        
        if not primary_assistant_id:
            return JSONResponse({"error": f"Assistant '{label}' not found. Run: python scripts/seed_multi_assistants.py"}, status_code=500)
        
        primary_result = None
        reviewer_result = None
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        
        # Strategy 1: Winner-take-all (confidence >= 0.8)
        if confidence >= 0.8:
            thread_id = _get_or_create_thread(label)
            add_message(thread_id, "user", user_msg, file_ids=file_ids if file_ids else None)
            primary_result = run_assistant_structured(thread_id, primary_assistant_id)
            total_usage = primary_result.get("usage", {})
        
        # Strategy 2: Consult-then-decide (0.5 <= confidence < 0.8 OR high-risk)
        elif (0.5 <= confidence < 0.8) or is_high_risk:
            if not reviewer_assistant_id:
                # Fallback to primary only if reviewer not available
                thread_id = _get_or_create_thread(label)
                add_message(thread_id, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(thread_id, primary_assistant_id)
                total_usage = primary_result.get("usage", {})
            else:
                # Run primary first
                thread_id_primary = _get_or_create_thread(label)
                add_message(thread_id_primary, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(thread_id_primary, primary_assistant_id)
                
                # Then ask reviewer to critique (Devil's Advocate pass)
                thread_id_reviewer = _get_or_create_thread(top2_label)
                primary_answer = primary_result.get("answer", "")
                primary_bullets = primary_result.get("bullets", [])
                
                # Construct critique prompt
                critique_prompt = f"""The following is a response from {label.capitalize()}Advisor to the question: "{user_msg}"

**{label.capitalize()}Advisor's Response:**
{primary_answer}"""
                
                if primary_bullets:
                    critique_prompt += "\n\n**Key Points:**\n"
                    for bullet in primary_bullets:
                        critique_prompt += f"- {bullet}\n"
                
                critique_prompt += f"""

Please provide a "Devil's Advocate" critique from a {top2_label} perspective. Specifically:
1. What risks, gaps, or alternative perspectives should be considered?
2. What might be missing from this analysis?
3. What additional factors from your domain expertise should be taken into account?
4. Are there any potential pitfalls or concerns?

Be constructive and specific. Focus on adding value, not just criticizing."""
                
                add_message(thread_id_reviewer, "user", critique_prompt, file_ids=file_ids if file_ids else None)
                reviewer_result = run_assistant_structured(thread_id_reviewer, reviewer_assistant_id)
                
                # Aggregate usage
                primary_usage = primary_result.get("usage", {})
                reviewer_usage = reviewer_result.get("usage", {})
                total_usage = {
                    "input_tokens": primary_usage.get("input_tokens", 0) + reviewer_usage.get("input_tokens", 0),
                    "output_tokens": primary_usage.get("output_tokens", 0) + reviewer_usage.get("output_tokens", 0),
                    "total_tokens": primary_usage.get("total_tokens", 0) + reviewer_usage.get("total_tokens", 0)
                }
        
        # Strategy 3: Parallel ensemble (confidence < 0.5 OR margin < 0.15)
        else:
            if not reviewer_assistant_id:
                # Fallback to primary only
                thread_id = _get_or_create_thread(label)
                add_message(thread_id, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(thread_id, primary_assistant_id)
                total_usage = primary_result.get("usage", {})
            else:
                # Run both in parallel (sequentially for now, but could be parallelized)
                thread_id_primary = _get_or_create_thread(label)
                add_message(thread_id_primary, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(thread_id_primary, primary_assistant_id)
                
                thread_id_reviewer = _get_or_create_thread(top2_label)
                add_message(thread_id_reviewer, "user", user_msg, file_ids=file_ids if file_ids else None)
                reviewer_result = run_assistant_structured(thread_id_reviewer, reviewer_assistant_id)
                
                # Aggregate usage
                primary_usage = primary_result.get("usage", {})
                reviewer_usage = reviewer_result.get("usage", {})
                total_usage = {
                    "input_tokens": primary_usage.get("input_tokens", 0) + reviewer_usage.get("input_tokens", 0),
                    "output_tokens": primary_usage.get("output_tokens", 0) + reviewer_usage.get("output_tokens", 0),
                    "total_tokens": primary_usage.get("total_tokens", 0) + reviewer_usage.get("total_tokens", 0)
                }
        
        # Step 4: Check if both assistants retrieved nothing (for ensemble cases)
        if reviewer_result and not _has_grounded_content(primary_result) and not _has_grounded_content(reviewer_result):
            return {
                "thread_id": _get_or_create_thread(label),
                "answer": "I need a bit more context to help you effectively. Could you clarify:\n- What specific aspect are you most interested in?\n- Are you looking for technical guidance, marketing strategy, or investor/fundraising advice?\n- What's your current situation or challenge?",
                "sources": [],
                "raw_text": "",
                "bullets": None,
                "images": [],
                "usage": total_usage,
                "routing": routing
            }
        
        # Step 5: Compose response
        if reviewer_result:
            # Determine if this was consult-then-decide (critique) or parallel ensemble (independent)
            # Check if reviewer was asked to critique by looking at routing strategy
            is_consult_then_decide = (0.5 <= confidence < 0.8) or is_high_risk
            
            primary_answer = primary_result.get("answer", "")
            reviewer_answer = reviewer_result.get("answer", "")
            
            # Combine sources
            all_sources = primary_result.get("sources", []) + reviewer_result.get("sources", [])
            # Dedupe sources by file_id
            seen_file_ids = set()
            unique_sources = []
            for source in all_sources:
                file_id = source.get("file_id")
                if file_id and file_id not in seen_file_ids:
                    seen_file_ids.add(file_id)
                    unique_sources.append(source)
            
            # Combine images
            all_images = primary_result.get("images", []) + reviewer_result.get("images", [])
            
            # Compose answer differently based on strategy
            if is_consult_then_decide:
                # Consult-then-decide: Primary answer + critique
                composed_answer = f"**{label.capitalize()}Advisor Response:**\n{primary_answer}\n\n"
                composed_answer += f"**{top2_label.capitalize()}Advisor Critique (Devil's Advocate):**\n{reviewer_answer}"
            else:
                # Parallel ensemble: Both perspectives equally
                composed_answer = f"**{label.capitalize()}Advisor Perspective:**\n{primary_answer}\n\n"
                composed_answer += f"**{top2_label.capitalize()}Advisor Perspective:**\n{reviewer_answer}"
            
            answer = composed_answer
            sources = unique_sources
            images = all_images
            bullets = primary_result.get("bullets")  # Use primary bullets if available
        else:
            answer = primary_result.get("answer", "")
            sources = primary_result.get("sources", [])
            images = primary_result.get("images", [])
            bullets = primary_result.get("bullets")
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Record metrics
        metrics.record_request(
            latency_ms=latency_ms,
            input_tokens=total_usage.get("input_tokens"),
            output_tokens=total_usage.get("output_tokens"),
            total_tokens=total_usage.get("total_tokens"),
            error=False
        )
        
        return {
            "thread_id": _get_or_create_thread(label),
            "answer": answer,
            "sources": sources,
            "raw_text": primary_result.get("raw_text", "") if primary_result else "",
            "bullets": bullets,
            "images": images,
            "usage": total_usage,
            "routing": routing  # Include routing info for debugging
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
