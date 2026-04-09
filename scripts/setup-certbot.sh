#!/usr/bin/env bash
# ─── setup-certbot.sh ────────────────────────────────────────────────────────
# Obtiene certificado TLS con Let's Encrypt (certbot) y configura renovación
# automática via systemd timer.
#
# Prerrequisitos:
#   - Puerto 80 accesible desde internet (para el challenge HTTP-01)
#   - El frontend ya está corriendo y nginx responde en :80
#   - El dominio apunta a este servidor
#
# Uso:
#   bash scripts/setup-certbot.sh --domain ejemplo.com --email admin@ejemplo.com
#   bash scripts/setup-certbot.sh --domain ejemplo.com --email admin@ejemplo.com --staging
#
# Opciones:
#   --domain   Dominio del sistema (requerido)
#   --email    Email para notificaciones de Let's Encrypt (requerido)
#   --staging  Usa el entorno de pruebas de Let's Encrypt (no expide cert real)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN=""
EMAIL=""
STAGING_FLAG=""
INSTALL_DIR="/opt/ilcdia"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain)  DOMAIN="$2"; shift 2 ;;
    --email)   EMAIL="$2"; shift 2 ;;
    --staging) STAGING_FLAG="--staging"; shift ;;
    *) error "Argumento desconocido: $1" ;;
  esac
done

[ -n "$DOMAIN" ] || error "Falta --domain"
[ -n "$EMAIL"  ] || error "Falta --email"
[[ "$(id -u)" -eq 0 ]] || error "Ejecutar como root"

info "Dominio: ${DOMAIN}"
info "Email:   ${EMAIL}"
[ -n "$STAGING_FLAG" ] && warn "Modo STAGING — no se emitirá certificado real"

# ── 1. Instalar certbot ───────────────────────────────────────────────────────
info "Instalando certbot..."
if command -v apt-get &>/dev/null; then
  apt-get update -qq && apt-get install -y -qq certbot
elif command -v yum &>/dev/null; then
  yum install -y certbot
elif command -v dnf &>/dev/null; then
  dnf install -y certbot
else
  error "Gestor de paquetes no soportado. Instala certbot manualmente: https://certbot.eff.org"
fi
info "certbot $(certbot --version 2>&1) instalado."

# ── 2. Obtener certificado (webroot vía nginx del frontend) ───────────────────
WEBROOT="/usr/share/nginx/html"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"

# Crea directorio webroot en el contenedor si no existe
info "Preparando webroot en contenedor frontend..."
docker exec "$(docker ps -qf name=frontend | head -1)" \
  mkdir -p "${WEBROOT}/.well-known/acme-challenge" 2>/dev/null || \
  warn "No se pudo crear el directorio en el contenedor — verifica que el frontend esté corriendo"

info "Solicitando certificado..."
# shellcheck disable=SC2086
certbot certonly \
  --webroot \
  --webroot-path "${WEBROOT}" \
  --domain "${DOMAIN}" \
  --email "${EMAIL}" \
  --agree-tos \
  --non-interactive \
  --keep-until-expiring \
  ${STAGING_FLAG}

info "Certificado obtenido en ${CERT_DIR}"

# ── 3. Actualizar .env con las rutas del certificado ─────────────────────────
ENV_FILE="${INSTALL_DIR}/.env"
if [ -f "${ENV_FILE}" ]; then
  info "Actualizando ${ENV_FILE} con rutas TLS..."
  # Quitar líneas TLS existentes y agregar las correctas
  grep -v "^TLS_CERT_PATH=\|^TLS_KEY_PATH=\|^TLS_ENABLED=\|^HTTPS_PORT=\|^FRONTEND_ORIGIN=" "${ENV_FILE}" > "${ENV_FILE}.tmp"
  {
    echo "TLS_ENABLED=true"
    echo "TLS_CERT_PATH=${CERT_DIR}/fullchain.pem"
    echo "TLS_KEY_PATH=${CERT_DIR}/privkey.pem"
    echo "HTTPS_PORT=443"
    echo "FRONTEND_ORIGIN=https://${DOMAIN}"
  } >> "${ENV_FILE}.tmp"
  mv "${ENV_FILE}.tmp" "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
  info ".env actualizado con TLS habilitado."
