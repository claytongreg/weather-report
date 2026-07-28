#!/usr/bin/env python3
"""
New-Wildfire SMS Alerts via Telnyx.

Texts the same numbers as the wind warning whenever a wildfire appears within
SMS_RADIUS_KM of Birchdale for the first time.

"New" is judged against state/wildfire_alerts.json, which the workflow commits
back to the repo. That file is the whole feature: without durable state every
run would re-text the same fire. On the first run (no state file) every current
fire is recorded silently so an already-burning fire is not announced as new.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

from utils import PACIFIC
from sms import get_recipients, send_sms
from wildfires import (
    WILDFIRE_MAP_URL,
    fetch_nearby_wildfires,
    fire_display_name,
    fire_key,
    format_fire_size,
)

SMS_RADIUS_KM = 15
STATE_PATH = os.path.join("state", "wildfire_alerts.json")
STATE_VERSION = 1

# Fires are recorded so they never re-alert. Drop entries after this long to
# keep the file bounded; nothing in BC stays active anywhere near this long.
STATE_RETENTION_DAYS = 730

# List at most this many fires in one message before switching to a count.
MAX_FIRES_LISTED = 3


def load_state():
    """Read the alert state. Returns None when no state file exists yet."""
    if not os.path.exists(STATE_PATH):
        return None

    with open(STATE_PATH, "r", encoding="utf-8") as handle:
        state = json.load(handle)

    if not isinstance(state, dict) or not isinstance(state.get("fires"), dict):
        raise ValueError(f"{STATE_PATH} is not a valid state file")
    return state


def save_state(state):
    """Write the alert state, creating the directory on first use."""
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"  Wrote {STATE_PATH}")


def prune_state(state, now):
    """Drop fire records older than the retention window."""
    cutoff = now - timedelta(days=STATE_RETENTION_DAYS)
    kept = {}
    for key, record in state["fires"].items():
        first_seen = record.get("first_seen")
        try:
            seen_at = datetime.fromisoformat(first_seen)
        except (TypeError, ValueError):
            kept[key] = record
            continue
        if seen_at >= cutoff:
            kept[key] = record
        else:
            print(f"  Pruned aged-out record: {key}")
    state["fires"] = kept


def describe_fire(fire):
    """Compact one-line description used inside the SMS."""
    name = fire_display_name(fire)
    label = f"{name} ({fire['fire_number']})" if name else fire["fire_number"]
    return (
        f"{label} {fire['distance_km']:.1f}km, "
        f"{fire['status']}, {format_fire_size(fire.get('size_ha'))}"
    )


def build_message(new_fires):
    """Build the alert SMS for one or more newly detected fires."""
    listed = new_fires[:MAX_FIRES_LISTED]
    details = "; ".join(describe_fire(fire) for fire in listed)

    remaining = len(new_fires) - len(listed)
    if remaining > 0:
        details += f"; +{remaining} more"

    if len(new_fires) == 1:
        headline = f"New wildfire within {SMS_RADIUS_KM}km of Birchdale:"
        link = new_fires[0]["url"]
    else:
        headline = (
            f"{len(new_fires)} new wildfires within {SMS_RADIUS_KM}km of Birchdale:"
        )
        link = WILDFIRE_MAP_URL

    return f"{headline} {details}. {link}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be sent without texting or writing state.",
    )
    parser.add_argument(
        "--test-sms",
        action="store_true",
        help="Send a test message to confirm delivery, then exit.",
    )
    args = parser.parse_args()

    now = datetime.now(PACIFIC)
    print(f"New-wildfire SMS monitor - {now:%Y-%m-%d %H:%M:%S %Z}")
    print(f"Radius: {SMS_RADIUS_KM} km from Birchdale")
    print("=" * 70)

    if args.test_sms:
        print("\nSending test message...")
        text = (
            f"Test from the Birchdale wildfire monitor. New fires within "
            f"{SMS_RADIUS_KM}km will arrive on this number."
        )
        sent = send_sms(text)
        if sent == 0:
            # A "successful" test that delivered nothing is worse than useless:
            # it is exactly how the wind monitor hid a dead Telnyx key for days.
            print("\nERROR: test message reached nobody.")
            return 1
        print(f"\nTest message delivered to {sent} recipient(s).")
        return 0

    # A corrupt state file must not be treated as "no fires known" - that would
    # announce every active fire as new. Fail loudly instead.
    try:
        state = load_state()
    except (json.JSONDecodeError, ValueError) as error:
        print(f"\nERROR: cannot read {STATE_PATH}: {error}")
        print("Refusing to run - fix or delete the file to re-seed a baseline.")
        return 1

    seeding = state is None
    if seeding:
        print(f"\nNo {STATE_PATH} yet - seeding a baseline, no SMS this run.")
        state = {"version": STATE_VERSION, "radius_km": SMS_RADIUS_KM, "fires": {}}
    elif state.get("radius_km") != SMS_RADIUS_KM:
        # A widened radius would make every fire in the new ring look new.
        print(
            f"\nRadius changed ({state.get('radius_km')} km -> {SMS_RADIUS_KM} km)"
            " - re-seeding baseline, no SMS this run."
        )
        seeding = True
        state["radius_km"] = SMS_RADIUS_KM

    print("\nFetching active BC wildfires...")
    try:
        nearby_fires = fetch_nearby_wildfires(SMS_RADIUS_KM)
    except Exception as error:  # noqa: BLE001 - surface any fetch failure as red CI
        print(f"ERROR: wildfire fetch failed: {error}")
        return 1

    print(f"  {len(nearby_fires)} active fire(s) within {SMS_RADIUS_KM} km")
    for fire in nearby_fires:
        print(f"    - {describe_fire(fire)}")

    known = state["fires"]
    new_fires = [fire for fire in nearby_fires if fire_key(fire) not in known]

    if not new_fires:
        print("\nNo new fires since the last check - nothing to send.")
    else:
        print(f"\n{len(new_fires)} fire(s) not seen before:")
        for fire in new_fires:
            print(f"    - {fire_key(fire)}: {describe_fire(fire)}")

    # Record every fire currently in range, whether or not it triggered an SMS.
    for fire in nearby_fires:
        key = fire_key(fire)
        if key in known:
            continue
        known[key] = {
            "first_seen": now.isoformat(),
            "name": fire_display_name(fire),
            "distance_km": round(fire["distance_km"], 1),
            "status": fire["status"],
            # Only fires reached here are new, so this run alerts on them
            # unless we are establishing the initial baseline.
            "alerted": not seeding,
            "seeded": seeding,
        }

    exit_code = 0
    if new_fires and not seeding:
        message = build_message(new_fires)
        print(f"\nSMS ({len(message)} chars):\n  {message}")

        recipients = get_recipients()
        if args.dry_run:
            print(f"\n[dry run] Would send to {len(recipients)} recipient(s).")
        else:
            print(f"\nSending to {len(recipients)} recipient(s)...")
            sent = send_sms(message, recipients)
            if sent == 0:
                # Do not record fires as alerted when nothing was delivered, so
                # the next run retries instead of silently swallowing the alert.
                print("\nERROR: no messages were delivered.")
                for fire in new_fires:
                    known.pop(fire_key(fire), None)
                exit_code = 1
            else:
                print(f"\nDelivered to {sent}/{len(recipients)} recipient(s).")

    prune_state(state, now)
    state["version"] = STATE_VERSION
    state["updated"] = now.isoformat()

    if args.dry_run:
        print("\n[dry run] State not written.")
    else:
        print("\nSaving state...")
        save_state(state)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
