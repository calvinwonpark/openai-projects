import os
import time
import json
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Depends, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from pydantic import BaseModel

from app.openai_client import create_thread, add_message, run_assistant_structured, run_assistant_stream, upload_file, download_file_bytes, download_container_file_bytes, get_response_config
from app.openai_client import get_schema_violation_count
from app.storage import get_ids, get_response_ids, get_all_response_ids
# Note: create_thread, run_assistant_structured, run_assistant_stream are compatibility wrappers
# that map to Responses API functions (create_conversation, run_response, etc.)
from app.router import route_query, heuristic_classify, is_high_risk
from app.metrics import metrics
from app.tool_schema import validate_tool_args, tool_count, tool_names, schema_error_payload
from app.product_card import (
    get_product_card, get_all_product_cards, create_or_update_product_card,
    detect_deictic_references, rewrite_message_with_product_card,
    format_product_card_for_message, auto_create_or_update_product_card
)

import redis.asyncio as redis
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

load_dotenv()
app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Conversation management (Responses API uses conversations instead of threads)
CONVERSATIONS = {}  # per-session demo (in-memory) - stores conversation_id per session
CONVERSATIONS_BY_LABEL = {}  # Stores conversation_id per response label per session
SESSION_PRODUCT_IDS = {}  # Track active product_id per session (IP-based for now)
SESSION_PRODUCED_FILES = {}  # Track files produced in previous turns per session
CONVERSATION_UPLOADED_FILES = {}  # Track files uploaded to each conversation: {conversation_id: [file_ids]}
SESSION_ANALYSIS_CONVERSATION = {}  # Shared analysis conversation for data flows (CSV/analysis iterations): {session_id: conversation_id}
SESSION_ANALYSIS_FILES = {}  # Track files in the shared analysis conversation: {session_id: [file_ids]}
ENTERPRISE_METRICS = {
    "schema_violations": 0,
}

# Legacy aliases for backward compatibility (deprecated - use CONVERSATIONS instead)
RESPONSES = CONVERSATIONS
RESPONSES_BY_LABEL = CONVERSATIONS_BY_LABEL
THREADS = CONVERSATIONS
THREADS_BY_ASSISTANT = CONVERSATIONS_BY_LABEL
RESPONSE_UPLOADED_FILES = CONVERSATION_UPLOADED_FILES
THREAD_UPLOADED_FILES = CONVERSATION_UPLOADED_FILES
SESSION_ANALYSIS_RESPONSE = SESSION_ANALYSIS_CONVERSATION
SESSION_ANALYSIS_THREAD = SESSION_ANALYSIS_CONVERSATION

async def client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    cf = req.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    return req.client.host if req.client else "unknown"

async def get_session_id(req: Request) -> str:
    """Get session identifier (using IP for now, could use session cookie)."""
    ip = await client_ip(req)
    return ip if ip else "default"


def _estimate_cost_usd(input_tokens: int, output_tokens: int, model: str = None) -> float:
    # Simple model-agnostic estimate for telemetry (template value, not billing source-of-truth).
    in_rate_per_million = 5.0
    out_rate_per_million = 15.0
    model_name = (model or os.getenv("OPENAI_MODEL", "gpt-4o")).lower()
    if "mini" in model_name:
        in_rate_per_million = 0.2
        out_rate_per_million = 0.6
    return round((input_tokens / 1_000_000) * in_rate_per_million + (output_tokens / 1_000_000) * out_rate_per_million, 6)


def _log_workflow_telemetry(
    workflow: str,
    tenant_id: str,
    route: str,
    latency_ms: float,
    tool_calls: int,
    tool_success: bool,
    schema_valid: bool,
    input_tokens: int,
    output_tokens: int,
    warning: Optional[str] = None,
):
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workflow": workflow,
        "tenant_id": tenant_id,
        "route": route,
        "latency_ms": round(latency_ms, 2),
        "tool_calls": tool_calls,
        "tool_success": tool_success,
        "schema_valid": schema_valid,
        "tokens": {"input": input_tokens, "output": output_tokens},
        "cost_estimate_usd": _estimate_cost_usd(input_tokens, output_tokens, os.getenv("OPENAI_MODEL", "gpt-4o")),
    }
    if warning:
        payload["warning"] = warning
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
        ),
        flush=True,
    )


def _deterministic_route(query: str) -> dict:
    label, confidence = heuristic_classify(query)
    fallback_top2 = "marketing" if label != "marketing" else "tech"
    return {
        "label": label,
        "confidence": confidence,
        "top2_label": fallback_top2,
        "margin": max(0.0, min(1.0, confidence - 0.2)),
        "is_high_risk": is_high_risk(query),
    }


def _should_refuse(message: str) -> bool:
    m = (message or "").lower()
    refusal_markers = ["malware", "exploit", "fraud", "illegal", "weapon", "violence", "violent", "extortion"]
    return any(k in m for k in refusal_markers)


def _tenant_scope_key(tenant_id: str, key: str) -> str:
    return f"{tenant_id}:{key}"


def _resolve_tools_for_response(response_id: Optional[str], tools_override: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if tools_override is not None:
        return tools_override
    if not response_id:
        return []
    cfg = get_response_config(response_id) or {}
    tools = cfg.get("tools")
    return tools if isinstance(tools, list) else []

def get_active_product_id(session_id: str) -> Optional[str]:
    """Get active product ID for session."""
    return SESSION_PRODUCT_IDS.get(session_id)

def set_active_product_id(session_id: str, product_id: str):
    """Set active product ID for session."""
    SESSION_PRODUCT_IDS[session_id] = product_id

def track_produced_files(session_id: str, file_ids: List[str]):
    """Track files produced in response outputs (e.g., charts from code_interpreter)."""
    if session_id not in SESSION_PRODUCED_FILES:
        SESSION_PRODUCED_FILES[session_id] = []
    existing = set(SESSION_PRODUCED_FILES[session_id])
    new_files = [fid for fid in file_ids if fid not in existing]
    SESSION_PRODUCED_FILES[session_id].extend(new_files)

def get_produced_files(session_id: str) -> List[str]:
    """Get files produced in previous turns."""
    return SESSION_PRODUCED_FILES.get(session_id, [])

def track_conversation_files(conversation_id: str, file_ids: List[str]):
    """Track files uploaded to a specific conversation."""
    if conversation_id not in CONVERSATION_UPLOADED_FILES:
        CONVERSATION_UPLOADED_FILES[conversation_id] = []
    existing = set(CONVERSATION_UPLOADED_FILES[conversation_id])
    new_files = [fid for fid in file_ids if fid not in existing]
    CONVERSATION_UPLOADED_FILES[conversation_id].extend(new_files)

def get_conversation_files(conversation_id: str) -> List[str]:
    """Get files previously uploaded to a conversation."""
    return CONVERSATION_UPLOADED_FILES.get(conversation_id, [])

# Legacy aliases for backward compatibility
def track_thread_files(conversation_id: str, file_ids: List[str]):
    """Legacy alias - use track_conversation_files instead."""
    return track_conversation_files(conversation_id, file_ids)

def get_thread_files(conversation_id: str) -> List[str]:
    """Legacy alias - use get_conversation_files instead."""
    return get_conversation_files(conversation_id)

def detect_data_reference(user_message: str) -> bool:
    """Detect if user message references data/files from previous conversation."""
    data_keywords = [
        "the data", "this data", "that data", "the file", "this file", "that file",
        "the csv", "this csv", "that csv", "the chart", "this chart", "that chart",
        "the visualization", "this visualization", "that visualization",
        "the graph", "this graph", "that graph", "the results", "these results",
        "the stats", "these stats", "the metrics", "these metrics",
        "the numbers", "these numbers", "the analysis", "this analysis",
        "q1", "q2", "q3", "q4", "quarter", "progress", "targets", "target",
        "best", "worst", "highest", "lowest", "top", "bottom"
    ]
    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in data_keywords)

