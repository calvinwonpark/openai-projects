import json
import os
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

from pii import detect_and_redact
from safety import classify_risk

load_dotenv()

app = FastAPI()

CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4o-mini")
REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime")
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.2"))
MAX_TURNS_STORED = int(os.getenv("MAX_TURNS_STORED", "12"))
MAX_INPUT_TOKENS = int(os.getenv("MAX_INPUT_TOKENS", "1200"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "300"))
STT_CONFIDENCE_THRESHOLD = float(os.getenv("STT_CONFIDENCE_THRESHOLD", "0.7"))
LLM_LATENCY_BUDGET_MS = int(os.getenv("LLM_LATENCY_BUDGET_MS", "2500"))
TRACE_STORE_MAX_TURNS = 200
SUMMARY_CHAR_BUDGET = 1500
APPROX_CHARS_PER_TOKEN = 4

# CORS (fine for local dev; you can tighten later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (index.html + realtime.js)
app.mount("/static", StaticFiles(directory="static"), name="static")

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
_session_state: Dict[str, Dict[str, Any]] = {}
_trace_by_session: Dict[str, List[Dict[str, Any]]] = {}
_trace_order = deque()
_metrics = {
    "total_turns": 0,
    "refusal_turns": 0,
    "text_only_turns": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
}


class ChatTextReq(BaseModel):
    transcript: str
    session_id: Optional[str] = None
    stt_confidence: Optional[float] = None
    tts_enabled: bool = False
    simulate_tts_failure: bool = False


class LatencyPayload(BaseModel):
    stt: Optional[int] = None
    llm: Optional[int] = None
    tts: Optional[int] = None
    end_to_end: Optional[int] = None


class SafetyPayload(BaseModel):
    level: str
    categories: List[str] = []


class PiiPayload(BaseModel):
    detected: bool
    redacted: bool


class TelemetryReq(BaseModel):
    session_id: str
    event: str
    turn_id: int
    latency_ms: LatencyPayload
    safety: SafetyPayload
    pii: PiiPayload
    mode: str
    notes: Optional[Dict[str, Any]] = None


def _detect_language(text: str) -> str:
    return "ko" if re.search(r"[\uac00-\ud7a3]", text or "") else "en"