else
  warn ".env no encontrado en ${ENV_FILE} — actualiza manualmente:"
  echo "  TLS_ENABLED=true"
  echo "  TLS_CERT_PATH=${CERT_DIR}/fullchain.pem"
  echo "  TLS_KEY_PATH=${CERT_DIR}/privkey.pem"
  echo "  HTTPS_PORT=443"
  echo "  FRONTEND_ORIGIN=https://${DOMAIN}"
fi

# ── 4. Reiniciar frontend con TLS activo ─────────────────────────────────────
if [ -f "${ENV_FILE}" ]; then
  info "Reiniciando frontend con TLS activo..."
  cd "${INSTALL_DIR}"
  docker compose \
    -f docker-compose.production.yml \
    -f docker-compose.production.tls.yml \
    up -d --no-deps frontend
  info "Frontend reiniciado con HTTPS."
fi

# ── 5. Systemd timer para renovación automática ───────────────────────────────
info "Configurando renovación automática de certificado..."

cat > /etc/systemd/system/ilcdia-certbot.service <<SERVICE
[Unit]
Description=Sistema ILCDIA - Renovación certificado TLS (Let's Encrypt)
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=${INSTALL_DIR}
# Renueva si faltan menos de 30 días para expirar
ExecStart=/usr/bin/certbot renew --quiet --deploy-hook "${INSTALL_DIR}/scripts/certbot-deploy-hook.sh"
StandardOutput=append:/var/log/ilcdia/certbot.log
StandardError=append:/var/log/ilcdia/certbot.log
SERVICE

cat > /etc/systemd/system/ilcdia-certbot.timer <<TIMER
[Unit]
Description=Sistema ILCDIA - Timer renovación TLS (2x/semana)
Requires=ilcdia-certbot.service

[Timer]
# Let's Encrypt recomienda renovar 2 veces por semana para detectar fallos pronto
OnCalendar=Mon,Thu 03:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
TIMER

# Deploy hook: recarga nginx del contenedor tras renovar
cat > "${INSTALL_DIR}/scripts/certbot-deploy-hook.sh" <<'HOOK'
#!/bin/sh
# Ejecutado por certbot tras renovar exitosamente el certificado.
# Recarga nginx del contenedor frontend para que use el nuevo cert sin downtime.
set -e
INSTALL_DIR="/opt/ilcdia"
cd "${INSTALL_DIR}"
docker compose -f docker-compose.production.yml -f docker-compose.production.tls.yml \
  exec -T frontend nginx -s reload
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Certificado renovado y nginx recargado."
HOOK
chmod +x "${INSTALL_DIR}/scripts/certbot-deploy-hook.sh"

systemctl daemon-reload
systemctl enable ilcdia-certbot.timer
systemctl start  ilcdia-certbot.timer
info "Timer de renovación TLS configurado: $(systemctl is-active ilcdia-certbot.timer)"

# ── 6. Resumen ────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────────"
info "Certificado TLS configurado para: https://${DOMAIN}"
echo ""
echo "  Cert:  ${CERT_DIR}/fullchain.pem"
echo "  Clave: ${CERT_DIR}/privkey.pem"
echo "  Expira: $(openssl x509 -enddate -noout -in "${CERT_DIR}/fullchain.pem" 2>/dev/null | cut -d= -f2)"
echo ""
echo "  Renovación automática: $(systemctl is-active ilcdia-certbot.timer)"
echo "  Ver próxima renovación: systemctl list-timers ilcdia-certbot.timer"
echo ""
echo "  Para verificar el certificado:"
echo "    curl -I https://${DOMAIN}/nginx-health"
echo "────────────────────────────────────────────────────────────────"
