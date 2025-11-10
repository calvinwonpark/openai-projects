import os
from dotenv import load_dotenv
load_dotenv()

from app.openai_client import update_assistant
from app.storage import get_ids

def main():
    assistant_id, vector_store_id = get_ids()
    if not assistant_id:
        raise SystemExit("No assistant found. Run seed_knowledge.py first.")
    if not vector_store_id:
        raise SystemExit("No vector store found. Run seed_knowledge.py first.")
    
    print(f"Updating assistant {assistant_id}...")
    asst = update_assistant(assistant_id, vector_store_id)
    print(f"Assistant updated: {asst.id}")
    print("New instructions will enforce file_search usage for all questions.")

if __name__ == "__main__":
    main()

