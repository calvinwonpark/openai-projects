"""
OpenAI Client for Responses API

This module provides functions for interacting with OpenAI's Responses API,
which replaces the deprecated Assistants API.

Key differences from Assistants API:
- Responses API uses response objects instead of assistants/threads/runs
- Conversations API (client.conversations) replaces Threads API
- Responses API (client.responses) replaces Assistants/Runs API
- Stateful conversations are managed via Conversations API
- Conversation history is tracked in-memory and passed as input to responses.create()
- Built-in tools (file_search, code_interpreter) are specified per response

All functions in this module use Responses API exclusively:
- create_thread() -> client.conversations.create()
- add_message_to_response() -> tracks conversation history in-memory
- run_response() -> client.responses.create()
- No Assistants API (client.assistants, client.threads, client.runs) calls
"""
import os
import re
import json
import io
import base64
import mimetypes
import time
from openai import OpenAI
from typing import Dict, Any, List, Generator, Optional
from app.tool_schema import validate_tool_args, schema_error_log

_client = None
_SCHEMA_VIOLATIONS = 0


def get_schema_violation_count() -> int:
    return _SCHEMA_VIOLATIONS


def _record_schema_violation(tool_name: str, error: str) -> None:
    global _SCHEMA_VIOLATIONS
    _SCHEMA_VIOLATIONS += 1
    print(schema_error_log(tool_name, error), flush=True)


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text


def _is_retryable_tool_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        _is_timeout_error(exc)
        or "tool" in text
        or "rate limit" in text
        or "temporar" in text
        or "connection" in text
    )

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing")
        _client = OpenAI(api_key=api_key)
    return _client

def get_model():
    return os.getenv("OPENAI_MODEL", "gpt-4o")

# ---------------- Vector Stores (beta) ----------------
# Vector stores are still used the same way

def create_vector_store(name: str):
    """Create a vector store for file search."""
    # Vector stores moved from beta to top-level namespace
    client = get_client()
    if hasattr(client, 'vector_stores'):
        return client.vector_stores.create(name=name)
    elif hasattr(client.beta, 'vector_stores'):
        # Fallback for older SDK versions
        return client.beta.vector_stores.create(name=name)
    else:
        raise NotImplementedError("Vector stores API is not available in this SDK version")

def upload_files_batch_to_vs(vector_store_id: str, file_paths: list[str]):
    """Upload files to a vector store in a batch."""
    client = get_client()
    files = [open(p, "rb") for p in file_paths]
    try:
        # Vector stores moved from beta to top-level namespace
        if hasattr(client, 'vector_stores'):
            batch = client.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store_id,
                files=files,
            )
        elif hasattr(client.beta, 'vector_stores'):
            # Fallback for older SDK versions
            batch = client.beta.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store_id,
                files=files,
            )
        else:
            raise NotImplementedError("Vector stores API is not available in this SDK version")
        return batch
    finally:
        for f in files:
            try:
                f.close()
            except Exception:
                pass

# ---------------- Responses API ----------------
# Responses API replaces Assistants/Threads/Runs

# Response configuration storage (in-memory, with persistence to state file)
_RESPONSE_CONFIGS: Dict[str, Dict[str, Any]] = {}  # response_id -> config
_RESPONSE_CONFIGS_LOADED = False  # Track if configs have been loaded from state file

