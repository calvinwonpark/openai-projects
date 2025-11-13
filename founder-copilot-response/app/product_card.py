"""
Product Card Management

Maintains a lightweight, neutral product card that any assistant can read.
Used to provide context when routing messages with deictic references.
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import json
import re

# In-memory storage (session-based, could be moved to Redis/DB later)
PRODUCT_CARDS: Dict[str, Dict[str, Any]] = {}
PRODUCT_CARD_VERSION: Dict[str, int] = {}  # Track versions per product_id

def create_or_update_product_card(
    product_id: str,
    name: str,
    description: str,
    target_audience: str,
    problem_uvp: str,
    key_features: List[str],
    stage: str,  # "idea" | "MVP" | "GA"
    constraints: Dict[str, str],  # e.g., {"budget": "$10K", "timeline": "3 months", "channels": "email, LinkedIn"}
    files: Optional[List[str]] = None  # File IDs
) -> Dict[str, Any]:
    """
    Create or update a product card. Returns the card with version and timestamp.
    """
    if files is None:
        files = []
    
    # Increment version if product exists
    if product_id in PRODUCT_CARD_VERSION:
        PRODUCT_CARD_VERSION[product_id] += 1
    else:
        PRODUCT_CARD_VERSION[product_id] = 1
    
    card = {
        "product_id": product_id,
        "name": name,
        "description": description,
        "target_audience": target_audience,
        "problem_uvp": problem_uvp,
        "key_features": key_features,
        "stage": stage,
        "constraints": constraints,
        "files": files,
        "version": PRODUCT_CARD_VERSION[product_id],
        "updated_at": datetime.utcnow().isoformat()
    }
    
    PRODUCT_CARDS[product_id] = card
    return card

def get_product_card(product_id: str) -> Optional[Dict[str, Any]]:
    """Get a product card by ID."""
    return PRODUCT_CARDS.get(product_id)

def get_all_product_cards() -> List[Dict[str, Any]]:
    """Get all product cards."""
    return list(PRODUCT_CARDS.values())

def format_product_card_for_message(card: Dict[str, Any]) -> str:
    """
    Format product card as a compact string for prepending to messages.
    Target: ≤ 200-300 tokens.
    """
    features_str = ", ".join(card["key_features"][:5])  # Limit to 5 features
    if len(card["key_features"]) > 5:
        features_str += f" (+{len(card['key_features']) - 5} more)"
    
    constraints_str = ", ".join([f"{k}: {v}" for k, v in card["constraints"].items()])
    
    formatted = f"""Product: "{card['name']}" — {card['description']}
Audience: {card['target_audience']}
UVP: {card['problem_uvp']}
Stage: {card['stage']}
Key Features: {features_str}
Constraints: {constraints_str}"""
    
    if card.get("files"):
        formatted += f"\nAttached Files: {', '.join(card['files'][:3])}"  # Show first 3 file IDs
        if len(card["files"]) > 3:
            formatted += f" (+{len(card['files']) - 3} more)"
    
    return formatted

def detect_deictic_references(text: str) -> bool:
    """
    Detect if message contains deictic/implicit references that require context.
    Returns True if deictic references are found.
    """
    deictic_patterns = [
        r'\bthis\b',
        r'\bthat\b',
        r'\babove\b',
        r'\bbelow\b',
        r'\bit\b',
        r'\bthey\b',
        r'\bthem\b',
        r'\bthese\b',
        r'\bthose\b',
        r'\bthe\s+(above|below|aforementioned|mentioned)',
        r'\bthe\s+(product|feature|chart|graph|data|analysis|result)',
        r'\bmy\s+(product|app|service|startup)',
        r'\bour\s+(product|app|service|startup)',
    ]
    
    text_lower = text.lower()
    for pattern in deictic_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    return False

def rewrite_message_with_product_card(
    user_message: str,
    product_card: Optional[Dict[str, Any]] = None,
    additional_file_ids: Optional[List[str]] = None
) -> Tuple[str, List[str]]:
    """
    Rewrite user message with product card context.
    Returns: (rewritten_message, file_ids_to_attach)
    """
    file_ids = []
    
    if product_card:
        card_text = format_product_card_for_message(product_card)
        rewritten = f"{card_text}\n\nUser asks: {user_message}"
        
        # Collect file IDs from product card
        if product_card.get("files"):
            file_ids.extend(product_card["files"])
    else:
        rewritten = user_message
    
    # Add additional file IDs (from previous turns)
    if additional_file_ids:
        for fid in additional_file_ids:
            if fid not in file_ids:
                file_ids.append(fid)
    
    return rewritten, file_ids

def extract_product_info_from_message(user_message: str) -> Optional[Dict[str, Any]]:
    """
    Use OpenAI to extract product information from a user message.
    Returns a dict with product card fields if product info is detected, None otherwise.
    """
    from app.openai_client import get_client
    
    # Check if message might contain product information
    product_keywords = [
        "my product", "my app", "my startup", "my company",
        "we're building", "we built", "our product", "our app",
        "product is", "app is", "startup is", "company is",
        "target audience", "target market", "target customers",
        "problem we solve", "value proposition", "unique value",
        "key features", "main features", "features include",
        "stage", "phase", "MVP", "beta", "launch", "GA"
    ]
    
    message_lower = user_message.lower()
    has_product_info = any(keyword in message_lower for keyword in product_keywords)
    
    if not has_product_info:
        return None
    
    client = get_client()
    
    # Use OpenAI to extract structured product information
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use cheaper model for extraction
            messages=[
                {
                    "role": "system",
                    "content": """Extract product information from the user's message. 
