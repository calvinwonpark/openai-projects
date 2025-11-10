import os
import re
import json
import io
import base64
import mimetypes
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
    """Legacy function for single assistant. Use create_specialized_assistant instead."""
    client = get_client()
    return client.beta.assistants.create(
        name=name,
        model=get_model(),
        instructions=_get_assistant_instructions(),
        tools=[
            {"type": "file_search"},
            {"type": "code_interpreter"}  # For founder analytics and calculations
        ],
        tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
    )

def create_specialized_assistant(label: str, vector_store_id: str, enable_code_interpreter: bool = False):
    """
    Create a specialized assistant for tech, marketing, or investor.
    
    Args:
        label: "tech", "marketing", or "investor"
        vector_store_id: Vector store ID for this assistant
        enable_code_interpreter: Whether to enable code_interpreter tool
    """
    client = get_client()
    instructions = _get_specialized_instructions(label)
    tools = [{"type": "file_search"}]
    
    if enable_code_interpreter:
        tools.append({"type": "code_interpreter"})
    
    name_map = {
        "tech": "TechAdvisor",
        "marketing": "MarketingAdvisor",
        "investor": "InvestorAdvisor"
    }
    
    return client.beta.assistants.create(
        name=name_map.get(label, f"{label.capitalize()}Advisor"),
        model=get_model(),
        instructions=instructions,
        tools=tools,
        tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
    )

def _get_assistant_instructions():
    """Get the assistant instructions that enforce file_search usage and enable code_interpreter for analytics."""
    return (
        "You are a YC-style startup advisor. "
        "IMPORTANT: You MUST use the file_search tool to retrieve information from the knowledge base "
        "for EVERY user question, even if you think you know the answer. "
        "Always search the vector store first before responding. "
        "Use the retrieval tool on the attached vector store to provide concrete, actionable guidance and cite snippets when helpful. "
        "When possible, produce a JSON object with keys: "
        "`answer` (string) and `bullets` (array of strings). "
        "If you cite specifics, reference them inline and expect the system to attach sources. "
        "For founder analytics questions involving calculations, data analysis, financial projections, or visualizations, "
        "use the code_interpreter tool to run Python code. This is especially useful for: "
        "- Calculating metrics (burn rate, runway, growth rates, etc.) "
        "- Analyzing financial data and projections "
        "- Creating charts and visualizations "
        "- Performing statistical analysis "
        "- Modeling scenarios and what-if analyses."
    )

def _get_specialized_instructions(label: str) -> str:
    """Get specialized instructions for each assistant type."""
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

def update_assistant(assistant_id: str, vector_store_id: str):
    """Update an existing assistant with new instructions."""
    client = get_client()
    return client.beta.assistants.update(
        assistant_id=assistant_id,
        instructions=_get_assistant_instructions(),
        tools=[
            {"type": "file_search"},
            {"type": "code_interpreter"}  # For founder analytics and calculations
        ],
        tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
    )

def create_thread():
    return get_client().beta.threads.create()

def upload_file(file_content: bytes, filename: str, purpose: str = "assistants"):
    """
    Upload a file to OpenAI for use with assistants.
    Returns the file object with file_id.
    """
    client = get_client()
    # Create a file-like object from bytes
    file_obj = io.BytesIO(file_content)
    file_obj.name = filename
    
    file = client.files.create(
        file=file_obj,
        purpose=purpose
    )
    return file

def add_message(thread_id: str, role: str, content: str, file_ids: List[str] = None):
    """
    Add a message to a thread, optionally with file attachments.
    
    Args:
        thread_id: Thread ID
        role: "user" or "assistant"
        content: Message text content
        file_ids: Optional list of file IDs to attach (for code_interpreter)
    """
    client = get_client()
    
    # Build message creation parameters
    message_params = {
        "thread_id": thread_id,
        "role": role,
        "content": content,
    }
    
    # If file_ids are provided, attach them using the attachments parameter
    # This is the correct way to attach files for code_interpreter
    if file_ids:
        message_params["attachments"] = [
            {"file_id": file_id, "tools": [{"type": "code_interpreter"}]}
            for file_id in file_ids
        ]
    
    return client.beta.threads.messages.create(**message_params)

def _extract_text_and_citations(message) -> Dict[str, Any]:
    """
    From an Assistant message, return:
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

    # Extract text, citations, and images from message
    extracted = _extract_text_and_citations(assistant_msg)
    text = extracted["text"]
    citations = _dedupe_sources(extracted["citations"])
    images = extracted.get("images", [])

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

    # Download images and convert to base64 for display
    image_data = []
    for img in images:
        file_id = img.get("file_id")
        if file_id:
            try:
                # Download the image file from OpenAI
                file_response = client.files.content(file_id)
                image_bytes = file_response.read()
                
                # Convert to base64 data URL
                # Try to determine content type from file metadata
                try:
                    file_info = client.files.retrieve(file_id)
                    filename = getattr(file_info, "filename", "image.png")
                    content_type, _ = mimetypes.guess_type(filename)
                    if not content_type:
                        content_type = "image/png"  # Default to PNG
                except Exception:
                    content_type = "image/png"
                
                base64_data = base64.b64encode(image_bytes).decode("utf-8")
                data_url = f"data:{content_type};base64,{base64_data}"
                
                image_data.append({
                    "file_id": file_id,
                    "data_url": data_url
                })
            except Exception:
                # If image download fails, skip it
                pass
    
    # Shape final payload
    payload = _shape_structured_payload(text, sources)
    payload["usage"] = usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if image_data:
        payload["images"] = image_data
    return payload
