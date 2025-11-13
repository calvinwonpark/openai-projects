"""
Seed script to create three specialized responses with separate vector stores:
- TechAdvisor (architecture, AI product patterns)
- MarketingAdvisor (launch/growth/copy)
- InvestorAdvisor (KPI, deck, fundraising)

This replaces the Assistants API with the Responses API.
"""
import os
import glob
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.openai_client import create_vector_store, upload_files_batch_to_vs, create_specialized_response
from app.storage import set_response_ids

# Response configurations
RESPONSES = {
    "tech": {
        "name": "TechAdvisor",
        "vector_store_name": "tech_knowledge",
        "data_dir": "data/tech",
        "enable_code_interpreter": True  # For quick technical calculations
    },
    "marketing": {
        "name": "MarketingAdvisor",
        "vector_store_name": "marketing_knowledge",
        "data_dir": "data/marketing",
        "enable_code_interpreter": False
    },
    "investor": {
        "name": "InvestorAdvisor",
        "vector_store_name": "investor_knowledge",
        "data_dir": "data/investor",
        "enable_code_interpreter": True  # For financial calculations and visualizations
    }
}

def main():
    responses_data = {}
    
    for label, config in RESPONSES.items():
        print(f"\n{'='*60}")
        print(f"Setting up {config['name']}...")
        print(f"{'='*60}")
        
        # Create vector store
        vs = create_vector_store(config["vector_store_name"])
        print(f"Vector Store: {vs.id}")
        
        # Find files in the response's data directory
        data_dir = config["data_dir"]
        if not os.path.exists(data_dir):
            print(f"Warning: {data_dir} does not exist. Creating directory...")
            os.makedirs(data_dir, exist_ok=True)
            print(f"Created {data_dir}. Please add .md/.txt/.json files to this directory.")
        
        file_paths = [
            p for p in glob.glob(f"{data_dir}/*")
            if any(p.endswith(ext) for ext in (".md", ".txt", ".json", ".csv"))
        ]
        
        if file_paths:
            print(f"Uploading {len(file_paths)} files to vector store...")
            batch = upload_files_batch_to_vs(vs.id, file_paths)
            print(f"File batch status: {batch.status}")
        else:
            print(f"Warning: No files found in {data_dir}. Response will be created with empty vector store.")
            print("You can add files later and re-run this script to update the vector store.")
        
        # Create specialized response
        response = create_specialized_response(
            label=label,
            vector_store_id=vs.id,
            enable_code_interpreter=config["enable_code_interpreter"]
        )
        print(f"Response: {response.id}")
        
        responses_data[label] = {
            "response_id": response.id,
            "vector_store_id": vs.id
        }
    
    # Save all response IDs
    set_response_ids(responses_data)
    print(f"\n{'='*60}")
    print("✅ All responses created and saved!")
    print(f"{'='*60}")
    print("\nResponse IDs:")
    for label, data in responses_data.items():
        print(f"  {label}: {data['response_id']}")

if __name__ == "__main__":
    main()