Return a JSON object with these fields if product information is present:
- name: Product name (required)
- description: One-line description (required)
- target_audience: Who the product is for (required)
- problem_uvp: Problem it solves or unique value proposition (required)
- key_features: Array of 3-5 key features (required)
- stage: One of "idea", "MVP", or "GA" (required)
- constraints: Object with budget, timeline, channels if mentioned (optional)

If the message doesn't contain clear product information, return null.
Keep descriptions concise (1-2 sentences max)."""
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Validate required fields
        required_fields = ["name", "description", "target_audience", "problem_uvp", "key_features", "stage"]
        if all(field in result and result[field] for field in required_fields):
            # Generate product_id from name
            product_id = re.sub(r'[^a-z0-9]+', '-', result["name"].lower()).strip('-')
            if not product_id:
                product_id = "product-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")
            
            return {
                "product_id": product_id,
                "name": result["name"],
                "description": result["description"],
                "target_audience": result["target_audience"],
                "problem_uvp": result["problem_uvp"],
                "key_features": result["key_features"] if isinstance(result["key_features"], list) else [result["key_features"]],
                "stage": result["stage"],
                "constraints": result.get("constraints", {})
            }
    except Exception as e:
        # If extraction fails, return None (don't block the conversation)
        print(f"Error extracting product info: {e}")
        return None
    
    return None

def auto_create_or_update_product_card(user_message: str, session_id: str) -> Optional[Dict[str, Any]]:
    """
    Automatically extract product information from user message and create/update product card.
    Returns the product card if created/updated, None otherwise.
    """
    extracted = extract_product_info_from_message(user_message)
    
    if not extracted:
        return None
    
    # Check if product already exists (by name or product_id)
    existing_card = None
    for card in PRODUCT_CARDS.values():
        if card["name"].lower() == extracted["name"].lower() or card["product_id"] == extracted["product_id"]:
            existing_card = card
            break
    
    if existing_card:
        # Update existing card (merge new info with existing)
        product_id = existing_card["product_id"]
        # Merge constraints
        merged_constraints = existing_card.get("constraints", {})
        merged_constraints.update(extracted.get("constraints", {}))
        
        # Update card with new information
        updated_card = create_or_update_product_card(
            product_id=product_id,
            name=extracted["name"],  # Update name in case it changed
            description=extracted["description"],
            target_audience=extracted["target_audience"],
            problem_uvp=extracted["problem_uvp"],
            key_features=extracted["key_features"],
            stage=extracted["stage"],
            constraints=merged_constraints,
            files=existing_card.get("files", [])  # Preserve existing files
        )
        
        # Note: set_active_product_id will be called by the caller to avoid circular import
        # The caller should import and call: from app.main import set_active_product_id
        
        return updated_card
    else:
        # Create new product card
        card = create_or_update_product_card(
            product_id=extracted["product_id"],
            name=extracted["name"],
            description=extracted["description"],
            target_audience=extracted["target_audience"],
            problem_uvp=extracted["problem_uvp"],
            key_features=extracted["key_features"],
            stage=extracted["stage"],
            constraints=extracted.get("constraints", {}),
            files=[]
        )
        
        # Note: set_active_product_id will be called by the caller to avoid circular import
        
        return card

