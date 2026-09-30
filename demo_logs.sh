#!/usr/bin/env bash
# Script de demonstração — Atividade 5: Logs e Auditoria
# Executa o fluxo completo e mostra todos os eventos no log de auditoria

set -euo pipefail

BASE="http://localhost:8080"
ADMIN_EMAIL="${AUTH_ADMIN_EMAIL:-}"
ADMIN_PASS="${AUTH_ADMIN_PASSWORD:-}"

# Carrega variáveis do .env se existirem
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
  ADMIN_EMAIL="${AUTH_ADMIN_EMAIL:-}"
  ADMIN_PASS="${AUTH_ADMIN_PASSWORD:-}"
fi

if [ -z "$ADMIN_EMAIL" ] || [ -z "$ADMIN_PASS" ]; then
  echo "❌  Defina AUTH_ADMIN_EMAIL e AUTH_ADMIN_PASSWORD no .env"
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Demonstração — Atividade 5: Logs e Auditoria           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Aguarda o app estar disponível ──────────────────────────────
echo "⏳  Aguardando o app em $BASE/api/health ..."
for i in $(seq 1 30); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/health" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "✅  App disponível!"
    break
  fi
  sleep 2
done

# ── 1. Registrar usuário comum ───────────────────────────────────
echo ""
echo "─── 1. Registrar usuário comum ─────────────────────────────"
TIMESTAMP=$(date +%s)
USER_EMAIL="demo_${TIMESTAMP}@teste.com"
USER_PASS="senha123"

REG=$(curl -s -c /tmp/demo_user_cookies.txt \
  -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"nome\":\"Demo User\",\"email\":\"$USER_EMAIL\",\"senha\":\"$USER_PASS\"}")
echo "Registro: $REG" | python3 -m json.tool 2>/dev/null || echo "$REG"
USER_ID=$(echo "$REG" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('user',{}).get('id','?'))" 2>/dev/null || echo "?")

# ── 2. Login como usuário comum ──────────────────────────────────
echo ""
echo "─── 2. Login como usuário comum ────────────────────────────"
LOGIN=$(curl -s -c /tmp/demo_user_cookies.txt -b /tmp/demo_user_cookies.txt \
  -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$USER_EMAIL\",\"senha\":\"$USER_PASS\"}")
echo "$LOGIN" | python3 -m json.tool 2>/dev/null || echo "$LOGIN"

# ── 3. Favoritar um filme ────────────────────────────────────────
echo ""
echo "─── 3. Favoritar filme (Forrest Gump — TMDB ID 13) ────────"
FAV=$(curl -s -b /tmp/demo_user_cookies.txt \
  -X POST "$BASE/api/favorites" \
  -H "Content-Type: application/json" \
  -d '{"tmdb_movie_id": 13}')
echo "$FAV" | python3 -m json.tool 2>/dev/null || echo "$FAV"

# ── 4. Criar um comentário ───────────────────────────────────────
echo ""
echo "─── 4. Criar comentário no Forrest Gump ───────────────────"
COMMENT=$(curl -s -b /tmp/demo_user_cookies.txt \
  -X POST "$BASE/api/comments" \
  -H "Content-Type: application/json" \
  -d '{"tmdb_movie_id": 13, "texto": "Vida é como uma caixa de chocolates!"}')
echo "$COMMENT" | python3 -m json.tool 2>/dev/null || echo "$COMMENT"
COMMENT_ID=$(echo "$COMMENT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('comment',{}).get('id','?'))" 2>/dev/null || echo "?")

# ── 5. Usuário tenta acessar /api/admin/logs (403 esperado) ─────
echo ""
echo "─── 5. Usuário comum tenta acessar /api/admin/logs (403) ──"
LOGS_403=$(curl -s -b /tmp/demo_user_cookies.txt \
  -X GET "$BASE/api/admin/logs?n=10")
echo "$LOGS_403" | python3 -m json.tool 2>/dev/null || echo "$LOGS_403"

# ── 6. Login como admin ──────────────────────────────────────────
echo ""
echo "─── 6. Login como admin ────────────────────────────────────"
ADMIN_LOGIN=$(curl -s -c /tmp/demo_admin_cookies.txt -b /tmp/demo_admin_cookies.txt \
  -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"senha\":\"$ADMIN_PASS\"}")
echo "$ADMIN_LOGIN" | python3 -m json.tool 2>/dev/null || echo "$ADMIN_LOGIN"

# ── 7. Admin apaga o comentário do usuário (moderação) ──────────
echo ""
echo "─── 7. Admin apaga comentário do usuário (moderação) ───────"
if [ "$COMMENT_ID" != "?" ]; then
  MOD=$(curl -s -b /tmp/demo_admin_cookies.txt \
    -X DELETE "$BASE/api/comments/$COMMENT_ID")
  echo "$MOD" | python3 -m json.tool 2>/dev/null || echo "$MOD"
else
  echo "  (pulando — comment_id não obtido)"
fi

# ── 8. Admin consulta o log de auditoria ────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "   8. Log de auditoria — últimos 20 eventos (como admin)   "
echo "═══════════════════════════════════════════════════════════"
AUDIT=$(curl -s -b /tmp/demo_admin_cookies.txt \
  -X GET "$BASE/api/admin/logs?n=20")
echo "$AUDIT" | python3 -m json.tool 2>/dev/null || echo "$AUDIT"

# ── 9. Logout do admin ──────────────────────────────────────────
echo ""
echo "─── 9. Logout do admin ──────────────────────────────────────"
LOGOUT=$(curl -s -b /tmp/demo_admin_cookies.txt \
  -X POST "$BASE/api/auth/logout")
echo "$LOGOUT" | python3 -m json.tool 2>/dev/null || echo "$LOGOUT"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅  Demonstração concluída!                              ║"
echo "║  Todos os eventos aparecem no log de auditoria, na       ║"
echo "║  ordem cronológica, com usuario_id, ação e timestamp.    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
