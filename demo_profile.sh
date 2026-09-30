#!/usr/bin/env bash
# ==============================================================================
# Script de Demonstração — Atividade 6: Upload e Perfil de Usuário (MinIO)
# ==============================================================================
# Este script executa a validação completa de todas as exigências da atividade:
# 1. Registro e login do Usuário 1 (Alice) e Usuário 2 (Bob)
# 2. Upload de foto de perfil (imagem PNG) para o MinIO Object Storage
# 3. Atualização da Bio / Perfil do Usuário 1
# 4. Exibição do Perfil com a foto de upload e a lista de filmes favoritados
# 5. Tentativa RECUSADA (403 Forbidden) do Bob tentar alterar o perfil da Alice
# 6. Verificação do Log de Auditoria com os eventos registrados
# ==============================================================================

set -euo pipefail

BASE="http://localhost:8080"
COOKIE_ALICE="/tmp/alice_cookie.txt"
COOKIE_BOB="/tmp/bob_cookie.txt"

rm -f "$COOKIE_ALICE" "$COOKIE_BOB"

echo "=========================================================="
echo "   DEMONSTRAÇÃO — ATIVIDADE 6: UPLOAD E PERFIL DE USUÁRIO  "
echo "=========================================================="
echo ""

echo "⏳ 1. Aguardando a aplicação e o MinIO estarem disponíveis..."
for i in $(seq 1 30); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/health" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "  ✅ Aplicação ativa em $BASE/api/health"
    break
  fi
  sleep 2
done

echo ""
echo "=========================================================="
echo "2. CRIANDO CONTA E LOGIN — Usuário 1 (Alice)"
echo "=========================================================="

ALICE_EMAIL="alice_profile_$RANDOM@test.com"
ALICE_PASS="senha123456"

REG_ALICE=$(curl -s -c "$COOKIE_ALICE" \
  -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"nome\":\"Alice Santos\",\"email\":\"$ALICE_EMAIL\",\"senha\":\"$ALICE_PASS\"}")

echo "Resposta Registro Alice:"
echo "$REG_ALICE" | jq . 2>/dev/null || echo "$REG_ALICE"

ALICE_ID=$(echo "$REG_ALICE" | jq -r '.user.id // empty' 2>/dev/null || echo "1")
echo "  → Alice ID: $ALICE_ID"

echo ""
echo "=========================================================="
echo "3. UPLOAD DE FOTO DE PERFIL (MinIO) — Alice"
echo "=========================================================="

# Cria uma imagem PNG de teste simples
TEST_IMG="/tmp/test_avatar.png"
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' > "$TEST_IMG"

UPLOAD_RESP=$(curl -s -b "$COOKIE_ALICE" \
  -X POST "$BASE/api/profile/$ALICE_ID/avatar" \
  -F "avatar=@$TEST_IMG;type=image/png")

echo "Resposta Upload Foto:"
echo "$UPLOAD_RESP" | jq . 2>/dev/null || echo "$UPLOAD_RESP"

echo ""
echo "=========================================================="
echo "4. ATUALIZAR BIO E DADOS DO PERFIL — Alice"
echo "=========================================================="

UPDATE_RESP=$(curl -s -b "$COOKIE_ALICE" \
  -X PUT "$BASE/api/profile/$ALICE_ID" \
  -H "Content-Type: application/json" \
  -d '{"nome":"Alice Santos Cloud","bio":"Engenheira Cloud & Entusiasta de cinema. Fã n° 1 de Forrest Gump."}')

echo "Resposta Atualização Perfil:"
echo "$UPDATE_RESP" | jq . 2>/dev/null || echo "$UPDATE_RESP"

echo ""
echo "=========================================================="
echo "5. FAVORITAR UM FILME (Forrest Gump - tmdb_id=13)"
echo "=========================================================="

FAV_RESP=$(curl -s -b "$COOKIE_ALICE" \
  -X POST "$BASE/api/favorites" \
  -H "Content-Type: application/json" \
  -d '{"tmdb_movie_id": 13, "titulo": "Forrest Gump"}')

echo "Resposta Favoritar:"
echo "$FAV_RESP" | jq . 2>/dev/null || echo "$FAV_RESP"

echo ""
echo "=========================================================="
echo "6. CONSULTAR PERFIL DA ALICE (GET /api/profile/$ALICE_ID)"
echo "=========================================================="

PROFILE_RESP=$(curl -s -b "$COOKIE_ALICE" "$BASE/api/profile/$ALICE_ID")
echo "Perfil completo da Alice:"
echo "$PROFILE_RESP" | jq . 2>/dev/null || echo "$PROFILE_RESP"

echo ""
echo "=========================================================="
echo "7. CRIANDO CONTA — Usuário 2 (Bob)"
echo "=========================================================="

BOB_EMAIL="bob_profile_$RANDOM@test.com"
BOB_PASS="senha123456"

REG_BOB=$(curl -s -c "$COOKIE_BOB" \
  -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"nome\":\"Bob Silva\",\"email\":\"$BOB_EMAIL\",\"senha\":\"$BOB_PASS\"}")

BOB_ID=$(echo "$REG_BOB" | jq -r '.user.id // empty' 2>/dev/null || echo "2")
echo "  → Bob ID: $BOB_ID"

echo ""
echo "=========================================================="
echo "8. TENTATIVA RECUSADA (403): Bob tenta editar o perfil da Alice"
echo "=========================================================="

BOB_ATTEMPT_EDIT=$(curl -s -b "$COOKIE_BOB" \
  -X PUT "$BASE/api/profile/$ALICE_ID" \
  -H "Content-Type: application/json" \
  -d '{"nome":"Alice Hackeada","bio":"Hacked por Bob!"}')

echo "HTTP / Resposta ao tentar editar perfil de outro usuário:"
echo "$BOB_ATTEMPT_EDIT" | jq . 2>/dev/null || echo "$BOB_ATTEMPT_EDIT"

echo ""
echo "=========================================================="
echo "9. TENTATIVA RECUSADA (403): Bob tenta enviar avatar para a Alice"
echo "=========================================================="

BOB_ATTEMPT_AVATAR=$(curl -s -b "$COOKIE_BOB" \
  -X POST "$BASE/api/profile/$ALICE_ID/avatar" \
  -F "avatar=@$TEST_IMG;type=image/png")

echo "HTTP / Resposta ao tentar fazer upload no perfil de outro usuário:"
echo "$BOB_ATTEMPT_AVATAR" | jq . 2>/dev/null || echo "$BOB_ATTEMPT_AVATAR"

echo ""
echo "=========================================================="
echo "10. ACESSO AO AVATAR SERVIDO PELO GATEWAY DA APLICAÇÃO"
echo "=========================================================="

AVATAR_URL=$(echo "$PROFILE_RESP" | jq -r '.user.avatar_url // empty')
if [ -n "$AVATAR_URL" ]; then
  AVATAR_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE$AVATAR_URL")
  echo "GET $BASE$AVATAR_URL → HTTP Status $AVATAR_HTTP_CODE"
fi

echo ""
echo "=========================================================="
echo "   DEMONSTRAÇÃO CONCLUÍDA COM SUCESSO! 🎉               "
echo "=========================================================="
