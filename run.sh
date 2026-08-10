#!/usr/bin/env bash
# Pantry launcher, started by the systemd service (also runnable by hand).
#
# When a certificate exists, serves BOTH:
#   - HTTPS on 8443  → phones / Tailscale / camera scanning (needs TLS)
#   - HTTP  on 8080  → home computers on the LAN (simple, no cert warning)
# A single gunicorn process can't mix HTTP and HTTPS across ports, so we run two
# processes: HTTP in the background, HTTPS in the foreground. The trap makes sure
# the background HTTP process is stopped whenever this script exits, so systemd
# restarts don't leave orphans behind.
#
# With no certificate, it falls back to HTTP only on 8080.
set -euo pipefail
cd "$(dirname "$0")"

GUNICORN="./venv/bin/gunicorn"
CERT="certs/cert.pem"
KEY="certs/key.pem"

http_pid=""
cleanup() {
  if [ -n "$http_pid" ] && kill -0 "$http_pid" 2>/dev/null; then
    kill "$http_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [ -f "$CERT" ] && [ -f "$KEY" ]; then
  echo "Starting Pantry: HTTPS on 8443 (phones) + HTTP on 8080 (home computers)."
  # HTTP for the LAN, in the background.
  "$GUNICORN" --workers 1 --bind 0.0.0.0:8080 app:app &
  http_pid=$!
  # HTTPS in the foreground. Not 'exec' — we keep this shell alive so the trap
  # can stop the background HTTP process when systemd stops/restarts the service.
  "$GUNICORN" --workers 2 --bind 0.0.0.0:8443 \
    --certfile "$CERT" --keyfile "$KEY" app:app
else
  echo "No certificate found — starting HTTP only on 8080."
  echo "Run ./make-cert.sh to enable HTTPS (needed for phone camera scanning)."
  exec "$GUNICORN" --workers 2 --bind 0.0.0.0:8080 app:app
fi
