from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from prometheus_flask_exporter import PrometheusMetrics
from sqlalchemy import delete, select

from backend.database import session_scope, upgrade_database
from backend.models import Comment, Favorite


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w500'
_LAST_KNOWN_CATALOG: list[dict[str, Any]] = []

app = Flask(__name__)
_flask_secret = os.getenv('FLASK_SECRET_KEY')
if not _flask_secret:
    import sys
    print(
        '[backend] ERRO: variável FLASK_SECRET_KEY não definida. '
        'Defina-a na seção *Environment* da stack no Portainer.',
        file=sys.stderr,
    )
    sys.exit(1)
app.secret_key = _flask_secret
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1',
)
metrics = PrometheusMetrics(app)


# ---------------------------------------------------------------------------
# Auth-service proxy helpers
# ---------------------------------------------------------------------------


def auth_service_url() -> str:
    return os.getenv('AUTH_SERVICE_URL', 'http://auth-service:3000')


def log_service_url() -> str:
    return os.getenv('LOG_SERVICE_URL', 'http://log-service:4000')


def minio_is_ready() -> bool:
    """Confere conectividade com o object storage usado pelos avatares."""
    try:
        from minio import Minio

        raw_endpoint = os.getenv('MINIO_ENDPOINT', 'minio:9000')
        endpoint = raw_endpoint.split('://')[-1] if '://' in raw_endpoint else raw_endpoint
        access_key = os.getenv('MINIO_ACCESS_KEY', '')
        secret_key = os.getenv('MINIO_SECRET_KEY', '')
        if not access_key or not secret_key:
            app.logger.warning('MINIO_ACCESS_KEY ou MINIO_SECRET_KEY não definidos — MinIO desabilitado.')
            return False
        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=False,
        )
        client.list_buckets()
        return True
    except Exception as exc:
        app.logger.warning('MinIO indisponível em healthcheck: %s', exc)
        return False


def internal_token() -> str:
    return os.getenv('INTERNAL_TOKEN', '')


def _forward_to_auth(method: str, path: str, **kwargs) -> requests.Response:
    """Encaminha uma requisição ao microsserviço de autenticação."""
    url = f'{auth_service_url()}{path}'
    # Repassa o cookie de sessão para que o auth-service reconheça o usuário
    cookies = request.cookies
    headers = kwargs.pop('headers', {})
    headers['X-Internal-Token'] = internal_token()
    return requests.request(method, url, cookies=cookies, headers=headers, timeout=30, **kwargs)


