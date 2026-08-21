#!/bin/sh
set -e

if [ -f venv/bin/activate ]; then
    . venv/bin/activate
fi

if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        if [ -z "$line" ] || [ "${line#\#}" != "$line" ]; then
            continue
        fi

        key=${line%%=*}
        value=${line#*=}
        export "$key=$value"
    done < .env
fi

if [ -x "$(dirname "$0")/venv/bin/python" ]; then
    PYTHON_BIN="$(dirname "$0")/venv/bin/python"
else
    PYTHON_BIN="$(command -v python3 || command -v python || echo python)"
fi

ensure_requirements() {
    missing=""

    check_pkg() {
        if ! "$PYTHON_BIN" -m pip show "$1" >/dev/null 2>&1; then
            missing="$missing $2"
        fi
    }

    check_pkg Flask Flask
    check_pkg SQLAlchemy SQLAlchemy
    check_pkg alembic alembic
    check_pkg gunicorn gunicorn
    check_pkg mysql-connector-python mysql-connector-python
    check_pkg requests requests

    if [ -z "$missing" ]; then
        return 0
    fi

    echo "Dependencias ausentes:$missing. Instalando com \"$PYTHON_BIN -m pip install -r requirements.txt\"..." >&2
    "$PYTHON_BIN" -m pip install -r requirements.txt
}

ensure_requirements

# Garante a criação do schema no banco de dados antes de iniciar o servidor Web
"$PYTHON_BIN" -c "from backend.app import app, ensure_schema; app.app_context().push(); ensure_schema()" 2>/dev/null || echo "Aviso: Nao foi possivel rodar ensure_schema antecipadamente, o app tentara na primeira requisicao."

# Executa o Gunicorn (seja como binario standalone no PATH ou como modulo python)
if command -v gunicorn >/dev/null 2>&1; then
    exec gunicorn -b 0.0.0.0:${PORT:-8080} backend.app:app
else
    exec "$PYTHON_BIN" -m gunicorn -b 0.0.0.0:${PORT:-8080} backend.app:app
fi
