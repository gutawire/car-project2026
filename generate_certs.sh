#!/bin/bash
# One-time setup: generate the self-signed TLS cert/key the app serves on
# port 443. Not committed to git (private key) - run this after cloning.
set -euo pipefail

CERTS_DIR="$(dirname "$0")/certs"
mkdir -p "$CERTS_DIR"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERTS_DIR/key.pem" \
  -out "$CERTS_DIR/cert.pem" \
  -days 3650 \
  -subj "/CN=driverwatch.local"

chmod 600 "$CERTS_DIR/key.pem"

echo "Generated $CERTS_DIR/cert.pem and $CERTS_DIR/key.pem (valid 10 years)."
echo "The phone browser will show a one-time 'not secure' warning for this"
echo "self-signed cert - that's expected, tap through it to continue."