def create_response(
    name: str,
    vector_store_id: Optional[str] = None,
    enable_code_interpreter: bool = False,
    instructions: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a response configuration (replaces assistant creation).
    This stores a response configuration that can be reused.
    
    Note: In Responses API, responses are created with input and conversation ID.
    This function stores a reusable response configuration.
    
    Args:
        name: Name for the response
        vector_store_id: Optional vector store ID for file_search tool
        enable_code_interpreter: Whether to enable code_interpreter tool
        instructions: System instructions for the response
    
    Returns:
        Response configuration object (with .id that can be used in run_response)
    """
    import uuid
    
    # Build tools list
    tools = []
    
    if vector_store_id:
        # In Responses API, vector_store_ids are embedded directly in the file_search tool
        tools.append({
            "type": "file_search",
            "vector_store_ids": [vector_store_id]
        })
    
    if enable_code_interpreter:
        # Code interpreter requires container configuration
        tools.append({
            "type": "code_interpreter",
            "container": {"type": "auto"}
        })
    
    # Generate response config ID
    response_id = f"resp_{uuid.uuid4().hex[:12]}"
    
    # Store configuration
    config = {
        "name": name,
        "model": get_model(),
        "instructions": instructions,
        "tools": tools
    }
    _RESPONSE_CONFIGS[response_id] = config
    
    # Also save to state file for persistence across processes
    _save_response_config_to_state(response_id, config)
    
    # Return configuration object
    class ResponseConfig:
        """Response configuration object."""
        def __init__(self, resp_id, name):
            self.id = resp_id
            self.name = name
    
    return ResponseConfig(response_id, name)

def get_response_config(response_id: str) -> Optional[Dict[str, Any]]:
    """
    Get response configuration by ID.
    Loads from state file if not found in memory.
    """
    # Load configs from state file if not already loaded
    if not _RESPONSE_CONFIGS_LOADED:
        _load_response_configs_from_state()
    
    # Check in-memory first
    if response_id in _RESPONSE_CONFIGS:
        return _RESPONSE_CONFIGS[response_id]
    
    # Try to reconstruct from state file
    config = _reconstruct_config_from_state(response_id)
    if config:
        _RESPONSE_CONFIGS[response_id] = config
        return config
    
    return None

def _save_response_config_to_state(response_id: str, config: Dict[str, Any]):
    """Save response configuration to state file."""
    from app.storage import load_state, save_state
    
    state = load_state()
    if "response_configs" not in state:
        state["response_configs"] = {}
    
    state["response_configs"][response_id] = config
    save_state(state)

def _load_response_configs_from_state():
    """Load all response configurations from state file."""
    global _RESPONSE_CONFIGS_LOADED
    
    from app.storage import load_state
    
    state = load_state()
    configs = state.get("response_configs", {})
    
    for response_id, config in configs.items():
        _RESPONSE_CONFIGS[response_id] = config
    
    _RESPONSE_CONFIGS_LOADED = True

def _reconstruct_config_from_state(response_id: str) -> Optional[Dict[str, Any]]:
    """
    Reconstruct response configuration from state file.
    This is used when configs weren't saved directly but we have response IDs.
    """
    from app.storage import load_state
    
    state = load_state()
    
    # First, try to load from saved configs
    configs = state.get("response_configs", {})
    if response_id in configs:
        return configs[response_id]
    
    # Otherwise, reconstruct from response IDs
    responses = state.get("responses", {})
    for label, response_data in responses.items():
        if response_data.get("response_id") == response_id:
            vector_store_id = response_data.get("vector_store_id")
            
            # Determine if code_interpreter is enabled based on label
            enable_code_interpreter = label in ["tech", "investor"]
            
            # Reconstruct tools
            tools = []
            if vector_store_id:
                tools.append({
                    "type": "file_search",
                    "vector_store_ids": [vector_store_id]
                })
            if enable_code_interpreter:
                tools.append({
                    "type": "code_interpreter",
                    "container": {"type": "auto"}
                })
            
            # Get instructions
            instructions = _get_specialized_instructions(label)
            
            # Reconstruct config
            config = {
                "name": label.capitalize() + "Advisor",
                "model": get_model(),
                "instructions": instructions,
                "tools": tools
            }
            
            # Save it for future use
            _save_response_config_to_state(response_id, config)
            return config
    
    return None

def create_specialized_response(
    label: str,
    vector_store_id: str,
    enable_code_interpreter: bool = False
):
    """
    Create a specialized response for tech, marketing, or investor.
    
    Args:
        label: "tech", "marketing", or "investor"
        vector_store_id: Vector store ID for this response
        enable_code_interpreter: Whether to enable code_interpreter tool
    """
    instructions = _get_specialized_instructions(label)
    
    name_map = {
        "tech": "TechAdvisor",
        "marketing": "MarketingAdvisor",
        "investor": "InvestorAdvisor"
    }
    
    return create_response(
        name=name_map.get(label, f"{label.capitalize()}Advisor"),
        vector_store_id=vector_store_id,
        enable_code_interpreter=enable_code_interpreter,
        instructions=instructions
    )

def _get_specialized_instructions(label: str) -> str:
    """Get specialized instructions for tech, marketing, or investor."""
    base = (
        "IMPORTANT: You MUST use the file_search tool to retrieve information from the knowledge base "
        "for EVERY user question, even if you think you know the answer. "
        "Always search the vector store first before responding. "
        "Use the retrieval tool on the attached vector store to provide concrete, actionable guidance and cite snippets when helpful. "
        "When possible, produce a JSON object with keys: "
        "`answer` (string) and `bullets` (array of strings). "
        "If you cite specifics, reference them inline and expect the system to attach sources. "
    )
    
    if label == "tech":
        return (
            base +
            "You are TechAdvisor, a YC-style technical advisor specializing in: "
            "- System architecture and scalability "
            "- AI/ML product patterns and model deployment "
            "- Infrastructure, databases, APIs, and tech stack decisions "
            "- Performance optimization and security "
            "- DevOps, CI/CD, and deployment strategies "
            "\n\n"
            "SCOPE ENFORCEMENT: If asked about fundraising, pitch decks, KPIs, or investor relations, "
            "briefly acknowledge the question and defer: 'This is better handled by InvestorAdvisor. "
            "For marketing, growth, or launch strategy questions, defer to MarketingAdvisor.' "
            "Then provide what technical insights you can from your domain. "
            "\n\n"
            "For technical calculations or quick computations, you may use code_interpreter if needed."
        )
    elif label == "marketing":
        return (
            base +
            "You are MarketingAdvisor, a YC-style marketing and growth advisor specializing in: "
            "- Launch strategy and go-to-market plans "
            "- Growth tactics and customer acquisition "
            "- Copywriting, messaging, and brand positioning "
            "- Content strategy, SEO, and distribution channels "
            "- Conversion optimization and funnel design "
            "\n\n"
            "SCOPE ENFORCEMENT: If asked about technical architecture, system design, or AI/ML models, "
            "briefly defer: 'This is better handled by TechAdvisor.' "
            "If asked about fundraising, pitch decks, KPIs, or investor relations, "
            "briefly defer: 'This is better handled by InvestorAdvisor.' "
            "Then provide what marketing insights you can from your domain."
        )
    elif label == "investor":
        return (
            base +
            "You are InvestorAdvisor, a YC-style fundraising and investor relations advisor specializing in: "
            "- Fundraising strategy and investor relations "
            "- Pitch deck creation and presentation "
            "- KPIs, financial metrics, and unit economics "
            "- Valuation, term sheets, and cap table management "
            "- Financial modeling and projections "
            "\n\n"
            "SCOPE ENFORCEMENT: If asked about technical architecture or system design, "
            "briefly defer: 'This is better handled by TechAdvisor.' "
            "If asked about marketing, growth, or launch strategy (unless related to investor pitch), "
            "briefly defer: 'This is better handled by MarketingAdvisor.' "
            "Then provide what investor/financial insights you can from your domain. "
            "\n\n"
            "For financial calculations, data analysis, financial projections, or visualizations, "
            "use the code_interpreter tool to run Python code. This is especially useful for: "
            "- Calculating metrics (burn rate, runway, growth rates, CAC, LTV, etc.) "
            "- Analyzing financial data and projections "
            "- Creating charts and visualizations "
            "- Performing statistical analysis "
            "- Modeling scenarios and what-if analyses."
        )
    else:
        return base

def _get_assistant_instructions():
    """Legacy function - kept for compatibility."""
    return (
        "You are a YC-style startup advisor. "
        "IMPORTANT: You MUST use the file_search tool to retrieve information from the knowledge base "
        "for EVERY user question, even if you think you know the answer. "
        "Always search the vector store first before responding. "
        "Use the retrieval tool on the attached vector store to provide concrete, actionable guidance and cite snippets when helpful. "
        "When possible, produce a JSON object with keys: "
        "`answer` (string) and `bullets` (array of strings). "
        "For analytics questions, use code_interpreter to run Python code for calculations and visualizations."
    )

# ---------------- File Management ----------------

def upload_file(file_content: bytes, filename: str, purpose: str = "assistants"):
    """
    Upload a file to OpenAI for use with responses.
    Returns the file object with file_id.
    """
    client = get_client()
    file_obj = io.BytesIO(file_content)
    file_obj.name = filename
    
    file = client.files.create(
        file=file_obj,
        purpose=purpose
    )
    return file

# ---------------- Response Operations ----------------
# These replace thread operations

# Conversation history tracking (in-memory for now)
_CONVERSATION_HISTORY: Dict[str, List[Dict[str, Any]]] = {}  # conversation_id -> messages

def add_message_to_response(
    conversation_id: str,
    role: str,
    content: str,
    file_ids: Optional[List[str]] = None
):
    """
    Add a message to conversation history (replaces thread message creation).
    
    In Responses API, we track conversation history ourselves and pass it as `input` when creating responses.
    
    Args:
        conversation_id: Conversation ID (replaces thread_id)
        role: "user" or "assistant"
        content: Message text content
        file_ids: Optional list of file IDs to attach (for code_interpreter)
    
    Returns:
        Message object (for compatibility)
    """
    # Track message in conversation history
    if conversation_id not in _CONVERSATION_HISTORY:
        _CONVERSATION_HISTORY[conversation_id] = []
    
    # In Responses API, files cannot be in attachments field
    # Files should be passed as a separate parameter at response creation level
    # For now, we'll store file_ids separately and pass them when creating the response
    message = {
        "role": role,
        "content": content,
    }
    
    # Store file_ids in a separate field that we'll extract when creating the response
    if file_ids:
        message["_file_ids"] = file_ids  # Internal field, not sent to API
    
    _CONVERSATION_HISTORY[conversation_id].append(message)
    
    # Return a simple object for compatibility
    class Message:
        def __init__(self, msg):
            self.role = msg["role"]
            self.content = msg["content"]
            # Extract file_ids from internal field
            self.attachments = []
            if "_file_ids" in msg:
                self.attachments = [
                    {"file_id": file_id, "tools": [{"type": "code_interpreter"}]}
                    for file_id in msg["_file_ids"]
                ]
    
    return Message(message)

def get_conversation_history(conversation_id: str) -> List[Dict[str, Any]]:
    """Get conversation history for a conversation ID."""
    return _CONVERSATION_HISTORY.get(conversation_id, [])

def run_response(
    conversation_id: str,
    response_config_id: str,
    stream: bool = False,
    instructions: Optional[str] = None,
    tools: Optional[List[Dict[str, Any]]] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Run a response to completion (replaces thread run).
    
    In Responses API, you create a response with `input` (messages) and `conversation` ID.
    The response executes immediately - no separate "run" step.
    
    Args:
        conversation_id: Conversation ID (replaces thread_id)
        response_config_id: Response configuration ID (from create_response, replaces assistant_id)
        stream: Whether to stream the response
        instructions: System instructions (if not in config)
        tools: Tools list (if not in config). Note: vector_store_ids are embedded directly in file_search tool definition.
    
    Yields:
        Response chunks if streaming, or final response if not
    """
    client = get_client()
    
    # Get response configuration to check which tools are enabled
    config = get_response_config(response_config_id)
    has_code_interpreter = False
    has_file_search = False
    if config:
        tools_list = config.get("tools", [])
        has_code_interpreter = any(tool.get("type") == "code_interpreter" for tool in tools_list)
        has_file_search = any(tool.get("type") == "file_search" for tool in tools_list)
    
    # Also check if tools are passed directly
    if tools:
        has_code_interpreter = has_code_interpreter or any(tool.get("type") == "code_interpreter" for tool in tools)
        has_file_search = has_file_search or any(tool.get("type") == "file_search" for tool in tools)
    
    # Get conversation history
    messages = get_conversation_history(conversation_id)
    if not messages:
        raise ValueError(f"No messages found for conversation {conversation_id}")
    
    # Collect all file_ids from messages for potential use at response level
    all_file_ids = []
    for msg in messages:
        if "_file_ids" in msg and msg["_file_ids"]:
            all_file_ids.extend(msg["_file_ids"])
    
    # Extract file_ids from messages and build proper input format
    # In Responses API, files should be in content array format
    # Note: input_file is for file_search (context stuffing), code_interpreter files might need different handling
    api_messages = []
    for msg in messages:
        api_msg = {
            "role": msg["role"],
            "content": msg["content"]
        }
        
        # If there are file_ids stored internally, add them to content array
        if "_file_ids" in msg and msg["_file_ids"]:
            # Convert content to array format with text and file parts
            # Responses API uses "input_text" for text
            # For files: use "input_file" only if file_search is enabled
            # For code_interpreter, files might need to be handled differently
            content_parts = []
            if msg["content"]:
                content_parts.append({"type": "input_text", "text": msg["content"]})
            
            # Add files to content
            # For code_interpreter: files are mounted in the container, not in input_file
            # For file_search: use input_file for PDFs
            if has_file_search and not has_code_interpreter:
                # Only file_search (no code_interpreter) - use input_file for PDFs
                for file_id in msg["_file_ids"]:
                    content_parts.append({
                        "type": "input_file",
                        "file_id": file_id
                    })
            # For code_interpreter, files will be passed in the tool's container configuration
            # Don't use input_file for CSV files when code_interpreter is enabled
            
            if content_parts:
                api_msg["content"] = content_parts
        
        api_messages.append(api_msg)
    
    # Build response parameters
    # In Responses API, input can be a string or array of messages
    # If we have multiple messages, use the array format
    # If we have a single user message, we could use string format, but array is safer
    response_params = {
        "model": get_model(),
        "input": api_messages,  # Array of messages (or could be string for single input)
    }
    
    # Add conversation ID if provided (may be optional in some cases)
    if conversation_id:
        response_params["conversation"] = conversation_id
    
    # Add instructions if provided
    if instructions:
        response_params["instructions"] = instructions
    
    # Add tools if provided
    # In Responses API, vector_store_ids are embedded directly in file_search tool definition
    # For code_interpreter, file_ids are passed in the container configuration
    if tools:
        # If code_interpreter is enabled and we have file_ids, mount them in the container
        if has_code_interpreter and all_file_ids:
            # Update tools to include file_ids in code_interpreter container
            updated_tools = []
            for tool in tools:
                if tool.get("type") == "code_interpreter":
                    # Mount files in the code_interpreter container
                    updated_tool = tool.copy()
                    if "container" not in updated_tool:
                        updated_tool["container"] = {"type": "auto"}
                    updated_tool["container"]["file_ids"] = all_file_ids
                    updated_tools.append(updated_tool)
                else:
                    updated_tools.append(tool)
            response_params["tools"] = updated_tools
        else:
            response_params["tools"] = tools
    elif has_code_interpreter and all_file_ids:
        # Tools not provided but code_interpreter is enabled - create tools with file_ids
        response_params["tools"] = [{
            "type": "code_interpreter",
            "container": {
                "type": "auto",
                "file_ids": all_file_ids
            }
        }]

    # Validate tool arguments against JSON Schema before any tool execution.
    if "tools" in response_params:
        schema_ok, schema_error = validate_tool_args(response_params["tools"])
        if not schema_ok:
            _record_schema_violation("workflow_tools", schema_error)
            yield {
                "type": "error",
                "error": "TOOL_SCHEMA_VALIDATION_ERROR",
                "schema_valid": False,
                "tool_name": "workflow_tools",
                "details": schema_error,
                "failure_mode": "schema_validation",
            }
            return
    
    # Use Responses API
    # Try responses first, then beta.responses (depending on SDK version)
    if hasattr(client, 'responses'):
        # Add stream parameter if streaming
        if stream:
            response_params["stream"] = True
        response = None
        for attempt in range(2):
            try:
                response = client.responses.create(**response_params)
                break
            except Exception as e:
                if attempt == 0 and _is_retryable_tool_error(e):
                    continue
                if _is_timeout_error(e):
                    yield {
                        "type": "done",
                        "answer": "",
                        "sources": [],
                        "images": [],
                        "usage": {},
                        "warning": "tool_timeout",
                        "partial": True,
                        "failure_mode": "timeout",
                    }
                    return
                yield {
                    "type": "error",
                    "error": f"Tool execution failed after retry: {str(e)}",
                    "failure_mode": "tool_failure",
                }
                return
        
        if stream:
            # Streaming: iterate over response stream
            accumulated_text = ""
            citations = []
            images = []
            event_count = 0
            
            try:
                for event in response:
                    event_count += 1
                    
                    event_type = None
                    if hasattr(event, "type"):
                        event_type = event.type
                    elif isinstance(event, dict):
                        event_type = event.get("type")
                    
                    
                    # Parse streaming events
                    parsed = _parse_response_stream_event(event, accumulated_text)
                    if parsed:
                        if parsed.get("type") == "text_delta":
                            delta = parsed.get("content", "")
                            accumulated_text += delta
                            
                            # Handle sources if they came with the text delta
                            if parsed.get("sources"):
                                citations.extend(parsed.get("sources", []))
                                yield {
                                    "type": "sources",
                                    "sources": _dedupe_sources(citations)
                                }
                            
                            yield {
                                "type": "text_delta",
                                "content": delta,
                                "accumulated": accumulated_text
                            }
                        elif parsed.get("type") == "sources":
                            citations.extend(parsed.get("sources", []))
                            yield {
                                "type": "sources",
                                "sources": _dedupe_sources(citations)
                            }
                        elif parsed.get("type") == "images":
                            images.extend(parsed.get("images", []))
                            yield {
                                "type": "images",
                                "images": images
                            }
                        elif parsed.get("type") == "done":
                            # Final event
                            extracted = _extract_text_and_citations_from_response(parsed.get("response"))
                            if extracted["text"]:
                                add_message_to_response(conversation_id, "assistant", extracted["text"])
                            yield {
                                "type": "done",
                                "answer": extracted["text"],
                                "sources": extracted["citations"],
                                "images": extracted.get("images", []),
                                "usage": _usage_to_dict(parsed.get("usage"))
                            }
                    else:
                        # If parsing returned None, try to extract text directly from event
                        # This handles cases where the event structure doesn't match our parser
                        if event_count == 1:
                            # First event - might be the full response if streaming isn't working
                            extracted = _extract_text_and_citations_from_response(event)
                            if extracted["text"]:
                                accumulated_text = extracted["text"]
                                yield {
                                    "type": "text_delta",
                                    "content": extracted["text"],
                                    "accumulated": accumulated_text
                                }
                                if extracted["citations"]:
                                    citations.extend(extracted["citations"])
                                    yield {
                                        "type": "sources",
                                        "sources": _dedupe_sources(citations)
                                    }
                                if extracted["images"]:
                                    images.extend(extracted["images"])
                                    yield {
                                        "type": "images",
                                        "images": images
                                    }
                                # Yield done event
                                if extracted["text"]:
                                    add_message_to_response(conversation_id, "assistant", extracted["text"])
                                yield {
                                    "type": "done",
                                    "answer": extracted["text"],
                                    "sources": extracted["citations"],
                                    "images": extracted.get("images", []),
                                    "usage": getattr(event, "usage", {}) if hasattr(event, "usage") else {}
                                }
                                break
                
                # If we processed events but got no text, yield an error
                if event_count > 0 and not accumulated_text:
                    yield {
                        "type": "error",
                        "error": f"Stream completed but no text was extracted. Processed {event_count} events. The Responses API streaming format may differ from expected. Please check the API documentation."
                    }
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                yield {
                    "type": "error",
                    "error": f"Stream error: {str(e)}",
                    "traceback": error_trace
                }
        else:
            # Non-streaming: extract response data
            extracted = _extract_text_and_citations_from_response(response)
            
            # Add assistant message to conversation history
            if extracted["text"]:
                add_message_to_response(conversation_id, "assistant", extracted["text"])
            
            yield {
                "type": "done",
                "answer": extracted["text"],
                "sources": extracted["citations"],
                "images": extracted.get("images", []),
                "usage": _usage_to_dict(getattr(response, "usage", None))
            }
    elif hasattr(client.beta, 'responses'):
        # Try beta.responses
        if stream:
            response_params["stream"] = True
        response = None
        for attempt in range(2):
            try:
                response = client.beta.responses.create(**response_params)
                break
            except Exception as e:
                if attempt == 0 and _is_retryable_tool_error(e):
                    continue
                if _is_timeout_error(e):
                    yield {
                        "type": "done",
                        "answer": "",
                        "sources": [],
                        "images": [],
                        "usage": {},
                        "warning": "tool_timeout",
                        "partial": True,
                        "failure_mode": "timeout",
                    }
                    return
                yield {
                    "type": "error",
                    "error": f"Tool execution failed after retry: {str(e)}",
                    "failure_mode": "tool_failure",
                }
                return
        
        if stream:
            # Streaming: iterate over response stream
            accumulated_text = ""
            citations = []
            images = []
            event_count = 0
            
            try:
                for event in response:
                    event_count += 1
                    parsed = _parse_response_stream_event(event, accumulated_text)
                    if parsed:
                        if parsed.get("type") == "text_delta":
                            delta = parsed.get("content", "")
                            accumulated_text += delta
                            yield {
                                "type": "text_delta",
                                "content": delta,
                                "accumulated": accumulated_text
                            }
                        elif parsed.get("type") == "sources":
                            citations.extend(parsed.get("sources", []))
                            yield {
                                "type": "sources",
                                "sources": _dedupe_sources(citations)
                            }
                        elif parsed.get("type") == "images":
                            images.extend(parsed.get("images", []))
                            yield {
                                "type": "images",
                                "images": images
                            }
                        elif parsed.get("type") == "done":
                            extracted = _extract_text_and_citations_from_response(parsed.get("response"))
                            if extracted["text"]:
                                add_message_to_response(conversation_id, "assistant", extracted["text"])
                            yield {
                                "type": "done",
                                "answer": extracted["text"],
                                "sources": extracted["citations"],
                                "images": extracted.get("images", []),
                                "usage": _usage_to_dict(parsed.get("usage"))
                            }
                    else:
                        # If parsing returned None, try to extract text directly from event
                        if event_count == 1:
                            extracted = _extract_text_and_citations_from_response(event)
                            if extracted["text"]:
                                accumulated_text = extracted["text"]
                                yield {
                                    "type": "text_delta",
                                    "content": extracted["text"],
                                    "accumulated": accumulated_text
                                }
                                if extracted["citations"]:
                                    citations.extend(extracted["citations"])
                                    yield {
                                        "type": "sources",
                                        "sources": _dedupe_sources(citations)
                                    }
                                if extracted["images"]:
                                    images.extend(extracted["images"])
                                    yield {
                                        "type": "images",
                                        "images": images
                                    }
                                if extracted["text"]:
                                    add_message_to_response(conversation_id, "assistant", extracted["text"])
                                yield {
                                    "type": "done",
                                    "answer": extracted["text"],
                                    "sources": extracted["citations"],
                                    "images": extracted.get("images", []),
                                    "usage": getattr(event, "usage", {}) if hasattr(event, "usage") else {}
                                }
                                break
                
                # If we processed events but got no text, yield an error
                if event_count > 0 and not accumulated_text:
                    yield {
                        "type": "error",
                        "error": f"Stream completed but no text was extracted. Processed {event_count} events. The Responses API streaming format may differ from expected."
                    }
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                yield {
                    "type": "error",
                    "error": f"Stream error: {str(e)}",
                    "traceback": error_trace
                }
        else:
            # Non-streaming: extract from response object
            extracted = _extract_text_and_citations_from_response(response)
            if extracted["text"]:
                add_message_to_response(conversation_id, "assistant", extracted["text"])
            
            # Extract images from response
            extracted_images = extracted.get("images", [])
            
            # In Responses API, code_interpreter generates files but file IDs need to be extracted
            # The file IDs might be:
            # 1. In the response output content (output_image type) - already checked above
            # 2. Mentioned in the response text (e.g., "file-abc123" or sandbox paths)
            # 3. Need to be retrieved from container
            # Since outputs are null, try to extract file IDs from response text as fallback
            if has_code_interpreter and not extracted_images:
                response_text = extracted.get("text", "")
                # Look for file IDs in the text (pattern: file- followed by alphanumeric)
                import re
                file_id_pattern = r'file-[a-zA-Z0-9_-]+'
                potential_file_ids = re.findall(file_id_pattern, response_text)
                
                # Also check for file references in sandbox paths (e.g., "sandbox:/mnt/data/file-abc123.png")
                sandbox_pattern = r'sandbox:/mnt/data/([^)\s]+)'
                sandbox_matches = re.findall(sandbox_pattern, response_text)
                
                if potential_file_ids:
                    # Try to download each potential file ID as an image
                    client = get_client()
                    for file_id in potential_file_ids:
                        try:
                            # Try to retrieve file info to verify it's an image
                            file_info = client.files.retrieve(file_id)
                            # Check if it's an image file
                            filename = getattr(file_info, "filename", "")
                            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                                extracted_images.append({"file_id": file_id})
                        except Exception as e:
                            # Not a valid file or not accessible - skip
                            pass
                
                # Also try to get files from containers if we have container IDs
                try:
                    output = getattr(response, "output", None)
                    if not output and hasattr(response, "model_dump"):
                        response_dict = response.model_dump()
                        output = response_dict.get("output")
                    
                    if output and isinstance(output, list):
                        container_ids = set()
                        for output_item in output:
                            output_type = getattr(output_item, "type", None)
                            if not output_type and isinstance(output_item, dict):
                                output_type = output_item.get("type")
                            
                            if output_type == "code_interpreter_call":
                                container_id = getattr(output_item, "container_id", None)
                                if not container_id and isinstance(output_item, dict):
                                    container_id = output_item.get("container_id")
                                
                                if container_id:
                                    container_ids.add(container_id)
                        
                        # Try to get files from containers
                        # Note: This might require a different API endpoint
                        # TODO: Implement container file listing if API supports it
                except Exception:
                    pass
            
            yield {
                "type": "done",
                "answer": extracted["text"],
                "sources": extracted["citations"],
                "images": extracted_images,
                "usage": _usage_to_dict(getattr(response, "usage", None))
            }
    else:
        raise NotImplementedError(
            "Responses API is not available in this SDK version. "
            "Please update the OpenAI Python SDK to a version that supports Responses API: "
            "pip install --upgrade openai"
        )

def _get_files_from_container(container_id: str) -> List[str]:
    """
    Attempt to get file IDs from a code_interpreter container.
    Note: This might not be directly supported by the API, but we'll try.
    """
    # TODO: Check if there's an API endpoint to list container files
    # For now, return empty list
    return []

def _extract_text_and_citations_from_response(response) -> Dict[str, Any]:
    """
    Extract text, citations, and images from a Responses API response object.
    
    Response structure:
    - Text: response.output[].content[].text
    - Citations: response.output[].content[].annotations[].file_citation
    - Images: response.output[].content[].image.file_id (when type == "output_image")
    
    Also tries alternative structures:
    - response.items[].content[].text
    - response.content[].text
    - response.citations (if citations are at top level)
    """
    text_parts: List[str] = []
    citations: List[Dict[str, str]] = []
    images: List[Dict[str, str]] = []
    
    # Try to get output using getattr (more robust for SDK objects)
    output = None
    try:
        if hasattr(response, "output"):
            output = response.output
        elif isinstance(response, dict):
            output = response.get("output")
    except Exception:
        pass
    
    # Check if citations are at the top level of the response
    top_level_citations = None
    if hasattr(response, "citations"):
        top_level_citations = response.citations
    elif isinstance(response, dict):
        top_level_citations = response.get("citations")
    
    if top_level_citations and isinstance(top_level_citations, list):
        for cit in top_level_citations:
            file_id = None
            if hasattr(cit, "file_id"):
                file_id = cit.file_id
            elif isinstance(cit, dict):
                file_id = cit.get("file_id")
            
            if file_id:
                quote = ""
                if hasattr(cit, "quote"):
                    quote = getattr(cit, "quote", "") or ""
                elif isinstance(cit, dict):
                    quote = cit.get("quote", "") or ""
                
                citations.append({
                    "file_id": file_id,
                    "quote": quote
                })
    
    # Check for images at top level of response (some API versions might have this)
    if hasattr(response, "images"):
        top_level_images = response.images
        if isinstance(top_level_images, list):
            for img in top_level_images:
                file_id = None
                if hasattr(img, "file_id"):
                    file_id = img.file_id
                elif isinstance(img, dict):
                    file_id = img.get("file_id")
                elif isinstance(img, str):
                    file_id = img
                
                if file_id:
                    images.append({"file_id": file_id})
    elif isinstance(response, dict):
        top_level_images = response.get("images")
        if isinstance(top_level_images, list):
            for img in top_level_images:
                file_id = None
                if isinstance(img, dict):
                    file_id = img.get("file_id")
                elif isinstance(img, str):
                    file_id = img
                
                if file_id:
                    images.append({"file_id": file_id})
    
    # Try alternative locations if output is not found
    if not output:
        # Try response.items (some API versions might use this)
        if hasattr(response, "items"):
            output = response.items
        elif isinstance(response, dict):
            output = response.get("items")
        
        # Try response.content directly
        if not output:
            if hasattr(response, "content"):
                # If content is a list, wrap it in a list of output items
                content = response.content
                if isinstance(content, list):
                    output = [{"content": content}]
            elif isinstance(response, dict):
                content = response.get("content")
                if isinstance(content, list):
                    output = [{"content": content}]
        
    
    if not output:
        # If no output found, return what we have (might have found images at top level)
        return {
            "text": "",
            "citations": [],
            "images": images
        }
    
    # Iterate through output array (using getattr pattern like user's example)
    if isinstance(output, list):
        for idx, output_item in enumerate(output):
            
            # Check if this is a code_interpreter tool call - images are in the outputs attribute
            output_type = getattr(output_item, "type", None)
            if not output_type and isinstance(output_item, dict):
                output_type = output_item.get("type")
            
            # For code_interpreter tool calls, check the outputs attribute for images
            # In Responses API, code_interpreter generates files but outputs might be null
            # We need to check the container for generated files or look for file references
            if output_type == "code_interpreter_call":
                container_id = getattr(output_item, "container_id", None)
                if not container_id and isinstance(output_item, dict):
                    container_id = output_item.get("container_id")
                
                # Try to get files from container using the Files API
                # Note: This might require a different API endpoint
                # For now, we'll check outputs first, then try container files
                outputs = getattr(output_item, "outputs", None)
                if not outputs and isinstance(output_item, dict):
                    outputs = output_item.get("outputs")
                
                # Try model_dump if it's a Pydantic model
                if not outputs and hasattr(output_item, "model_dump"):
                    try:
                        dumped = output_item.model_dump()
                        outputs = dumped.get("outputs")
                    except:
                        pass
                
                if outputs:
                    # Outputs might be a list of output items (which could contain images)
                    if isinstance(outputs, list):
                        for output_idx, output in enumerate(outputs):
                            # Check if this output has image content
                            output_content = getattr(output, "content", None)
                            if not output_content and isinstance(output, dict):
                                output_content = output.get("content")
                            
                            if output_content:
                                # Process this output's content for images
                                if isinstance(output_content, list):
                                    for content_item in output_content:
                                        content_type = getattr(content_item, "type", None)
                                        if not content_type and isinstance(content_item, dict):
                                            content_type = content_item.get("type")
                                        
                                        if content_type == "output_image":
                                            image_obj = getattr(content_item, "image", None)
                                            if not image_obj and isinstance(content_item, dict):
                                                image_obj = content_item.get("image")
                                            
                                            if image_obj:
                                                file_id = getattr(image_obj, "file_id", None)
                                                if not file_id and isinstance(image_obj, dict):
                                                    file_id = image_obj.get("file_id")
                                                
                                                if file_id:
                                                    images.append({"file_id": file_id})
                                elif hasattr(output_content, "type"):
                                    # Single content item
                                    if getattr(output_content, "type", None) == "output_image":
                                        image_obj = getattr(output_content, "image", None)
                                        if image_obj:
                                            file_id = getattr(image_obj, "file_id", None)
                                            if file_id:
                                                images.append({"file_id": file_id})
            
            # Get content array from output item using getattr (for message types)
            content = getattr(output_item, "content", None)
            if not content and isinstance(output_item, dict):
                content = output_item.get("content")
            
            # Also try other possible attribute names
            if not content:
                if isinstance(output_item, dict):
                    # Check for other possible keys
                    for key in ["contents", "items", "data"]:
                        if key in output_item:
                            potential_content = output_item[key]
                            if isinstance(potential_content, list):
                                content = potential_content
                                break
                else:
                    # Try other attribute names
                    for attr_name in ["contents", "items", "data"]:
                        if hasattr(output_item, attr_name):
                            potential_content = getattr(output_item, attr_name)
                            if isinstance(potential_content, list):
                                content = potential_content
                                break
            
            if not content or not isinstance(content, list):
                # Skip if no content (already processed code_interpreter outputs above)
                continue
            
            # Iterate through content array
            for content_idx, content_item in enumerate(content):
                # First check the content type to see if it's an image
                # Use getattr pattern like the user's example
                content_type = getattr(content_item, "type", None)
                if not content_type and isinstance(content_item, dict):
                    content_type = content_item.get("type")
                
                # Handle image content types FIRST (before text extraction)
                # This ensures we catch images even if they're mixed with text
                # Based on Responses API structure:
                # content_item = {"type": "output_image", "image": {"file_id": "file-abc123", "format": "png"}}
                if content_type == "output_image":
                    # Handle output_image content type (from code_interpreter)
                    # Structure: content.image.file_id (exactly as user's example)
                    image_obj = getattr(content_item, "image", None)
                    if not image_obj and isinstance(content_item, dict):
                        image_obj = content_item.get("image")
                    
                    if image_obj:
                        file_id = getattr(image_obj, "file_id", None)
                        if not file_id and isinstance(image_obj, dict):
                            file_id = image_obj.get("file_id")
                        
                        if file_id:
                            images.append({"file_id": file_id})
                            continue  # Skip text extraction for image items
                
                elif content_type == "image_file":
                    # Handle image_file content type (alternative format)
                    image_file_obj = None
                    if hasattr(content_item, "image_file"):
                        image_file_obj = content_item.image_file
                    elif isinstance(content_item, dict):
                        image_file_obj = content_item.get("image_file")
                    
                    if image_file_obj:
                        file_id = None
                        if hasattr(image_file_obj, "file_id"):
                            file_id = image_file_obj.file_id
                        elif isinstance(image_file_obj, dict):
                            file_id = image_file_obj.get("file_id")
                        
                        if file_id:
                            images.append({"file_id": file_id})
                            continue  # Skip text extraction for image items
                
                elif content_type == "output_file":
                    # Handle output_file content type (from code_interpreter)
                    output_file_obj = None
                    if hasattr(content_item, "output_file"):
                        output_file_obj = content_item.output_file
                    elif isinstance(content_item, dict):
                        output_file_obj = content_item.get("output_file")
                    
                    if output_file_obj:
                        file_id = None
                        if hasattr(output_file_obj, "file_id"):
                            file_id = output_file_obj.file_id
                        elif isinstance(output_file_obj, dict):
                            file_id = output_file_obj.get("file_id")
                        
                        if file_id:
                            images.append({"file_id": file_id})
                            continue  # Skip text extraction for image items
                
                # Handle text content - try multiple formats
                # Based on actual Responses API structure:
                # content_item = {"type": "output_text", "text": "actual text string", "annotations": []}
                text_value = ""
                annotations = []
                
                # Check if content_item itself is a string
                if isinstance(content_item, str):
                    text_value = content_item
                # Check if content_item is a dict with "text" key (most common case)
                elif isinstance(content_item, dict):
                    # Text is directly in the dict as "text" key (string value)
                    text_value = content_item.get("text", "") or ""
                    # Annotations are also directly in the dict
                    annotations = content_item.get("annotations", []) or []
                # Check if content_item has a text attribute (object case)
                elif hasattr(content_item, "text"):
                    # Text might be a string directly
                    text_attr = content_item.text
                    if isinstance(text_attr, str):
                        text_value = text_attr
                    elif hasattr(text_attr, "value"):
                        text_value = text_attr.value or ""
                    elif isinstance(text_attr, dict):
                        text_value = text_attr.get("value", "") or ""
                    
                    # Get annotations - check both content_item and text_attr
                    if hasattr(content_item, "annotations"):
                        annotations = content_item.annotations or []
                    elif hasattr(text_attr, "annotations"):
                        annotations = text_attr.annotations or []
                    elif isinstance(text_attr, dict):
                        annotations = text_attr.get("annotations", []) or []
                
                if text_value:
                    text_parts.append(text_value)
                
                # Extract annotations (citations and images) from annotations array
                # Do this even if text_value is empty, in case citations are standalone
                if annotations:
                    for ann in annotations:
                        # Check annotation type - could be "file_citation" or "container_file_citation"
                        ann_type = None
                        if hasattr(ann, "type"):
                            ann_type = ann.type
                        elif isinstance(ann, dict):
                            ann_type = ann.get("type")
                        
                        # Handle container_file_citation - these can contain image file IDs
                        if ann_type == "container_file_citation":
                            # Extract file_id and container_id from container_file_citation
                            file_id = None
                            filename = None
                            container_id = None
                            
                            if hasattr(ann, "file_id"):
                                file_id = ann.file_id
                            elif isinstance(ann, dict):
                                file_id = ann.get("file_id")
                            
                            if hasattr(ann, "filename"):
                                filename = ann.filename
                            elif isinstance(ann, dict):
                                filename = ann.get("filename")
                            
                            if hasattr(ann, "container_id"):
                                container_id = ann.container_id
                            elif isinstance(ann, dict):
                                container_id = ann.get("container_id")
                            
                            # Check if this is an image file based on filename
                            if file_id and filename:
                                filename_lower = filename.lower()
                                if filename_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')):
                                    images.append({
                                        "file_id": file_id,
                                        "container_id": container_id  # Store container_id for downloading
                                    })
                                    continue  # Skip citation processing for images
                        
                        # Only process file_citation annotations for citations
                        if ann_type != "file_citation":
                            continue
                        
                        # Get file_citation - could be nested or direct
                        file_citation = None
                        file_id = None
                        quote = ""
                        
                        # Try nested structure first (file_citation object)
                        if hasattr(ann, "file_citation"):
                            file_citation = ann.file_citation
                        elif isinstance(ann, dict):
                            file_citation = ann.get("file_citation")
                        
                        if file_citation:
                            # Nested structure: ann.file_citation.file_id
                            if hasattr(file_citation, "file_id"):
                                file_id = file_citation.file_id
                            elif isinstance(file_citation, dict):
                                file_id = file_citation.get("file_id")
                            
                            if hasattr(file_citation, "quote"):
                                quote = getattr(file_citation, "quote", "") or ""
                            elif isinstance(file_citation, dict):
                                quote = file_citation.get("quote", "") or ""
                        else:
                            # Direct structure: ann.file_id (file_id directly on annotation)
                            if hasattr(ann, "file_id"):
                                file_id = ann.file_id
                            elif isinstance(ann, dict):
                                file_id = ann.get("file_id")
                            
                            # Quote might be directly on annotation too
                            if hasattr(ann, "quote"):
                                quote = getattr(ann, "quote", "") or ""
                            elif isinstance(ann, dict):
                                quote = ann.get("quote", "") or ""
                        
                        if file_id:
                            citations.append({
                                "file_id": file_id,
                                "quote": quote
                            })
                
                # Handle legacy "image" structure (fallback) - only if not already handled above
                if content_type == "image" or (not content_type and hasattr(content_item, "image")):
                    image_obj = None
                    if hasattr(content_item, "image"):
                        image_obj = content_item.image
                    elif isinstance(content_item, dict):
                        image_obj = content_item.get("image")
                    
                    if image_obj:
                        file_id = None
                        if hasattr(image_obj, "file_id"):
                            file_id = image_obj.file_id
                        elif isinstance(image_obj, dict):
                            file_id = image_obj.get("file_id")
                        
                        if file_id:
                            images.append({"file_id": file_id})
    
    # If no citations found in annotations, try extracting from citation markers in text
    if not citations and text_parts:
        full_text = "\n".join(text_parts)
        marker_citations = _extract_citations_from_markers(full_text)
        if marker_citations:
            citations.extend(marker_citations)
    
    return {
        "text": "\n".join(text_parts).strip(),
        "citations": citations,
        "images": images
    }

def _parse_response_stream_event(event, accumulated_text: str = "") -> Optional[Dict[str, Any]]:
    """
    Parse a streaming event from Responses API.
    
    Actual event structure based on logs:
    - type: "response.created", "response.in_progress", "response.output_item.added", "response.output_item.delta", "response.completed"
    - item: Contains the actual content when type is "response.output_item.added" or "response.output_item.delta"
    """
    # Get event type
    event_type = None
    if hasattr(event, "type"):
        event_type = event.type
    elif isinstance(event, dict):
        event_type = event.get("type")
    elif hasattr(event, "__dict__") and "type" in event.__dict__:
        event_type = event.__dict__["type"]
    
    # Handle different event types
    # Newer SDKs emit response.output_text.* events directly.
    if event_type == "response.output_text.delta":
        delta_text = None
        if hasattr(event, "delta"):
            delta = event.delta
            if isinstance(delta, str):
                delta_text = delta
            elif hasattr(delta, "text"):
                delta_text = delta.text
            elif isinstance(delta, dict):
                delta_text = delta.get("text") or delta.get("value")
        elif isinstance(event, dict):
            delta = event.get("delta")
            if isinstance(delta, str):
                delta_text = delta
            elif isinstance(delta, dict):
                delta_text = delta.get("text") or delta.get("value")

        if delta_text:
            return {
                "type": "text_delta",
                "content": str(delta_text),
            }

    elif event_type == "response.output_text.done":
        # Keep stream open for final response.completed event; no-op here.
        return None

    if event_type == "response.output_item.added":
        # New output item was added - extract text from item
        item = None
        if hasattr(event, "item"):
            item = event.item
        elif isinstance(event, dict):
            item = event.get("item")
        
        if item:
            # Check if this is a tool call (skip it)
            item_type = None
            if hasattr(item, "type"):
                item_type = item.type
            elif isinstance(item, dict):
                item_type = item.get("type")
            elif "ToolCall" in str(type(item)):
                # Skip tool calls
                return None
            
            # Only process text output items
            if item_type == "output_text" or "OutputText" in str(type(item)) or (not item_type and hasattr(item, "text")):
                # Try to extract text from the item
                # Item might be a ResponseOutputText or similar object
                text_content = None
                
                # Check if item has text directly
                if hasattr(item, "text"):
                    text_obj = item.text
                    if hasattr(text_obj, "value"):
                        text_content = text_obj.value
                    elif isinstance(text_obj, str):
                        text_content = text_obj
                elif hasattr(item, "content"):
                    content = item.content
                    if isinstance(content, str):
                        text_content = content
                    elif isinstance(content, list):
                        # Content might be a list of content items
                        for content_item in content:
                            if hasattr(content_item, "text"):
                                text_obj = content_item.text
                                if hasattr(text_obj, "value"):
                                    text_content = text_obj.value
                                    break
                            elif isinstance(content_item, dict) and "text" in content_item:
                                text_obj = content_item["text"]
                                if isinstance(text_obj, dict) and "value" in text_obj:
                                    text_content = text_obj["value"]
                                    break
                
                # Also check for annotations/citations in the text
                citations = []
                if hasattr(item, "text") and hasattr(item.text, "annotations"):
                    annotations = item.text.annotations or []
                    for ann in annotations:
                        if hasattr(ann, "file_citation"):
                            fc = ann.file_citation
                            file_id = getattr(fc, "file_id", None) if fc else None
                            quote = getattr(fc, "quote", "") if fc else ""
                            if file_id:
                                citations.append({"file_id": file_id, "quote": quote})
                
                if text_content:
                    return {
                        "type": "text_delta",
                        "content": text_content,
                        "sources": citations if citations else None
                    }
    
    elif event_type == "response.output_item.delta":
        # Incremental update to output item - extract delta text
        item = None
        if hasattr(event, "item"):
            item = event.item
        elif isinstance(event, dict):
            item = event.get("item")
        
        if item:
            # Extract delta text
            text_content = None
            if hasattr(item, "text"):
                text_obj = item.text
                if hasattr(text_obj, "value"):
                    text_content = text_obj.value
                elif isinstance(text_obj, str):
                    text_content = text_obj
            elif hasattr(item, "delta"):
                delta = item.delta
                if hasattr(delta, "text"):
                    text_obj = delta.text
                    if hasattr(text_obj, "value"):
                        text_content = text_obj.value
                elif isinstance(delta, dict):
                    text_obj = delta.get("text")
                    if isinstance(text_obj, dict):
                        text_content = text_obj.get("value")
                    elif isinstance(text_obj, str):
                        text_content = text_obj
            
            if text_content:
                return {
                    "type": "text_delta",
                    "content": text_content
                }
    
    elif event_type == "response.completed":
        # Final event - extract full response
        response_obj = None
        if hasattr(event, "response"):
            response_obj = event.response
        elif isinstance(event, dict):
            response_obj = event.get("response")
        
        if response_obj:
            extracted = _extract_text_and_citations_from_response(response_obj)
            return {
                "type": "done",
                "response": response_obj,
                "usage": getattr(response_obj, "usage", {}) if hasattr(response_obj, "usage") else {}
            }
        else:
            # Fallback: use the event itself
            return {
                "type": "done",
                "response": event,
                "usage": getattr(event, "usage", {}) if hasattr(event, "usage") else {}
            }
    
    # Legacy fallback methods (keep for compatibility)
    # Try multiple ways to access the event structure
    # Method 1: Check for output_text.delta (documented structure)
    output_text = None
    if hasattr(event, "output_text"):
        output_text = event.output_text
    elif isinstance(event, dict):
        output_text = event.get("output_text")
    elif hasattr(event, "data") and hasattr(event.data, "output_text"):
        output_text = event.data.output_text
    
    if output_text:
        delta = None
        if hasattr(output_text, "delta"):
            delta = output_text.delta
        elif isinstance(output_text, dict):
            delta = output_text.get("delta")
        
        if delta:
            # Extract text from delta
            text_content = ""
            if hasattr(delta, "text"):
                text_obj = delta.text
                if hasattr(text_obj, "value"):
                    text_content = text_obj.value or ""
                elif isinstance(text_obj, dict):
                    text_content = text_obj.get("value", "")
            elif isinstance(delta, dict):
                text_obj = delta.get("text")
                if isinstance(text_obj, dict):
                    text_content = text_obj.get("value", "")
                elif hasattr(text_obj, "value"):
                    text_content = text_obj.value or ""
            elif hasattr(delta, "value"):
                text_content = delta.value or ""
            elif isinstance(delta, str):
                text_content = delta
            
            if text_content:
                return {
                    "type": "text_delta",
                    "content": text_content
                }
    
    # Method 2: Check for direct text content in event
    if hasattr(event, "text"):
        text_content = event.text
        if isinstance(text_content, str) and text_content:
            return {
                "type": "text_delta",
                "content": text_content
            }
    elif isinstance(event, dict) and "text" in event:
        text_content = event.get("text")
        if isinstance(text_content, str) and text_content:
            return {
                "type": "text_delta",
                "content": text_content
            }
    
    # Method 3: Check for content field
    if hasattr(event, "content"):
        content = event.content
        if isinstance(content, str) and content:
            return {
                "type": "text_delta",
                "content": content
            }
    elif isinstance(event, dict) and "content" in event:
        content = event.get("content")
        if isinstance(content, str) and content:
            return {
                "type": "text_delta",
                "content": content
            }
    
    # Method 4: Check for delta field directly
    if hasattr(event, "delta"):
        delta = event.delta
        if hasattr(delta, "content"):
            content = delta.content
            if isinstance(content, str) and content:
                return {
                    "type": "text_delta",
                    "content": content
                }
        elif isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                return {
                    "type": "text_delta",
                    "content": content
                }
    
    # Try to get output_image delta (image streaming)
    output_image = None
    if hasattr(event, "output_image"):
        output_image = event.output_image
    elif isinstance(event, dict):
        output_image = event.get("output_image")
    
    if output_image:
        delta = None
        if hasattr(output_image, "delta"):
            delta = output_image.delta
        elif isinstance(output_image, dict):
            delta = output_image.get("delta")
        
        if delta:
            file_id = None
            if hasattr(delta, "file_id"):
                file_id = delta.file_id
            elif isinstance(delta, dict):
                file_id = delta.get("file_id")
            
            if file_id:
                return {
                    "type": "images",
                    "images": [{"file_id": file_id}]
                }
    
    # Check if this is a completion event
    if hasattr(event, "status"):
        status = event.status
    elif isinstance(event, dict):
        status = event.get("status")
    else:
        status = None
    
    if status == "completed":
        # Final event - return the full response
        return {
            "type": "done",
            "response": event,
            "usage": _usage_to_dict(getattr(event, "usage", None) if hasattr(event, "usage") else (event.get("usage") if isinstance(event, dict) else None))
        }
    
    # Method 5: If event has an 'output' field, try to extract from it
    if hasattr(event, "output"):
        output = event.output
        if isinstance(output, list) and len(output) > 0:
            # Try to extract text from first output item
            first_output = output[0]
            if hasattr(first_output, "content"):
                content_list = first_output.content
                if isinstance(content_list, list):
                    for content_item in content_list:
                        if hasattr(content_item, "text"):
                            text_obj = content_item.text
                            if hasattr(text_obj, "value"):
                                text_value = text_obj.value
                                if text_value:
                                    return {
                                        "type": "text_delta",
                                        "content": text_value
                                    }
    
    return None

def _parse_assistant_stream_event(event) -> Dict[str, Any]:
    """Parse an Assistants API stream event into Responses API format."""
    # This is a simplified parser - will need to be expanded based on actual events
    event_type = getattr(event, "event", None)
    
    if event_type == "thread.message.delta":
        # Text delta
        if hasattr(event, "data") and hasattr(event.data, "delta"):
            delta = event.data.delta
            if hasattr(delta, "content") and delta.content:
                for content_item in delta.content:
                    if hasattr(content_item, "type") and content_item.type == "text":
                        if hasattr(content_item, "text") and hasattr(content_item.text, "value"):
                            return {
                                "type": "text_delta",
                                "content": content_item.text.value,
                                "delta": content_item.text.value,
                                "accumulated": ""  # Will be accumulated by caller
                            }
    
    return {
        "type": "unknown",
        "content": ""
    }

def _parse_response_chunk(chunk) -> Dict[str, Any]:
    """Parse a streaming response chunk."""
    # Implementation depends on actual API structure
    # This is a placeholder that will need to be updated
    return {
        "type": "text_delta",
        "content": getattr(chunk, "content", ""),
        "delta": getattr(chunk, "delta", ""),
        "accumulated": getattr(chunk, "accumulated", "")
    }

def _parse_response(response) -> Dict[str, Any]:
    """Parse a completed response."""
    # Implementation depends on actual API structure
    # This is a placeholder that will need to be updated
    return {
        "type": "done",
        "answer": getattr(response, "content", ""),
        "sources": [],
        "images": []
    }

# ---------------- Helper Functions ----------------
# These are used for extracting and processing response data

def _usage_to_dict(usage_obj) -> Dict[str, int]:
    """
    Convert ResponseUsage object to dictionary.
    Handles both ResponseUsage objects and dicts.
    """
    if usage_obj is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    
    if isinstance(usage_obj, dict):
        return {
            "input_tokens": usage_obj.get("input_tokens", 0),
            "output_tokens": usage_obj.get("output_tokens", 0),
            "total_tokens": usage_obj.get("total_tokens", 0)
        }
    
    # ResponseUsage object with attributes
    return {
        "input_tokens": getattr(usage_obj, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage_obj, "output_tokens", 0) or 0,
        "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0
    }

def _extract_text_and_citations(message) -> Dict[str, Any]:
    """
    From a Response message, return:
    - text: concatenated assistant text
    - citations: list of {file_id, quote}
    - images: list of {file_id} for image_file content (from code_interpreter)
    """
    text_parts: List[str] = []
    citations: List[Dict[str, str]] = []
    images: List[Dict[str, str]] = []

    # Get message content - try multiple access methods
    content = []
    if hasattr(message, "content"):
        content = message.content or []
    elif hasattr(message, "model_dump"):
        # Pydantic model - convert to dict
        msg_dict = message.model_dump()
        content = msg_dict.get("content", [])
    elif isinstance(message, dict):
        content = message.get("content", [])
    
    for part in content:
        # Handle both object and dict representations
        part_type = None
        if hasattr(part, "type"):
            part_type = part.type
        elif isinstance(part, dict):
            part_type = part.get("type")
        
        # Handle image_file content (from code_interpreter visualizations)
        if part_type == "image_file":
            image_file_obj = None
            if hasattr(part, "image_file"):
                image_file_obj = part.image_file
            elif isinstance(part, dict):
                image_file_obj = part.get("image_file")
            
            if image_file_obj:
                file_id = None
                if hasattr(image_file_obj, "file_id"):
                    file_id = image_file_obj.file_id
                elif isinstance(image_file_obj, dict):
                    file_id = image_file_obj.get("file_id")
                
                if file_id:
                    images.append({"file_id": file_id})
            continue
        
        if part_type != "text":
            continue
        
        # Get text object
        text_obj = None
        if hasattr(part, "text"):
            text_obj = part.text
        elif isinstance(part, dict):
            text_obj = part.get("text")
        
        if not text_obj:
            continue
            
        # Extract text value
        txt = ""
        if hasattr(text_obj, "value"):
            txt = text_obj.value or ""
        elif isinstance(text_obj, dict):
            txt = text_obj.get("value", "") or ""
        
        if txt:
            text_parts.append(txt)

        # Parse annotations for file citations
        anns = []
        if hasattr(text_obj, "annotations"):
            anns = text_obj.annotations or []
        elif isinstance(text_obj, dict):
            anns = text_obj.get("annotations", []) or []
        
        for a in anns:
            # Get annotation type - try multiple access methods
            ann_type = None
            if hasattr(a, "type"):
                ann_type = a.type
            elif isinstance(a, dict):
                ann_type = a.get("type")
            elif hasattr(a, "model_dump"):
                a_dict = a.model_dump()
                ann_type = a_dict.get("type")
            
            if not ann_type and hasattr(a, "__dict__"):
                ann_type = a.__dict__.get("type")
            
            if ann_type == "file_citation":
                # Get file_citation object - try multiple access methods
                fc = None
                if hasattr(a, "file_citation"):
                    fc = a.file_citation
                elif isinstance(a, dict):
                    fc = a.get("file_citation")
                elif hasattr(a, "model_dump"):
                    a_dict = a.model_dump()
                    fc = a_dict.get("file_citation")
                
                if not fc and hasattr(a, "__dict__"):
                    fc = a.__dict__.get("file_citation")
                
                if fc:
                    # Extract file_id - try multiple ways
                    file_id = None
                    if hasattr(fc, "file_id"):
                        file_id = fc.file_id
                    elif isinstance(fc, dict):
                        file_id = fc.get("file_id")
                    elif hasattr(fc, "model_dump"):
                        fc_dict = fc.model_dump()
                        file_id = fc_dict.get("file_id")
                    
                    if not file_id and hasattr(fc, "__dict__"):
                        file_id = fc.__dict__.get("file_id")
                    
                    if file_id:
                        # Extract quote if available
                        quote = ""
                        if hasattr(fc, "quote"):
                            quote = getattr(fc, "quote", "") or ""
                        elif isinstance(fc, dict):
                            quote = fc.get("quote", "") or ""
                        elif hasattr(fc, "model_dump"):
                            fc_dict = fc.model_dump()
                            quote = fc_dict.get("quote", "") or ""
                        
                        if not quote and hasattr(fc, "__dict__"):
                            quote = fc.__dict__.get("quote", "") or ""
                        
                        citations.append({
                            "file_id": file_id,
                            "quote": quote or ""
                        })

    return {
        "text": "\n".join(text_parts).strip(),
        "citations": citations,
        "images": images
    }

def _filename_for_file_id(file_id: str) -> str:
    """
    Retrieve file metadata to get the original filename.
    """
    try:
        f = get_client().files.retrieve(file_id)
        # SDK returns fields like f.id, f.filename
        return getattr(f, "filename", file_id)
    except Exception:
        return file_id

def download_file_bytes(file_id: str) -> bytes:
    """
    Download a normal Files API file by file_id.
    """
    client = get_client()
    resp = client.files.content(file_id)
    return resp.read()

def download_container_file_bytes(container_id: str, file_id: str) -> bytes:
    """
    Download a file (e.g. cfile_...png) generated inside a Code Interpreter
    container via the Containers API.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    
    org_id = os.getenv("OPENAI_ORG")
    project_id = os.getenv("OPENAI_PROJECT")
    
    # Get base URL from environment variable, default to standard OpenAI API
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    
    # Ensure base_url is a string and properly formatted
    if not isinstance(base_url, str):
        base_url = "https://api.openai.com/v1"
    
    # Ensure base_url doesn't have trailing slash and ends with /v1
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = base_url + "/v1"
    
    url = f"{base_url}/containers/{container_id}/files/{file_id}/content"
    
    # Use urllib from standard library
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    
    req = Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    if org_id:
        req.add_header("OpenAI-Organization", org_id)
    if project_id:
        req.add_header("OpenAI-Project", project_id)
    
    response = urlopen(req, timeout=60.0)
    return response.read()

def _dedupe_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Deduplicate sources by file_id.
    If multiple sources have the same file_id, keep the first one.
    """
    seen_file_ids = set()
    out = []
    for s in sources:
        file_id = s.get("file_id")
        if file_id and file_id not in seen_file_ids:
            seen_file_ids.add(file_id)
            out.append(s)
    return out

def _extract_citations_from_markers(text: str) -> List[Dict[str, str]]:
    """
    Extract file citations from citation markers in text.
    Markers format: 【number:number†file_id】 or 【number:number†filename】
    Returns list of {file_id, quote} dicts.
    """
    citations = []
    # Pattern matches 【number:number†file_id_or_filename】
    pattern = r'【(\d+):(\d+)†([^】]+)】'
    matches = re.findall(pattern, text)
    
    for match in matches:
        # match[2] is the file_id or filename
        file_identifier = match[2].strip()
        if file_identifier:
            # Try to get file_id - if it looks like a file_id (starts with file-), use it
            # Otherwise, it might be a filename and we'd need to look it up
            if file_identifier.startswith('file-'):
                citations.append({
                    "file_id": file_identifier,
                    "quote": ""  # Quote not available from markers
                })
            else:
                # Might be a filename - try to find file_id by filename
                # For now, just store the identifier
                citations.append({
                    "file_id": file_identifier,  # Will be treated as file_id or looked up
                    "quote": ""
                })
    
    return citations

def _clean_citation_markers(text: str) -> str:
    """
    Remove citation markers like 【4:0†filename.md】 from text.
    These markers are added by OpenAI when file_search is used.
    """
    # Pattern matches 【number:number†filename】 or similar citation markers
    pattern = r'【[^】]+】'
    cleaned = re.sub(pattern, '', text)
    return cleaned.strip()

def _extract_answer_from_incomplete_json(text: str) -> Optional[str]:
    """
    Try to extract the answer field from JSON, even if the JSON is incomplete.
    This is useful during streaming when JSON might not be fully formed yet.
    """
    if not text:
        return None
    
    cleaned = _clean_citation_markers(text)
    trimmed = cleaned.strip()
    
    # If it doesn't look like JSON, return None
    if not (trimmed.startswith('{') or '"answer"' in trimmed or "'answer'" in trimmed):
        return None
    
    # Try to find "answer" field and extract its value
    try:
        # Find the position of "answer":
        answer_key_pos = trimmed.find('"answer"')
        if answer_key_pos == -1:
            answer_key_pos = trimmed.find("'answer'")
            quote_char = "'"
        else:
            quote_char = '"'
        
        if answer_key_pos >= 0:
            # Find the colon after "answer"
            colon_pos = trimmed.find(':', answer_key_pos)
            if colon_pos >= 0:
                # Find the opening quote of the value
                value_start = trimmed.find(quote_char, colon_pos + 1)
                if value_start >= 0:
                    value_start += 1  # Skip the opening quote
                    # Now find the closing quote, accounting for escaped quotes
                    value_end = None
                    i = value_start
                    while i < len(trimmed):
                        if trimmed[i] == '\\':
                            # Skip escaped character
                            i += 2
                            continue
                        elif trimmed[i] == quote_char:
                            value_end = i
                            break
                        i += 1
                    
                    if value_end is not None and value_end > value_start:
                        answer_value = trimmed[value_start:value_end]
                    elif value_start < len(trimmed):
                        # Incomplete value (no closing quote yet)
                        answer_value = trimmed[value_start:]
                    else:
                        answer_value = None
                    
                    if answer_value:
                        # Unescape the string
                        answer_value = answer_value.replace('\\"', '"').replace("\\'", "'")
                        answer_value = answer_value.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
                        answer_value = answer_value.replace('\\\\', '\\')
                        if answer_value.strip():
                            return answer_value
    except Exception:
        pass
    
    return None

def _shape_structured_payload(text: str, sources: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Try to parse a JSON object if the model returned one.
    Otherwise, wrap into {answer, sources, raw_text}.
    """
    # Clean citation markers from text first
    cleaned_text = _clean_citation_markers(text)
    
    # 1) Attempt to parse JSON directly (either whole body or fenced)
    candidate = cleaned_text.strip()
    parsed = None
    
    # Try to extract JSON from code fences first
    if "```" in candidate:
        try:
            parts = candidate.split("```")
            for i, part in enumerate(parts):
                part = part.strip()
                if part.lower() in ["json"]:
                    continue
                if part.startswith("{") and part.endswith("}"):
                    try:
                        test_parsed = json.loads(part)
                        if isinstance(test_parsed, dict) and ("answer" in test_parsed or "bullets" in test_parsed):
                            parsed = test_parsed
                            break
                    except Exception:
                        continue
        except Exception:
            pass
    
    # If no JSON found in code fences, try the whole text
    if not parsed:
        try:
            if "{" in candidate:
                start_idx = candidate.find("{")
                if start_idx >= 0:
                    brace_count = 0
                    end_idx = start_idx
                    for i in range(start_idx, len(candidate)):
                        if candidate[i] == "{":
                            brace_count += 1
                        elif candidate[i] == "}":
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i
                                break
                    
                    if brace_count == 0:
                        json_str = candidate[start_idx:end_idx + 1]
                        try:
                            test_parsed = json.loads(json_str)
                            if isinstance(test_parsed, dict) and ("answer" in test_parsed or "bullets" in test_parsed):
                                parsed = test_parsed
                        except Exception:
                            pass
        except Exception:
            pass
        
        # Last resort: try parsing the whole candidate
        if not parsed and candidate.startswith("{") and candidate.endswith("}"):
            try:
                test_parsed = json.loads(candidate)
                if isinstance(test_parsed, dict) and ("answer" in test_parsed or "bullets" in test_parsed):
                    parsed = test_parsed
            except Exception:
                parsed = None

    # 2) If parsed is OK and has "answer", use it; else build our own
    if isinstance(parsed, dict) and ("answer" in parsed or "bullets" in parsed):
        answer = parsed.get("answer") or cleaned_text
        answer = _clean_citation_markers(answer)
        shaped = {
            "answer": answer,
            "sources": sources,
            "raw_text": cleaned_text
        }
        if "bullets" in parsed and isinstance(parsed["bullets"], list):
            cleaned_bullets = [_clean_citation_markers(bullet) for bullet in parsed["bullets"]]
            shaped["bullets"] = cleaned_bullets
        # If answer is very short/truncated but we have bullets, 
        # combine them for a better answer display
        if answer and len(answer) < 150 and shaped.get("bullets"):
            # Answer seems truncated - use bullets as the main content
            # Keep the short answer as an intro if it exists
            pass  # Bullets will be displayed separately, which is fine
        return shaped

    # 3) Fallback shape - use cleaned text
    return {
        "answer": cleaned_text,
        "sources": sources,
        "raw_text": cleaned_text
    }

# ---------------- Legacy Compatibility Functions ----------------
# These map old function names to new Responses API functions

def create_thread():
    """
    Create a conversation (replaces thread creation).
    
    In Responses API, conversations are created with openai.conversations.create()
    using `items` parameter (not `messages` like threads).
    
    Returns:
        Conversation object with .id
    """
    client = get_client()
    
    # Use Conversations API
    # Try conversations first, then beta.conversations (depending on SDK version)
    if hasattr(client, 'conversations'):
        conversation = client.conversations.create(
            items=[]  # Start with empty conversation
        )
        # Initialize conversation history
        _CONVERSATION_HISTORY[conversation.id] = []
        return conversation
    elif hasattr(client.beta, 'conversations'):
        conversation = client.beta.conversations.create(
            items=[]  # Start with empty conversation
        )
        # Initialize conversation history
        _CONVERSATION_HISTORY[conversation.id] = []
        return conversation
    else:
        raise NotImplementedError(
            "Conversations API is not available in this SDK version. "
            "According to the migration guide, Conversations replace Threads in Responses API. "
            "Please update the OpenAI Python SDK to a version that supports Conversations API: "
            "pip install --upgrade openai"
        )

def add_message(thread_id: str, role: str, content: str, file_ids: Optional[List[str]] = None):
    """
    Legacy function - maps to add_message_to_response.
    In Responses API, thread_id is actually response_id.
    """
    return add_message_to_response(thread_id, role, content, file_ids)

def run_assistant_structured(thread_id: str, assistant_id: str, tools_override: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Legacy function - maps to run_response.
    In Responses API:
    - thread_id is conversation_id
    - assistant_id is response_config_id (from create_response)
    """
    conversation_id = thread_id
    response_config_id = assistant_id
    
    # Get response configuration
    config = get_response_config(response_config_id)
    if not config:
        raise ValueError(f"Response config not found: {response_config_id}")
    
    result = None
    run_meta: Dict[str, Any] = {
        "failed": False,
        "warning": None,
        "partial": False,
        "failure_mode": None,
        "error": None,
    }
    selected_tools = tools_override if tools_override is not None else config.get("tools")

    for chunk in run_response(
        conversation_id=conversation_id,
        response_config_id=response_config_id,
        stream=False,
        instructions=config.get("instructions"),
        tools=selected_tools
    ):
        result = chunk
        chunk_type = chunk.get("type")
        if chunk_type == "error":
            run_meta["failed"] = True
            run_meta["error"] = chunk.get("error")
            run_meta["failure_mode"] = chunk.get("failure_mode")
        elif chunk_type == "done":
            if chunk.get("warning"):
                run_meta["warning"] = chunk.get("warning")
            if chunk.get("partial"):
                run_meta["partial"] = True
            if chunk.get("failure_mode"):
                run_meta["failure_mode"] = chunk.get("failure_mode")
    
    if not result:
        return {
            "answer": "",
            "sources": [],
            "raw_text": "",
            "bullets": None,
            "images": [],
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "run_meta": {
                "failed": True,
                "warning": "empty_result",
                "partial": True,
                "failure_mode": "empty_result",
                "error": "No result returned from run_response",
            },
        }
    
    # Extract structured data from response
    text = result.get("answer", "")
    sources = result.get("sources", [])
    images = result.get("images", [])
    usage = _usage_to_dict(result.get("usage"))
    
    # Convert images to URL format (don't download - serve via API endpoints)
    image_data = []
    for img in images:
        file_id = img.get("file_id") if isinstance(img, dict) else getattr(img, "file_id", None)
        container_id = img.get("container_id") if isinstance(img, dict) else getattr(img, "container_id", None)
        
        if file_id:
            if container_id:
                # Container file - use container-file endpoint
                image_data.append({
                    "file_id": file_id,
                    "container_id": container_id,
                    "url": f"/api/container-file/{container_id}/{file_id}"
                })
            else:
                # Regular file - use file endpoint
                image_data.append({
                    "file_id": file_id,
                    "container_id": None,
                    "url": f"/api/file/{file_id}"
                })
    
    # Enrich sources with filenames and deduplicate by file_id
    enriched_sources = []
    seen_file_ids = set()
    for s in sources:
        file_id = s.get("file_id") if isinstance(s, dict) else getattr(s, "file_id", None)
        if file_id and file_id not in seen_file_ids:
            seen_file_ids.add(file_id)
            enriched_sources.append({
                "file_id": file_id,
                "filename": _filename_for_file_id(file_id),
                "quote": s.get("quote", "") if isinstance(s, dict) else getattr(s, "quote", "")
            })
    
    # Shape the payload
    # If text is truncated but we have the full response, try to get the full text
    # The Responses API might return the full text in the response object itself
    payload = _shape_structured_payload(text, enriched_sources)
    
    # If the answer is very short (likely truncated) but we have bullets, 
    # try to reconstruct a better answer from the bullets or use raw_text
    if payload.get("answer") and len(payload.get("answer", "")) < 200 and payload.get("bullets"):
        # Answer seems truncated, but we have bullets - that's fine, bullets will display
        pass
    elif payload.get("answer") and len(payload.get("answer", "")) < 100:
        # Very short answer - might be truncated, check if we can get more from raw_text
        raw_text = payload.get("raw_text", "")
        if raw_text and len(raw_text) > len(payload.get("answer", "")):
            # Try to extract full answer from raw_text JSON
            try:
                # Look for JSON in raw_text
                json_match = re.search(r'\{[^{}]*"answer"\s*:\s*"([^"]+)"', raw_text, re.DOTALL)
                if json_match:
                    full_answer = json_match.group(1)
                    # Unescape JSON string
                    full_answer = full_answer.replace('\\"', '"').replace('\\n', '\n')
                    if len(full_answer) > len(payload.get("answer", "")):
                        payload["answer"] = full_answer
            except Exception:
                pass
    
    payload["usage"] = usage
    if image_data:
        payload["images"] = image_data
    payload["run_meta"] = run_meta
    
    return payload

def run_assistant_stream(thread_id: str, assistant_id: str) -> Generator[Dict[str, Any], None, None]:
    """
    Legacy function - maps to run_response with streaming.
    In Responses API:
    - thread_id is conversation_id
    - assistant_id is response_config_id (from create_response)
    """
    conversation_id = thread_id
    response_config_id = assistant_id
    
    # Get response configuration
    config = get_response_config(response_config_id)
    if not config:
        yield {
            "type": "error",
            "error": f"Response config not found: {response_config_id}. Please run: python scripts/seed_multi_responses.py"
        }
        return
    
    accumulated_text = ""
    citations = []
    images = []
    
    try:
        # Check if Responses API is available before trying to stream
        client = get_client()
        if not hasattr(client, 'responses') and not hasattr(client.beta, 'responses'):
            yield {
                "type": "error",
                "error": "Responses API is not available in this SDK version. The Responses API is still in development. Please check OpenAI SDK version and API availability."
            }
            return
        
        chunk_generator = run_response(
            conversation_id=conversation_id,
            response_config_id=response_config_id,
            stream=True,
            instructions=config.get("instructions"),
            tools=config.get("tools")
        )
        
        for chunk in chunk_generator:
            chunk_type = chunk.get("type", "unknown")
            
            if chunk_type == "text_delta":
                content = chunk.get("content", "")
                accumulated = chunk.get("accumulated", "")
                if content:
                    accumulated_text += content
                
                # Clean citation markers
                cleaned_delta = _clean_citation_markers(content)
                cleaned_accumulated = _clean_citation_markers(accumulated_text)
                
                # Try to extract answer from JSON if present
                display_text = cleaned_accumulated
                extracted_answer = _extract_answer_from_incomplete_json(cleaned_accumulated)
                if extracted_answer:
                    display_text = extracted_answer
                
                yield {
                    "type": "text_delta",
                    "content": cleaned_delta,
                    "accumulated": display_text
                }
            
            elif chunk_type == "sources":
                # Sources update
                chunk_sources = chunk.get("sources", [])
                if chunk_sources:
                    citations.extend(chunk_sources)
                    yield {
                        "type": "sources",
                        "sources": _dedupe_sources(citations)
                    }
            
            elif chunk_type == "images":
                # Images update
                chunk_images = chunk.get("images", [])
                if chunk_images:
                    images.extend(chunk_images)
            
            elif chunk_type == "done":
                # Final chunk
                final_text = chunk.get("answer", accumulated_text)
                final_sources = chunk.get("sources", citations)
                final_images = chunk.get("images", images)
                final_usage = _usage_to_dict(chunk.get("usage"))
                
                # Convert images to URL format (don't download - serve via API endpoints)
                image_data = []
                for img in final_images:
                    file_id = img.get("file_id") if isinstance(img, dict) else getattr(img, "file_id", None)
                    container_id = img.get("container_id") if isinstance(img, dict) else getattr(img, "container_id", None)
                    
                    if file_id:
                        if container_id:
                            # Container file - use container-file endpoint
                            image_data.append({
                                "file_id": file_id,
                                "container_id": container_id,
                                "url": f"/api/container-file/{container_id}/{file_id}"
                            })
                        else:
                            # Regular file - use file endpoint
                            image_data.append({
                                "file_id": file_id,
                                "container_id": None,
                                "url": f"/api/file/{file_id}"
                            })
                
                # Enrich sources with filenames and deduplicate by file_id
                enriched_sources = []
                seen_file_ids = set()
                for s in final_sources:
                    file_id = s.get("file_id") if isinstance(s, dict) else getattr(s, "file_id", None)
                    if file_id and file_id not in seen_file_ids:
                        seen_file_ids.add(file_id)
                        enriched_sources.append({
                            "file_id": file_id,
                            "filename": _filename_for_file_id(file_id),
                            "quote": s.get("quote", "") if isinstance(s, dict) else getattr(s, "quote", "")
                        })
                
                # Shape final payload
                shaped = _shape_structured_payload(final_text, enriched_sources)
                
                yield {
                    "type": "done",
                    "answer": shaped.get("answer", ""),
                    "bullets": shaped.get("bullets"),
                    "sources": enriched_sources,
                    "images": image_data,
                    "usage": final_usage
                }
            
            elif chunk_type == "error":
                yield chunk
    
    except NotImplementedError as e:
        # Responses API not available
        yield {
            "type": "error",
            "error": f"Responses API not available: {str(e)}. Please check OpenAI SDK version and API availability."
        }
    except ValueError as e:
        # Configuration or conversation error
        yield {
            "type": "error",
            "error": f"Configuration error: {str(e)}"
        }
    except Exception as e:
        # Log the full exception for debugging
        import traceback
        error_trace = traceback.format_exc()
        yield {
            "type": "error",
            "error": f"Stream error: {str(e)}",
            "traceback": error_trace  # Include traceback for debugging
        }
