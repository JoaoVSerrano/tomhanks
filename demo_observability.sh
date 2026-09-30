#!/usr/bin/env bash
# ==============================================================================
# Script de Demonstração — Atividade Extra: Observabilidade (Health & Métricas)
# ==============================================================================
# Este script valida:
# 1. Endpoints /health de cada serviço testando dependências reais (200 OK)
# 2. Endpoints /metrics em formato Prometheus
# 3. Teste de falha real: derruba o Redis e comprova:
#    a) log-service responde HTTP 503 Service Unavailable
#    b) docker compose ps marca log-service como UNHEALTHY automaticamente
# 4. Teste de recuperação: relança o Redis e mostra log-service voltando a HEALTHY
# ==============================================================================

set -euo pipefail

BASE="http://localhost:8080"

cleanup() {
  docker compose start redis >/dev/null 2>&1 || true
}

trap cleanup EXIT

wait_for_http() {
  local url="$1"
  local attempts=30
  while (( attempts > 0 )); do
    if curl --silent --fail "$url" >/dev/null; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 1
  done
  echo "Serviço não ficou pronto: $url" >&2
  return 1
}

wait_for_log_status() {
  local expected="$1"
  local attempts=30
  local marker="($expected)"
  while (( attempts > 0 )); do
    if docker compose ps -a --format '{{.Service}} {{.Status}}' \
      | awk -v marker="$marker" '$1 == "log-service" && index($0, marker) { found = 1 } END { exit found ? 0 : 1 }'; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 1
  done
  return 1
}

echo "=========================================================="
echo "   DEMONSTRAÇÃO — ATIVIDADE EXTRA: OBSERVABILIDADE      "
echo "=========================================================="
echo ""

echo "Aguardando serviços estarem prontos..."
wait_for_http "$BASE/api/health"

echo ""
echo "=========================================================="
echo "2. TESTANDO READINESS E HEALTHCHECKS (HTTP 200 OK)"
echo "=========================================================="

echo "a) Health App Gateway (GET $BASE/api/health):"
HEALTH_APP=$(curl -s "$BASE/api/health")
echo "$HEALTH_APP" | jq . 2>/dev/null || echo "$HEALTH_APP"

echo ""
echo "b) Health Log-Service (via Docker exec log-service):"
HEALTH_LOG=$(docker compose exec -T log-service python3 -c 'import urllib.request; print(urllib.request.urlopen("http://localhost:4000/health").read().decode())')
echo "$HEALTH_LOG" | jq . 2>/dev/null || echo "$HEALTH_LOG"

echo ""
echo "c) Health Auth-Service (via Docker exec auth-service):"
HEALTH_AUTH=$(docker compose exec -T auth-service python3 -c 'import urllib.request; print(urllib.request.urlopen("http://localhost:3000/health").read().decode())')
echo "$HEALTH_AUTH" | jq . 2>/dev/null || echo "$HEALTH_AUTH"

echo ""
echo "=========================================================="
echo "3. METRICAS EM FORMATO PROMETHEUS (GET /metrics)"
echo "=========================================================="

echo "Primeiras linhas do endpoint /metrics em $BASE/metrics:"
METRICS=$(curl --silent --fail "$BASE/metrics")
printf '%s\n' "$METRICS" | grep -E '^flask_http_request_(total|duration_seconds)' | head -n 15

echo ""
echo "=========================================================="
echo "4. PROVA DE FALHA REAL: DERRUBANDO CONTAINER REDIS"
echo "=========================================================="

echo "Parando o container redis (docker compose stop redis)..."
docker compose stop redis >/dev/null 2>&1

echo ""
echo "Consultando GET /health do log-service com o Redis fora:"
LOG_503_CODE=$(docker compose exec -T log-service python3 -c '
import urllib.request, urllib.error
try:
    urllib.request.urlopen("http://localhost:4000/health")
except urllib.error.HTTPError as e:
    print(f"HTTP Status: {e.code}")
    print(e.read().decode())
' )
echo "$LOG_503_CODE"
grep -q "HTTP Status: 503" <<< "$LOG_503_CODE"

echo ""
echo "Aguardando ciclo do Docker HEALTHCHECK..."
wait_for_log_status "unhealthy"

echo ""
echo "Status do docker compose ps (observe o log-service virando UNHEALTHY):"
docker compose ps -a --format "table {{.Name}}\t{{.Service}}\t{{.Status}}" | grep -E "redis|log-service|NAME"

echo ""
echo "=========================================================="
echo "5. RECUPERAÇÃO AUTOMÁTICA: REINICIANDO O REDIS"
echo "=========================================================="

echo "Iniciando o container redis (docker compose start redis)..."
docker compose start redis >/dev/null 2>&1

echo ""
echo "Aguardando reconexão e ciclo do HEALTHCHECK..."
wait_for_log_status "healthy"

echo ""
echo "Status do docker compose ps após recuperar o Redis (voltando a HEALTHY):"
docker compose ps -a --format "table {{.Name}}\t{{.Service}}\t{{.Status}}" | grep -E "redis|log-service|NAME"

echo ""
echo "=========================================================="
echo "   OBSERVABILIDADE E READINESS VALIDADOS COM SUCESSO! "
echo "=========================================================="
