"""Phase 2C: product identification, bundle component extraction, condition risk.

Condition-risk detection is deterministic keyword matching (cheap, testable,
no AI round-trip needed). Brand/model/component identification uses Claude
because free-text listings are messy -- but it follows the same
safe-fallback pattern as the existing scanner/ai_value.py: on any failure
it returns an object with model_identified_confidently=False rather than
raising or guessing.
"""
from __future__ import annotations

import json
import re

import requests

from scanner.models import BundleComponent, ProductIdentification

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_VERSION = "2023-06-01"


def detect_condition_risk(text: str, risk_phrases: list[str]) -> tuple[str, list[str]]:
    """Deterministic keyword scan. Returns (risk_level, matched_phrases).

    Presence of risk phrases does NOT mean "reject" -- callers decide how
    to weigh it (spec section 17). More matches / more severe phrases ->
    higher risk level.
    """
    text_l = (text or "").lower()
    matched = [p for p in risk_phrases if p.lower() in text_l]
    if not matched:
        return "low", []
    if len(matched) == 1:
        return "medium", matched
    return "high", matched


_RESEARCHER_PROMPT = """You are identifying a physical product from a marketplace listing so its \
resale value can be researched. Respond with ONLY a JSON object, no prose.

Listing title: {title}
Listing description: {description}

Return JSON with this exact shape:
{{
  "brand": string or null,
  "model": string or null,
  "is_bundle": boolean,
  "components": [{{"name": string}}, ...],
  "model_identified_confidently": boolean
}}

Rules:
- Only set model_identified_confidently=true if the exact model number/name is stated or unambiguous from the text.
- If this is a bundle/lot of multiple items, set is_bundle=true and list each identifiable component separately (e.g. camera body, each lens, accessories).
- If you cannot identify the brand or model, use null. Do not guess a specific model from a vague description.
"""


def identify_product(title: str, description: str, api_key: str) -> ProductIdentification:
    if not api_key:
        return ProductIdentification()  # honest: no AI available, no fabricated ID

    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 500,
                "messages": [
                    {
                        "role": "user",
                        "content": _RESEARCHER_PROMPT.format(
                            title=title or "", description=description or ""
                        ),
                    }
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
    except Exception:
        return ProductIdentification()

    components = [BundleComponent(name=c.get("name", "")) for c in data.get("components", []) if c.get("name")]
    return ProductIdentification(
        brand=data.get("brand"),
        model=data.get("model"),
        is_bundle=bool(data.get("is_bundle")),
        components=components,
        model_identified_confidently=bool(data.get("model_identified_confidently")),
    )
