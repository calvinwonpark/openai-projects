"""
Update response configuration (Responses API).
Note: In Responses API, response configurations are stored in memory.
This script updates the stored configuration with new instructions.
"""
import os
from dotenv import load_dotenv
load_dotenv()

from app.openai_client import get_response_config, create_response
from app.storage import get_ids

def main():
    response_id, vector_store_id = get_ids()
    if not response_id:
        raise SystemExit("No response config found. Run seed_knowledge.py first.")
    if not vector_store_id:
        raise SystemExit("No vector store found. Run seed_knowledge.py first.")
    
    print(f"Updating response config {response_id}...")
    
    # Get existing config
    config = get_response_config(response_id)
    if not config:
        raise SystemExit(f"Response config {response_id} not found in memory. You may need to restart the server or re-run seed_knowledge.py.")
    
    # Update instructions
    updated_instructions = (
        "IMPORTANT: You MUST use the file_search tool to retrieve information from the knowledge base "
        "for EVERY user question, even if you think you know the answer. "
        "Always search the vector store first before responding. "
        "Use the retrieval tool on the attached vector store to provide concrete, actionable guidance and cite snippets when helpful."
    )
    
    # Update the stored config
    config["instructions"] = updated_instructions
    
    print(f"Response config updated: {response_id}")
    print("New instructions will enforce file_search usage for all questions.")
    print("Note: This updates the in-memory configuration. Restart the server for changes to take effect.")

if __name__ == "__main__":
    main()

