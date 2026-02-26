from typing import Dict, List

RISK_KEYWORDS = {
    "self_harm": [
        "suicide",
        "kill myself",
        "self-harm",
        "hurt myself",
        "end my life",
        "자해",
        "죽고 싶",
        "목숨",
    ],
    "medical": [
        "diagnose",
        "prescription",
        "medical advice",
        "treat my",
        "symptom",
        "병원",
        "진단",
        "처방",
    ],
    "legal": [
        "legal advice",
        "lawsuit",
        "sue",
        "contract dispute",
        "변호사",
        "소송",
        "법률",
    ],
    "financial": [
        "invest",
        "stock tip",
        "crypto",
        "financial advice",
        "trading signal",
        "주식",
        "코인",
        "투자",
    ],
    "hate_harassment": [
        "hate",
        "harass",
        "racial slur",
        "violent threat",
        "혐오",
        "괴롭혀",
    ],
}


def classify_risk(text: str) -> Dict[str, object]:
    lowered = (text or "").lower()
    categories: List[str] = []
    for category, keywords in RISK_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            categories.append(category)

    level = "high" if categories else "low"
    return {"level": level, "categories": categories}
