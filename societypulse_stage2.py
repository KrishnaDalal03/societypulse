import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

try:
    from google import genai
    from google.genai import types

    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


def normalize_message(event: dict) -> dict:
    sender = str(event.get("sender") or "unknown").strip()
    channel = str(event.get("channel") or "whatsapp").strip().lower()
    raw_message = str(event.get("message") or "").strip()

    cleaned = re.sub(r"[^\w\s]", " ", raw_message.lower())
    normalized = re.sub(r"\s+", " ", cleaned).strip()

    fingerprint_source = f"{sender}|{channel}|{normalized}"
    digest = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:12]

    return {
        "sender": sender,
        "channel": channel,
        "raw_message": raw_message,
        "normalized_message": normalized,
        "idempotency_key": f"msg_{digest}",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def rule_based_triage(normalized_text: str) -> dict[str, Any]:
    """Fast fallback so your demo works even offline or without API credits."""
    wing_match = re.search(r"\b([a-z])\s*wing\b", normalized_text)
    flat_match = re.search(r"\b(?:flat|room|no)?\s*(\d{3,4})\b", normalized_text)

    wing = wing_match.group(1).upper() if wing_match else None
    flat = flat_match.group(1) if flat_match else None

    if any(k in normalized_text for k in ["lift", "elevator", "stuck"]):
        category = "lift"
    elif any(k in normalized_text for k in ["paani", "pani", "water", "tank", "supply"]):
        category = "water"
    elif any(k in normalized_text for k in ["plumber", "pipe", "leak", "tap", "drain"]):
        category = "plumbing"
    elif any(k in normalized_text for k in ["gate", "guard", "security", "visitor", "pass"]):
        category = "security"
    elif any(k in normalized_text for k in ["park", "car", "bike", "slot"]):
        category = "parking"
    elif any(k in normalized_text for k in ["bill", "maintenance", "invoice", "payment", "due"]):
        category = "billing"
    else:
        category = "other"

    if category == "lift" and "stuck" in normalized_text:
        urgency = "high"
    elif any(
        k in normalized_text
        for k in ["jaldi", "urgent", "emergency", "subah se", "no water", "paani nahi"]
    ):
        urgency = "high"
    elif category in {"billing", "security"} and "pass" in normalized_text:
        urgency = "low"
    else:
        urgency = "medium"

    return {
        "wing": wing,
        "flat": flat,
        "category": category,
        "urgency": urgency,
        "triage_source": "rule_fallback",
    }


def triage_message(normalized_text: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not HAS_GENAI:
        return rule_based_triage(normalized_text)

    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "You are an RWA / housing society helpdesk triage assistant. "
            "Messages may be in English or Hinglish. Return ONLY valid JSON with keys:\n"
            '- "wing": single uppercase letter like "A", "B", "C" if mentioned, else null\n'
            '- "flat": flat/unit number string like "402" if mentioned, else null\n'
            '- "category": one of "water", "plumbing", "lift", "security", "parking", "billing", "other"\n'
            '- "urgency": one of "high", "medium", "low"\n\n'
            f"Message: {normalized_text}"
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        parsed = json.loads(response.text)
        parsed["triage_source"] = "gemini"
        return parsed
    except Exception:
        return rule_based_triage(normalized_text)


if __name__ == "__main__":
    sample_messages = [
        {
            "sender": "+919820112233",
            "channel": "whatsapp",
            "message": "B wing 402 mein subah se paani nahi aa raha, plumber bhejo jaldi",
        },
        {
            "sender": "+919820112233",
            "channel": "whatsapp",
            "message": "B wing 402 mein subah se paani nahi aa raha, plumber bhejo jaldi!!",
        },
        {
            "sender": "+919820445566",
            "channel": "whatsapp",
            "message": "Lift 2 stuck between 3rd and 4th floor in A wing!",
        },
        {
            "sender": "+919820778899",
            "channel": "app",
            "message": "Visitor pass chahiye kal subah 10 baje delivery ke liye",
        },
    ]

    seen_keys = set()

    for idx, msg in enumerate(sample_messages, start=1):
        record = normalize_message(msg)
        is_duplicate = record["idempotency_key"] in seen_keys
        seen_keys.add(record["idempotency_key"])

        print(f"=== Message #{idx} ===")
        print("Normalized :", record["normalized_message"])
        print("Duplicate? :", is_duplicate)

        if is_duplicate:
            print("Action     : Suppressed duplicate\n")
            continue

        triage = triage_message(record["normalized_message"])
        print("Triage     :", triage, "\n")