def is_data_analysis_flow(user_message: str, has_files: bool) -> bool:
    """
    Detect if this is a data analysis flow (iterating on CSV/data files).
    Returns True if user is asking about data analysis, visualizations, or has uploaded data files.
    """
    analysis_keywords = [
        "visualize", "chart", "graph", "plot", "analysis", "analyze",
        "calculate", "compute", "metrics", "kpi", "stats", "statistics",
        "data", "csv", "excel", "spreadsheet", "numbers", "figures"
    ]
    message_lower = user_message.lower()
    has_analysis_keywords = any(keyword in message_lower for keyword in analysis_keywords)
    
    # If user uploaded files (CSV, Excel) or is asking about data analysis, it's a data flow
    return has_files or (has_analysis_keywords and detect_data_reference(user_message))

def get_or_create_analysis_conversation(session_id: str, tenant_id: str = "default") -> str:
    """Get or create a shared analysis conversation for data flows."""
    scoped = _tenant_scope_key(tenant_id, session_id)
    if scoped not in SESSION_ANALYSIS_CONVERSATION:
        conversation = create_thread()  # create_thread creates a conversation in Responses API
        SESSION_ANALYSIS_CONVERSATION[scoped] = conversation.id
    return SESSION_ANALYSIS_CONVERSATION[scoped]

def track_analysis_files(session_id: str, file_ids: List[str], tenant_id: str = "default"):
    """Track files in the shared analysis conversation."""
    scoped = _tenant_scope_key(tenant_id, session_id)
    if scoped not in SESSION_ANALYSIS_FILES:
        SESSION_ANALYSIS_FILES[scoped] = []
    existing = set(SESSION_ANALYSIS_FILES[scoped])
    new_files = [fid for fid in file_ids if fid not in existing]
    SESSION_ANALYSIS_FILES[scoped].extend(new_files)

def get_analysis_files(session_id: str, tenant_id: str = "default") -> List[str]:
    """Get files from the shared analysis conversation."""
    scoped = _tenant_scope_key(tenant_id, session_id)
    return SESSION_ANALYSIS_FILES.get(scoped, [])

# Legacy alias for backward compatibility
def get_or_create_analysis_thread(session_id: str, tenant_id: str = "default") -> str:
    """Legacy alias - use get_or_create_analysis_conversation instead."""
    return get_or_create_analysis_conversation(session_id, tenant_id=tenant_id)

redis_client = None
_reset_limiter = RateLimiter(times=10, seconds=60)
_chat_limiter = RateLimiter(times=3, seconds=60)
_chat_text_limiter = RateLimiter(times=10, seconds=60)


