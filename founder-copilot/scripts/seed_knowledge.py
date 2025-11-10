import os, glob
from dotenv import load_dotenv
load_dotenv()

from app.openai_client import create_vector_store, upload_files_batch_to_vs, create_assistant
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

    asst = create_assistant(COPILOT_NAME, vs.id)
    print("Assistant:", asst.id)

    set_ids(asst.id, vs.id)
    print("Saved IDs to .copilot_state.json")

if __name__ == "__main__":
    main()
