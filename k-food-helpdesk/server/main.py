import os
import time
from collections import deque
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from rag import top_k
from prompts import SYSTEM_PROMPT

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()

# Metrics tracking
_metrics = {
    "total_requests": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "latencies": deque(maxlen=1000)  # Keep last 1000 latencies for p95 calculation
}

def _calculate_p95(latencies):
    """Calculate 95th percentile latency."""
    if not latencies:
        return 0.0
    sorted_latencies = sorted(latencies)
    index = int(len(sorted_latencies) * 0.95)
    return sorted_latencies[index] if index < len(sorted_latencies) else sorted_latencies[-1]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatReq(BaseModel):
    message: str
    session_id: str | None = None

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/search")
def search(req: ChatReq):
    snips = top_k(req.message, 4, session_id=req.session_id)
    return {"results": [{"source": s, "content": c} for c, s in snips]}

@app.post("/chat")
def chat(req: ChatReq):
    start_time = time.time()
    
    snips = top_k(req.message, 4, session_id=req.session_id)
    context = "\n\n".join([f"[{s}]\n{c}" for c, s in snips])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": f"Context:\n{context}"},
        {"role": "user", "content": req.message},
    ]
    out = client.chat.completions.create(model="gpt-4-turbo", messages=messages, temperature=0.2)
    
    # Track metrics
    latency = time.time() - start_time
    _metrics["total_requests"] += 1
    _metrics["total_input_tokens"] += out.usage.prompt_tokens
    _metrics["total_output_tokens"] += out.usage.completion_tokens
    _metrics["latencies"].append(latency)
    
    # Deduplicate sources while preserving order
    sources = []
    seen = set()
    for _, s in snips:
        if s not in seen:
            sources.append(s)
            seen.add(s)
    return {"answer": out.choices[0].message.content, "sources": sources}

@app.get("/metrics")
def metrics():
    """Returns metrics: request counts, token usage, and p95 latency."""
    p95_latency = _calculate_p95(_metrics["latencies"])
    total_tokens = _metrics["total_input_tokens"] + _metrics["total_output_tokens"]
    
    return {
        "total_requests": _metrics["total_requests"],
        "total_tokens": total_tokens,
        "total_input_tokens": _metrics["total_input_tokens"],
        "total_output_tokens": _metrics["total_output_tokens"],
        "tokens_per_request": total_tokens / _metrics["total_requests"] if _metrics["total_requests"] > 0 else 0,
        "p95_latency_seconds": round(p95_latency, 4),
        "p95_latency_ms": round(p95_latency * 1000, 2)
    }
