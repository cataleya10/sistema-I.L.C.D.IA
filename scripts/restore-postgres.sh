#!/usr/bin/env bash
# ─── restore-postgres.sh ─────────────────────────────────────────────────────
# Restaura un backup de PostgreSQL y verifica la integridad post-restore.
#
# Uso:
#   bash scripts/restore-postgres.sh backups/ilcdia_20260401_020001.sql.gz
#   bash scripts/restore-postgres.sh --verify-only backups/ilcdia_20260401_020001.sql.gz
#   bash scripts/restore-postgres.sh --latest
#
# Opciones:
#   --latest          Usa el backup más reciente en BACKUP_DIR
#   --verify-only     Solo verifica la integridad del archivo (sin restaurar)
#   --dry-run         Muestra lo que haría, sin ejecutar
#
# Variables de entorno (o cargadas desde .env):
#   BACKUP_DIR        Directorio de backups (default: /opt/ilcdia/backups)
#   COMPOSE_FILE      (default: docker-compose.production.yml)
#   DB_USER           Usuario PostgreSQL
#   DB_NAME           Nombre de la BD (default: ilcdia)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

# Cargar .env si existe
if [ -f "${PROJECT_DIR}/.env" ]; then
  # shellcheck source=/dev/null
  set -a; source "${PROJECT_DIR}/.env"; set +a
fi

BACKUP_DIR="${BACKUP_DIR:-${PROJECT_DIR}/backups}"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_DIR}/docker-compose.production.yml}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-ilcdia}"
VERIFY_ONLY=false
DRY_RUN=false
BACKUP_FILE=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "[$(date '+%H:%M:%S')] ${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "[$(date '+%H:%M:%S')] ${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "[$(date '+%H:%M:%S')] ${RED}[ERROR]${NC} $*"; exit 1; }

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --verify-only) VERIFY_ONLY=true; shift ;;
    --dry-run)     DRY_RUN=true; shift ;;
    --latest)
      BACKUP_FILE=$(ls -t "${BACKUP_DIR}"/ilcdia_*.sql.gz 2>/dev/null | head -1)
      [ -n "$BACKUP_FILE" ] || error "No se encontraron backups en ${BACKUP_DIR}"
      shift ;;
    -*)  error "Opción desconocida: $1" ;;
    *)   BACKUP_FILE="$1"; shift ;;
  esac
done

[ -n "$BACKUP_FILE" ] || error "Debes indicar un archivo de backup o usar --latest"
[ -f "$BACKUP_FILE" ] || error "Archivo no encontrado: ${BACKUP_FILE}"

info "Archivo de backup: ${BACKUP_FILE}"
info "Tamaño: $(du -sh "${BACKUP_FILE}" | cut -f1)"

# ── 1. Verificar integridad del gzip ─────────────────────────────────────────
info "Verificando integridad del archivo comprimido..."
if ! gzip -t "${BACKUP_FILE}" 2>/dev/null; then
  error "El archivo gzip está corrupto: ${BACKUP_FILE}"
fi
info "Integridad gzip: OK"

# ── 2. Verificar que contiene SQL válido ──────────────────────────────────────
info "Verificando contenido SQL..."
FIRST_LINE=$(zcat "${BACKUP_FILE}" | head -1)
if ! echo "$FIRST_LINE" | grep -qi "postgresql\|pg_dump"; then
  error "El archivo no parece ser un dump de PostgreSQL válido. Primera línea: ${FIRST_LINE}"
fi
TABLE_COUNT=$(zcat "${BACKUP_FILE}" | grep -c "^CREATE TABLE" || true)
info "Tablas encontradas en dump: ${TABLE_COUNT}"
[ "$TABLE_COUNT" -gt 0 ] || warn "No se encontraron sentencias CREATE TABLE — ¿dump vacío?"

if [ "$VERIFY_ONLY" = "true" ]; then
  info "Verificación completada (--verify-only). Sin cambios en la BD."
  exit 0
fi

# ── 3. Confirmación interactiva (saltar en CI con DRY_RUN) ───────────────────
if [ "$DRY_RUN" = "false" ] && [ -t 0 ]; then
  echo ""
  warn "ADVERTENCIA: Esto ELIMINARÁ y recreará la base de datos '${DB_NAME}'."
  warn "Todos los datos actuales se perderán."
  echo -n "¿Continuar? Escribe 'RESTAURAR' para confirmar: "
  read -r CONFIRM
  [ "$CONFIRM" = "RESTAURAR" ] || { info "Operación cancelada."; exit 0; }
fi

if [ "$DRY_RUN" = "true" ]; then
  info "[DRY-RUN] Se ejecutaría:"
  info "  dropdb + createdb ${DB_NAME} en el contenedor postgres"
  info "  pg_restore desde ${BACKUP_FILE}"
  info "[DRY-RUN] Sin cambios realizados."
  exit 0
fi

# ── 4. Drop + recrear BD ─────────────────────────────────────────────────────
info "Desconectando sesiones activas de ${DB_NAME}..."
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  psql -U "${DB_USER}" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" \
  > /dev/null

info "Eliminando BD existente..."
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  dropdb -U "${DB_USER}" --if-exists "${DB_NAME}"

info "Recreando BD vacía..."
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  createdb -U "${DB_USER}" "${DB_NAME}"

# ── 5. Restaurar ─────────────────────────────────────────────────────────────
info "Restaurando desde backup..."
zcat "${BACKUP_FILE}" | docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  psql -U "${DB_USER}" -d "${DB_NAME}" -q

info "Restore completado."

# ── 6. Verificar post-restore ─────────────────────────────────────────────────
info "Verificando integridad post-restore..."
RESTORED_TABLES=$(docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')

info "Tablas restauradas en BD: ${RESTORED_TABLES}"

if [ "${RESTORED_TABLES}" -lt "${TABLE_COUNT}" ]; then
  warn "Número de tablas post-restore (${RESTORED_TABLES}) menor que en el dump (${TABLE_COUNT})"
else
  info "Verificación post-restore: OK"
fi

# Verificar que la tabla principal de documentos existe
HAS_DOCS=$(docker compose -f "${COMPOSE_FILE}" exec -T postgres \
  psql -U "${DB_USER}" -d "${DB_NAME}" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name ILIKE '%document%';" | tr -d '[:space:]')
info "Tablas de documentos encontradas: ${HAS_DOCS}"

echo ""
info "Restore y verificación completados exitosamente."
info "Archivo restaurado: ${BACKUP_FILE}"
