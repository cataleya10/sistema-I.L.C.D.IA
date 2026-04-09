#!/usr/bin/env bash
# ─── setup-gitlab-vars.sh ────────────────────────────────────────────────────
# Configura automáticamente las variables de CI/CD en GitLab usando la API.
#
# Uso:
#   export GITLAB_TOKEN="tu-personal-access-token"   (scope: api)
#   export GITLAB_PROJECT_ID="tu-project-id"         (número en GitLab → Settings → General)
#   bash scripts/setup-gitlab-vars.sh
#
# O pasar como argumentos:
#   bash scripts/setup-gitlab-vars.sh <TOKEN> <PROJECT_ID>
#
# Obtener Personal Access Token:
#   GitLab → tu avatar → Preferences → Access Tokens → scopes: api
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

GITLAB_TOKEN="${1:-${GITLAB_TOKEN:-}}"
GITLAB_PROJECT_ID="${2:-${GITLAB_PROJECT_ID:-}}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.com}"
ENV_FILE="${ENV_FILE:-$(dirname "$(dirname "${BASH_SOURCE[0]}")")/.env}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Validaciones ──────────────────────────────────────────────────────────────
[ -n "${GITLAB_TOKEN}" ]      || error "GITLAB_TOKEN no definido. Expórtalo o pásalo como primer argumento."
[ -n "${GITLAB_PROJECT_ID}" ] || error "GITLAB_PROJECT_ID no definido. Expórtalo o pásalo como segundo argumento."
[ -f "${ENV_FILE}" ]          || error "Archivo .env no encontrado en: ${ENV_FILE}"
command -v curl >/dev/null 2>&1 || error "curl no está instalado"

API_BASE="${GITLAB_URL}/api/v4/projects/${GITLAB_PROJECT_ID}/variables"

# ── Función para crear/actualizar variable ────────────────────────────────────
set_var() {
    local key="$1"
    local value="$2"
    local masked="${3:-false}"
    local protected="${4:-true}"

    # Intentar PUT (actualizar) primero, si falla intentar POST (crear)
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        --request PUT \
        --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
        --form "value=${value}" \
        --form "masked=${masked}" \
        --form "protected=${protected}" \
        "${API_BASE}/${key}" 2>&1)

    if [ "${http_code}" = "200" ]; then
        info "Actualizada: ${key}"
    else
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
            --request POST \
            --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
            --form "key=${key}" \
            --form "value=${value}" \
            --form "masked=${masked}" \
            --form "protected=${protected}" \
            "${API_BASE}" 2>&1)
        if [ "${http_code}" = "201" ]; then
            info "Creada: ${key}"
        else
            warn "Error (HTTP ${http_code}) al configurar: ${key}"
        fi
    fi
}

# ── Leer .env y subir variables ───────────────────────────────────────────────
info "Leyendo variables desde ${ENV_FILE}..."
info "Subiendo a GitLab proyecto ID: ${GITLAB_PROJECT_ID}..."
echo ""

# Variables que se marcan como masked (secretos reales)
MASKED_KEYS=("DB_PASSWORD" "Jwt__SigningKey" "API_KEY" "ANTHROPIC_API_KEY" "DEPLOY_SSH_KEY")

while IFS= read -r line || [ -n "${line}" ]; do
    # Saltar comentarios y líneas vacías
    [[ "${line}" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    # Parsear KEY=VALUE
    if [[ "${line}" =~ ^([^=]+)=(.*)$ ]]; then
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        # Saltar CHANGE_ME
        if [[ "${value}" == *"CHANGE_ME"* ]]; then
            warn "Saltando (CHANGE_ME sin reemplazar): ${key}"
            continue
        fi
        # Determinar si debe ser masked
        masked="false"
        for mk in "${MASKED_KEYS[@]}"; do
            if [ "${key}" = "${mk}" ]; then
                masked="true"
                break
            fi
        done
        set_var "${key}" "${value}" "${masked}" "true"
    fi
done < "${ENV_FILE}"

echo ""
info "Variables configuradas. Verificar en:"
echo "  ${GITLAB_URL}/<tu-grupo>/<tu-proyecto>/-/settings/ci_cd"
echo ""
warn "Variables NO subidas (requieren acción manual):"
echo "  DEPLOY_SSH_KEY   → Clave privada SSH para deploy"
echo "  (crear con: ssh-keygen -t ed25519 -f ~/.ssh/ilcdia_deploy -N '')"
echo "  (luego agregar ~/.ssh/ilcdia_deploy.pub al servidor en ~/.ssh/authorized_keys)"
