#!/usr/bin/env python3
"""
Helper script to create or update a product card.

Usage:
    python scripts/create_product_card.py \
        --product-id "acme-inbox" \
        --name "Acme Inbox Copilot" \
        --description "AI email triage for SMB founders" \
        --target-audience "solo founders" \
        --problem-uvp "prioritizes investor emails and action items" \
        --key-features '["Smart prioritization", "Action item extraction", "Investor email alerts"]' \
        --stage "MVP" \
        --constraints '{"budget": "$200/mo CAC", "timeline": "2 weeks"}' \
        --files '["file_abc123", "file_xyz789"]'
"""

import argparse
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.product_card import create_or_update_product_card

def main():
    parser = argparse.ArgumentParser(description='Create or update a product card')
    parser.add_argument('--product-id', required=True, help='Product ID (stable handle)')
    parser.add_argument('--name', required=True, help='Product name')
    parser.add_argument('--description', required=True, help='One-line description')
    parser.add_argument('--target-audience', required=True, help='Target audience')
    parser.add_argument('--problem-uvp', required=True, help='Problem/UVP')
    parser.add_argument('--key-features', required=True, help='JSON array of key features')
    parser.add_argument('--stage', required=True, choices=['idea', 'MVP', 'GA'], help='Product stage')
    parser.add_argument('--constraints', required=True, help='JSON object with constraints (budget, timeline, channels)')
    parser.add_argument('--files', default='[]', help='JSON array of file IDs (optional)')
    
    args = parser.parse_args()
    
    # Parse JSON fields
    try:
        key_features = json.loads(args.key_features)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in --key-features: {args.key_features}")
        sys.exit(1)
    
    try:
        constraints = json.loads(args.constraints)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in --constraints: {args.constraints}")
        sys.exit(1)
    
    try:
        files = json.loads(args.files) if args.files else []
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in --files: {args.files}")
        sys.exit(1)
    
    # Create or update product card
    card = create_or_update_product_card(
        product_id=args.product_id,
        name=args.name,
        description=args.description,
        target_audience=args.target_audience,
        problem_uvp=args.problem_uvp,
        key_features=key_features,
        stage=args.stage,
        constraints=constraints,
        files=files
    )
    
    print(f"✅ Product card created/updated: {card['product_id']} (version {card['version']})")
    print(f"\nCard details:")
    print(json.dumps(card, indent=2))
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

