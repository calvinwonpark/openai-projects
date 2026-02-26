import json
import os
import re
import time
from collections import deque
from typing import Any, Dict, List
from uuid import uuid4
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from rag import top_k
from prompts import SYSTEM_PROMPT
from pii import detect_and_redact

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.1"))

# Metrics tracking
_metrics = {
    "total_requests": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "latencies": deque(maxlen=1000)  # Keep last 1000 latencies for p95 calculation
}

_trace_store: Dict[str, Dict[str, Any]] = {}
_trace_order = deque(maxlen=200)

MODEL_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "language": {"type": "string", "enum": ["ko", "en"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "doc_id": {"type": "integer"},
                    "source": {"type": "string"},
                    "chunk": {"type": ["integer", "null"]},
                    "quote": {"type": "string"},
                },
                "required": ["doc_id", "source", "chunk", "quote"],
            },
        },
        "refusal": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "is_refusal": {"type": "boolean"},
                "reason": {"type": ["string", "null"]},
            },
            "required": ["is_refusal", "reason"],
        },
    },
    "required": ["answer", "language", "confidence", "citations", "refusal"],
}


def _calculate_p95(latencies):
    """Calculate 95th percentile latency."""
    if not latencies:
        return 0.0
    sorted_latencies = sorted(latencies)
    index = int(len(sorted_latencies) * 0.95)
    return sorted_latencies[index] if index < len(sorted_latencies) else sorted_latencies[-1]


def _detect_language(text: str) -> str:
    return "ko" if re.search(r"[\uac00-\ud7a3]", text or "") else "en"


def _build_reference_block(snips: List[Dict[str, Any]]) -> str:
    lines = ["REFERENCE_START"]
    for item in snips:
        lines.append(
            (
                f"- doc_id={item['doc_id']} source={item['source']} chunk={item['chunk']} "
                f"score={item['score']:.6f}\n{item['content']}"
            )
        )
    lines.append("REFERENCE_END")
    return "\n".join(lines)


def _fallback_payload(user_text: str) -> Dict[str, Any]:
    lang = _detect_language(user_text)
    answer = (
        "죄송하지만 제공된 REFERENCE에서 답변 근거를 찾을 수 없습니다."
        if lang == "ko"
        else "Sorry, I cannot answer from the provided REFERENCE."
    )
    return {
        "answer": answer,
        "language": lang,
        "confidence": 0.0,
        "citations": [],
        "refusal": {"is_refusal": True, "reason": "INSUFFICIENT_CONTEXT"},
    }


def _validated_payload(model_payload: Dict[str, Any], snips: List[Dict[str, Any]], user_text: str) -> Dict[str, Any]:
    payload = _fallback_payload(user_text)
    payload.update(
        {
            "answer": str(model_payload.get("answer", payload["answer"])),
            "language": model_payload.get("language", payload["language"]),
            "confidence": float(model_payload.get("confidence", 0.0)),
            "refusal": model_payload.get("refusal", payload["refusal"]),
        }
    )
    payload["confidence"] = max(0.0, min(1.0, payload["confidence"]))
    if payload["language"] not in {"ko", "en"}:
        payload["language"] = _detect_language(user_text)

    allowed = {(i["doc_id"], i["source"], i["chunk"]) for i in snips}
    content_lookup = {
        (i["doc_id"], i["source"], i["chunk"]): str(i.get("content", ""))
        for i in snips
    }
    safe_citations = []
    for cit in model_payload.get("citations", []):
        try:
            doc_id = int(cit.get("doc_id"))
            source = str(cit.get("source", ""))
            chunk = cit.get("chunk")
            chunk = int(chunk) if isinstance(chunk, int) else None
            quote = str(cit.get("quote", "")).strip()
            key = (doc_id, source, chunk)
            content = content_lookup.get(key, "")
            if key in allowed and quote and quote in content:
                safe_citations.append(
                    {"doc_id": doc_id, "source": source, "chunk": chunk, "quote": quote[:300]}
                )
        except Exception:
            continue
    payload["citations"] = safe_citations

    refusal = payload.get("refusal", {})
    is_refusal = bool(refusal.get("is_refusal"))
    reason = refusal.get("reason")
    if is_refusal and reason is None:
        reason = "INSUFFICIENT_CONTEXT"
    if not is_refusal:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", payload["answer"].strip()) if p.strip()]
        paragraph_count = len(paragraphs)
        required_citations = max(1, min(paragraph_count, 3))
        if len(payload["citations"]) < required_citations:
            return _fallback_payload(user_text)

    payload["refusal"] = {"is_refusal": is_refusal, "reason": reason}
    return payload


