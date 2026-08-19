#!/usr/bin/env python3
"""
Pantry -> Homey notifier.

Runs hourly (via the systemd timer below) and checks whether *now* matches
your configured notify time for today — a different time on weekdays vs.
weekends, both set below. When it's the right moment, it reads Pantry's own
"Use soon" list and triggers a Homey Pro local webhook, so a Flow can turn it
into a phone notification, a light, an announcement — whatever you build.

This is deliberately a separate script from app.py: if this fails for any
reason (Homey offline, network hiccup), it can never take Pantry itself down.
It only ever reads from Pantry's local API; it never writes anything.

Setup:
  1. Fill in HOMEY_IP, WEBHOOK_EVENT, WEEKDAY_HOUR and WEEKEND_HOUR below (or
     set them as environment variables of the same name — env vars win).
  2. In the Homey app: Flow -> New Flow -> When -> Logic ->
     "Webhook event [Event] has been received" -> set Event to the same
     string as WEBHOOK_EVENT below (default: "pantry_expiring").
  3. Test it by hand, ignoring the time check:  ./venv/bin/python notify_homey.py --force
  4. Install the hourly timer so it runs automatically (see README).
"""
import os
import sys
import json
import ssl
import argparse
from datetime import datetime
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

# What hour (0-23, Pi's local time) to notify — separately for weekdays
# (Mon-Fri) and weekends (Sat-Sun). Change these two numbers any time; no
# systemd editing needed. The timer checks every hour, so pick whole hours.
WEEKDAY_HOUR = int(os.environ.get("WEEKDAY_HOUR", "18"))   # 6pm on weekdays
WEEKEND_HOUR = int(os.environ.get("WEEKEND_HOUR", "10"))   # 10am on weekends

# Where Pantry itself is running. This script runs on the same Pi as Pantry,
# so it talks over localhost either way. If your Pi serves HTTPS-only (the
# default once a certificate exists — see make-cert.sh), set this to
# "https://127.0.0.1:8443" instead; if it also serves plain HTTP on 8080
# (the dual-port run.sh), the default below works unchanged.
PANTRY_URL = os.environ.get("PANTRY_URL", "http://127.0.0.1:8080")

# A self-signed cert only exists to satisfy the browser padlock for real users
# on the network — this script talks to 127.0.0.1 on the same machine, where
# certificate verification protects against nothing, so we skip it rather than
# asking the household to also install the Pi's cert into this script's trust
# store. Only used when PANTRY_URL is https://.
_LOCAL_SSL_CONTEXT = ssl._create_unverified_context()

# Tracks the last date we notified, so the hourly timer only actually fires
# once per day even though it checks in every hour.
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", ".last_notify")

# ---------------------------------------------------------------- scheduling

def target_hour_for(now):
    """Which hour we should notify at today, given it's a weekday or weekend."""
    is_weekend = now.weekday() >= 5   # Mon=0 ... Sat=5, Sun=6
    return WEEKEND_HOUR if is_weekend else WEEKDAY_HOUR

def already_notified_today(now):
    try:
        with open(_STATE_FILE) as f:
            return f.read().strip() == now.strftime("%Y-%m-%d")
    except FileNotFoundError:
        return False

def mark_notified_today(now):
    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        f.write(now.strftime("%Y-%m-%d"))

def is_notify_time(now):
    """True once per day, during the hour matching today's configured time."""
    if already_notified_today(now):
        return False
    return now.hour == target_hour_for(now)

# ---------------------------------------------------------------- logic

def fetch_expiring():
    """Pull the at-risk grocery list straight from Pantry's own API."""
    url = f"{PANTRY_URL}/api/items?filter=expiring"
    req = urllib.request.Request(url, headers={"User-Agent": "PantryNotifier/1.0"})
    ctx = _LOCAL_SSL_CONTEXT if PANTRY_URL.startswith("https://") else None
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
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
    """Trigger Homey's local webhook with the expiring list in the 'tag' field.

    Homey's *built-in* Logic -> Webhook trigger only ever exposes a single,
    fixed token, and the query parameter that fills it must be named exactly
    "tag" (not any custom name) — see Homey's own docs:
        http://<homey-ip>/webhook?event=<event>&tag=<value>
    Custom key names like "summary" or "count" are silently ignored by the
    built-in trigger, which is why they never appeared as tags. Everything we
    want to say goes into that one "tag" string.
    """
    count = len(items)
    summary = "; ".join(describe(i) for i in items)
    tag_text = f"{count} item{'s' if count != 1 else ''} expiring: {summary}"
    params = {"event": WEBHOOK_EVENT, "tag": tag_text}
    url = f"http://{HOMEY_IP}/webhook?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET",
                                  headers={"User-Agent": "PantryNotifier/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status

def main():
    parser = argparse.ArgumentParser(description="Pantry -> Homey expiring-items notifier")
    parser.add_argument("--force", action="store_true",
                         help="Send now regardless of the configured schedule (for testing).")
    args = parser.parse_args()

    now = datetime.now()
    if not args.force and not is_notify_time(now):
        # Not our configured hour today (or already sent) — this is the normal,
        # silent outcome for most of the hourly timer's runs.
        print(f"Not notify time yet today (target hour: {target_hour_for(now)}:00, "
              f"now: {now.hour}:00). Skipping.")
        return

    try:
        items = fetch_expiring()
    except Exception as e:
        print(f"Couldn't read Pantry's expiring list: {e}", file=sys.stderr)
        sys.exit(1)

    if not items:
        # Nothing to report — skip Homey entirely rather than sending an empty
        # notification. Still counts as today's check, so we don't retry hourly.
        print("Nothing expiring today — not notifying Homey.")
        if not args.force:
            mark_notified_today(now)
        return

    try:
        status = send_to_homey(items)
        print(f"Sent {len(items)} expiring item(s) to Homey (HTTP {status}).")
        if not args.force:
            mark_notified_today(now)
    except Exception as e:
        print(f"Couldn't reach Homey at {HOMEY_IP}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