def _auth_response_payload(resp: requests.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        app.logger.error(
            'Auth-service retornou resposta não JSON em %s %s: status=%s body=%r',
            resp.request.method if resp.request else 'UNKNOWN',
            resp.url,
            resp.status_code,
            resp.text[:500],
        )
        payload = {'error': 'Serviço de autenticação retornou uma resposta inválida.'}

    if isinstance(payload, dict):
        return payload
    return {'data': payload}


def _set_cookie_headers(resp: requests.Response) -> list[str]:
    headers = resp.raw.headers
    if hasattr(headers, 'getlist'):
        return headers.getlist('Set-Cookie')
    if hasattr(headers, 'get_all'):
        return headers.get_all('Set-Cookie')
    header = resp.headers.get('Set-Cookie')
    return [header] if header else []


def _proxy_auth(method: str, path: str, **kwargs):
    """Faz proxy de uma requisição de auth e retorna a resposta Flask completa."""
    try:
        resp = _forward_to_auth(method, path, **kwargs)
    except requests.RequestException as exc:
        app.logger.error('Auth-service indisponível: %s', exc)
        return jsonify({'error': 'Serviço de autenticação indisponível.'}), 503

    response = jsonify(_auth_response_payload(resp))
    response.status_code = resp.status_code

    # Mantém todos os atributos do cookie assinado pelo auth-service.
    for header in _set_cookie_headers(resp):
        response.headers.add('Set-Cookie', header)

    return response


# ---------------------------------------------------------------------------
# Log de auditoria — envia evento ao log-service (fire-and-forget)
# ---------------------------------------------------------------------------

def log_event(
    acao: str,
    usuario_id: int | None = None,
    detalhe: str = '',
) -> None:
    """Envia um evento de auditoria ao log-service de forma assíncrona.

    Erros de conectividade são registrados no log do app mas nunca
    propagam para o usuário — auditoria nunca deve travar a ação.
    """
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        if ip:
            # X-Forwarded-For pode ter múltiplos IPs; pega o primeiro
            ip = ip.split(',')[0].strip()

        requests.post(
            f'{log_service_url()}/log',
            json={
                'usuario_id': usuario_id,
                'acao': acao,
                'detalhe': detalhe,
                'ip': ip,
            },
            headers={'X-Internal-Token': internal_token()},
            timeout=3,
        )
    except Exception as exc:
        app.logger.warning('log-service indisponível (evento=%s): %s', acao, exc)


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def _cors_origins() -> set[str]:
    raw = os.getenv('CORS_ORIGINS', 'http://localhost:4200').strip()
    return {item.strip() for item in raw.split(',') if item.strip()}


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin')
    if origin and origin in _cors_origins():
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,DELETE,OPTIONS'
        response.headers['Vary'] = 'Origin'
    if response.content_type.startswith('text/html'):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@app.route('/api/<path:_path>', methods=['OPTIONS'])
def api_preflight(_path: str):
    return ('', 204)


def json_error(message: str, status: int = 400):
    return jsonify({'error': message}), status


# ---------------------------------------------------------------------------
# TMDB helpers
# ---------------------------------------------------------------------------

def normalize_poster_path(poster_path: str | None) -> str | None:
    if not poster_path:
        return None
    return poster_path if poster_path.startswith('http') else f'{TMDB_IMAGE_BASE_URL}{poster_path}'


def tmdb_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.getenv('TMDB_API_KEY')
    if not api_key:
        raise RuntimeError('TMDB_API_KEY não configurada no servidor.')

    query = {'api_key': api_key, 'language': os.getenv('TMDB_LANGUAGE', 'pt-BR')}
    if params:
        query.update(params)

    response = requests.get(f'{TMDB_BASE_URL}{path}', params=query, timeout=20)
    response.raise_for_status()
    return response.json()


@lru_cache(maxsize=1)
def get_tom_hanks_person_id() -> int:
    payload = tmdb_request('/search/person', {'query': 'Tom Hanks'})
    results = payload.get('results', [])
    if not results:
        raise RuntimeError('Tom Hanks não foi encontrado na TMDB.')

    for person in results:
        if person.get('name', '').strip().lower() == 'tom hanks':
            return int(person['id'])
    return int(results[0]['id'])


@lru_cache(maxsize=128)
def get_movie_details(movie_id: int) -> dict[str, Any]:
    payload = tmdb_request(f'/movie/{movie_id}')
    return {
        'tmdb_movie_id': int(payload['id']),
        'title': payload.get('title') or payload.get('original_title') or 'Título indisponível',
        'overview': payload.get('overview') or 'Sinopse indisponível.',
        'poster_path': payload.get('poster_path'),
        'poster_url': normalize_poster_path(payload.get('poster_path')),
        'release_date': payload.get('release_date'),
    }


def _catalog_copy(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [movie.copy() for movie in catalog]


@lru_cache(maxsize=1)
def get_tom_hanks_catalog() -> list[dict[str, Any]]:
    person_id = get_tom_hanks_person_id()
    payload = tmdb_request(f'/person/{person_id}/movie_credits')
    credits = payload.get('cast', [])

    selected = [
        movie
        for movie in sorted(
            credits,
            key=lambda item: (
                item.get('release_date') or '0000-00-00',
                item.get('popularity') or 0,
            ),
            reverse=True,
        )
        if movie.get('id') and movie.get('media_type', 'movie') == 'movie'
    ][:24]

    catalog: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for movie in selected:
        movie_id = int(movie['id'])
        if movie_id in seen_ids:
            continue
        seen_ids.add(movie_id)
        try:
            details = get_movie_details(movie_id)
        except Exception:
            details = {
                'tmdb_movie_id': movie_id,
                'title': movie.get('title') or movie.get('original_title') or 'Título indisponível',
                'overview': movie.get('overview') or 'Sinopse indisponível.',
                'poster_path': movie.get('poster_path'),
                'poster_url': normalize_poster_path(movie.get('poster_path')),
                'release_date': movie.get('release_date'),
            }
        catalog.append(details)

    global _LAST_KNOWN_CATALOG
    _LAST_KNOWN_CATALOG = _catalog_copy(catalog)
    return catalog


# ---------------------------------------------------------------------------
# Sessão local (o user_id fica na cookie do catálogo após login no auth-service)
# ---------------------------------------------------------------------------

def require_login():
    """Verifica se o usuário está autenticado consultando o auth-service."""
    try:
        resp = _forward_to_auth('GET', '/me')
        if resp.status_code != 200:
            return None, json_error('Faça login para continuar.', 401)
        data = resp.json()
        user_id = int(data['user']['id'])
        return user_id, None
    except requests.RequestException as exc:
        app.logger.error('Auth-service indisponível em require_login: %s', exc)
        return None, json_error('Serviço de autenticação indisponível.', 503)


def require_role(expected_role: str):
    """Verifica autenticação e role do usuário consultando o auth-service.

    Retorna (user_data, None) em caso de sucesso, ou (None, resposta_erro)
    se não autenticado (401) ou sem o papel exigido (403).
    O enforcement real da permissão acontece aqui, no servidor — nunca no cliente.
    """
    try:
        resp = _forward_to_auth('GET', '/me')
        if resp.status_code != 200:
            return None, json_error('Faça login para continuar.', 401)
        data = resp.json()
        user = data.get('user', {})
        role = user.get('role', 'usuario')
        if role != expected_role:
            return None, json_error(
                'Acesso negado. Apenas administradores podem executar esta ação.', 403
            )
        return user, None
    except requests.RequestException as exc:
        app.logger.error('Auth-service indisponível em require_role: %s', exc)
        return None, json_error('Serviço de autenticação indisponível.', 503)


def serialize_movie(movie: dict[str, Any], favorite_ids: set[int], comments: list[dict[str, Any]]):
    movie_id = int(movie['tmdb_movie_id'])
    movie_comments = [item for item in comments if item['tmdb_movie_id'] == movie_id]
    return {
        'tmdb_movie_id': movie_id,
        'title': movie['title'],
        'overview': movie['overview'],
        'poster_path': movie.get('poster_path'),
        'poster_url': movie.get('poster_url'),
        'release_date': movie.get('release_date'),
        'is_favorite': movie_id in favorite_ids,
        'comments': movie_comments,
        'comment_count': len(movie_comments),
        'favorite': movie_id in favorite_ids,
    }


def ensure_schema() -> None:
    upgrade_database()


@app.before_request
def initialize_app():
    if request.method == 'OPTIONS':
        return None
    if not request.path.startswith('/api/'):
        return None
    if not getattr(app, '_schema_attempted', False):
        app._schema_attempted = True
        try:
            ensure_schema()
        except Exception:
            app.logger.exception('Não foi possível garantir o schema do banco na inicialização.')
    return None


# ---------------------------------------------------------------------------
# Health & Readiness
# ---------------------------------------------------------------------------

@app.get('/health')
@app.get('/api/health')
def health():
    db_ok = False
    auth_ok = False
    log_ok = False
    minio_ok = minio_is_ready()

    try:
        with session_scope() as db:
            db.execute(select(1))
        db_ok = True
    except Exception:
        db_ok = False

    try:
        resp = requests.get(f"{auth_service_url()}/health", timeout=2)
        auth_ok = resp.status_code == 200
    except Exception:
        auth_ok = False

    try:
        resp = requests.get(f"{log_service_url()}/health", timeout=2)
        log_ok = resp.status_code == 200
    except Exception:
        log_ok = False

    status_code = 200 if (db_ok and auth_ok and log_ok and minio_ok) else 503
    return jsonify({
        'status': 'healthy' if status_code == 200 else 'unhealthy',
        'service': 'app-gateway',
        'dependencies': {
            'database': 'connected' if db_ok else 'disconnected',
            'auth_service': 'reachable' if auth_ok else 'unreachable',
            'log_service': 'reachable' if log_ok else 'unreachable',
            'minio': 'connected' if minio_ok else 'disconnected',
        }
    }), status_code


# ---------------------------------------------------------------------------
# Auth — proxy para o microsserviço de autenticação
# ---------------------------------------------------------------------------

@app.get('/api/auth/me')
def me():
    response = _proxy_auth('GET', '/me')
    if response.status_code == 401:
        return jsonify({'user': None})
    return response


@app.post('/api/auth/register')
def register():
    return _proxy_auth('POST', '/register', json=request.get_json(silent=True) or {})


@app.post('/api/auth/login')
def login():
    payload = request.get_json(silent=True) or {}
    response = _proxy_auth('POST', '/login', json=payload)
    # Loga o evento apenas quando o login for bem-sucedido
    if response.status_code == 200:
        try:
            user_data = response.get_json()
            uid = user_data.get('user', {}).get('id') if user_data else None
            email = payload.get('email', '')
            log_event('login', usuario_id=uid, detalhe=f'email={email}')
        except Exception:
            log_event('login', detalhe=f"email={payload.get('email', '')}")
    elif response.status_code == 401:
        log_event('login_falhou', detalhe=f"email={payload.get('email', '')}")
    return response


@app.post('/api/auth/logout')
def logout():
    # Obtém o usuário atual antes de deslogar para registrar o ID
    uid = None
    try:
        me_resp = _forward_to_auth('GET', '/me')
        if me_resp.status_code == 200:
            uid = me_resp.json().get('user', {}).get('id')
    except Exception:
        pass
    response = _proxy_auth('POST', '/logout')
    log_event('logout', usuario_id=uid)
    return response


@app.post('/api/auth/forgot-password')
def forgot_password():
    return _proxy_auth('POST', '/forgot-password', json=request.get_json(silent=True) or {})


@app.post('/api/auth/reset-password')
def reset_password():
    return _proxy_auth('POST', '/reset-password', json=request.get_json(silent=True) or {})


@app.get('/api/auth/reset-password/check')
def check_reset_token():
    token = request.args.get('token', '')
    return _proxy_auth('GET', f'/reset-password/check?token={token}')


# ---------------------------------------------------------------------------
# Admin — proxy das rotas administrativas do auth-service
# ---------------------------------------------------------------------------

@app.get('/api/admin/users')
def admin_list_users():
    """Lista todos os usuários. Exclusivo de admin (enforced no auth-service)."""
    return _proxy_auth('GET', '/admin/users')


@app.post('/api/admin/users/<int:target_id>/role')
def admin_change_role(target_id: int):
    """Promove ou rebaixa o papel de um usuário. Exclusivo de admin (enforced no auth-service)."""
    return _proxy_auth('POST', f'/admin/users/{target_id}/role', json=request.get_json(silent=True) or {})


@app.get('/api/admin/logs')
def admin_list_logs():
    """Retorna os últimos N eventos de auditoria. Exclusivo de admin.

    Query params:
        n     : int (padrão 50, máx 500) — quantos eventos retornar
        start : str                       — ID de início do range (XRANGE notation)
        end   : str                       — ID de fim do range

    Usuário comum tentando acessar recebe 403.
    """
    admin_user, err = require_role('admin')
    if err:
        # Loga tentativa de acesso negado (403)
        uid = None
        try:
            resp = _forward_to_auth('GET', '/me')
            if resp.status_code == 200:
                uid = resp.json().get('user', {}).get('id')
        except Exception:
            pass
        log_event('403_acesso_logs', usuario_id=uid, detalhe='tentativa de acesso ao log de auditoria')
        return err

    n = request.args.get('n', '50')
    start = request.args.get('start', '-')
    end = request.args.get('end', '+')

    try:
        resp = requests.get(
            f'{log_service_url()}/logs',
            params={'n': n, 'start': start, 'end': end},
            headers={'X-Internal-Token': internal_token()},
            timeout=10,
        )
        resp.raise_for_status()
        return jsonify(resp.json())
    except requests.RequestException as exc:
        app.logger.error('log-service indisponível em admin_list_logs: %s', exc)
        return json_error('Serviço de log indisponível.', 503)


# ---------------------------------------------------------------------------
# Perfil de usuário & Upload de Avatar (Atividade 6)
# ---------------------------------------------------------------------------

@app.get('/api/profile/<int:user_id>')
def get_user_profile(user_id: int):
    """Retorna os dados do perfil do usuário e a lista de filmes favoritados por ele."""
    try:
        resp = _forward_to_auth('GET', f'/users/{user_id}')
        if resp.status_code != 200:
            return _proxy_auth('GET', f'/users/{user_id}')
        user_data = resp.json().get('user', {})
    except Exception as exc:
        app.logger.error('Erro ao buscar perfil no auth-service: %s', exc)
        return json_error('Serviço de autenticação indisponível.', 503)

    # Busca os favoritos do usuário no MariaDB local
    with session_scope() as db:
        fav_rows = db.scalars(
            select(Favorite).where(Favorite.usuario_id == user_id).order_by(Favorite.criado_em.desc())
        ).all()
        favorites = [
            {
                'id': int(f.id),
                'tmdb_movie_id': int(f.tmdb_movie_id),
                'title': f.titulo,
                'poster_path': f.poster_path,
                'poster_url': normalize_poster_path(f.poster_path),
                'criado_em': f.criado_em.isoformat() if hasattr(f.criado_em, 'isoformat') else f.criado_em,
            }
            for f in fav_rows
        ]

    return jsonify({
        'user': user_data,
        'favorites': favorites,
        'favorite_count': len(favorites),
    })


@app.put('/api/profile/<int:user_id>')
def update_user_profile(user_id: int):
    """Atualiza o perfil do usuário (nome e bio). Regra 403 tratada no auth-service."""
    return _proxy_auth('PUT', f'/users/{user_id}', json=request.get_json(silent=True) or {})


@app.post('/api/profile/<int:user_id>/avatar')
def upload_user_avatar(user_id: int):
    """Realiza upload de imagem de perfil do usuário. Regra 403 tratada no auth-service."""
    if 'avatar' not in request.files and 'file' not in request.files:
        return json_error('Nenhum arquivo enviado.', 400)

    file_obj = request.files.get('avatar') or request.files.get('file')
    if not file_obj or not file_obj.filename:
        return json_error('Arquivo inválido.', 400)

    files = {'avatar': (file_obj.filename, file_obj.stream, file_obj.content_type or 'image/jpeg')}
    return _proxy_auth('POST', f'/users/{user_id}/avatar', files=files)


@app.get('/api/profile/avatar/<path:key>')
def serve_user_avatar(key: str):
    """Serve a imagem de avatar do MinIO diretamente aos clientes."""
    from minio import Minio
    raw_endpoint = os.getenv('MINIO_ENDPOINT', 'minio:9000')
    access_key = os.getenv('MINIO_ACCESS_KEY', '')
    secret_key = os.getenv('MINIO_SECRET_KEY', '')
    bucket_name = os.getenv('MINIO_BUCKET_NAME', 'tomhanks-avatars')

    if not access_key or not secret_key:
        return json_error('Serviço de armazenamento não configurado.', 503)

    endpoint = raw_endpoint.split('://')[-1] if '://' in raw_endpoint else raw_endpoint
    try:
        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
        content_type = 'image/png'
        key_lower = key.lower()
        if key_lower.endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        elif key_lower.endswith('.webp'):
            content_type = 'image/webp'
        elif key_lower.endswith('.gif'):
            content_type = 'image/gif'

        with client.get_object(bucket_name, key) as response:
            data = response.read()

        return Response(data, content_type=content_type)
    except Exception as exc:
        app.logger.warning('Avatar key=%s não encontrado no MinIO: %s', key, exc)
        return json_error('Avatar não encontrado.', 404)


# ---------------------------------------------------------------------------
# Documentação Swagger / OpenAPI 3.0 (Atividade Extra)
# ---------------------------------------------------------------------------

@app.get('/api/docs/openapi.json')
def openapi_json():
    """Retorna a especificação OpenAPI 3.0 em formato JSON."""
    from backend.swagger_spec import get_openapi_json
    return Response(get_openapi_json(), content_type='application/json; charset=utf-8')


@app.get('/api/docs/openapi.yaml')
def openapi_yaml():
    """Retorna a especificação OpenAPI 3.0 em formato YAML."""
    from backend.swagger_spec import get_openapi_yaml
    return Response(get_openapi_yaml(), content_type='text/yaml; charset=utf-8')


@app.get('/apidocs')
@app.get('/docs')
def swagger_ui():
    """Renderiza a interface interativa do Swagger UI integrada à aplicação."""
    html_content = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Documentação Swagger / OpenAPI — Catálogo Tom Hanks</title>
  <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui.min.css" />
  <style>
    html { box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }
    *, *:before, *:after { box-sizing: inherit; }
    body { margin:0; background: #0f172a; color: #f8fafc; font-family: sans-serif; }
    .swagger-ui .topbar { background-color: #1e293b; border-bottom: 2px solid #e94560; }
    .swagger-ui .info .title { color: #f8fafc; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-bundle.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-standalone-preset.min.js"></script>
  <script>
    window.onload = function() {
      const ui = SwaggerUIBundle({
        url: "/api/docs/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIStandalonePreset
        ],
        plugins: [
          SwaggerUIBundle.plugins.DownloadUrl
        ],
        layout: "StandaloneLayout"
      });
      window.ui = ui;
    };
  </script>
</body>
</html>
"""
    return Response(html_content, content_type='text/html; charset=utf-8')


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def load_user_state(db, user_id: int) -> tuple[set[int], list[dict[str, Any]]]:
    favorite_ids = set(
        db.scalars(
            select(Favorite.tmdb_movie_id).where(Favorite.usuario_id == user_id).order_by(Favorite.criado_em.desc())
        ).all()
    )
    comment_rows = db.scalars(
        select(Comment).where(Comment.usuario_id == user_id).order_by(Comment.criado_em.desc(), Comment.id.desc())
    ).all()
    comments = [
        {
            'id': int(row.id),
            'tmdb_movie_id': int(row.tmdb_movie_id),
            'texto': row.texto,
            'criado_em': row.criado_em.isoformat() if hasattr(row.criado_em, 'isoformat') else row.criado_em,
        }
        for row in comment_rows
    ]
    return favorite_ids, comments


@app.get('/api/catalog')
def catalog():
    user_id, error = require_login()
    if error:
        return error

    with session_scope() as db:
        favorite_ids, comments = load_user_state(db, user_id)
        try:
            tmdb_movies = get_tom_hanks_catalog()
            catalog_warning = None
        except Exception as exc:
            if _LAST_KNOWN_CATALOG:
                tmdb_movies = _catalog_copy(_LAST_KNOWN_CATALOG)
                catalog_warning = 'A TMDB ficou indisponível; exibindo o último catálogo carregado.'
                app.logger.warning('Servindo catálogo em cache após falha na TMDB: %s', exc)
            else:
                tmdb_movies = []
                catalog_warning = 'Não foi possível carregar o catálogo da TMDB neste momento.'
                app.logger.exception('Falha ao carregar catálogo da TMDB.')

        movies = [serialize_movie(movie, favorite_ids, comments) for movie in tmdb_movies]
        favorites = [movie for movie in movies if movie['is_favorite']]
        payload = {
            'user_id': user_id,
            'movies': movies,
            'favorites': favorites,
            'stats': {
                'favorite_count': len(favorites),
                'comment_count': len(comments),
            },
        }
        if catalog_warning:
            payload['warning'] = catalog_warning
        return jsonify(payload)


# ---------------------------------------------------------------------------
# Favoritos
# ---------------------------------------------------------------------------

@app.get('/api/favorites')
def favorites():
    user_id, error = require_login()
    if error:
        return error

    with session_scope() as db:
        rows = db.scalars(
            select(Favorite).where(Favorite.usuario_id == user_id).order_by(Favorite.criado_em.desc())
        ).all()
        payload = []
        for row in rows:
            payload.append(
                {
                    'id': int(row.id),
                    'tmdb_movie_id': int(row.tmdb_movie_id),
                    'title': row.titulo,
                    'poster_path': row.poster_path,
                    'poster_url': normalize_poster_path(row.poster_path),
                    'criado_em': row.criado_em.isoformat() if hasattr(row.criado_em, 'isoformat') else row.criado_em,
                }
            )
        return jsonify({'favorites': payload})


@app.post('/api/favorites')
def create_favorite():
    user_id, error = require_login()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    movie_id = payload.get('tmdb_movie_id')
    if movie_id is None:
        return json_error('Informe o filme a favoritar.')

    try:
        movie_id = int(movie_id)
    except (TypeError, ValueError):
        return json_error('tmdb_movie_id inválido.')

    try:
        movie = get_movie_details(movie_id)
    except Exception as exc:
        return json_error(f'Não foi possível carregar o filme da TMDB: {exc}', 502)

    with session_scope() as db:
        favorite = db.scalar(
            select(Favorite).where(Favorite.usuario_id == user_id, Favorite.tmdb_movie_id == movie_id)
        )
        if favorite is None:
            favorite = Favorite(
                usuario_id=user_id,
                tmdb_movie_id=movie_id,
                titulo=movie['title'],
                poster_path=movie.get('poster_path'),
            )
            db.add(favorite)
        else:
            favorite.titulo = movie['title']
            favorite.poster_path = movie.get('poster_path')

        log_event('favoritar', usuario_id=user_id, detalhe=f'movie_id={movie_id} title={movie["title"]!r}')
        return jsonify(
            {
                'ok': True,
                'favorite': {
                    'tmdb_movie_id': movie_id,
                    'title': movie['title'],
                    'poster_path': movie.get('poster_path'),
                    'poster_url': movie.get('poster_url'),
                },
            }
        ), 201


@app.delete('/api/favorites/<int:movie_id>')
def delete_favorite(movie_id: int):
    user_id, error = require_login()
    if error:
        return error

    with session_scope() as db:
        result = db.execute(
            delete(Favorite).where(Favorite.usuario_id == user_id, Favorite.tmdb_movie_id == movie_id)
        )
        log_event('desfavoritar', usuario_id=user_id, detalhe=f'movie_id={movie_id}')
        return jsonify({'ok': True, 'deleted': result.rowcount > 0})


# ---------------------------------------------------------------------------
# Comentários
# ---------------------------------------------------------------------------

@app.get('/api/comments')
def list_comments():
    user_id, error = require_login()
    if error:
        return error

    movie_id_raw = request.args.get('movie_id')
    with session_scope() as db:
        if movie_id_raw:
            try:
                movie_id = int(movie_id_raw)
            except (TypeError, ValueError):
                return json_error('movie_id inválido.')
            rows = db.scalars(
                select(Comment)
                .where(Comment.usuario_id == user_id, Comment.tmdb_movie_id == movie_id)
                .order_by(Comment.criado_em.desc(), Comment.id.desc())
            ).all()
        else:
            rows = db.scalars(
                select(Comment).where(Comment.usuario_id == user_id).order_by(Comment.criado_em.desc(), Comment.id.desc())
            ).all()

        comments = [
            {
                'id': int(row.id),
                'tmdb_movie_id': int(row.tmdb_movie_id),
                'texto': row.texto,
                'criado_em': row.criado_em.isoformat() if hasattr(row.criado_em, 'isoformat') else row.criado_em,
            }
            for row in rows
        ]
        return jsonify({'comments': comments})


@app.post('/api/comments')
def create_comment():
    user_id, error = require_login()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    texto = str(payload.get('texto', '')).strip()
    movie_id = payload.get('tmdb_movie_id')
    if movie_id is None:
        return json_error('Informe o filme comentado.')

    try:
        movie_id = int(movie_id)
    except (TypeError, ValueError):
        return json_error('tmdb_movie_id inválido.')

    if not texto:
        return json_error('Escreva um comentário antes de salvar.')

    if len(texto) > 4000:
        return json_error('O comentário é muito longo.')

    with session_scope() as db:
        comment = Comment(usuario_id=user_id, tmdb_movie_id=movie_id, texto=texto)
        db.add(comment)
        db.flush()
        db.refresh(comment)
        log_event('comentar', usuario_id=user_id, detalhe=f'movie_id={movie_id} comment_id={comment.id}')
        return jsonify(
            {
                'ok': True,
                'comment': {
                    'id': int(comment.id),
                    'tmdb_movie_id': movie_id,
                    'texto': texto,
                },
            }
        ), 201


@app.delete('/api/comments/<int:comment_id>')
def delete_comment(comment_id: int):
    user_id, error = require_login()
    if error:
        return error

    # Verifica se o usuário é admin (enforcement no servidor, não no cliente)
    admin_user, _ = require_role('admin')
    is_admin = admin_user is not None

    with session_scope() as db:
        if is_admin:
            # Admin pode apagar comentários de qualquer usuário (moderação)
            result = db.execute(delete(Comment).where(Comment.id == comment_id))
        else:
            # Usuário comum só pode apagar os próprios comentários
            result = db.execute(delete(Comment).where(Comment.id == comment_id, Comment.usuario_id == user_id))

        deleted = result.rowcount > 0
        if not deleted and not is_admin:
            # Se não deletou nada e não é admin, pode ser que o comentário pertence a outro usuário
            comment_exists = db.scalar(select(Comment).where(Comment.id == comment_id))
            if comment_exists:
                log_event(
                    '403_apagar_comentario',
                    usuario_id=user_id,
                    detalhe=f'comment_id={comment_id} motivo=sem_permissao',
                )
                return json_error('Sem permissão para apagar este comentário.', 403)

        acao = 'moderacao_apagar_comentario' if is_admin else 'apagar_comentario'
        log_event(acao, usuario_id=user_id, detalhe=f'comment_id={comment_id} deleted={deleted}')
        return jsonify({'ok': True, 'deleted': deleted})


# ---------------------------------------------------------------------------
# Frontend estático
# ---------------------------------------------------------------------------

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path: str):
    if path.startswith('api/'):
        return json_error('Not found', 404)

    if path:
        candidate = STATIC_DIR / path
        if candidate.is_file():
            return send_from_directory(STATIC_DIR, path)

    index_file = STATIC_DIR / 'index.html'
    if index_file.is_file():
        return send_from_directory(STATIC_DIR, 'index.html')

    return jsonify(
        {
            'message': 'Frontend build not found. Build the Angular app into backend/static.',
            'hint': 'Use the Dockerfile or copy the Angular browser dist folder to backend/static.',
        }
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=os.getenv('FLASK_DEBUG', '0') == '1')
