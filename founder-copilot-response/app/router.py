"""
Multi-assistant router with hybrid heuristic + classifier approach.
Routes queries to TechAdvisor, MarketingAdvisor, or InvestorAdvisor.
"""
import re
import json
from typing import Dict, Any, List, Tuple
from openai import OpenAI
import os

# High-risk keywords that require consult-then-decide even with good confidence
HIGH_RISK_KEYWORDS = [
    "fundraising", "investor", "pitch", "deck", "valuation", "equity",
    "legal", "compliance", "contract", "agreement", "lawsuit"
]

# Heuristic keyword mappings
TECH_KEYWORDS = [
    "architecture", "system design", "scalability", "infrastructure", "api",
    "database", "backend", "frontend", "tech stack", "framework", "library",
    "algorithm", "performance", "optimization", "security", "encryption",
    "deployment", "devops", "ci/cd", "microservices", "ai model", "ml model",
    "llm", "embedding", "vector", "rag", "prompt engineering", "fine-tuning"
]

MARKETING_KEYWORDS = [
    "marketing", "growth", "launch", "copy", "messaging", "branding",
    "content", "seo", "sem", "social media", "advertising", "campaign",
    "conversion", "funnel", "landing page", "email", "newsletter",
    "pr", "press", "influencer", "partnership", "distribution", "channel",
    "customer acquisition", "retention", "engagement", "viral", "referral"
]

INVESTOR_KEYWORDS = [
    "fundraising", "investor", "vc", "angel", "seed", "series a", "series b",
    "pitch deck", "deck", "valuation", "equity", "dilution", "cap table",
    "term sheet", "due diligence", "kpi", "metrics", "burn rate", "runway",
    "cac", "ltv", "arr", "mrr", "churn", "retention", "growth rate",
    "revenue", "profit", "margin", "unit economics", "financial model",
    "projection", "forecast", "budget", "spend", "roi"
]

def heuristic_classify(query: str) -> Tuple[str, float]:
    """
    Heuristic classification based on keyword matching.
    Returns (label, confidence_score).
    """
    query_lower = query.lower()
    
    tech_score = sum(1 for kw in TECH_KEYWORDS if kw in query_lower)
    marketing_score = sum(1 for kw in MARKETING_KEYWORDS if kw in query_lower)
    investor_score = sum(1 for kw in INVESTOR_KEYWORDS if kw in query_lower)
    
    scores = {
        "tech": tech_score,
        "marketing": marketing_score,
        "investor": investor_score
    }
    
    max_score = max(scores.values())
    total_score = sum(scores.values())
    
    if total_score == 0:
        return ("tech", 0.3)  # Default fallback
    
    # Find label with max score
    label = max(scores, key=scores.get)
    
    # Confidence based on dominance
    if max_score == 0:
        confidence = 0.3
    elif total_score == max_score:
        confidence = 0.9  # Only one category matched
    else:
        # Normalize: how much does max dominate?
        confidence = max_score / total_score
        confidence = max(0.4, min(0.85, confidence))  # Clamp between 0.4 and 0.85
    
    return (label, confidence)

def classifier_classify(query: str) -> Tuple[str, float, str, float]:
    """
    Use OpenAI to classify the query.
    Returns (label, confidence, top2_label, margin).
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    prompt = f"""Classify this startup founder question into one of three categories:
- tech: Technical architecture, AI/ML models, system design, infrastructure, scalability
- marketing: Growth, launch strategy, copywriting, messaging, customer acquisition, distribution
- investor: Fundraising, pitch decks, KPIs, financial metrics, valuation, investor relations

Question: "{query}"

Respond with ONLY a JSON object:
{{
  "label": "tech" | "marketing" | "investor",
  "confidence": 0.0-1.0,
  "top2_label": "tech" | "marketing" | "investor",
  "margin": 0.0-1.0 (difference between top and second confidence)
}}"""

    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": "You are a classification assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=150
        )
        
        result = json.loads(response.choices[0].message.content.strip())
        
        label = result.get("label", "tech")
        confidence = float(result.get("confidence", 0.5))
        top2_label = result.get("top2_label", "marketing")
        margin = float(result.get("margin", 0.2))
        
        return (label, confidence, top2_label, margin)
    except Exception:
        # Fallback to heuristic if classifier fails
        label, conf = heuristic_classify(query)
        return (label, conf, "marketing", 0.2)

def is_high_risk(query: str) -> bool:
    """Check if query contains high-risk keywords."""
    query_lower = query.lower()
    return any(kw in query_lower for kw in HIGH_RISK_KEYWORDS)

def route_query(query: str) -> Dict[str, Any]:
    """
    Hybrid routing: heuristic first, classifier if ambiguous.
    Returns {label, confidence, top2_label, margin, is_high_risk}.
    """
    # Step 1: Heuristic classification
    heuristic_label, heuristic_conf = heuristic_classify(query)
    
    # Step 2: Determine if we need classifier
    use_classifier = False
    
    # Use classifier if:
    # - Heuristic confidence is low (< 0.6)
    # - Multiple categories have similar scores (ambiguous)
    if heuristic_conf < 0.6:
        use_classifier = True
    
    if use_classifier:
        label, confidence, top2_label, margin = classifier_classify(query)
    else:
        # Use heuristic result, estimate top2 and margin
        label = heuristic_label
        confidence = heuristic_conf
        
        # Estimate top2 (simplified - could be improved)
        query_lower = query.lower()
        tech_score = sum(1 for kw in TECH_KEYWORDS if kw in query_lower)
        marketing_score = sum(1 for kw in MARKETING_KEYWORDS if kw in query_lower)
        investor_score = sum(1 for kw in INVESTOR_KEYWORDS if kw in query_lower)
        
        scores = {"tech": tech_score, "marketing": marketing_score, "investor": investor_score}
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        if len(sorted_scores) > 1:
            top2_label = sorted_scores[1][0]
            total = sum(scores.values())
            if total > 0:
                margin = (sorted_scores[0][1] - sorted_scores[1][1]) / total
            else:
                margin = 0.2
        else:
            top2_label = "marketing" if label != "marketing" else "tech"
            margin = 0.3
    
    high_risk = is_high_risk(query)
    
    return {
        "label": label,
        "confidence": confidence,
        "top2_label": top2_label,
        "margin": margin,
        "is_high_risk": high_risk
    }

