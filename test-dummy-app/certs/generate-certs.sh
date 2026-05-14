#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# generate-certs.sh
# Re-generates the full two-chain PKI used by the HTTP/HTTPS dummy-app tests.
#
# Chain 1  (truststore t1)
#   ca1.pem / ca1.key        – root CA that signs server-t1 and client c1
#   server-t1.pem / .key     – TLS server cert for dummy-app-https-t1 (port 9082)
#   c1.pem / c1.key          – mTLS client cert accepted by port 9082
#
# Chain 2  (truststore t2)
#   ca2.pem / ca2.key        – root CA that signs server-t2 and client c2
#   server-t2.pem / .key     – TLS server cert for dummy-app-https-t2 (port 9083)
#   c2.pem / c2.key          – mTLS client cert accepted by port 9083
#
# ⚠️  For DEV / testing only – keys are NOT password-protected.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

SAN="subjectAltName=DNS:localhost,IP:127.0.0.1"

make_ca() {
  local name="$1" cn="$2"
  openssl genrsa -out "${name}.key" 4096 2>/dev/null
  openssl req -new -x509 -days 3650 -key "${name}.key" -out "${name}.pem" \
    -subj "/CN=${cn}/O=KafkaWiremockTesting/C=FR" 2>/dev/null
  echo "  ✅ ${name}"
}

make_server() {
  local name="$1" cn="$2" ca="$3"
  openssl genrsa -out "${name}.key" 2048 2>/dev/null
  openssl req -new -key "${name}.key" -out "${name}.csr" \
    -subj "/CN=${cn}/O=KafkaWiremockTesting/C=FR" 2>/dev/null
  openssl x509 -req -days 3650 -in "${name}.csr" \
    -CA "${ca}.pem" -CAkey "${ca}.key" -CAcreateserial \
    -out "${name}.pem" -extfile <(echo "$SAN") 2>/dev/null
  rm -f "${name}.csr" "${ca}.srl"
  echo "  ✅ ${name} (signed by ${ca})"
}

make_client() {
  local name="$1" cn="$2" ca="$3"
  openssl genrsa -out "${name}.key" 2048 2>/dev/null
  openssl req -new -key "${name}.key" -out "${name}.csr" \
    -subj "/CN=${cn}/O=KafkaWiremockTesting/C=FR" 2>/dev/null
  openssl x509 -req -days 3650 -in "${name}.csr" \
    -CA "${ca}.pem" -CAkey "${ca}.key" -CAcreateserial \
    -out "${name}.pem" 2>/dev/null
  rm -f "${name}.csr" "${ca}.srl"
  echo "  ✅ ${name} (signed by ${ca})"
}

echo "── Chain 1 (truststore t1) ──────────────────────────────"
make_ca      ca1        "TestCA1"
make_server  server-t1  "localhost"  ca1
make_client  c1         "client-c1"  ca1

echo ""
echo "── Chain 2 (truststore t2) ──────────────────────────────"
make_ca      ca2        "TestCA2"
make_server  server-t2  "localhost"  ca2
make_client  c2         "client-c2"  ca2

echo ""
echo "Done. Generated:"
ls -1 *.pem *.key
