#!/usr/bin/env bash
# ─── setup-server.sh ────────────────────────────────────────────────────────
# Configura el servidor de producción desde cero.
# Ejecutar como root en el servidor:
#
#   scp -r scripts/ root@TU_SERVIDOR:/tmp/ilcdia-setup/
#   scp docker-compose.production.yml .env.deploy.example root@TU_SERVIDOR:/tmp/ilcdia-setup/
#   ssh root@TU_SERVIDOR "bash /tmp/ilcdia-setup/scripts/setup-server.sh"
#
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_DIR="/opt/ilcdia"
BACKUP_DIR="/opt/ilcdia/backups"
LOG_DIR="/var/log/ilcdia"
SYSTEMD_DIR="/etc/systemd/system"
SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_SRC="$(dirname "${SCRIPT_SRC}")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 1. Verificaciones previas ─────────────────────────────────────────────────
info "Verificando requisitos..."
[[ "$(id -u)" -eq 0 ]] || error "Este script debe ejecutarse como root"
command -v docker  >/dev/null 2>&1 || error "docker no está instalado. Instálalo con: curl -fsSL https://get.docker.com | bash"
docker compose version >/dev/null 2>&1 || error "docker compose (v2) no está disponible"

# ── 2. Firewall (ufw) ─────────────────────────────────────────────────────────
info "Configurando firewall (ufw)..."
if command -v ufw &>/dev/null; then
    # Reglas: solo SSH, HTTP y HTTPS accesibles desde el exterior.
    # PostgreSQL (5432) y AI Engine (8000) son internos — NUNCA exponer al exterior.
    ufw --force reset          # reset seguro: no hace nada si ya está configurado igual
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp  comment "SSH"
    ufw allow 80/tcp  comment "HTTP (redirect a HTTPS)"
    ufw allow 443/tcp comment "HTTPS"
    # Habilitar sin prompt interactivo
    ufw --force enable
    info "Firewall habilitado:"
    ufw status verbose
else
    warn "ufw no encontrado. Instalando..."
    if command -v apt-get &>/dev/null; then
        apt-get install -y -qq ufw
        ufw --force reset
        ufw default deny incoming
        ufw default allow outgoing
        ufw allow 22/tcp  comment "SSH"
        ufw allow 80/tcp  comment "HTTP"
        ufw allow 443/tcp comment "HTTPS"
        ufw --force enable
        info "Firewall instalado y habilitado."
    else
        warn "No se pudo instalar ufw. Configura el firewall manualmente (permite 22, 80, 443 — bloquea 5432, 8000)."
    fi
fi

# ── 3. Crear estructura de directorios ────────────────────────────────────────
info "Creando directorios en ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"/{scripts,backups,storage,logs}
mkdir -p "${LOG_DIR}"
chmod 750 "${INSTALL_DIR}"
chmod 700 "${INSTALL_DIR}/backups"

# ── 4. Copiar archivos del proyecto ───────────────────────────────────────────
info "Copiando archivos..."
cp "${PROJECT_SRC}/docker-compose.production.yml"        "${INSTALL_DIR}/"
cp "${PROJECT_SRC}/docker-compose.production.tls.yml"    "${INSTALL_DIR}/"
cp "${PROJECT_SRC}/scripts/backup-postgres.sh"           "${INSTALL_DIR}/scripts/"
cp "${PROJECT_SRC}/scripts/restore-postgres.sh"          "${INSTALL_DIR}/scripts/"
cp "${PROJECT_SRC}/scripts/setup-certbot.sh"             "${INSTALL_DIR}/scripts/"
chmod +x "${INSTALL_DIR}/scripts/"*.sh

# ── 5. Crear .env si no existe ────────────────────────────────────────────────
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    cp "${PROJECT_SRC}/.env.deploy.example" "${INSTALL_DIR}/.env"
    warn ".env creado desde plantilla. DEBES editar ${INSTALL_DIR}/.env con tus valores reales antes de continuar."
    warn "Edítalo con:  nano ${INSTALL_DIR}/.env"
fi
# Siempre asegurar permisos restrictivos — el .env contiene secrets
chmod 600 "${INSTALL_DIR}/.env"
info ".env protegido con chmod 600 (solo root puede leerlo)"

# Copiar también el health-check script
cp "${PROJECT_SRC}/scripts/health-check.sh" "${INSTALL_DIR}/scripts/"
chmod +x "${INSTALL_DIR}/scripts/health-check.sh"

# ── 6. Systemd timer para backup diario ──────────────────────────────────────
info "Configurando backup diario via systemd timer..."

cat > "${SYSTEMD_DIR}/ilcdia-backup.service" <<'SERVICE'
[Unit]
Description=Sistema ILCDIA - Backup PostgreSQL
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/ilcdia
EnvironmentFile=/opt/ilcdia/.env
ExecStart=/opt/ilcdia/scripts/backup-postgres.sh
StandardOutput=append:/var/log/ilcdia/backup.log
StandardError=append:/var/log/ilcdia/backup.log
SERVICE

cat > "${SYSTEMD_DIR}/ilcdia-backup.timer" <<'TIMER'
[Unit]
Description=Sistema ILCDIA - Timer backup diario 02:00 AM
Requires=ilcdia-backup.service

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
TIMER

systemctl daemon-reload
systemctl enable  ilcdia-backup.timer
systemctl start   ilcdia-backup.timer
info "Timer de backup configurado: $(systemctl is-active ilcdia-backup.timer)"

# ── 7. Logrotate para logs de la app ──────────────────────────────────────────
info "Configurando logrotate..."
cat > /etc/logrotate.d/ilcdia <<'LOGROTATE'
/var/log/ilcdia/*.log /opt/ilcdia/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root root
}
LOGROTATE

# ── 7. Resumen ────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────────────────────────────"
info "Setup completado. Próximos pasos:"
echo ""
echo "  1. Editar variables de entorno:"
echo "     nano ${INSTALL_DIR}/.env"
echo ""
echo "  2. Verificar que no quedan CHANGE_ME sin reemplazar:"
echo "     grep 'CHANGE_ME' ${INSTALL_DIR}/.env"
echo ""
echo "  3. Levantar los servicios:"
echo "     cd ${INSTALL_DIR}"
echo "     docker compose -f docker-compose.production.yml pull"
echo "     docker compose -f docker-compose.production.yml up -d"
echo ""
echo "  4. (Opcional) Activar HTTPS con Let's Encrypt:"
echo "     bash ${INSTALL_DIR}/scripts/setup-certbot.sh --domain TU_DOMINIO --email TU_EMAIL"
echo ""
echo "  5. Health check post-arranque:"
echo "     bash ${INSTALL_DIR}/scripts/health-check.sh"
echo ""
echo "  6. Verificar timers activos:"
echo "     systemctl list-timers 'ilcdia-*'"
echo ""
echo "  7. (Si necesitas restaurar un backup):"
echo "     bash ${INSTALL_DIR}/scripts/restore-postgres.sh --latest"
echo "────────────────────────────────────────────────────────────────"
