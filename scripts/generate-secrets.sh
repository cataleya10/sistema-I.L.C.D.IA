#!/usr/bin/env bash
# ─── generate-secrets.sh ─────────────────────────────────────────────────────
# Genera todos los secretos necesarios para producción y los escribe en .env
#
# Uso:
#   bash scripts/generate-secrets.sh
#
# Crea (o actualiza) el archivo .env con secretos aleatorios seguros.
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
ENV_FILE="${PROJECT_DIR}/.env"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }

gen() { python3 -c "import secrets; print(secrets.token_hex($1))"; }

bcrypt_hash() {
    local password="$1"
    python3 -c "
import sys
try:
    import bcrypt
    h = bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(12)).decode()
    print(h)
except ImportError:
    print('BCRYPT_NOT_AVAILABLE')
" "$password"
}

# ── Generar secretos ──────────────────────────────────────────────────────────
info "Generando secretos seguros..."
JWT_KEY=$(gen 32)
API_KEY=$(gen 32)
DB_PASS=$(gen 24)

# Generar contraseñas aleatorias para los usuarios y hashearlas con bcrypt
ADMIN_PASS=$(gen 16)
USER_PASS=$(gen 16)

# Intentar hashear con bcrypt (requiere: pip install bcrypt)
info "Generando hashes bcrypt para usuarios (instalando bcrypt si falta)..."
python3 -m pip install bcrypt --quiet 2>/dev/null || true

ADMIN_HASH=$(bcrypt_hash "${ADMIN_PASS}")
USER_HASH=$(bcrypt_hash "${USER_PASS}")

info "Secretos generados:"
echo "  Jwt__SigningKey   = ${JWT_KEY}"
echo "  API_KEY           = ${API_KEY}"
echo "  DB_PASSWORD       = ${DB_PASS}"
if [ "${ADMIN_HASH}" != "BCRYPT_NOT_AVAILABLE" ]; then
    echo "  ADMIN (admin)     password = ${ADMIN_PASS}  →  hash generado"
    echo "  USER  (analyst)   password = ${USER_PASS}   →  hash generado"
else
    echo "  ADMIN password    = ${ADMIN_PASS}  (hash requiere instalación manual de bcrypt)"
    echo "  USER  password    = ${USER_PASS}   (hash requiere instalación manual de bcrypt)"
fi

# ── Escribir en .env ──────────────────────────────────────────────────────────
if [ ! -f "${ENV_FILE}" ]; then
    cp "${PROJECT_DIR}/.env.deploy.example" "${ENV_FILE}"
    info ".env creado desde plantilla"
fi

# Reemplazar los CHANGE_ME de secretos
sed -i "s|CHANGE_ME_RANDOM_32_PLUS_CHARS_JWT_SIGNING_KEY|${JWT_KEY}|g" "${ENV_FILE}"
sed -i "s|CHANGE_ME_SHARED_API_KEY_RANDOM_32_CHARS|${API_KEY}|g"       "${ENV_FILE}"
sed -i "s|CHANGE_ME_DB_PASSWORD_RANDOM_32_CHARS|${DB_PASS}|g"          "${ENV_FILE}"

if [ "${ADMIN_HASH}" != "BCRYPT_NOT_AVAILABLE" ]; then
    # El hash bcrypt contiene $ que sed interpreta — usar python para el replace
    python3 - "${ENV_FILE}" "${ADMIN_HASH}" "${USER_HASH}" <<'PY'
import sys
env_file, admin_hash, user_hash = sys.argv[1], sys.argv[2], sys.argv[3]
with open(env_file) as f:
    content = f.read()
content = content.replace("CHANGE_ME_BCRYPT_HASH_FOR_ADMIN",  admin_hash)
content = content.replace("CHANGE_ME_BCRYPT_HASH_FOR_ANALYST", user_hash)
with open(env_file, "w") as f:
    f.write(content)
PY
    info "Hashes bcrypt escritos en .env"
fi

info ".env actualizado con secretos generados."
echo ""
warn "Aún debes editar manualmente en ${ENV_FILE}:"
echo "  - GITHUB_REPOSITORY  (tu org/repo)"
echo "  - DB_USER"
echo "  - FRONTEND_ORIGIN    (URL real del frontend)"
echo "  - ANTHROPIC_API_KEY  (si usas LLM fallback)"
echo ""
if [ "${ADMIN_HASH}" != "BCRYPT_NOT_AVAILABLE" ]; then
    warn "GUARDA estas contraseñas en un gestor de contraseñas — no se vuelven a mostrar:"
    echo "  admin    → ${ADMIN_PASS}"
    echo "  analyst  → ${USER_PASS}"
fi
echo ""
warn "NUNCA commitees el archivo .env"

# ── Verificar que no quedan CHANGE_ME ────────────────────────────────────────
REMAINING=$(grep -c "CHANGE_ME" "${ENV_FILE}" 2>/dev/null || true)
if [ "${REMAINING}" -gt 0 ]; then
    warn "Quedan ${REMAINING} valor(es) CHANGE_ME en .env que requieren edición manual"
    grep "CHANGE_ME" "${ENV_FILE}" | sed 's/^/    /'
fi