async def _safe_limit_call(limiter: RateLimiter, request: Request, response: Response, route_name: str):
    try:
        await limiter(request=request, response=response)
    except Exception as exc:
        # Fail-open only for Redis snapshot MISCONF (local/dev reliability issue).
        if "MISCONF" in str(exc):
            print(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "workflow": "rate_limiter",
                        "route": route_name,
                        "warning": "rate_limiter_fail_open_redis_misconf",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return
        raise


async def safe_reset_rate_limit(request: Request, response: Response):
    await _safe_limit_call(_reset_limiter, request, response, "reset")


async def safe_chat_rate_limit(request: Request, response: Response):
    await _safe_limit_call(_chat_limiter, request, response, "chat")


async def safe_chat_text_rate_limit(request: Request, response: Response):
    await _safe_limit_call(_chat_text_limiter, request, response, "chat_text")


class WorkflowEvalReq(BaseModel):
    message: str
    tenant_id: str = "default"
    tools: Optional[List[Dict[str, Any]]] = None
    force_refusal: bool = False
    simulate_failure_mode: Optional[str] = None  # "timeout" | "tool_error"


class ChatTextReq(BaseModel):
    message: str
    tenant_id: str
    tools_override: Optional[List[Dict[str, Any]]] = None

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


def _default_tools_for_route(route_label: str) -> List[Dict[str, Any]]:
    if route_label in {"tech", "investor"}:
        return [
            {"type": "file_search", "vector_store_ids": ["vs-default"]},
            {"type": "code_interpreter", "container": {"type": "auto"}},
        ]
    return [{"type": "file_search", "vector_store_ids": ["vs-default"]}]


def _simulate_tool_call_with_retry(tool: Dict[str, Any], failure_mode: Optional[str]) -> Dict[str, Any]:
    attempts = 0
    while attempts < 2:
        attempts += 1
        if failure_mode == "timeout":
            if attempts == 1:
                continue
            raise TimeoutError("tool timed out")
        if failure_mode == "tool_error":
            if attempts == 1:
                continue
            raise RuntimeError("tool execution failed")
        return {"ok": True, "attempts": attempts, "tool": tool.get("type", "unknown")}
    return {"ok": False, "attempts": attempts, "tool": tool.get("type", "unknown")}


@app.post("/workflow/execute")
async def workflow_execute(req: WorkflowEvalReq):
    started = time.time()
    route = _deterministic_route(req.message)
    tools = req.tools if req.tools is not None else _default_tools_for_route(route["label"])
    schema_valid, schema_error = validate_tool_args(tools)
    if not schema_valid:
        ENTERPRISE_METRICS["schema_violations"] += 1
        payload = schema_error_payload("workflow_tools", schema_error)
        _log_workflow_telemetry(
            workflow="workflow_execute",
            tenant_id=req.tenant_id,
            route=route["label"],
            latency_ms=(time.time() - started) * 1000,
            tool_calls=tool_count(tools),
            tool_success=False,
            schema_valid=False,
            input_tokens=0,
            output_tokens=0,
        )
        return JSONResponse(payload, status_code=400)

    should_refuse = req.force_refusal or _should_refuse(req.message)
    refusal_reason = "SAFETY_REFUSAL" if should_refuse else None
    warning = None
    tool_success = True
    failure_mode = None

    if not should_refuse:
        for t in tools:
            try:
                _simulate_tool_call_with_retry(t, req.simulate_failure_mode)
            except TimeoutError:
                tool_success = False
                warning = "partial_response_due_to_tool_timeout"
                failure_mode = "timeout"
                break
            except Exception:
                tool_success = False
                failure_mode = "tool_failure"
                break

    answer = (
        "I cannot help with that request."
        if should_refuse
        else "Workflow executed successfully."
    )
    output_tokens = max(1, len(answer.split()))
    input_tokens = max(1, len(req.message.split()))
    _log_workflow_telemetry(
        workflow="workflow_execute",
        tenant_id=req.tenant_id,
        route=route["label"],
        latency_ms=(time.time() - started) * 1000,
        tool_calls=tool_count(tools),
        tool_success=tool_success,
        schema_valid=True,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return {
        "workflow": "workflow_execute",
        "route": route,
        "tool_names": tool_names(tools),
        "tool_calls": tool_count(tools),
        "tool_success": tool_success,
        "schema_valid": True,
        "schema_violation": False,
        "refusal": {"is_refusal": should_refuse, "reason": refusal_reason},
        "warning": warning,
        "failure_mode": failure_mode,
        "answer": answer,
        "tokens": {"input": input_tokens, "output": output_tokens},
        "cost_estimate_usd": _estimate_cost_usd(input_tokens, output_tokens, os.getenv("OPENAI_MODEL", "gpt-4o")),
    }


@app.post("/chat_text", dependencies=[Depends(safe_chat_text_rate_limit)])
async def chat_text(req: ChatTextReq):
    start_time = time.time()
    user_msg = req.message.strip()
    tenant_id = (req.tenant_id or "default").strip() or "default"
    if not user_msg:
        return JSONResponse({"error": "message required"}, status_code=400)

    telemetry_warning = None
    fallback_mode = None
    tool_success = True
    schema_valid = True

    if req.tools_override is not None:
        schema_ok, schema_error = validate_tool_args(req.tools_override)
        if not schema_ok:
            ENTERPRISE_METRICS["schema_violations"] += 1
            tool_success = False
            schema_valid = False
            telemetry_warning = "tool_schema_validation_error"
            latency_ms = int((time.time() - start_time) * 1000)
            _log_workflow_telemetry(
                workflow="chat_text",
                tenant_id=tenant_id,
                route="unknown",
                latency_ms=latency_ms,
                tool_calls=0,
                tool_success=False,
                schema_valid=False,
                input_tokens=0,
                output_tokens=0,
                warning=telemetry_warning,
            )
            return JSONResponse(
                {
                    "answer": "",
                    "routing": {},
                    "strategy": "winner_take_all",
                    "tool_names": [],
                    "schema_valid": schema_valid,
                    "refusal": {"is_refusal": True, "reason": "TOOL_SCHEMA_VALIDATION_ERROR"},
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model": os.getenv("OPENAI_MODEL", "gpt-4o")},
                    "telemetry": {
                        "latency_ms": latency_ms,
                        "cost_estimate_usd": 0.0,
                        "tenant_id": tenant_id,
                        "tool_success": False,
                        "warning": telemetry_warning,
                    },
                    "error": schema_error_payload("tools_override", schema_error),
                },
                status_code=400,
            )

    routing = route_query(user_msg)
    label = routing["label"]
    confidence = routing["confidence"]
    top2_label = routing["top2_label"]
    margin = routing["margin"]
    is_high_risk = routing["is_high_risk"]
    session_id = "chat_text"

    if _should_refuse(user_msg):
        tool_success = False
        fallback_mode = "safety_refusal"
        telemetry_warning = "safety_refusal"
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model": os.getenv("OPENAI_MODEL", "gpt-4o")}
        latency_ms = int((time.time() - start_time) * 1000)
        _log_workflow_telemetry(
            workflow="chat_text",
            tenant_id=tenant_id,
            route=label,
            latency_ms=latency_ms,
            tool_calls=0,
            tool_success=tool_success,
            schema_valid=schema_valid,
            input_tokens=0,
            output_tokens=0,
            warning=telemetry_warning,
        )
        return {
            "answer": "I cannot help with that request.",
            "routing": routing,
            "strategy": "winner_take_all",
            "tool_names": [],
            "schema_valid": schema_valid,
            "refusal": {"is_refusal": True, "reason": "SAFETY_REFUSAL"},
            "usage": usage,
            "telemetry": {
                "latency_ms": latency_ms,
                "cost_estimate_usd": 0.0,
                "tenant_id": tenant_id,
                "tool_success": tool_success,
                "warning": telemetry_warning,
                "fallback_mode": fallback_mode,
            },
        }

    strategy = "winner_take_all"
    primary_response_id, _ = get_response_ids(label)
    reviewer_response_id, _ = get_response_ids(top2_label)
    if not primary_response_id:
        latency_ms = int((time.time() - start_time) * 1000)
        _log_workflow_telemetry(
            workflow="chat_text",
            tenant_id=tenant_id,
            route=label,
            latency_ms=latency_ms,
            tool_calls=0,
            tool_success=False,
            schema_valid=schema_valid,
            input_tokens=0,
            output_tokens=0,
            warning="missing_primary_response_config",
        )
        return JSONResponse({"error": f"Response '{label}' not found. Run: python scripts/seed_multi_responses.py"}, status_code=500)

    primary_tools = _resolve_tools_for_response(primary_response_id, req.tools_override)
    selected_tool_names = tool_names(primary_tools)
    if primary_tools:
        schema_ok, schema_error = validate_tool_args(primary_tools)
        if not schema_ok:
            ENTERPRISE_METRICS["schema_violations"] += 1
            tool_success = False
            schema_valid = False
            telemetry_warning = "resolved_tool_schema_validation_error"
            latency_ms = int((time.time() - start_time) * 1000)
            _log_workflow_telemetry(
                workflow="chat_text",
                tenant_id=tenant_id,
                route=label,
                latency_ms=latency_ms,
                tool_calls=len(selected_tool_names),
                tool_success=False,
                schema_valid=False,
                input_tokens=0,
                output_tokens=0,
                warning=telemetry_warning,
            )
            return JSONResponse(
                {
                    "answer": "",
                    "routing": routing,
                    "strategy": "winner_take_all",
                    "tool_names": selected_tool_names,
                    "schema_valid": schema_valid,
                    "refusal": {"is_refusal": True, "reason": "TOOL_SCHEMA_VALIDATION_ERROR"},
                    "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model": os.getenv("OPENAI_MODEL", "gpt-4o")},
                    "telemetry": {
                        "latency_ms": latency_ms,
                        "cost_estimate_usd": 0.0,
                        "tenant_id": tenant_id,
                        "tool_success": False,
                        "warning": telemetry_warning,
                    },
                    "error": schema_error_payload("resolved_tools", schema_error),
                },
                status_code=400,
            )
    primary_result = None
    reviewer_result = None
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    reviewer_failed = False

    try:
        if is_data_analysis_flow(user_msg, False):
            strategy = "data_analysis_flow"
            analysis_conversation_id = get_or_create_analysis_conversation(session_id, tenant_id=tenant_id)
            add_message(analysis_conversation_id, "user", user_msg, file_ids=None)
            primary_result = run_assistant_structured(analysis_conversation_id, primary_response_id, tools_override=req.tools_override)
            total_usage = primary_result.get("usage", {})
        elif confidence >= 0.8:
            strategy = "winner_take_all"
            conversation_id = _get_or_create_conversation(label, tenant_id=tenant_id)
            add_message(conversation_id, "user", user_msg, file_ids=None)
            primary_result = run_assistant_structured(conversation_id, primary_response_id, tools_override=req.tools_override)
            total_usage = primary_result.get("usage", {})
        elif (0.5 <= confidence < 0.8) or is_high_risk:
            strategy = "consult_then_decide"
            conversation_id_primary = _get_or_create_conversation(label, tenant_id=tenant_id)
            add_message(conversation_id_primary, "user", user_msg, file_ids=None)
            primary_result = run_assistant_structured(conversation_id_primary, primary_response_id, tools_override=req.tools_override)
            if reviewer_response_id:
                reviewer_tools = _resolve_tools_for_response(reviewer_response_id, req.tools_override)
                selected_tool_names = sorted(set(selected_tool_names + tool_names(reviewer_tools)))
                conversation_id_reviewer = _get_or_create_conversation(top2_label, tenant_id=tenant_id)
                critique_prompt = (
                    f'The following is a response from {label.capitalize()}Advisor to the question: "{user_msg}"\n\n'
                    f'{primary_result.get("answer", "")}\n\n'
                    f'Provide a concise critique from a {top2_label} perspective.'
                )
                add_message(conversation_id_reviewer, "user", critique_prompt, file_ids=None)
                try:
                    reviewer_result = run_assistant_structured(conversation_id_reviewer, reviewer_response_id, tools_override=req.tools_override)
                except Exception:
                    reviewer_failed = True
                    fallback_mode = "reviewer_call_failed"
                    telemetry_warning = "reviewer_call_failed"
                    reviewer_result = None
                pu = primary_result.get("usage", {})
                ru = reviewer_result.get("usage", {}) if reviewer_result else {}
                total_usage = {
                    "input_tokens": pu.get("input_tokens", 0) + ru.get("input_tokens", 0),
                    "output_tokens": pu.get("output_tokens", 0) + ru.get("output_tokens", 0),
                    "total_tokens": pu.get("total_tokens", 0) + ru.get("total_tokens", 0),
                }
            else:
                fallback_mode = "missing_reviewer"
                telemetry_warning = "missing_reviewer_fallback"
                total_usage = primary_result.get("usage", {})
        else:
            strategy = "parallel_ensemble"
            conversation_id_primary = _get_or_create_conversation(label, tenant_id=tenant_id)
            add_message(conversation_id_primary, "user", user_msg, file_ids=None)
            primary_result = run_assistant_structured(conversation_id_primary, primary_response_id, tools_override=req.tools_override)
            if reviewer_response_id:
                reviewer_tools = _resolve_tools_for_response(reviewer_response_id, req.tools_override)
                selected_tool_names = sorted(set(selected_tool_names + tool_names(reviewer_tools)))
                conversation_id_reviewer = _get_or_create_conversation(top2_label, tenant_id=tenant_id)
                add_message(conversation_id_reviewer, "user", user_msg, file_ids=None)
                try:
                    reviewer_result = run_assistant_structured(conversation_id_reviewer, reviewer_response_id, tools_override=req.tools_override)
                except Exception:
                    reviewer_failed = True
                    fallback_mode = "reviewer_call_failed"
                    telemetry_warning = "reviewer_call_failed"
                    reviewer_result = None
                pu = primary_result.get("usage", {})
                ru = reviewer_result.get("usage", {}) if reviewer_result else {}
                total_usage = {
                    "input_tokens": pu.get("input_tokens", 0) + ru.get("input_tokens", 0),
                    "output_tokens": pu.get("output_tokens", 0) + ru.get("output_tokens", 0),
                    "total_tokens": pu.get("total_tokens", 0) + ru.get("total_tokens", 0),
                }
            else:
                fallback_mode = "missing_reviewer"
                telemetry_warning = "missing_reviewer_fallback"
                total_usage = primary_result.get("usage", {})
    except Exception as e:
        tool_success = False
        telemetry_warning = "responses_run_error"
        latency_ms = int((time.time() - start_time) * 1000)
        _log_workflow_telemetry(
            workflow="chat_text",
            tenant_id=tenant_id,
            route=label,
            latency_ms=latency_ms,
            tool_calls=len(selected_tool_names),
            tool_success=False,
            schema_valid=schema_valid,
            input_tokens=0,
            output_tokens=0,
            warning=telemetry_warning,
        )
        return JSONResponse(
            {
                "error": str(e),
                "routing": routing,
                "strategy": strategy,
                "tool_names": selected_tool_names,
                "schema_valid": schema_valid,
                "refusal": {"is_refusal": False, "reason": None},
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model": os.getenv("OPENAI_MODEL", "gpt-4o")},
                "telemetry": {
                    "latency_ms": latency_ms,
                    "cost_estimate_usd": 0.0,
                    "tenant_id": tenant_id,
                    "tool_success": tool_success,
                    "warning": telemetry_warning,
                },
            },
            status_code=500,
        )

    primary_meta = primary_result.get("run_meta", {}) if primary_result else {"failed": True, "failure_mode": "missing_primary_result"}
    reviewer_meta = reviewer_result.get("run_meta", {}) if reviewer_result else {}
    if primary_meta.get("failed") or primary_meta.get("warning") or primary_meta.get("partial"):
        tool_success = False
        if not telemetry_warning:
            telemetry_warning = primary_meta.get("warning") or primary_meta.get("failure_mode") or "primary_run_issue"
    if reviewer_failed or reviewer_meta.get("failed") or reviewer_meta.get("warning") or reviewer_meta.get("partial"):
        tool_success = False
        telemetry_warning = telemetry_warning or reviewer_meta.get("warning") or "reviewer_call_failed"
        fallback_mode = fallback_mode or "reviewer_call_failed"
    if fallback_mode and fallback_mode != "safety_refusal":
        tool_success = False

    answer = primary_result.get("answer", "") if primary_result else ""
    if reviewer_result:
        answer = f"{answer}\n\n{reviewer_result.get('answer', '')}".strip()

    usage_payload = {
        "input_tokens": int(total_usage.get("input_tokens", 0) or 0),
        "output_tokens": int(total_usage.get("output_tokens", 0) or 0),
        "total_tokens": int(total_usage.get("total_tokens", 0) or 0),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
    }
    latency_ms = int((time.time() - start_time) * 1000)
    _log_workflow_telemetry(
        workflow="chat_text",
        tenant_id=tenant_id,
        route=label,
        latency_ms=latency_ms,
        tool_calls=len(selected_tool_names),
        tool_success=tool_success,
        schema_valid=schema_valid,
        input_tokens=usage_payload["input_tokens"],
        output_tokens=usage_payload["output_tokens"],
        warning=telemetry_warning,
    )
    return {
        "answer": answer,
        "routing": routing,
        "strategy": strategy,
        "tool_names": selected_tool_names,
        "schema_valid": schema_valid,
        "refusal": {"is_refusal": False, "reason": None},
        "usage": usage_payload,
        "telemetry": {
            "latency_ms": latency_ms,
            "cost_estimate_usd": _estimate_cost_usd(usage_payload["input_tokens"], usage_payload["output_tokens"], usage_payload["model"]),
            "tenant_id": tenant_id,
            "tool_success": tool_success,
            "warning": telemetry_warning,
            "fallback_mode": fallback_mode,
        },
    }

@app.post("/reset", dependencies=[Depends(safe_reset_rate_limit)])
async def reset(request: Request):
    """Reset conversations (Responses API uses conversations instead of threads)."""
    session_id = await get_session_id(request)
    tenant_id = (request.headers.get("x-tenant-id", "default") or "default").strip() or "default"
    scoped_session = _tenant_scope_key(tenant_id, session_id)
    scoped_legacy_key = _tenant_scope_key(tenant_id, "conversation_id")
    conversation = create_thread()  # Creates a new conversation
    CONVERSATIONS[scoped_legacy_key] = conversation.id
    # Clear all label-specific conversations for this tenant
    tenant_prefix = f"{tenant_id}:"
    for key in [k for k in list(CONVERSATIONS_BY_LABEL.keys()) if k.startswith(tenant_prefix)]:
        del CONVERSATIONS_BY_LABEL[key]
    # Clear analysis conversation for this session
    if scoped_session in SESSION_ANALYSIS_CONVERSATION:
        del SESSION_ANALYSIS_CONVERSATION[scoped_session]
    if scoped_session in SESSION_ANALYSIS_FILES:
        del SESSION_ANALYSIS_FILES[scoped_session]
    return {"thread_id": conversation.id, "message": "All conversations reset"}  # Keep thread_id in response for API compatibility

def _has_grounded_content(result: dict) -> bool:
    """Check if response retrieved grounded content (sources or substantial answer)."""
    sources = result.get("sources", [])
    answer = result.get("answer", "").strip()
    # Consider it grounded if there are sources or a substantial answer (>50 chars)
    return len(sources) > 0 or len(answer) > 50

def _get_or_create_conversation(label: str, tenant_id: str = "default") -> str:
    """Get or create a conversation for a specific response label."""
    scoped_label = _tenant_scope_key(tenant_id, label)
    if scoped_label not in CONVERSATIONS_BY_LABEL:
        conversation = create_thread()  # create_thread creates a conversation in Responses API
        CONVERSATIONS_BY_LABEL[scoped_label] = conversation.id
    return CONVERSATIONS_BY_LABEL[scoped_label]

# Legacy alias for backward compatibility
def _get_or_create_thread(label: str, tenant_id: str = "default") -> str:
    """Legacy alias - use _get_or_create_conversation instead."""
    return _get_or_create_conversation(label, tenant_id=tenant_id)

# main costed endpoint: 3 req / 60s per IP
# This endpoint uses Responses API exclusively:
# - Conversations API (client.conversations.create) for conversation management
# - Responses API (client.responses.create) for generating responses
# - In-memory conversation history tracking (passed as input to responses.create)
@app.post("/chat", dependencies=[Depends(safe_chat_rate_limit)])
async def chat(
    request: Request,
    message: str = Form(...),
    files: Optional[List[UploadFile]] = File(None)
):
    """
    Chat endpoint using Responses API.
    
    Uses:
    - Conversations API for conversation management (create_thread -> conversations.create)
    - Responses API for response generation (run_assistant_structured -> responses.create)
    - In-memory conversation history tracking (passed as input parameter)
    """
    start_time = time.time()
    user_msg = message.strip()
    tenant_id = (request.headers.get("x-tenant-id", "default") or "default").strip() or "default"
    if not user_msg:
        return JSONResponse({"error": "message required"}, status_code=400)

    # Check if multi-assistant setup exists, fallback to legacy single assistant
    all_responses = get_all_response_ids()
    if not all_responses:
        # Legacy single assistant mode
        response_id, _ = get_ids()
        if not response_id:
            return JSONResponse({"error": "Seed first: python scripts/seed_multi_responses.py"}, status_code=500)
        
        legacy_conversation_key = _tenant_scope_key(tenant_id, "conversation_id")
        conversation_id = CONVERSATIONS.get(legacy_conversation_key)
        if not conversation_id:
            conversation = create_thread()  # Creates a conversation in Responses API
            conversation_id = conversation.id
            CONVERSATIONS[legacy_conversation_key] = conversation_id
        
        try:
            file_ids = []
            if files:
                for file in files:
                    if file.filename:
                        file_content = await file.read()
                        uploaded_file = upload_file(file_content, file.filename)
                        file_ids.append(uploaded_file.id)
            
            # If no new files but user is asking about data, re-attach previous files from this conversation
            if not file_ids and detect_data_reference(user_msg):
                previous_files = get_conversation_files(conversation_id)
                if previous_files:
                    file_ids = previous_files
            
            # Track files uploaded to this conversation
            if file_ids:
                track_conversation_files(conversation_id, file_ids)
            
            add_message(conversation_id, "user", user_msg, file_ids=file_ids if file_ids else None)
            result = run_assistant_structured(conversation_id, response_id)  # conversation_id is used as conversation_id, response_id is response_config_id
            
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
                "thread_id": conversation_id,  # Keep thread_id in response for API compatibility
                "answer": result.get("answer", ""),
                "sources": result.get("sources", []),
                "raw_text": result.get("raw_text", ""),
                "bullets": result.get("bullets"),
                "images": result.get("images", []),
                "usage": usage
            }
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_request(latency_ms=latency_ms, error=True)
            # Include traceback in development for debugging
            error_msg = str(e)
            if os.getenv("DEBUG", "false").lower() == "true":
                error_msg += f"\n\nTraceback:\n{error_trace}"
            return JSONResponse({"error": error_msg, "traceback": error_trace}, status_code=500)
    
    # Multi-assistant routing mode
    try:
        # Get session ID for analysis thread tracking
        session_id = await get_session_id(request) if hasattr(request, 'client') else "default"
        
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
        
        # Check if this is a data analysis flow
        is_data_flow = is_data_analysis_flow(user_msg, bool(file_ids))
        
        # Step 3: Handle data analysis flows with shared analysis conversation
        if is_data_flow:
            analysis_conversation_id = get_or_create_analysis_conversation(session_id, tenant_id=tenant_id)
            
            # Track files in analysis conversation
            analysis_file_ids = list(file_ids) if file_ids else []
            if not analysis_file_ids:
                previous_analysis_files = get_analysis_files(session_id, tenant_id=tenant_id)
                if previous_analysis_files:
                    analysis_file_ids = previous_analysis_files
            
            if file_ids:
                track_analysis_files(session_id, file_ids, tenant_id=tenant_id)
            
            # Use InvestorAdvisor for data analysis (has code_interpreter)
            response_id, _ = get_response_ids("investor")
            if not response_id:
                response_id, _ = get_response_ids(label)
            
            if not response_id:
                return JSONResponse({"error": f"Response not found. Run: python scripts/seed_multi_responses.py"}, status_code=500)
            
            add_message(analysis_conversation_id, "user", user_msg, file_ids=analysis_file_ids if analysis_file_ids else None)
            result = run_assistant_structured(analysis_conversation_id, response_id)  # conversation_id is used as conversation_id, response_id is response_config_id
            
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
                "thread_id": analysis_conversation_id,  # Keep thread_id in response for API compatibility
                "answer": result.get("answer", ""),
                "sources": result.get("sources", []),
                "raw_text": result.get("raw_text", ""),
                "bullets": result.get("bullets"),
                "images": result.get("images", []),
                "usage": usage,
                "routing": {"strategy": "data_analysis_flow", "label": "investor"}
            }
        
        # Step 4: Normal routing (not data analysis)
        # Determine routing strategy
        primary_response_id, _ = get_response_ids(label)
        reviewer_response_id, _ = get_response_ids(top2_label)
        
        if not primary_response_id:
            return JSONResponse({"error": f"Response '{label}' not found. Run: python scripts/seed_multi_responses.py"}, status_code=500)
        
        primary_result = None
        reviewer_result = None
        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        
        # Strategy 1: Winner-take-all (confidence >= 0.8)
        if confidence >= 0.8:
            conversation_id = _get_or_create_conversation(label, tenant_id=tenant_id)
            
            # If no new files but user is asking about data, re-attach previous files from this conversation
            if not file_ids and detect_data_reference(user_msg):
                previous_files = get_conversation_files(conversation_id)
                if previous_files:
                    file_ids = previous_files
            
            # Track files uploaded to this conversation
            if file_ids:
                track_conversation_files(conversation_id, file_ids)
            
            add_message(conversation_id, "user", user_msg, file_ids=file_ids if file_ids else None)
            primary_result = run_assistant_structured(conversation_id, primary_response_id)  # conversation_id is used as conversation_id, response_id is response_config_id
            total_usage = primary_result.get("usage", {})
        
        # Strategy 2: Consult-then-decide (0.5 <= confidence < 0.8 OR high-risk)
        elif (0.5 <= confidence < 0.8) or is_high_risk:
            if not reviewer_response_id:
                # Fallback to primary only if reviewer not available
                conversation_id = _get_or_create_conversation(label, tenant_id=tenant_id)
                
                # If no new files but user is asking about data, re-attach previous files from this conversation
                if not file_ids and detect_data_reference(user_msg):
                    previous_files = get_conversation_files(conversation_id)
                    if previous_files:
                        file_ids = previous_files
                
                # Track files uploaded to this conversation
                if file_ids:
                    track_conversation_files(conversation_id, file_ids)
                
                add_message(conversation_id, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(conversation_id, primary_response_id)
                total_usage = primary_result.get("usage", {})
            else:
                # Run primary first
                conversation_id_primary = _get_or_create_conversation(label, tenant_id=tenant_id)
                
                # If no new files but user is asking about data, re-attach previous files from this conversation
                if not file_ids and detect_data_reference(user_msg):
                    previous_files = get_conversation_files(conversation_id_primary)
                    if previous_files:
                        file_ids = previous_files
                
                # Track files uploaded to this conversation
                if file_ids:
                    track_conversation_files(conversation_id_primary, file_ids)
                
                add_message(conversation_id_primary, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(conversation_id_primary, primary_response_id)
                
                # Then ask reviewer to critique (Devil's Advocate pass)
                conversation_id_reviewer = _get_or_create_conversation(top2_label, tenant_id=tenant_id)
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
                
                add_message(conversation_id_reviewer, "user", critique_prompt, file_ids=file_ids if file_ids else None)
                reviewer_result = run_assistant_structured(conversation_id_reviewer, reviewer_response_id)  # conversation_id is used as conversation_id, response_id is response_config_id
                
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
            if not reviewer_response_id:
                # Fallback to primary only
                conversation_id = _get_or_create_conversation(label, tenant_id=tenant_id)
                
                # If no new files but user is asking about data, re-attach previous files from this conversation
                if not file_ids and detect_data_reference(user_msg):
                    previous_files = get_conversation_files(conversation_id)
                    if previous_files:
                        file_ids = previous_files
                
                # Track files uploaded to this conversation
                if file_ids:
                    track_conversation_files(conversation_id, file_ids)
                
                add_message(conversation_id, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(conversation_id, primary_response_id)
                total_usage = primary_result.get("usage", {})
            else:
                # Run both in parallel (sequentially for now, but could be parallelized)
                conversation_id_primary = _get_or_create_conversation(label, tenant_id=tenant_id)
                
                # If no new files but user is asking about data, re-attach previous files from this conversation
                if not file_ids and detect_data_reference(user_msg):
                    previous_files = get_conversation_files(conversation_id_primary)
                    if previous_files:
                        file_ids = previous_files
                
                # Track files uploaded to this conversation
                if file_ids:
                    track_conversation_files(conversation_id_primary, file_ids)
                
                add_message(conversation_id_primary, "user", user_msg, file_ids=file_ids if file_ids else None)
                primary_result = run_assistant_structured(conversation_id_primary, primary_response_id)
                
                conversation_id_reviewer = _get_or_create_conversation(top2_label, tenant_id=tenant_id)
                # Reviewer also gets the same files if available
                add_message(conversation_id_reviewer, "user", user_msg, file_ids=file_ids if file_ids else None)
                reviewer_result = run_assistant_structured(conversation_id_reviewer, reviewer_response_id)  # conversation_id is used as conversation_id, response_id is response_config_id
                
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
                "thread_id": _get_or_create_conversation(label, tenant_id=tenant_id),  # Keep thread_id in response for API compatibility
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
                
                # Format reviewer critique (may have structured output with bullets)
                reviewer_bullets = reviewer_result.get("bullets", [])
                if reviewer_bullets and isinstance(reviewer_bullets, list):
                    # If reviewer has bullets, format them nicely
                    critique_text = reviewer_answer
                    if reviewer_bullets:
                        critique_text += "\n\n**Key Points:**\n"
                        for bullet in reviewer_bullets:
                            critique_text += f"- {bullet}\n"
                    composed_answer += f"**{top2_label.capitalize()}Advisor Critique (Devil's Advocate):**\n{critique_text}"
                else:
                    # Just use the answer text
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
            "thread_id": _get_or_create_conversation(label, tenant_id=tenant_id),  # Keep thread_id in response for API compatibility
            "answer": answer,
            "sources": sources,
            "raw_text": primary_result.get("raw_text", "") if primary_result else "",
            "bullets": bullets,
            "images": images,
            "usage": total_usage,
            "routing": routing  # Include routing info for debugging
        }
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        latency_ms = (time.time() - start_time) * 1000
        metrics.record_request(latency_ms=latency_ms, error=True)
        # Include traceback in development for debugging
        error_msg = str(e)
        if os.getenv("DEBUG", "false").lower() == "true":
            error_msg += f"\n\nTraceback:\n{error_trace}"
        return JSONResponse({"error": error_msg, "traceback": error_trace}, status_code=500)

@app.get("/")
def root():
    return FileResponse("app/static/index.html")

@app.get("/api/metrics")
def get_metrics():
    """Get metrics data as JSON."""
    payload = metrics.get_stats()
    payload["enterprise"] = {
        "schema_violations": ENTERPRISE_METRICS["schema_violations"] + get_schema_violation_count()
    }
    return payload

@app.post("/api/metrics/reset")
def reset_metrics():
    """Reset all metrics."""    
    metrics.reset()
    return {"status": "reset"}

@app.get("/metrics")
def metrics_page():
    """Serve the metrics dashboard page."""
    return FileResponse("app/static/metrics.html")

@app.get("/api/file/{file_id}")
def get_file(file_id: str):
    """Download a file from OpenAI Files API."""
    try:
        data = download_file_bytes(file_id)
        return Response(content=data, media_type="application/octet-stream")
    except Exception as e:
        return JSONResponse(
            status_code=404,
            content={"error": f"Could not download file {file_id}: {str(e)}"}
        )

@app.get("/api/container-file/{container_id}/{file_id}")
def get_container_file(container_id: str, file_id: str):
    """Download a container file (e.g., image generated by code_interpreter)."""
    try:
        data = download_container_file_bytes(container_id, file_id)
        # PNG is most common; octet-stream would also work
        return Response(content=data, media_type="image/png")
    except Exception as e:
        return JSONResponse(
            status_code=404,
            content={"error": f"Could not download container file {file_id}: {str(e)}"}
        )

@app.post("/chat/stream", dependencies=[Depends(safe_chat_rate_limit)])
async def chat_stream(
    request: Request,
    message: str = Form(...),
    files: Optional[List[UploadFile]] = File(None)
):
    """Streaming chat endpoint using Server-Sent Events."""
    start_time = time.time()
    user_msg = message.strip()
    tenant_id = (request.headers.get("x-tenant-id", "default") or "default").strip() or "default"
    if not user_msg:
        return JSONResponse({"error": "message required"}, status_code=400)

    # Get session ID for product card tracking
    session_id = await get_session_id(request)
    
    # Read all files upfront before the async generator (files can only be read once)
    file_ids = []
    if files:
        for file in files:
            if file.filename:
                try:
                    file_content = await file.read()
                    uploaded_file = upload_file(file_content, file.filename)
                    file_ids.append(uploaded_file.id)
                except Exception as e:
                    # If file read fails, return error immediately
                    return StreamingResponse(
                        f"data: {json.dumps({'type': 'error', 'error': f'Failed to read file {file.filename}: {str(e)}'})}\n\n",
                        media_type="text/event-stream"
                    )
    
    async def stream_response():
        nonlocal file_ids  # Allow modification of outer scope variable
        try:
            # Check if multi-assistant setup exists
            all_responses = get_all_response_ids()
            if not all_responses:
                # Legacy single assistant mode
                response_id, _ = get_ids()
                if not response_id:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'Seed first: python scripts/seed_multi_responses.py'})}\n\n"
                    return
                
                legacy_conversation_key = _tenant_scope_key(tenant_id, "conversation_id")
                conversation_id = CONVERSATIONS.get(legacy_conversation_key)
                if not conversation_id:
                    conversation = create_thread()  # Creates a conversation in Responses API
                    conversation_id = conversation.id
                    CONVERSATIONS[legacy_conversation_key] = conversation_id
                
                # If no new files but user is asking about data, re-attach previous files from this conversation
                if not file_ids and detect_data_reference(user_msg):
                    previous_files = get_conversation_files(conversation_id)
                    if previous_files:
                        file_ids = previous_files
                
                # Track files uploaded to this conversation
                if file_ids:
                    track_conversation_files(conversation_id, file_ids)
                
                add_message(conversation_id, "user", user_msg, file_ids=file_ids if file_ids else None)
                
                # Stream response
                for chunk in run_assistant_stream(conversation_id, response_id):  # conversation_id is used as conversation_id, response_id is response_config_id
                    chunk["routing"] = {"strategy": "legacy"}
                    yield f"data: {json.dumps(chunk)}\n\n"
                    
                    # Track files produced in response
                    if chunk.get("type") == "done":
                        if chunk.get("images"):
                            image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                            if image_file_ids:
                                track_produced_files(session_id, image_file_ids)
                
                # Record metrics
                latency_ms = (time.time() - start_time) * 1000
                metrics.record_request(latency_ms=latency_ms, error=False)
                return
            
            # Multi-assistant routing mode
            routing = route_query(user_msg)
            label = routing["label"]
            confidence = routing["confidence"]
            top2_label = routing["top2_label"]
            margin = routing["margin"]
            is_high_risk = routing["is_high_risk"]
            
            # Check if this is a data analysis flow (CSV/data file iteration)
            is_data_flow = is_data_analysis_flow(user_msg, bool(file_ids))
            
            # Product card logic: try to auto-extract product info from message
            # This happens before deictic detection so we can create cards on-the-fly
            product_card = None
            auto_created_card = auto_create_or_update_product_card(user_msg, session_id)
            if auto_created_card:
                # Product card was created/updated from this message
                product_card = auto_created_card
                set_active_product_id(session_id, product_card['product_id'])
                # Yield a notification that product card was created (optional, for UI feedback)
                yield f"data: {json.dumps({'type': 'product_card_updated', 'product_id': product_card['product_id'], 'name': product_card['name']})}\n\n"
            
            # Detect deictic references and get product context
            has_deictic = detect_deictic_references(user_msg)
            active_product_id = get_active_product_id(session_id)
            if not product_card and active_product_id:
                product_card = get_product_card(active_product_id)
            
            # Check if we need clarification (low confidence + no product card)
            all_products = get_all_product_cards()
            if confidence < 0.6 and not product_card:
                if len(all_products) > 1:
                    # Multiple products exist - ask user to select
                    product_list = "\n".join([f"- {p['name']} (ID: {p['product_id']})" for p in all_products])
                    clarification = f"I see multiple products. Which one are you referring to?\n\n{product_list}\n\nPlease specify the product name or ID."
                    yield f"data: {json.dumps({'type': 'clarification', 'message': clarification})}\n\n"
                    return
                elif len(all_products) == 0:
                    # No products exist - could ask to create one, but for now just proceed
                    pass
            
            # Data analysis flow: use shared analysis conversation for CSV/data iterations
            if is_data_flow:
                # Use shared analysis conversation for data flows
                analysis_conversation_id = get_or_create_analysis_conversation(session_id, tenant_id=tenant_id)
                
                # Track files in analysis conversation
                analysis_file_ids = list(file_ids) if file_ids else []
                if not analysis_file_ids:
                    # If no new files, get previous analysis files
                    previous_analysis_files = get_analysis_files(session_id, tenant_id=tenant_id)
                    if previous_analysis_files:
                        analysis_file_ids = previous_analysis_files
                
                if file_ids:
                    track_analysis_files(session_id, file_ids, tenant_id=tenant_id)
                
                # For data flows, use InvestorAdvisor (has code_interpreter) or the routed assistant
                # But prefer InvestorAdvisor for data analysis
                if label == "investor" or is_data_flow:
                    response_id, _ = get_response_ids("investor")
                    if not response_id:
                        response_id, _ = get_response_ids(label)
                else:
                    response_id, _ = get_response_ids(label)
                
                if not response_id:
                    error_msg = f"Response not found. Run: python scripts/seed_multi_responses.py"
                    yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"
                    return
                
                add_message(analysis_conversation_id, "user", user_msg, file_ids=analysis_file_ids if analysis_file_ids else None)
                
                yield f"data: {json.dumps({'type': 'routing', 'strategy': 'data_analysis_flow', 'label': 'investor', 'confidence': 1.0})}\n\n"
                
                # Stream response from analysis conversation
                for chunk in run_assistant_stream(analysis_conversation_id, response_id):  # conversation_id is used as conversation_id, response_id is response_config_id
                    chunk["routing"] = {"strategy": "data_analysis_flow", "label": "investor"}
                    yield f"data: {json.dumps(chunk)}\n\n"
                    
                    # Track files produced
                    if chunk.get("type") == "done" and chunk.get("images"):
                        image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                        if image_file_ids:
                            track_produced_files(session_id, image_file_ids)
                
                # Record metrics
                latency_ms = (time.time() - start_time) * 1000
                metrics.record_request(latency_ms=latency_ms, error=False)
                return
            
            # Normal routing flow (not data analysis)
            # Rewrite message with product card if needed
            final_message = user_msg
            final_file_ids = list(file_ids) if file_ids else []
            
            if has_deictic and product_card:
                # Rewrite message with product card context
                rewritten, card_file_ids = rewrite_message_with_product_card(
                    user_msg,
                    product_card,
                    get_produced_files(session_id)
                )
                final_message = rewritten
                final_file_ids.extend(card_file_ids)
            elif has_deictic and not product_card and len(all_products) == 1:
                # Only one product exists - use it automatically
                product_card = all_products[0]
                set_active_product_id(session_id, product_card["product_id"])
                rewritten, card_file_ids = rewrite_message_with_product_card(
                    user_msg,
                    product_card,
                    get_produced_files(session_id)
                )
                final_message = rewritten
                final_file_ids.extend(card_file_ids)
            else:
                # No deictic references or no product card - use produced files if available
                produced_files = get_produced_files(session_id)
                if produced_files:
                    final_file_ids.extend(produced_files)
            
            # Files already uploaded above (plus any from product card)
            
            primary_response_id, _ = get_response_ids(label)
            reviewer_response_id, _ = get_response_ids(top2_label)
            
            if not primary_response_id:
                error_msg = f"Response '{label}' not found. Run: python scripts/seed_multi_responses.py"
                yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"
                return
            
            # Strategy 1: Winner-take-all (confidence >= 0.8)
            if confidence >= 0.8:
                conversation_id = _get_or_create_conversation(label, tenant_id=tenant_id)
                
                # If no new files but user is asking about data, re-attach previous files from this conversation
                if not final_file_ids and detect_data_reference(user_msg):
                    previous_files = get_conversation_files(conversation_id)
                    if previous_files:
                        final_file_ids = previous_files
                
                # Track files uploaded to this conversation
                if final_file_ids:
                    track_conversation_files(conversation_id, final_file_ids)
                
                add_message(conversation_id, "user", final_message, file_ids=final_file_ids if final_file_ids else None)
                
                yield f"data: {json.dumps({'type': 'routing', 'strategy': 'winner_take_all', 'label': label, 'confidence': confidence})}\n\n"
                
                # Stream primary response
                for chunk in run_assistant_stream(conversation_id, primary_response_id):  # conversation_id is used as conversation_id, response_id is response_config_id
                    chunk["routing"] = routing
                    yield f"data: {json.dumps(chunk)}\n\n"
                    
                    # Track files produced
                    if chunk.get("type") == "done" and chunk.get("images"):
                        image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                        if image_file_ids:
                            track_produced_files(session_id, image_file_ids)
            
            # Strategy 2: Consult-then-decide (0.5 <= confidence < 0.8 OR high-risk)
            elif (0.5 <= confidence < 0.8) or is_high_risk:
                if not reviewer_response_id:
                    # Fallback to primary only
                    thread_id = _get_or_create_thread(label, tenant_id=tenant_id)
                    
                    # If no new files but user is asking about data, re-attach previous files from this thread
                    if not final_file_ids and detect_data_reference(user_msg):
                        previous_files = get_thread_files(thread_id)
                        if previous_files:
                            final_file_ids = previous_files
                    
                    # Track files uploaded to this thread
                    if final_file_ids:
                        track_thread_files(thread_id, final_file_ids)
                    
                    add_message(thread_id, "user", final_message, file_ids=final_file_ids if final_file_ids else None)
                    
                    yield f"data: {json.dumps({'type': 'routing', 'strategy': 'winner_take_all', 'label': label, 'confidence': confidence})}\n\n"
                    
                    for chunk in run_assistant_stream(thread_id, primary_response_id):  # In Responses API, thread_id and response_id are the same
                        chunk["routing"] = routing
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                        # Track files produced
                        if chunk.get("type") == "done" and chunk.get("images"):
                            image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                            if image_file_ids:
                                track_produced_files(session_id, image_file_ids)
                else:
                    # Stream primary first
                    conversation_id_primary = _get_or_create_conversation(label, tenant_id=tenant_id)
                    
                    # If no new files but user is asking about data, re-attach previous files from this conversation
                    if not final_file_ids and detect_data_reference(user_msg):
                        previous_files = get_conversation_files(conversation_id_primary)
                        if previous_files:
                            final_file_ids = previous_files
                    
                    # Track files uploaded to this conversation
                    if final_file_ids:
                        track_conversation_files(conversation_id_primary, final_file_ids)
                    
                    add_message(conversation_id_primary, "user", final_message, file_ids=final_file_ids if final_file_ids else None)
                    
                    yield f"data: {json.dumps({'type': 'routing', 'strategy': 'consult_then_decide', 'primary_label': label, 'reviewer_label': top2_label, 'confidence': confidence})}\n\n"
                    
                    # Stream primary response
                    primary_answer = ""
                    primary_bullets = []
                    for chunk in run_assistant_stream(conversation_id_primary, primary_response_id):  # conversation_id is used as conversation_id, response_id is response_config_id
                        if chunk.get("type") == "text_delta":
                            primary_answer = chunk.get("accumulated", "")
                        elif chunk.get("type") == "done":
                            primary_answer = chunk.get("answer", "")
                            primary_bullets = chunk.get("bullets", [])
                            # Track files produced
                            if chunk.get("images"):
                                image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                                if image_file_ids:
                                    track_produced_files(session_id, image_file_ids)
                        chunk["routing"] = routing
                        chunk["phase"] = "primary"
                        yield f"data: {json.dumps(chunk)}\n\n"
                    
                    # Signal primary is done, starting reviewer
                    yield f"data: {json.dumps({'type': 'phase_transition', 'from': 'primary', 'to': 'reviewer'})}\n\n"
                    
                    # Then ask reviewer to critique
                    conversation_id_reviewer = _get_or_create_conversation(top2_label, tenant_id=tenant_id)
                    # Include product card in critique prompt if available
                    critique_context = ""
                    if product_card:
                        critique_context = f"\n\n{format_product_card_for_message(product_card)}\n\n"
                    critique_prompt = f"""The following is a response from {label.capitalize()}Advisor to the question: "{user_msg}"{critique_context}**{label.capitalize()}Advisor's Response:**
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
                    
                    add_message(conversation_id_reviewer, "user", critique_prompt, file_ids=final_file_ids if final_file_ids else None)
                    
                    # Stream reviewer response
                    for chunk in run_assistant_stream(conversation_id_reviewer, reviewer_response_id):  # conversation_id is used as conversation_id, response_id is response_config_id
                        chunk["routing"] = routing
                        chunk["phase"] = "reviewer"
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                        # Track files produced
                        if chunk.get("type") == "done" and chunk.get("images"):
                            image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                            if image_file_ids:
                                track_produced_files(session_id, image_file_ids)
            
            # Strategy 3: Parallel ensemble (confidence < 0.5 OR margin < 0.15)
            else:
                if not reviewer_response_id:
                    # Fallback to primary only
                    thread_id = _get_or_create_thread(label, tenant_id=tenant_id)
                    
                    # If no new files but user is asking about data, re-attach previous files from this thread
                    if not final_file_ids and detect_data_reference(user_msg):
                        previous_files = get_thread_files(thread_id)
                        if previous_files:
                            final_file_ids = previous_files
                    
                    # Track files uploaded to this thread
                    if final_file_ids:
                        track_thread_files(thread_id, final_file_ids)
                    
                    add_message(thread_id, "user", final_message, file_ids=final_file_ids if final_file_ids else None)
                    
                    yield f"data: {json.dumps({'type': 'routing', 'strategy': 'winner_take_all', 'label': label, 'confidence': confidence})}\n\n"
                    
                    for chunk in run_assistant_stream(thread_id, primary_response_id):  # In Responses API, thread_id and response_id are the same
                        chunk["routing"] = routing
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                        # Track files produced
                        if chunk.get("type") == "done" and chunk.get("images"):
                            image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                            if image_file_ids:
                                track_produced_files(session_id, image_file_ids)
                else:
                    # Stream primary first
                    thread_id_primary = _get_or_create_thread(label, tenant_id=tenant_id)
                    
                    # If no new files but user is asking about data, re-attach previous files from this thread
                    if not final_file_ids and detect_data_reference(user_msg):
                        previous_files = get_thread_files(thread_id_primary)
                        if previous_files:
                            final_file_ids = previous_files
                    
                    # Track files uploaded to this thread
                    if final_file_ids:
                        track_thread_files(thread_id_primary, final_file_ids)
                    
                    add_message(thread_id_primary, "user", final_message, file_ids=final_file_ids if final_file_ids else None)
                    
                    yield f"data: {json.dumps({'type': 'routing', 'strategy': 'parallel_ensemble', 'primary_label': label, 'reviewer_label': top2_label, 'confidence': confidence})}\n\n"
                    
                    # Stream primary response
                    for chunk in run_assistant_stream(thread_id_primary, primary_response_id):  # In Responses API, thread_id and response_id are the same
                        chunk["routing"] = routing
                        chunk["phase"] = "primary"
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                        # Track files produced
                        if chunk.get("type") == "done" and chunk.get("images"):
                            image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                            if image_file_ids:
                                track_produced_files(session_id, image_file_ids)
                    
                    # Signal primary is done, starting reviewer
                    yield f"data: {json.dumps({'type': 'phase_transition', 'from': 'primary', 'to': 'reviewer'})}\n\n"
                    
                    # Stream reviewer response (independent answer)
                    conversation_id_reviewer = _get_or_create_conversation(top2_label, tenant_id=tenant_id)
                    add_message(conversation_id_reviewer, "user", final_message, file_ids=final_file_ids if final_file_ids else None)
                    
                    for chunk in run_assistant_stream(conversation_id_reviewer, reviewer_response_id):  # conversation_id is used as conversation_id, response_id is response_config_id
                        chunk["routing"] = routing
                        chunk["phase"] = "reviewer"
                        yield f"data: {json.dumps(chunk)}\n\n"
                        
                        # Track files produced
                        if chunk.get("type") == "done" and chunk.get("images"):
                            image_file_ids = [img.get("file_id") for img in chunk.get("images", []) if img.get("file_id")]
                            if image_file_ids:
                                track_produced_files(session_id, image_file_ids)
            
            # Track files from primary response in consult-then-decide
            # (already handled above for other strategies)
            
            # Record metrics
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_request(latency_ms=latency_ms, error=False)
            
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            metrics.record_request(latency_ms=latency_ms, error=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )
