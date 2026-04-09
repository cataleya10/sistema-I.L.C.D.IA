#!/bin/sh
# ─── docker-entrypoint.sh ────────────────────────────────────────────────────
# Genera la config de nginx en runtime basándose en variables de entorno:
#   TLS_ENABLED   "true" activa HTTPS+redirect HTTP→HTTPS (default: false)
#   TLS_CERT      ruta al certificado PEM  (default: /etc/nginx/certs/fullchain.pem)
#   TLS_KEY       ruta a la clave privada  (default: /etc/nginx/certs/privkey.pem)
# ─────────────────────────────────────────────────────────────────────────────
set -e

TLS_ENABLED="${TLS_ENABLED:-false}"
TLS_CERT="${TLS_CERT:-/etc/nginx/certs/fullchain.pem}"
TLS_KEY="${TLS_KEY:-/etc/nginx/certs/privkey.pem}"
CONF="/etc/nginx/conf.d/default.conf"

# Validate TLS files before writing config
if [ "$TLS_ENABLED" = "true" ]; then
  if [ ! -f "$TLS_CERT" ]; then
    echo "ERROR: TLS_ENABLED=true pero certificado no encontrado: $TLS_CERT" >&2
    exit 1
  fi
  if [ ! -f "$TLS_KEY" ]; then
    echo "ERROR: TLS_ENABLED=true pero clave privada no encontrada: $TLS_KEY" >&2
    exit 1
  fi
  echo "[nginx] Modo HTTPS — cert: $TLS_CERT"
else
  echo "[nginx] Modo HTTP"
fi

# ── Write nginx config ────────────────────────────────────────────────────────
{
  # HTTP→HTTPS redirect (solo cuando TLS activo)
  if [ "$TLS_ENABLED" = "true" ]; then
    printf 'server {\n'
    printf '  listen 80;\n'
    printf '  server_name _;\n'
    printf '  return 301 https://$host$request_uri;\n'
    printf '}\n\n'
  fi

  # Main server block
  printf 'server {\n'
  if [ "$TLS_ENABLED" = "true" ]; then
    printf '  listen 443 ssl http2;\n'
    printf '  ssl_certificate %s;\n'       "$TLS_CERT"
    printf '  ssl_certificate_key %s;\n'   "$TLS_KEY"
    printf '  ssl_protocols TLSv1.2 TLSv1.3;\n'
    printf '  ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;\n'
    printf '  ssl_prefer_server_ciphers off;\n'
    printf '  ssl_session_cache shared:SSL:10m;\n'
    printf '  ssl_session_timeout 1d;\n'
    printf '  ssl_session_tickets off;\n'
    printf '  add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;\n'
  else
    printf '  listen 80;\n'
  fi

  printf '  server_tokens off;\n'
  printf '  root /usr/share/nginx/html;\n'
  printf '  index index.html;\n\n'

  # Gzip
  printf '  gzip on;\n'
  printf '  gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;\n'
  printf '  gzip_min_length 256;\n'
  printf '  gzip_vary on;\n\n'

  # Security headers
  printf '  add_header X-Content-Type-Options "nosniff" always;\n'
  printf '  add_header X-Frame-Options "DENY" always;\n'
  printf '  add_header X-XSS-Protection "1; mode=block" always;\n'
  printf '  add_header Referrer-Policy "no-referrer" always;\n'
  printf '  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;\n'
  # CSP: unsafe-inline removido de script-src; Angular prod build usa archivos externos
  printf "  add_header Content-Security-Policy \"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self';\" always;\n\n"

  # Static assets cache
  printf '  location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {\n'
  printf '    expires 1y;\n'
  printf '    add_header Cache-Control "public, immutable";\n'
  printf '  }\n\n'

  # SPA fallback
  printf '  location / {\n'
  printf '    try_files $uri $uri/ /index.html;\n'
  printf '  }\n\n'

  # Backend proxy — API
  printf '  location /api/ {\n'
  printf '    proxy_pass http://backend:5000/api/;\n'
  printf '    proxy_http_version 1.1;\n'
  printf '    proxy_set_header Host $host;\n'
  printf '    proxy_set_header X-Real-IP $remote_addr;\n'
  printf '    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
  printf '    proxy_set_header X-Forwarded-Proto $scheme;\n'
  printf '    proxy_read_timeout 310s;\n'
  printf '    proxy_connect_timeout 10s;\n'
  printf '    proxy_send_timeout 310s;\n'
  printf '  }\n\n'

  # Backend health endpoints — accesibles desde el host para health-check.sh
  printf '  location ~ ^/(health|ready)$ {\n'
  printf '    proxy_pass http://backend:5000/$1;\n'
  printf '    proxy_http_version 1.1;\n'
  printf '    proxy_set_header Host $host;\n'
  printf '    proxy_read_timeout 10s;\n'
  printf '    proxy_connect_timeout 5s;\n'
  printf '    access_log off;\n'
  printf '  }\n\n'

  # Health endpoint
  printf '  location /nginx-health {\n'
  printf '    access_log off;\n'
  printf '    return 200 "ok";\n'
  printf '    add_header Content-Type text/plain;\n'
  printf '  }\n'
  printf '}\n'
} > "$CONF"

echo "[nginx] Config generada en $CONF"

exec nginx -g 'daemon off;'
