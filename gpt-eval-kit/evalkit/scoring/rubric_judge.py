from typing import Any, Dict, Optional

import yaml


def maybe_rubric_score(answer: str, rubric_path: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Optional rubric scorer. Keeps CI deterministic by default (returns None when no rubric).
    """
    if not rubric_path:
        return None
    with open(rubric_path, "r", encoding="utf-8") as f:
        rubric = yaml.safe_load(f)
    criteria = rubric.get("criteria", [])
    # Lightweight deterministic placeholder: score 3 when answer exists, otherwise 1.
    base = 3 if (answer or "").strip() else 1
    return {
        "rubric": rubric.get("name", "unknown"),
        "scores": {c.get("id", f"c{idx}"): base for idx, c in enumerate(criteria)},
    }
