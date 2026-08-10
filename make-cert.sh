#!/usr/bin/env bash
# Generate a self-signed HTTPS certificate for Pantry so phone cameras work.
# Covers the Pi's hostname (stable) plus its current IP addresses (fallback),
# so it keeps working even if the router hands out a different IP later.
set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$CERT_DIR"

HOST="$(hostname)"                       # e.g. raspberrypi
# Collect every current IPv4 address (space-separated), skipping loopback.
IPS="$(hostname -I 2>/dev/null || true)"

echo "→ Building a certificate for:"
echo "   hostname: ${HOST}.local  (and ${HOST})"
echo "   IPs:      ${IPS:-<none found>}"
echo ""

# Assemble the Subject Alternative Names. Phones connect by any of these.
CNF="$(mktemp)"
cat > "$CNF" <<EOF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = ${HOST}.local
[v3]
subjectAltName = @alt
[alt]
DNS.1 = ${HOST}.local
DNS.2 = ${HOST}
IP.1 = 127.0.0.1
EOF

# Append each detected IP as an additional SAN entry.
i=2
for ip in $IPS; do
  echo "IP.${i} = ${ip}" >> "$CNF"
  i=$((i+1))
done

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
  -days 3650 -config "$CNF" >/dev/null 2>&1

rm -f "$CNF"
chmod 600 "$CERT_DIR/key.pem"

echo "✓ Certificate written to certs/ (valid 10 years)."
echo "  Covers: ${HOST}.local, ${HOST}, 127.0.0.1${IPS:+, }${IPS}"
