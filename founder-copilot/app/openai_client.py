import os
import re
import json
from openai import OpenAI
from typing import Dict, Any, List

_client = None

def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing")
        _client = OpenAI(api_key=api_key)
    return _client

def get_model():
    return os.getenv("OPENAI_MODEL", "gpt-4.1")

# ---------------- Vector Stores (beta) ----------------

def create_vector_store(name: str):
    return get_client().beta.vector_stores.create(name=name)

def upload_files_batch_to_vs(vector_store_id: str, file_paths: list[str]):
    client = get_client()
    files = [open(p, "rb") for p in file_paths]
    try:
        batch = client.beta.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store_id,
            files=files,
        )
        return batch
    finally:
        for f in files:
            try:
                f.close()
            except Exception:
                pass

# ---------------- Assistants / Threads (beta) ----------------

def create_assistant(name: str, vector_store_id: str):
    client = get_client()
    return client.beta.assistants.create(
        name=name,
        model=get_model(),
        instructions=_get_assistant_instructions(),
        tools=[{"type": "file_search"}],  # retrieval tool in v2 is 'file_search'
        tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
    )

def _get_assistant_instructions():
    """Get the assistant instructions that enforce file_search usage."""
    return (
        "You are a YC-style startup advisor. "
        "IMPORTANT: You MUST use the file_search tool to retrieve information from the knowledge base "
        "for EVERY user question, even if you think you know the answer. "
        "Always search the vector store first before responding. "
        "Use the retrieval tool on the attached vector store to provide concrete, actionable guidance and cite snippets when helpful. "
        "When possible, produce a JSON object with keys: "
        "`answer` (string) and `bullets` (array of strings). "
        "If you cite specifics, reference them inline and expect the system to attach sources."
    )

def update_assistant(assistant_id: str, vector_store_id: str):
    """Update an existing assistant with new instructions."""
    client = get_client()
    return client.beta.assistants.update(
        assistant_id=assistant_id,
        instructions=_get_assistant_instructions(),
        tools=[{"type": "file_search"}],
        tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
    )

def create_thread():
    return get_client().beta.threads.create()

def add_message(thread_id: str, role: str, content: str):
    return get_client().beta.threads.messages.create(
        thread_id=thread_id,
        role=role,
        content=content,
    )

def _extract_text_and_citations(message) -> Dict[str, Any]:
    """
    From an Assistant message, return:
    - text: concatenated assistant text
    - citations: list of {file_id, quote}
    """
    text_parts: List[str] = []
    citations: List[Dict[str, str]] = []

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
        # Annotations are on text_obj.annotations
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
                # Pydantic model
                a_dict = a.model_dump()
                ann_type = a_dict.get("type")
            
            # Also try to get type from __dict__ if it exists
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
                
                # Also try __dict__ access
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
                    
                    # Also try __dict__ access
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
                        
                        # Also try __dict__ access
                        if not quote and hasattr(fc, "__dict__"):
                            quote = fc.__dict__.get("quote", "") or ""
                        
                        citations.append({
                            "file_id": file_id,
                            "quote": quote or ""
                        })

    return {"text": "\n".join(text_parts).strip(), "citations": citations}

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

def _dedupe_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for s in sources:
        key = (s.get("file_id"), s.get("quote"))
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out

def _clean_citation_markers(text: str) -> str:
    """
    Remove citation markers like 【4:0†filename.md】 from text.
    These markers are added by OpenAI when file_search is used.
    """
    # Pattern matches 【number:number†filename】 or similar citation markers
    # Examples: 【4:0†yc_do_things_dont_scale.md】, 【1:2†file.txt】
    pattern = r'【[^】]+】'
    cleaned = re.sub(pattern, '', text)
    return cleaned.strip()

