#!/usr/bin/env bash
# ─── health-check.sh ─────────────────────────────────────────────────────────
# Verifica que todos los servicios del sistema estén operativos después de un
# despliegue. Sale con código 0 si todo está bien, código 1 si algo falla.
#
# Uso:
#   ./scripts/health-check.sh
#   ./scripts/health-check.sh --base-url https://mi-dominio.com
#
# Variables de entorno opcionales:
#   BASE_URL        URL base del sistema (default: http://localhost)
#   AI_BASE_URL     URL del AI engine (default: http://localhost:8000)
#   API_KEY         Clave de API para endpoints protegidos
#   MAX_RETRIES     Intentos por servicio (default: 6)
#   RETRY_SLEEP     Segundos entre intentos (default: 10)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost}"
AI_BASE_URL="${AI_BASE_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-}"
MAX_RETRIES="${MAX_RETRIES:-6}"
RETRY_SLEEP="${RETRY_SLEEP:-10}"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --ai-url)   AI_BASE_URL="$2"; shift 2 ;;
    *) echo "Argumento desconocido: $1"; exit 1 ;;
  esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS=0; FAIL=0

log_ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
log_fail() { echo -e "${RED}[FAIL]${NC}  $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_info() { echo -e "        $*"; }

# ─── wait_for <url> <description> [extra curl args] ──────────────────────────
wait_for() {
  local url="$1" desc="$2"; shift 2
  local attempt=1
  while [[ $attempt -le $MAX_RETRIES ]]; do
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$@" "$url" 2>/dev/null || echo "000")
    if [[ "$http_code" =~ ^[23] ]]; then
      log_ok "$desc  →  HTTP $http_code"
      (( PASS++ ))
      return 0
    fi
    log_info "Intento $attempt/$MAX_RETRIES — HTTP $http_code (esperando ${RETRY_SLEEP}s)"
    sleep "$RETRY_SLEEP"
    (( attempt++ ))
  done
  log_fail "$desc  →  no responde tras $MAX_RETRIES intentos"
  (( FAIL++ ))
  return 1
}

# ─── check_json <url> <jq_filter> <expected> <description> ──────────────────
check_json() {
  local url="$1" filter="$2" expected="$3" desc="$4"; shift 4
  local body
  body=$(curl -s --max-time 10 "$@" "$url" 2>/dev/null || echo "{}")
  local actual
  actual=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print($filter)" 2>/dev/null || echo "__error__")
  if [[ "$actual" == "$expected" ]]; then
    log_ok "$desc  →  $actual"
    (( PASS++ ))
  else
    log_fail "$desc  →  esperado='$expected'  obtenido='$actual'"
    log_info "Body: $(echo "$body" | head -c 200)"
    (( FAIL++ ))
  fi
}

echo "════════════════════════════════════════════════════════"
echo "  Sistema I.L.C.D.IA — Health Check Post-Deploy"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "════════════════════════════════════════════════════════"
echo ""

# ── 1. Frontend nginx ─────────────────────────────────────────────────────────
echo "── Frontend ──────────────────────────────────────────"
wait_for "${BASE_URL}/" "Frontend SPA carga" || true
wait_for "${BASE_URL}/nginx-health" "nginx health probe" || true

# ── 2. Backend .NET ───────────────────────────────────────────────────────────
echo ""
echo "── Backend .NET ──────────────────────────────────────"
# /ready incluye db connectivity
wait_for "${BASE_URL}/ready" "Backend /ready" || true
wait_for "${BASE_URL}/health" "Backend /health" || true

# ── 3. AI Engine ─────────────────────────────────────────────────────────────
echo ""
echo "── AI Engine ─────────────────────────────────────────"
wait_for "${AI_BASE_URL}/health" "AI Engine /health" || true

if [[ -n "$API_KEY" ]]; then
  check_json "${AI_BASE_URL}/health" \
    "d.get('status','unknown')" "ok" \
    "AI Engine status=ok" \
    -H "X-Api-Key: ${API_KEY}" || true
else
  log_warn "API_KEY no definida — saltando verificación de estado AI Engine"
fi

# ── 4. Docker container states ───────────────────────────────────────────────
echo ""
echo "── Docker containers ─────────────────────────────────"
if command -v docker &>/dev/null; then
  for svc in postgres ai-engine backend frontend; do
    # Busca cualquier contenedor cuyo nombre contenga el servicio
    state=$(docker ps --filter "name=${svc}" --format "{{.Status}}" 2>/dev/null | head -1)
    if [[ -z "$state" ]]; then
      log_fail "Contenedor '$svc'  →  no encontrado / no corriendo"
      (( FAIL++ ))
    elif echo "$state" | grep -qi "unhealthy"; then
      log_fail "Contenedor '$svc'  →  $state"
      (( FAIL++ ))
    else
      log_ok "Contenedor '$svc'  →  $state"
      (( PASS++ ))
    fi
  done
else
  log_warn "docker CLI no disponible — saltando verificación de contenedores"
fi

# ── 5. Resumen ────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo -e "  Resultado:  ${GREEN}${PASS} OK${NC}  /  ${RED}${FAIL} FAIL${NC}"
echo "════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
  echo -e "${RED}Deploy verificado con errores — revisar logs arriba.${NC}"
  exit 1
fi
echo -e "${GREEN}Sistema operativo. Deploy exitoso.${NC}"
exit 0
