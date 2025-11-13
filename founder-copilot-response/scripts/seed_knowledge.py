"""
Legacy script for single response setup (Responses API).
Note: For multi-assistant setup, use seed_multi_responses.py instead.
"""
import os, glob
from dotenv import load_dotenv
load_dotenv()

from app.openai_client import create_vector_store, upload_files_batch_to_vs, create_response
from app.storage import set_ids

VS_NAME = "founder_copilot_knowledge"
COPILOT_NAME = os.getenv("COPILOT_NAME", "FounderCopilot")

def main():
    vs = create_vector_store(VS_NAME)
    print("Vector Store:", vs.id)

    file_paths = [p for p in glob.glob("data/*") if any(p.endswith(ext) for ext in (".md", ".txt", ".json"))]
    if not file_paths:
        raise SystemExit("No files found under ./data. Add .md/.txt/.json files and rerun.")

    print(f"Uploading {len(file_paths)} files...")
    batch = upload_files_batch_to_vs(vs.id, file_paths)
    print("File batch status:", batch.status)

    # Create response configuration (replaces assistant)
    response_config = create_response(
        name=COPILOT_NAME,
        vector_store_id=vs.id,
        enable_code_interpreter=False,
        instructions="You are a helpful startup advisor. Use file_search to retrieve information from the knowledge base for every question."
    )
    print("Response Config:", response_config.id)

    set_ids(response_config.id, vs.id)
    print("Saved IDs to .copilot_state.json")

if __name__ == "__main__":
    main()
