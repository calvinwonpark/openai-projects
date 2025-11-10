import os
from openai import OpenAI

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

def upload_file_to_vs(vector_store_id: str, path: str):
    return upload_files_batch_to_vs(vector_store_id, [path])

# ---------------- Assistants / Threads (beta) ----------------

def create_assistant(name: str, vector_store_id: str):
    client = get_client()
    return client.beta.assistants.create(
        name=name,
        model=get_model(),
        instructions=(
            "You are a YC-style startup advisor. Use the retrieval tool on the attached "
            "vector store to provide concrete, actionable guidance and cite snippets when helpful."
        ),
        tools=[{"type": "file_search"}],  # retrieval tool in v2 is 'file_search'
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

def run_assistant(thread_id: str, assistant_id: str):
    client = get_client()
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    # poll
    while True:
        r = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        if r.status in ("completed", "failed", "cancelled", "expired"):
            run = r
            break
    if run.status != "completed":
        raise RuntimeError(f"Run failed: {run.status}")
    msgs = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=10)
    for m in msgs.data:
        if m.role == "assistant":
            # Extract usage information from the run
            usage = None
            if hasattr(run, 'usage') and run.usage:
                usage = {
                    "input_tokens": getattr(run.usage, 'prompt_tokens', 0),
                    "output_tokens": getattr(run.usage, 'completion_tokens', 0),
                    "total_tokens": getattr(run.usage, 'total_tokens', 0)
                }
            return m, usage
    return None, None
