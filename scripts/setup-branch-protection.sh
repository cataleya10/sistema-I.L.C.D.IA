#!/usr/bin/env bash
# ─── setup-branch-protection.sh ──────────────────────────────────────────────
# Configura protección de rama main en GitLab via API.
#
# Uso:
#   export GITLAB_TOKEN="tu-personal-access-token"
#   export GITLAB_PROJECT_ID="tu-project-id"
#   bash scripts/setup-branch-protection.sh
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

GITLAB_TOKEN="${1:-${GITLAB_TOKEN:-}}"
GITLAB_PROJECT_ID="${2:-${GITLAB_PROJECT_ID:-}}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.com}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[ -n "${GITLAB_TOKEN}" ]      || error "GITLAB_TOKEN no definido"
[ -n "${GITLAB_PROJECT_ID}" ] || error "GITLAB_PROJECT_ID no definido"
command -v curl >/dev/null 2>&1 || error "curl no está instalado"

API="${GITLAB_URL}/api/v4/projects/${GITLAB_PROJECT_ID}"

# ── Eliminar protección existente si hay ─────────────────────────────────────
info "Removiendo configuración previa de rama main..."
curl -s -o /dev/null \
    --request DELETE \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    "${API}/protected_branches/main" || true

# ── Proteger rama main ────────────────────────────────────────────────────────
# push_access_level:  0=No one, 30=Developers, 40=Maintainers
# merge_access_level: 30=Developers+Maintainers, 40=Maintainers only
# unprotect_access_level: 40=Maintainers only
info "Configurando protección en rama main..."
response=$(curl -s -w "\n%{http_code}" \
    --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --header "Content-Type: application/json" \
    --data '{
        "name": "main",
        "push_access_level": 0,
        "merge_access_level": 40,
        "unprotect_access_level": 40,
        "allow_force_push": false,
        "code_owner_approval_required": false
    }' \
    "${API}/protected_branches")

http_code=$(echo "${response}" | tail -1)
body=$(echo "${response}" | head -n -1)

if [ "${http_code}" = "201" ]; then
    info "Rama main protegida correctamente"
    echo "  - Push directo: BLOQUEADO (solo via MR)"
    echo "  - Merge: solo Maintainers"
    echo "  - Force push: BLOQUEADO"
else
    warn "HTTP ${http_code} al proteger rama. Respuesta: ${body}"
fi

# ── Configurar aprobaciones de merge request ──────────────────────────────────
info "Configurando aprobaciones requeridas en MRs..."
curl -s -o /dev/null \
    --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
    --header "Content-Type: application/json" \
    --data '{
        "approvals_before_merge": 1,
        "reset_approvals_on_push": true,
        "disable_overriding_approvers_per_merge_request": false
    }' \
    "${API}/approvals" && info "Aprobaciones configuradas: 1 requerida" || warn "No se pudo configurar aprobaciones (requiere GitLab Premium)"

echo ""
info "Branch protection completada. Verificar en:"
echo "  ${GITLAB_URL}/<grupo>/<proyecto>/-/settings/repository"
