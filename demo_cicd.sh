#!/usr/bin/env bash
# ==============================================================================
# Script de Demonstração — Atividade Extra: CI/CD com GitHub Actions & GHCR
# ==============================================================================
# Este script valida:
# 1. Existência e estrutura do arquivo de workflow .github/workflows/ci-cd.yml
# 2. Execução da suíte de testes automatizados (pytest) no estágio de CI
# 3. Verificação de imagens e tags de commit (sha-xxx e latest)
# ==============================================================================

set -euo pipefail

WORKFLOW_FILE=".github/workflows/ci-cd.yml"

echo "=========================================================="
echo "   DEMONSTRAÇÃO — ATIVIDADE EXTRA: CI/CD GITHUB ACTIONS   "
echo "=========================================================="
echo ""

echo "1. VERIFICANDO ARQUIVO DE WORKFLOW GITHUB ACTIONS..."
if [ -f "$WORKFLOW_FILE" ]; then
  echo "  ✅ Workflow encontrado em $WORKFLOW_FILE"
else
  echo "  ❌ Workflow não encontrado em $WORKFLOW_FILE"
  exit 1
fi

echo ""
echo "=========================================================="
echo "2. ETAPAS DEFINIDAS NO PIPELINE (.github/workflows/ci-cd.yml)"
echo "=========================================================="
grep -E "name:|runs-on:|uses:|pytest|ghcr.io" "$WORKFLOW_FILE" | head -n 30

echo ""
echo "=========================================================="
echo "3. EXECUTANDO ESTÁGIO DE CI (TESTES AUTOMATIZADOS LOCALMENTE)"
echo "=========================================================="

if [ -f "./venv/bin/pytest" ]; then
  ./venv/bin/pytest tests/ -v
else
  python3 -m pytest tests/ -v
fi

echo ""
echo "=========================================================="
echo "4. VERIFICANDO COMMIT SHA ATUAL PARA TAG DA IMAGEM"
echo "=========================================================="

COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "dev")
echo "  📌 Commit SHA atual: $COMMIT_SHA"
echo "  📌 Tag da imagem no GHCR: ghcr.io/joaovserrano/tomhanks-app:sha-$COMMIT_SHA"
echo "  📌 Tag latest no GHCR:    ghcr.io/joaovserrano/tomhanks-app:latest"

echo ""
echo "=========================================================="
echo "   PIPELINE CI/CD CONFIGURADO E VALIDADO COM SUCESSO! 🎉  "
echo "=========================================================="