def _should_ask_clarifying(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if len(lowered) <= 12:
        return True
    markers = [
        "i don't get it",
        "help me",
        "what about this",
        "can you explain",
        "not sure",
        "모르겠",
        "이거 뭐",
        "도와줘",
        "설명해줘",
    ]
    return any(marker in lowered for marker in markers)


def _clarifying_prompt(language: str) -> str:
    if language == "ko":
        return "좋아요. 어느 과목의 어떤 부분이 어려운지, 문제 문장을 함께 알려주실 수 있나요?"
    return "Sure. Which subject and exact part are you stuck on? Please share the problem statement too."


def _safety_refusal(language: str, categories: List[str]) -> str:
    if "self_harm" in categories:
        if language == "ko":
            return "지금 매우 힘든 상황으로 들립니다. 저는 그 요청을 도와드릴 수 없어요. 즉시 가까운 응급실이나 지역 위기 상담 번호에 연락해 주세요."
        return "I am sorry you're going through this. I cannot help with that request. Please contact local emergency services or a crisis hotline right now."
    if language == "ko":
        return "그 요청은 안전 정책상 도와드릴 수 없습니다. 일반적인 학습 설명이나 개념 정리는 도와드릴 수 있어요."
    return "I cannot help with that request due to safety policy. I can still help with general learning explanations and concepts."


def _fallback_tutor_response(language: str) -> str:
    if language == "ko":
        return "좋아요. 핵심 개념부터 차근차근 설명해 드릴게요. 문제 문장이나 조건을 보내주시면 단계별로 도와드릴 수 있어요."
    return "Great, let's break it down step by step. Share the full problem text and I can guide you through it."


def _compact_context(session: Dict[str, Any]) -> None:
    turns = session["turns"]
    if len(turns) <= MAX_TURNS_STORED:
        return
    overflow = turns[:-MAX_TURNS_STORED]
    session["turns"] = turns[-MAX_TURNS_STORED:]
    summary_bits = []
    for item in overflow:
        snippet = str(item.get("content", ""))[:100]
        summary_bits.append(f"{item.get('role', 'user')}: {snippet}")
    merged = (session.get("summary", "") + " " + " | ".join(summary_bits)).strip()
    session["summary"] = merged[-SUMMARY_CHAR_BUDGET:]


def _trim_messages(messages: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
    max_chars = max_tokens * APPROX_CHARS_PER_TOKEN
    total_chars = sum(len(m.get("content", "")) for m in messages)
    while total_chars > max_chars and len(messages) > 2:
        # Drop oldest conversational turn first, preserve system prompt.
        del messages[1]
        total_chars = sum(len(m.get("content", "")) for m in messages)
    return messages


def _store_trace(session_id: str, trace_item: Dict[str, Any]) -> None:
    if session_id not in _trace_by_session:
        _trace_by_session[session_id] = []
    _trace_by_session[session_id].append(trace_item)
    _trace_order.append((session_id, trace_item["request_id"]))
    while len(_trace_order) > TRACE_STORE_MAX_TURNS:
        old_session_id, old_request_id = _trace_order.popleft()
        turns = _trace_by_session.get(old_session_id, [])
        _trace_by_session[old_session_id] = [t for t in turns if t["request_id"] != old_request_id]
        if not _trace_by_session[old_session_id]:
            _trace_by_session.pop(old_session_id, None)


def _build_tutor_messages(language: str, session: Dict[str, Any], transcript: str) -> List[Dict[str, str]]:
    system_prompt = (
        "You are a concise realtime tutor. Keep explanations practical and short. "
        "If the user is unclear, ask one clarifying question first. "
        f"Respond only in {'Korean' if language == 'ko' else 'English'}."
    )
    messages = [{"role": "system", "content": system_prompt}]
    if session.get("summary"):
        messages.append({"role": "system", "content": f"Summary of earlier turns: {session['summary']}"})
    messages.extend(session["turns"])
    messages.append({"role": "user", "content": transcript})
    return _trim_messages(messages, MAX_INPUT_TOKENS)


def _synthesize_tts_or_raise(text: str, should_fail: bool) -> None:
    if should_fail:
        raise RuntimeError("TTS backend unavailable")
    _ = text  # Placeholder hook for actual TTS integration.


@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/realtime-token")
def get_realtime_token():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Missing OPENAI_API_KEY"}, status_code=500)

    body = {"session": {"type": "realtime", "model": REALTIME_MODEL}}

    try:
        resp = httpx.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
    except Exception as e:
        return JSONResponse({"error": "Failed to call client_secrets", "details": str(e)}, status_code=500)

    if resp.status_code != 200:
        return JSONResponse({"error": "Failed to create client secret", "details": resp.text}, status_code=500)

    data = resp.json()
    client_secret = data.get("client_secret", {}).get("value") or data.get("value")
    if not client_secret:
        return JSONResponse({"error": "client_secret not in response", "raw": data}, status_code=500)
    return {"client_secret": client_secret, "realtime_model": REALTIME_MODEL}


@app.post("/chat_text")
def chat_text(req: ChatTextReq):
    started = time.perf_counter()
    session_id = req.session_id or str(uuid4())
    request_id = str(uuid4())
    language = _detect_language(req.transcript)

    session = _session_state.setdefault(session_id, {"turn_counter": 0, "summary": "", "turns": []})
    session["turn_counter"] += 1
    turn_id = session["turn_counter"]

    pii = detect_and_redact(req.transcript)
    redacted_transcript = str(pii["redacted_text"])
    safety = classify_risk(redacted_transcript)

    mode = "normal"
    refusal = {"is_refusal": False, "reason": None}
    ask_clarifying = False
    answer = ""

    stt_latency_ms = 0
    llm_latency_ms = 0
    tts_latency_ms = 0
    input_tokens = 0
    output_tokens = 0

    if req.stt_confidence is not None and req.stt_confidence < STT_CONFIDENCE_THRESHOLD:
        mode = "text_only"
        ask_clarifying = True
        answer = (
            "I may have misheard you. Please repeat slowly and include the exact question."
            if language == "en"
            else "제가 정확히 못 들었을 수 있어요. 천천히 다시 말씀해 주시고 질문 문장을 함께 알려주세요."
        )
    elif safety["level"] == "high":
        mode = "refusal"
        refusal = {"is_refusal": True, "reason": "SAFETY_POLICY"}
        answer = _safety_refusal(language, safety["categories"])
    elif _should_ask_clarifying(redacted_transcript):
        mode = "text_only"
        ask_clarifying = True
        answer = _clarifying_prompt(language)
    else:
        _compact_context(session)
        messages = _build_tutor_messages(language, session, redacted_transcript)
        llm_started = time.perf_counter()
        if _client is not None:
            try:
                out = _client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=messages,
                    temperature=CHAT_TEMPERATURE,
                    max_tokens=MAX_OUTPUT_TOKENS,
                )
                answer = (out.choices[0].message.content or "").strip() or _fallback_tutor_response(language)
                input_tokens = out.usage.prompt_tokens if out.usage else 0
                output_tokens = out.usage.completion_tokens if out.usage else 0
            except Exception:
                answer = _fallback_tutor_response(language)
        else:
            answer = _fallback_tutor_response(language)
        llm_latency_ms = int((time.perf_counter() - llm_started) * 1000)
        if llm_latency_ms > LLM_LATENCY_BUDGET_MS:
            mode = "text_only"

    if req.tts_enabled:
        tts_started = time.perf_counter()
        try:
            _synthesize_tts_or_raise(answer, req.simulate_tts_failure)
        except Exception:
            mode = "text_only"
        tts_latency_ms = int((time.perf_counter() - tts_started) * 1000)

    if not refusal["is_refusal"]:
        session["turns"].append({"role": "user", "content": redacted_transcript})
        session["turns"].append({"role": "assistant", "content": answer})
        _compact_context(session)

    end_to_end_ms = int((time.perf_counter() - started) * 1000)
    _metrics["total_turns"] += 1
    _metrics["total_input_tokens"] += input_tokens
    _metrics["total_output_tokens"] += output_tokens
    if refusal["is_refusal"]:
        _metrics["refusal_turns"] += 1
    if mode == "text_only":
        _metrics["text_only_turns"] += 1

    trace_item = {
        "request_id": request_id,
        "turn_id": turn_id,
        "redacted_transcript": redacted_transcript,
        "response_text": answer,
        "language": language,
        "mode": mode,
        "safety": safety,
        "pii": {"detected": pii["detected"], "redacted": pii["redacted"]},
        "latency_ms": {
            "stt": stt_latency_ms,
            "llm": llm_latency_ms,
            "tts": tts_latency_ms,
            "end_to_end": end_to_end_ms,
        },
        "tokens": {"input": input_tokens, "output": output_tokens},
        "refusal": refusal,
    }
    _store_trace(session_id, trace_item)

    print(
        json.dumps(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": session_id,
                "turn_id": turn_id,
                "request_id": request_id,
                "latency_ms": trace_item["latency_ms"],
                "model": CHAT_MODEL,
                "tokens": trace_item["tokens"],
                "safety": safety,
                "pii": trace_item["pii"],
                "mode": mode,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    return {
        "request_id": request_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "answer": answer,
        "language": language,
        "refusal": refusal,
        "safety": safety,
        "pii": trace_item["pii"],
        "mode": mode,
        "ask_clarifying": ask_clarifying,
        "latency_ms": trace_item["latency_ms"],
        "tokens": trace_item["tokens"],
    }


@app.post("/telemetry")
def telemetry(req: TelemetryReq):
    request_id = str(uuid4())
    trace_item = {
        "request_id": request_id,
        "event": req.event,
        "turn_id": req.turn_id,
        "mode": req.mode,
        "safety": {"level": req.safety.level, "categories": req.safety.categories},
        "pii": {"detected": req.pii.detected, "redacted": req.pii.redacted},
        "latency_ms": {
            "stt": req.latency_ms.stt,
            "llm": req.latency_ms.llm,
            "tts": req.latency_ms.tts,
            "end_to_end": req.latency_ms.end_to_end,
        },
        "notes": req.notes or {},
    }
    _store_trace(req.session_id, trace_item)
    print(
        json.dumps(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": req.session_id,
                "turn_id": req.turn_id,
                "request_id": request_id,
                "latency_ms": trace_item["latency_ms"],
                "model": REALTIME_MODEL,
                "tokens": {"input": None, "output": None},
                "safety": trace_item["safety"],
                "pii": trace_item["pii"],
                "mode": req.mode,
                "event": req.event,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return {"ok": True, "request_id": request_id}


@app.get("/debug/trace/{session_id}")
def get_trace(session_id: str):
    traces = _trace_by_session.get(session_id)
    if traces is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    return {"session_id": session_id, "turns": traces}


@app.get("/metrics")
def metrics():
    total_turns = _metrics["total_turns"]
    return {
        "total_turns": total_turns,
        "refusal_turns": _metrics["refusal_turns"],
        "text_only_turns": _metrics["text_only_turns"],
        "total_input_tokens": _metrics["total_input_tokens"],
        "total_output_tokens": _metrics["total_output_tokens"],
        "tokens_per_turn": (
            (_metrics["total_input_tokens"] + _metrics["total_output_tokens"]) / total_turns
            if total_turns
            else 0
        ),
    }
