import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from google import genai
    from google.genai import types

    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

SLA_MINUTES = {
    "high": 30,
    "medium": 240,
    "low": 1440,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_message(event: dict) -> dict[str, Any]:
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
        "received_at": now_iso(),
    }


def rule_based_triage(normalized_text: str) -> dict[str, Any]:
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


def run_pipeline(messages: list[dict], data_dir: str = "data") -> dict[str, Any]:
    out_path = Path(data_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    residents: dict[str, dict] = {}
    tickets: list[dict] = []
    master_incidents: dict[str, dict] = {}
    execution_logs: list[dict] = []
    seen_idempotency_keys: set[str] = set()

    for idx, msg in enumerate(messages, start=1):
        norm = normalize_message(msg)
        key = norm["idempotency_key"]
        sender = norm["sender"]

        # Ensure resident record exists
        if sender not in residents:
            residents[sender] = {
                "sender": sender,
                "channel": norm["channel"],
                "wing": None,
                "flat": None,
                "total_messages": 0,
            }
        residents[sender]["total_messages"] += 1

        # 1. Exact duplicate suppression
        if key in seen_idempotency_keys:
            execution_logs.append({
                "log_id": f"log_{idx:03d}",
                "timestamp": now_iso(),
                "idempotency_key": key,
                "sender": sender,
                "status": "duplicate_suppressed",
                "detail": "Repeated message suppressed via idempotency key",
            })
            continue

        seen_idempotency_keys.add(key)

        # 2. Triage
        triage = triage_message(norm["normalized_message"])
        wing = triage.get("wing")
        flat = triage.get("flat")
        category = triage.get("category", "other")
        urgency = triage.get("urgency", "medium")

        if wing:
            residents[sender]["wing"] = wing
        if flat:
            residents[sender]["flat"] = flat

        # 3. Outage clustering for wing-level infrastructure issues
        incident_id = None
        clusterable_categories = {"water", "lift", "security", "parking"}
        if wing and category in clusterable_categories:
            cluster_key = f"{wing}:{category}"
            if cluster_key not in master_incidents:
                incident_id = f"inc_{wing.lower()}_{category}"
                master_incidents[cluster_key] = {
                    "incident_id": incident_id,
                    "wing": wing,
                    "category": category,
                    "urgency": urgency,
                    "status": "open",
                    "affected_flats": [flat] if flat else [],
                    "ticket_ids": [],
                    "created_at": now_iso(),
                }
            else:
                inc = master_incidents[cluster_key]
                incident_id = inc["incident_id"]
                if flat and flat not in inc["affected_flats"]:
                    inc["affected_flats"].append(flat)
                if urgency == "high":
                    inc["urgency"] = "high"

        # 4. Create ticket with SLA due time
        sla_mins = SLA_MINUTES.get(urgency, 240)
        sla_due_at = (datetime.now(timezone.utc) + timedelta(minutes=sla_mins)).isoformat()
        ticket_id = f"tkt_{len(tickets) + 1:03d}"

        ticket = {
            "ticket_id": ticket_id,
            "idempotency_key": key,
            "sender": sender,
            "wing": wing,
            "flat": flat,
            "category": category,
            "urgency": urgency,
            "status": "open",
            "master_incident_id": incident_id,
            "sla_minutes": sla_mins,
            "sla_due_at": sla_due_at,
            "message": norm["raw_message"],
            "triage_source": triage.get("triage_source", "rule_fallback"),
            "created_at": now_iso(),
        }
        tickets.append(ticket)

        if incident_id:
            for inc in master_incidents.values():
                if inc["incident_id"] == incident_id:
                    inc["ticket_ids"].append(ticket_id)

        execution_logs.append({
            "log_id": f"log_{idx:03d}",
            "timestamp": now_iso(),
            "idempotency_key": key,
            "sender": sender,
            "status": "clustered_to_incident" if incident_id else "ticket_created",
            "ticket_id": ticket_id,
            "master_incident_id": incident_id,
            "triage_source": triage.get("triage_source"),
        })

    stores = {
        "residents": list(residents.values()),
        "tickets": tickets,
        "master_incidents": list(master_incidents.values()),
        "execution_logs": execution_logs,
    }

    for name, content in stores.items():
        (out_path / f"{name}.json").write_text(
            json.dumps(content, indent=2), encoding="utf-8"
        )

    return stores


if __name__ == "__main__":
    test_messages = [
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
            "sender": "+919820112299",
            "channel": "whatsapp",
            "message": "B wing 602 mein bhi paani band hai subah se",
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
        {
            "sender": "+919820889900",
            "channel": "whatsapp",
            "message": "C wing 105 kitchen sink ke niche pipe leak ho raha hai",
        },
        {
            "sender": "+919820990011",
            "channel": "app",
            "message": "Monthly maintenance bill April ka receipt chahiye",
        },
        {
            "sender": "+919820667788",
            "channel": "whatsapp",
            "message": "A wing gate ke paas visitor car galat park hai",
        },
    ]

    result = run_pipeline(test_messages)
    print(f"Residents        : {len(result['residents'])}")
    print(f"Tickets created  : {len(result['tickets'])}")
    print(f"Master incidents : {len(result['master_incidents'])}")
    print(f"Execution logs   : {len(result['execution_logs'])}")
    print("\n--- Master Incidents ---")
    print(json.dumps(result["master_incidents"], indent=2))
    print("\n--- Execution Logs ---")
    print(json.dumps(result["execution_logs"], indent=2))