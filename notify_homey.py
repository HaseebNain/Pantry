#!/usr/bin/env python3
"""
Pantry -> Homey notifier.

Run once a day (via the systemd timer below). Reads Pantry's own "Use soon"
list and POSTs it to a Homey Pro local webhook, so a Homey Flow can turn it
into a phone notification, a light, an announcement — whatever you build.

This is deliberately a separate script from app.py: if this fails for any
reason (Homey offline, network hiccup), it can never take Pantry itself down.
It only ever reads from Pantry's local API; it never writes anything.

Setup:
  1. Fill in HOMEY_IP and WEBHOOK_EVENT below (or set them as environment
     variables of the same name — env vars win if set).
  2. In the Homey app: Flow -> New Flow -> When -> Logic ->
     "Webhook event [Event] has been received" -> set Event to the same
     string as WEBHOOK_EVENT below (default: "pantry_expiring").
  3. Test it by hand:  ./venv/bin/python notify_homey.py
  4. Install the timer so it runs automatically (see README).
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------- settings

# Homey Pro's local IP on your home network (Homey app -> Settings -> General,
# or check your router's device list). Local webhooks only work on the same
# LAN as Homey, which is exactly where the Pi already lives.
HOMEY_IP = os.environ.get("HOMEY_IP", "192.168.1.XXX")

# The event name your Homey Flow listens for. Must match the Flow's
# "Webhook event ... has been received" card exactly.
WEBHOOK_EVENT = os.environ.get("WEBHOOK_EVENT", "pantry_expiring")

# Where Pantry itself is running (this script runs on the same Pi, so localhost
# is right even if HTTPS uses a self-signed cert we don't need to verify here).
PANTRY_URL = os.environ.get("PANTRY_URL", "http://127.0.0.1:8080")

# ---------------------------------------------------------------- logic

def fetch_expiring():
    """Pull the at-risk grocery list straight from Pantry's own API."""
    url = f"{PANTRY_URL}/api/items?filter=expiring"
    req = urllib.request.Request(url, headers={"User-Agent": "PantryNotifier/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def describe(item):
    """Turn one item into a short human phrase, e.g. 'Spinach (1 day)'."""
    days = item.get("days_left")
    fresh = item.get("freshness")
    if fresh == "expired":
        when = "expired" if days is None else f"expired {abs(days)}d ago"
    elif days == 0:
        when = "today"
    elif days == 1:
        when = "1 day"
    else:
        when = f"{days} days"
    return f"{item['name']} ({when})"

def send_to_homey(items):
    """POST the expiring list to Homey's local webhook as a JSON body."""
    summary = "; ".join(describe(i) for i in items) if items else ""
    payload = {
        "count": len(items),
        "summary": summary,             # e.g. "Spinach (1 day); Milk (today)"
        "items": [i["name"] for i in items],
    }
    # Local webhook format: http://<homey-ip>/webhook?event=<event>
    # Homey exposes the POST body to the Flow as the JSON token.
    url = f"http://{HOMEY_IP}/webhook?event={urllib.parse.quote(WEBHOOK_EVENT)}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "PantryNotifier/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status

def main():
    try:
        items = fetch_expiring()
    except Exception as e:
        print(f"Couldn't read Pantry's expiring list: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        status = send_to_homey(items)
        print(f"Sent {len(items)} expiring item(s) to Homey (HTTP {status}).")
    except Exception as e:
        print(f"Couldn't reach Homey at {HOMEY_IP}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
