"""
Telnyx SMS delivery shared by the Birchdale alert monitors.

Recipients come from the PHONE_NUMBERS secret (a JSON list), which is the same
list the wind warning uses.
"""
import json
import os

import requests

TELNYX_API_URL = "https://api.telnyx.com/v2/messages"


def get_recipients():
    """Parse the PHONE_NUMBERS secret into a flat list of phone numbers."""
    raw = os.environ.get("PHONE_NUMBERS")
    if not raw:
        return []

    recipients = raw
    if isinstance(recipients, str):
        try:
            recipients = json.loads(recipients)
        except json.JSONDecodeError:
            # Tolerate a bare or comma-separated number instead of a JSON list.
            recipients = [part.strip() for part in raw.split(",") if part.strip()]

    if not isinstance(recipients, list):
        recipients = [recipients]

    flattened = []
    for recipient in recipients:
        if isinstance(recipient, list):
            recipient = recipient[0] if recipient else None
        if recipient:
            flattened.append(str(recipient).strip())
    return flattened


def send_sms(text, recipients=None):
    """Send text to every recipient. Returns the number delivered successfully."""
    api_key = os.environ.get("TELNYX_API_KEY")
    from_number = os.environ.get("TELNYX_PHONE_NUMBER")

    if recipients is None:
        recipients = get_recipients()

    if not recipients:
        print("  No phone numbers configured - nothing sent")
        return 0
    if not api_key or not from_number:
        raise RuntimeError("TELNYX_API_KEY / TELNYX_PHONE_NUMBER are not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    sent = 0
    for index, recipient in enumerate(recipients, start=1):
        print(f"  [{index}/{len(recipients)}] Sending to {recipient}...")
        try:
            response = requests.post(
                TELNYX_API_URL,
                headers=headers,
                json={"from": from_number, "to": recipient, "text": text},
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            print(f"    Sent (id {result['data']['id']})")
            sent += 1
        except Exception as error:  # noqa: BLE001 - one bad number must not stop the rest
            print(f"    FAILED: {error}")
            if getattr(error, "response", None) is not None:
                print(f"    Response: {error.response.text}")

    return sent
