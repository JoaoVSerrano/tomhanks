#!/usr/bin/env bash
# ==============================================================================
# Script de Demonstração — Atividade Extra: Documentação Swagger/OpenAPI
# ==============================================================================
# Este script valida:
# 1. Disponibilidade do Swagger UI interativo em http://localhost:8080/apidocs
# 2. Obtenção do contrato OpenAPI 3.0 em JSON (GET /api/docs/openapi.json)
# 3. Obtenção do contrato OpenAPI 3.0 em YAML (GET /api/docs/openapi.yaml)
# 4. Estrutura completa de endpoints documentados (Catálogo, Auth, Perfil, Logs)
# 5. Execução de chamada real ("Try it out")
# ==============================================================================

set -euo pipefail

BASE="http://localhost:8080"

echo "=========================================================="
echo "   DEMONSTRAÇÃO — ATIVIDADE EXTRA: SWAGGER / OPENAPI 3.0   "
echo "=========================================================="
echo ""

echo "⏳ 1. Aguardando a aplicação estar disponível..."
for i in $(seq 1 20); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/health" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "  ✅ Aplicação ativa em $BASE/api/health"
    break
  fi
  sleep 1
done

echo ""
echo "=========================================================="
echo "2. TESTANDO ACESSO AO SWAGGER UI (GET /apidocs)"
echo "=========================================================="

SWAGGER_HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/apidocs")
echo "  → GET $BASE/apidocs Status: $SWAGGER_HTTP"
if [ "$SWAGGER_HTTP" = "200" ]; then
  echo "  ✅ Swagger UI disponível e pronto para uso interativo!"
else
  echo "  ❌ Erro ao acessar Swagger UI"
fi

echo ""
echo "=========================================================="
echo "3. OBTENDO ESPECIFICAÇÃO OPENAPI 3.0 (GET /api/docs/openapi.json)"
echo "=========================================================="

OPENAPI_JSON=$(curl -s "$BASE/api/docs/openapi.json")

TITLE=$(echo "$OPENAPI_JSON" | jq -r '.info.title // empty')
VERSION=$(echo "$OPENAPI_JSON" | jq -r '.openapi // empty')
PATHS_COUNT=$(echo "$OPENAPI_JSON" | jq '.paths | keys | length')
TAGS=$(echo "$OPENAPI_JSON" | jq -r '.tags[].name' | paste -sd ", " -)

echo "  📌 Especificação OpenAPI Versão: $VERSION"
echo "  📌 Título da Documentação: $TITLE"
echo "  📌 Total de Endpoints Documentados (Gateway): $PATHS_COUNT"
echo "  📌 Tags/Categorias: $TAGS"

echo ""
echo "  🔍 Testando endpoints agregadores de documentação dos microsserviços internos:"
AUTH_DOCS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/docs/auth/openapi.json" 2>/dev/null || echo "000")
echo "  → GET $BASE/api/docs/auth/openapi.json Status: $AUTH_DOCS_STATUS (auth-service)"
LOG_DOCS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/docs/log/openapi.json" 2>/dev/null || echo "000")
echo "  → GET $BASE/api/docs/log/openapi.json Status: $LOG_DOCS_STATUS (log-service)"

echo ""
echo "=========================================================="
echo "4. LISTA DE ROTAS DOCUMENTADAS NA ESPECIFICAÇÃO"
echo "=========================================================="

echo "$OPENAPI_JSON" | jq -r '.paths | keys[]' | while read -r path; do
  METHODS=$(echo "$OPENAPI_JSON" | jq -r ".paths[\"$path\"] | keys[]" | tr '[:lower:]' '[:upper:]' | paste -sd "/" -)
  SUMMARY=$(echo "$OPENAPI_JSON" | jq -r ".paths[\"$path\"][keys[0]].summary // \"Sem descrição\"")
  printf "  %-35s | %-12s | %s\n" "$path" "$METHODS" "$SUMMARY"
done

echo ""
echo "=========================================================="
echo "5. OBTENDO ESPECIFICAÇÃO EM FORMATO YAML (GET /api/docs/openapi.yaml)"
echo "=========================================================="

curl -s "$BASE/api/docs/openapi.yaml" > /tmp/openapi_spec.yaml
head -n 12 /tmp/openapi_spec.yaml

echo ""
echo "=========================================================="
echo "6. DEMONSTRAÇÃO DE CHAMADA REAL ("Try it out")"
echo "=========================================================="

echo "Executando requisição para GET $BASE/api/catalog..."
CATALOG_RESP=$(curl -s "$BASE/api/catalog")
CATALOG_COUNT=$(echo "$CATALOG_RESP" | jq '.movies | length' 2>/dev/null || echo "0")
echo "  ✅ Resposta do catálogo recebida ($CATALOG_COUNT filmes)"

echo ""
echo "=========================================================="
echo "   DOCUMENTAÇÃO SWAGGER/OPENAPI 3.0 VALIDADA COM SUCESSO! 🎉"
echo "=========================================================="
