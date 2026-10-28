#!/bin/sh
set -eu
mkdir -p /etc/nginx/certs
if [ ! -f /etc/nginx/certs/mapi.crt ] || [ ! -f /etc/nginx/certs/mapi.key ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout /etc/nginx/certs/mapi.key \
    -out /etc/nginx/certs/mapi.crt \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi
exec nginx -g "daemon off;"
