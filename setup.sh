#!/usr/bin/env bash
# Pantry — Raspberry Pi setup. Run once from inside the pantry/ folder.
set -euo pipefail

echo "→ Installing Pantry on this Raspberry Pi…"
echo ""

# ---------------------------------------------------------------------------
# 1. System packages.
#    We TRY to install python3/venv/pip, but we don't treat apt problems as
#    fatal — on older Raspberry Pi OS releases (e.g. Buster) the apt mirrors
#    have moved to archive servers and `apt-get update` errors out. Pantry only
#    needs Python 3 + venv, which such systems almost always already have, so we
#    verify those directly further down instead of trusting apt to succeed.
# ---------------------------------------------------------------------------
echo "→ Checking system packages (apt problems here are non-fatal)…"
if sudo apt-get update -qq 2>/dev/null; then
  sudo apt-get install -y python3 python3-venv python3-pip 2>/dev/null \
    || echo "  ! apt couldn't install packages — will check if they're already present."
else
  echo "  ! apt-get update failed (common on end-of-life Raspberry Pi OS)."
  echo "    Skipping apt and checking for what Pantry actually needs…"
fi
echo ""

# ---------------------------------------------------------------------------
# 2. Verify the two things Pantry genuinely requires.
# ---------------------------------------------------------------------------
missing=0

if command -v python3 >/dev/null 2>&1; then
  echo "  ✓ python3: $(python3 --version 2>&1)"
else
  echo "  ✗ python3 is not installed."
  missing=1
fi

if python3 -m venv --help >/dev/null 2>&1; then
  echo "  ✓ python venv module available"
else
  echo "  ✗ python3-venv is not installed."
  missing=1
fi

if [ "$missing" -eq 1 ]; then
  cat <<'EOF'

──────────────────────────────────────────────────────────────────────
Pantry needs Python 3 and the venv module, and apt can't install them
on this system (its package mirrors are offline — a sign the OS is past
end-of-life).

Two ways forward:

  A) Re-point apt at Debian's archive, then install:
       sudo sed -i 's|deb.debian.org/debian |archive.debian.org/debian |g' /etc/apt/sources.list
       sudo sed -i '/security.debian.org/d' /etc/apt/sources.list
       sudo apt-get -o Acquire::Check-Valid-Until=false update
       sudo apt-get install -y python3 python3-venv python3-pip
     then re-run ./setup.sh

  B) Recommended: reflash the SD card with the current Raspberry Pi OS
     (Bookworm) for security updates. Your pantry/ folder — including
     data/pantry.db — copies across unchanged; just run ./setup.sh there.
──────────────────────────────────────────────────────────────────────
EOF
  exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# 3. Virtual environment + dependencies.
#    We upgrade pip first so it honours each package's Requires-Python and picks
#    versions compatible with this Python. If the normal install still fails
#    (very old Python 3.7 on Buster), we retry with versions known to support
#    3.7: Flask/Werkzeug 2.2.x and an older gunicorn.
# ---------------------------------------------------------------------------
echo "→ Creating virtual environment…"
python3 -m venv venv
./venv/bin/pip install --upgrade pip -q || echo "  ! couldn't upgrade pip; continuing with what's here."
echo "→ Installing Python dependencies…"
if ./venv/bin/pip install -r requirements.txt -q 2>/dev/null; then
  echo "  ✓ Dependencies installed."
else
  echo "  ! Standard install failed — falling back to Python 3.7-compatible versions…"
  ./venv/bin/pip install -q "Flask>=2.2,<2.3" "Werkzeug>=2.2,<2.3" "gunicorn>=20.1,<21" \
    && echo "  ✓ Installed Flask 2.2.x (Python 3.7-compatible)."
fi

# ---------------------------------------------------------------------------
# 4. Initialise the database (safe to run on an existing db — it migrates).
# ---------------------------------------------------------------------------
./venv/bin/python -c "import app; app.init_db(); print('  ✓ Database ready.')"

# ---------------------------------------------------------------------------
# 4b. Generate the HTTPS certificate (needed for phone camera scanning).
#     Skipped if one already exists, so re-running setup won't disturb it.
# ---------------------------------------------------------------------------
if [ -f certs/cert.pem ] && [ -f certs/key.pem ]; then
  echo "  ✓ HTTPS certificate already present (keeping it)."
else
  echo "→ Generating HTTPS certificate for camera scanning…"
  ./make-cert.sh
fi

# ---------------------------------------------------------------------------
# 5. Install & start the service (auto-starts on boot).
#    The unit file assumes /home/pi/pantry + user 'pi'. If you're elsewhere,
#    we patch the paths/user to match wherever this script is actually running.
# ---------------------------------------------------------------------------
echo "→ Installing the auto-start service…"
HERE="$(cd "$(dirname "$0")" && pwd)"
WHO="$(whoami)"
TMP_UNIT="$(mktemp)"
sed -e "s|/home/pi/pantry|${HERE}|g" -e "s|^User=pi|User=${WHO}|" \
    pantry.service > "$TMP_UNIT"
sudo cp "$TMP_UNIT" /etc/systemd/system/pantry.service
rm -f "$TMP_UNIT"
sudo systemctl daemon-reload
sudo systemctl enable pantry
sudo systemctl restart pantry

HOST="$(hostname)"
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "✅ Pantry is running over HTTPS."
echo ""
echo "   On any phone on your Wi-Fi, open:"
echo "     https://${HOST}.local:8443     (preferred — survives IP changes)"
echo "     https://${IP}:8443             (if .local doesn't resolve)"
echo ""
echo "   The first time, your phone will warn that the connection isn't"
echo "   private — that's expected with a self-signed certificate. Tap"
echo "   Advanced → Proceed (once per phone). The camera scanner then works."
echo "   Tip: 'Add to Home Screen' to use it like an app."
