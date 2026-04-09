#!/usr/bin/env bash
# ─── backup-postgres.sh ─────────────────────────────────────────────────────
# Backup diario de PostgreSQL para Sistema I.L.C.D.IA.
#
# Configurar como cron (como root o usuario con acceso a docker):
#   0 2 * * * /opt/ilcdia/scripts/backup-postgres.sh >> /var/log/ilcdia-backup.log 2>&1
#
# Variables de entorno (o editar defaults abajo):
#   BACKUP_DIR      Directorio donde se guardan los backups (default: /opt/ilcdia/backups)
#   RETAIN_DAYS     Días de retención (default: 7)
#   COMPOSE_FILE    Ruta al docker-compose.production.yml
#   DB_USER         Usuario PostgreSQL (default: el del .env)
#   DB_NAME         Nombre de la BD (default: ilcdia)
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/docker-compose.production.yml}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-ilcdia}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/ilcdia_${TIMESTAMP}.sql.gz"

# ── Crear directorio de backups si no existe ─────────────────────────────────
mkdir -p "${BACKUP_DIR}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup → ${BACKUP_FILE}"

# ── Dump + compresión ────────────────────────────────────────────────────────
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U "${DB_USER}" "${DB_NAME}" \
  | gzip > "${BACKUP_FILE}"

BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup completado: ${BACKUP_SIZE}"

# ── Verificar que el archivo no está vacío ───────────────────────────────────
if [ ! -s "${BACKUP_FILE}" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: El archivo de backup está vacío"
    exit 1
fi

# ── Purgar backups antiguos ───────────────────────────────────────────────────
DELETED=$(find "${BACKUP_DIR}" -name "ilcdia_*.sql.gz" -mtime +"${RETAIN_DAYS}" -print -delete | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backups eliminados (>${RETAIN_DAYS}d): ${DELETED}"

TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Total en disco: ${TOTAL_SIZE}"