def _shape_structured_payload(text: str, sources: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Try to parse a JSON object if the model returned one.
    Otherwise, wrap into {answer, sources, raw_text}.
    """
    # Clean citation markers from text first
    cleaned_text = _clean_citation_markers(text)
    
    # 1) Attempt to parse JSON directly (either whole body or fenced)
    candidate = cleaned_text.strip()
    # yank JSON between code fences if present
    if "```" in candidate:
        try:
            fence = candidate.split("```")
            # look for the first plausible JSON block
            for block in fence:
                b = block.strip()
                if b.startswith("{") and b.endswith("}"):
                    candidate = b
                    break
        except Exception:
            pass

    parsed = None
    if candidate.startswith("{") and candidate.endswith("}"):
        try:
            parsed = json.loads(candidate)
        except Exception:
            parsed = None

    # 2) If parsed is OK and has "answer", use it; else build our own
    if isinstance(parsed, dict) and ("answer" in parsed or "bullets" in parsed):
        answer = parsed.get("answer") or cleaned_text
        # Clean citation markers from answer too
        answer = _clean_citation_markers(answer)
        shaped = {
            "answer": answer,
            "sources": sources,
            "raw_text": cleaned_text  # Store cleaned version
        }
        # Preserve extra structured fields if they exist
        if "bullets" in parsed and isinstance(parsed["bullets"], list):
            # Clean citation markers from bullets too
            cleaned_bullets = [_clean_citation_markers(bullet) for bullet in parsed["bullets"]]
            shaped["bullets"] = cleaned_bullets
        return shaped

    # 3) Fallback shape - use cleaned text
    return {
        "answer": cleaned_text,
        "sources": sources,
        "raw_text": cleaned_text
    }

def run_assistant_structured(thread_id: str, assistant_id: str) -> Dict[str, Any]:
    """
    Run the assistant and return a normalized, structured payload:
    { answer, sources: [{file_id, filename, quote}], raw_text, usage: {input_tokens, output_tokens, total_tokens} }
    """
    client = get_client()
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    # poll to completion
    while True:
        r = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if r.status in ("completed", "failed", "cancelled", "expired"):
            run = r
            break
    if run.status != "completed":
        raise RuntimeError(f"Run failed: {run.status}")
    
    # Extract usage information from the run
    usage = None
    if hasattr(run, 'usage') and run.usage:
        usage = {
            "input_tokens": getattr(run.usage, 'prompt_tokens', 0),
            "output_tokens": getattr(run.usage, 'completion_tokens', 0),
            "total_tokens": getattr(run.usage, 'total_tokens', 0)
        }

    # After successful run, the newest message should be the assistant's response
    msgs = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=1)
    if not msgs.data or msgs.data[0].role != "assistant":
        return {
            "answer": "",
            "sources": [],
            "raw_text": "",
            "usage": usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        }

    assistant_msg = msgs.data[0]

    # Extract text and annotations from message
    extracted = _extract_text_and_citations(assistant_msg)
    text = extracted["text"]
    citations = _dedupe_sources(extracted["citations"])

    # Fallback: Try to extract file IDs from run steps if no citations found
    file_ids_from_steps = set()
    if not citations:
        try:
            run_steps = client.beta.threads.runs.steps.list(
                thread_id=thread_id,
                run_id=run.id
            )
            for step in run_steps.data:
                if hasattr(step, "step_details") and step.step_details:
                    step_details = step.step_details
                    step_type = getattr(step_details, "type", "")
                    
                    # Check for tool_outputs to get file IDs from file_search results
                    if step_type == "tool_outputs":
                        tool_outputs = getattr(step_details, "tool_outputs", []) or []
                        for output in tool_outputs:
                            # Try to extract file IDs from output
                            output_dict = None
                            if hasattr(output, "model_dump"):
                                output_dict = output.model_dump()
                            elif hasattr(output, "dict"):
                                output_dict = output.dict()
                            elif isinstance(output, dict):
                                output_dict = output
                            
                            if output_dict:
                                # File search outputs might contain file_ids or results
                                if "file_ids" in output_dict:
                                    file_ids_from_steps.update(output_dict["file_ids"])
                                elif "results" in output_dict:
                                    results = output_dict["results"]
                                    if isinstance(results, list):
                                        for result in results:
                                            if isinstance(result, dict) and "file_id" in result:
                                                file_ids_from_steps.add(result["file_id"])
                                            elif hasattr(result, "file_id"):
                                                file_ids_from_steps.add(result.file_id)
        except Exception:
            pass  # Silently fail if run steps can't be retrieved
    
    # If we found file IDs from run steps but no citations, add them
    if file_ids_from_steps and not citations:
        for file_id in file_ids_from_steps:
            citations.append({
                "file_id": file_id,
                "quote": ""  # No quote available from run steps
            })

    # Fallback: Try converting message to dict if it's a Pydantic model
    if not citations:
        try:
            msg_dict = None
            if hasattr(assistant_msg, "model_dump"):
                msg_dict = assistant_msg.model_dump()
            elif hasattr(assistant_msg, "dict"):
                msg_dict = assistant_msg.dict()
            
            # If we have a dict representation and no citations, try extracting from dict
            if msg_dict:
                content_list = msg_dict.get("content", [])
                for part_dict in content_list:
                    if isinstance(part_dict, dict) and part_dict.get("type") == "text":
                        text_dict = part_dict.get("text", {})
                        anns_list = text_dict.get("annotations", [])
                        for ann_dict in anns_list:
                            if isinstance(ann_dict, dict) and ann_dict.get("type") == "file_citation":
                                fc_dict = ann_dict.get("file_citation", {})
                                file_id = fc_dict.get("file_id")
                                if file_id:
                                    quote = fc_dict.get("quote", "") or ""
                                    citations.append({
                                        "file_id": file_id,
                                        "quote": quote
                                    })
        except Exception:
            pass  # Silently fail if dict extraction fails
    
    # Re-dedupe after potential fallback extraction
    citations = _dedupe_sources(citations)

    # Enrich with filenames
    sources = []
    for c in citations:
        sources.append({
            "file_id": c["file_id"],
            "filename": _filename_for_file_id(c["file_id"]),
            "quote": c.get("quote", "")
        })

    # Shape final payload
    payload = _shape_structured_payload(text, sources)
    payload["usage"] = usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    return payload
