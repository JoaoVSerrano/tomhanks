from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request, send_from_directory, session
from sqlalchemy import delete, select
from werkzeug.security import check_password_hash, generate_password_hash

from backend.database import session_scope, upgrade_database
from backend.models import Comment, Favorite, User


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'
TMDB_BASE_URL = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w500'
_LAST_KNOWN_CATALOG: list[dict[str, Any]] = []

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-change-me')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1',
)


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
    return response


@app.route('/api/<path:_path>', methods=['OPTIONS'])
def api_preflight(_path: str):
    return ('', 204)


def json_error(message: str, status: int = 400):
    return jsonify({'error': message}), status


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


def current_user_id() -> int | None:
    user_id = session.get('user_id')
    return int(user_id) if user_id is not None else None


def require_login():
    user_id = current_user_id()
    if user_id is None:
        return None, json_error('Faça login para continuar.', 401)
    return user_id, None


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


@app.get('/api/health')
def health():
    return jsonify({'ok': True})


@app.get('/api/auth/me')
def me():
    user_id = current_user_id()
    if user_id is None:
        return json_error('Não autenticado.', 401)

    with session_scope() as db:
        user = db.get(User, user_id)
        if not user:
            session.clear()
            return json_error('Sessão expirada.', 401)

        return jsonify(
            {
                'user': {
                    'id': int(user.id),
                    'nome': user.nome,
                    'email': user.email,
                    'criado_em': user.criado_em.isoformat() if hasattr(user.criado_em, 'isoformat') else user.criado_em,
                }
            }
        )


@app.post('/api/auth/register')
def register():
    payload = request.get_json(silent=True) or {}
    nome = str(payload.get('nome', '')).strip()
    email = str(payload.get('email', '')).strip().lower()
    senha = str(payload.get('senha', ''))

    if len(nome) < 2:
        return json_error('Informe um nome válido.')
    if '@' not in email or len(email) < 5:
        return json_error('Informe um e-mail válido.')
    if len(senha) < 6:
        return json_error('A senha precisa ter pelo menos 6 caracteres.')

    senha_hash = generate_password_hash(senha)
    with session_scope() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            return json_error('Já existe uma conta com esse e-mail.', 409)

        user = User(nome=nome, email=email, senha_hash=senha_hash)
        db.add(user)
        db.flush()
        db.refresh(user)
        session['user_id'] = int(user.id)
        return jsonify(
            {
                'user': {
                    'id': int(user.id),
                    'nome': user.nome,
                    'email': user.email,
                    'criado_em': user.criado_em.isoformat() if hasattr(user.criado_em, 'isoformat') else user.criado_em,
                }
            }
        ), 201


@app.post('/api/auth/login')
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get('email', '')).strip().lower()
    senha = str(payload.get('senha', ''))

    if not email or not senha:
        return json_error('Informe e-mail e senha.')

    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == email))
        if not user or not check_password_hash(user.senha_hash, senha):
            return json_error('Credenciais inválidas.', 401)

        session['user_id'] = int(user.id)
        return jsonify(
            {
                'user': {
                    'id': int(user.id),
                    'nome': user.nome,
                    'email': user.email,
                    'criado_em': user.criado_em.isoformat() if hasattr(user.criado_em, 'isoformat') else user.criado_em,
                }
            }
        )


@app.post('/api/auth/logout')
def logout():
    session.clear()
    return jsonify({'ok': True})


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
        return jsonify({'ok': True, 'deleted': result.rowcount > 0})


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

    with session_scope() as db:
        result = db.execute(delete(Comment).where(Comment.id == comment_id, Comment.usuario_id == user_id))
        return jsonify({'ok': True, 'deleted': result.rowcount > 0})


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