def _store_trace(request_id: str, trace: Dict[str, Any]) -> None:
    if len(_trace_order) >= _trace_order.maxlen:
        oldest = _trace_order.popleft()
        _trace_store.pop(oldest, None)
    _trace_order.append(request_id)
    _trace_store[request_id] = trace


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
    return {
        "results": [
            {
                "doc_id": s["doc_id"],
                "source": s["source"],
                "content": s["content"],
                "score": s["score"],
                "chunk": s["chunk"],
            }
            for s in snips
        ]
    }

@app.post("/chat")
def chat(req: ChatReq):
    request_id = str(uuid4())
    start_time = time.time()

    redacted_message, pii_detected, pii_redacted = detect_and_redact(req.message)
    snips = top_k(redacted_message, 4, session_id=req.session_id)
    context_block = _build_reference_block(snips)
    system_content = f"{SYSTEM_PROMPT}\n\n{context_block}"
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": redacted_message},
    ]

    try:
        out = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=CHAT_TEMPERATURE,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "grounded_helpdesk_response",
                    "strict": True,
                    "schema": MODEL_JSON_SCHEMA,
                },
            },
        )
    except Exception:
        out = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            temperature=CHAT_TEMPERATURE,
            response_format={"type": "json_object"},
        )

    raw_content = out.choices[0].message.content or "{}"
    try:
        model_payload = json.loads(raw_content)
    except json.JSONDecodeError:
        model_payload = _fallback_payload(redacted_message)

    answer_payload = _validated_payload(model_payload, snips, redacted_message)

    # Track metrics
    latency = time.time() - start_time
    latency_ms = int(latency * 1000)
    input_tokens = out.usage.prompt_tokens if out.usage else None
    output_tokens = out.usage.completion_tokens if out.usage else None
    _metrics["total_requests"] += 1
    _metrics["total_input_tokens"] += input_tokens or 0
    _metrics["total_output_tokens"] += output_tokens or 0
    _metrics["latencies"].append(latency)

    retrieval_trace = {
        "k": 4,
        "results": [
            {
                "doc_id": s["doc_id"],
                "source": s["source"],
                "score": s["score"],
                "chunk": s["chunk"],
            }
            for s in snips
        ],
    }

    response_payload = {
        "request_id": request_id,
        "answer": answer_payload["answer"],
        "language": answer_payload["language"],
        "confidence": answer_payload["confidence"],
        "citations": answer_payload["citations"],
        "refusal": answer_payload["refusal"],
        "pii": {"detected": pii_detected, "redacted": pii_redacted},
        "retrieval_trace": retrieval_trace,
        "usage": {
            "model": MODEL_NAME,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        },
    }

    _store_trace(
        request_id,
        {
            "request_id": request_id,
            "session_id": req.session_id,
            "redacted_user_text": redacted_message,
            "response": response_payload,
        },
    )

    print(
        json.dumps(
            {
                "request_id": request_id,
                "session_id": req.session_id,
                "model": MODEL_NAME,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "retrieved_doc_ids": [s["doc_id"] for s in snips],
                "refusal.is_refusal": response_payload["refusal"]["is_refusal"],
                "pii.detected": pii_detected,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    return response_payload


@app.get("/debug/trace/{request_id}")
def get_trace(request_id: str):
    trace = _trace_store.get(request_id)
    if not trace:
        raise HTTPException(status_code=404, detail="request_id not found")
    return trace

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
