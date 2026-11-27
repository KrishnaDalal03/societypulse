import hashlib
import re
from datetime import datetime, timezone


def normalize_message(event: dict) -> dict:
    sender = str(event.get("sender") or "unknown").strip()
    channel = str(event.get("channel") or "whatsapp").strip().lower()
    raw_message = str(event.get("message") or "").strip()

    # Lowercase, remove punctuation, and collapse extra spaces
    cleaned = re.sub(r"[^\w\s]", " ", raw_message.lower())
    normalized = re.sub(r"\s+", " ", cleaned).strip()

    # Create a consistent fingerprint (idempotency key)
    fingerprint_source = f"{sender}|{channel}|{normalized}"
    digest = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:12]
    idempotency_key = f"msg_{digest}"

    return {
        "sender": sender,
        "channel": channel,
        "raw_message": raw_message,
        "normalized_message": normalized,
        "idempotency_key": idempotency_key,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


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

        print(f"--- Message #{idx} ---")
        print("Sender:          ", record["sender"])
        print("Normalized:      ", record["normalized_message"])
        print("Idempotency Key: ", record["idempotency_key"])
        print("Duplicate?:      ", is_duplicate)