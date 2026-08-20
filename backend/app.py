from __future__ import annotations

import os
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
)


def _cors_origins() -> set[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:4200").strip()
    return {item.strip() for item in raw.split(",") if item.strip()}


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin and origin in _cors_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
        response.headers["Vary"] = "Origin"
    return response


@app.route("/api/<path:_path>", methods=["OPTIONS"])
def api_preflight(_path: str):
    return ("", 204)


def json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def get_db_connection():
    try:
        import mysql.connector as mysql_connector
    except ImportError as exc:  # pragma: no cover - surfaced in deployment if dependency is missing
        raise RuntimeError(
            "mysql-connector-python is required to run this application."
        ) from exc

    return mysql_connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "tomhanks"),
        autocommit=False,
        connection_timeout=5,
    )


def with_db(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        conn = get_db_connection()
        try:
            result = func(conn, *args, **kwargs)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return wrapper


@with_db
def ensure_schema(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            nome VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            senha_hash VARCHAR(255) NOT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS favoritos (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id INT NOT NULL,
            tmdb_movie_id INT NOT NULL,
            titulo VARCHAR(255) NOT NULL,
            poster_path VARCHAR(255),
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_favoritos_usuario
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                ON DELETE CASCADE,
            UNIQUE KEY uniq_usuario_filme (usuario_id, tmdb_movie_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS comentarios (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id INT NOT NULL,
            tmdb_movie_id INT NOT NULL,
            texto TEXT NOT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_comentarios_usuario
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cursor.close()


def run_query(conn, sql: str, params: tuple[Any, ...] = (), *, fetch: str | None = None):
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params)
    if fetch == "one":
        row = cursor.fetchone()
        cursor.close()
        return row
    if fetch == "all":
        rows = cursor.fetchall()
        cursor.close()
        return rows
    last_id = cursor.lastrowid
    rowcount = cursor.rowcount
    cursor.close()
    return {"lastrowid": last_id, "rowcount": rowcount}


def current_user_id() -> int | None:
    user_id = session.get("user_id")
    return int(user_id) if user_id is not None else None


def require_login():
    user_id = current_user_id()
    if user_id is None:
        return None, json_error("Faça login para continuar.", 401)
    return user_id, None


def normalize_poster_path(poster_path: str | None) -> str | None:
    if not poster_path:
        return None
    return poster_path if poster_path.startswith("http") else f"{TMDB_IMAGE_BASE_URL}{poster_path}"


def tmdb_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.getenv("TMDB_API_KEY")
    if not api_key:
        raise RuntimeError("TMDB_API_KEY não configurada no servidor.")

    query = {"api_key": api_key, "language": os.getenv("TMDB_LANGUAGE", "pt-BR")}
    if params:
        query.update(params)

    response = requests.get(f"{TMDB_BASE_URL}{path}", params=query, timeout=20)
    response.raise_for_status()
    return response.json()


@lru_cache(maxsize=1)
def get_tom_hanks_person_id() -> int:
    payload = tmdb_request("/search/person", {"query": "Tom Hanks"})
    results = payload.get("results", [])
    if not results:
        raise RuntimeError("Tom Hanks não foi encontrado na TMDB.")

    for person in results:
        if person.get("name", "").strip().lower() == "tom hanks":
            return int(person["id"])
    return int(results[0]["id"])


@lru_cache(maxsize=128)
def get_movie_details(movie_id: int) -> dict[str, Any]:
    payload = tmdb_request(f"/movie/{movie_id}")
    return {
        "tmdb_movie_id": int(payload["id"]),
        "title": payload.get("title") or payload.get("original_title") or "Título indisponível",
        "overview": payload.get("overview") or "Sinopse indisponível.",
        "poster_path": payload.get("poster_path"),
        "poster_url": normalize_poster_path(payload.get("poster_path")),
        "release_date": payload.get("release_date"),
    }


def get_tom_hanks_catalog() -> list[dict[str, Any]]:
    person_id = get_tom_hanks_person_id()
    payload = tmdb_request(f"/person/{person_id}/movie_credits")
    credits = payload.get("cast", [])

    selected = [
        movie
        for movie in sorted(
            credits,
            key=lambda item: (
                item.get("release_date") or "0000-00-00",
                item.get("popularity") or 0,
            ),
            reverse=True,
        )
        if movie.get("id") and movie.get("media_type", "movie") == "movie"
    ][:24]

    catalog: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for movie in selected:
        movie_id = int(movie["id"])
        if movie_id in seen_ids:
            continue
        seen_ids.add(movie_id)
        try:
            details = get_movie_details(movie_id)
        except Exception:
            details = {
                "tmdb_movie_id": movie_id,
                "title": movie.get("title") or movie.get("original_title") or "Título indisponível",
                "overview": movie.get("overview") or "Sinopse indisponível.",
                "poster_path": movie.get("poster_path"),
                "poster_url": normalize_poster_path(movie.get("poster_path")),
                "release_date": movie.get("release_date"),
            }
        catalog.append(details)

    return catalog


def load_user_state(conn, user_id: int) -> tuple[set[int], list[dict[str, Any]]]:
    favorite_rows = run_query(
        conn,
        """
        SELECT id, tmdb_movie_id, titulo, poster_path, criado_em
        FROM favoritos
        WHERE usuario_id = %s
        ORDER BY criado_em DESC
        """,
        (user_id,),
        fetch="all",
    )
    comment_rows = run_query(
        conn,
        """
        SELECT id, tmdb_movie_id, texto, criado_em
        FROM comentarios
        WHERE usuario_id = %s
        ORDER BY criado_em DESC, id DESC
        """,
        (user_id,),
        fetch="all",
    )
    favorite_ids = {int(row["tmdb_movie_id"]) for row in favorite_rows}
    comments = [
        {
            "id": int(row["id"]),
            "tmdb_movie_id": int(row["tmdb_movie_id"]),
            "texto": row["texto"],
            "criado_em": row["criado_em"].isoformat() if hasattr(row["criado_em"], "isoformat") else row["criado_em"],
        }
        for row in comment_rows
    ]
    return favorite_ids, comments


def serialize_movie(movie: dict[str, Any], favorite_ids: set[int], comments: list[dict[str, Any]]):
    movie_id = int(movie["tmdb_movie_id"])
    movie_comments = [item for item in comments if item["tmdb_movie_id"] == movie_id]
    return {
        "tmdb_movie_id": movie_id,
        "title": movie["title"],
        "overview": movie["overview"],
        "poster_path": movie.get("poster_path"),
        "poster_url": movie.get("poster_url"),
        "release_date": movie.get("release_date"),
        "is_favorite": movie_id in favorite_ids,
        "comments": movie_comments,
        "comment_count": len(movie_comments),
        "favorite": movie_id in favorite_ids,
    }


@app.before_request
def initialize_app():
    if request.method == "OPTIONS":
        return None
    if not request.path.startswith("/api/"):
        return None
    if not getattr(app, "_schema_ready", False):
        ensure_schema()
        app._schema_ready = True
    return None


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/auth/me")
def me():
    user_id = current_user_id()
    if user_id is None:
        return json_error("Não autenticado.", 401)

    conn = get_db_connection()
    try:
        user = run_query(
            conn,
            "SELECT id, nome, email, criado_em FROM usuarios WHERE id = %s",
            (user_id,),
            fetch="one",
        )
        if not user:
            session.clear()
            return json_error("Sessão expirada.", 401)
        user["id"] = int(user["id"])
        user["criado_em"] = user["criado_em"].isoformat() if hasattr(user["criado_em"], "isoformat") else user["criado_em"]
        return jsonify({"user": user})
    finally:
        conn.close()


@app.post("/api/auth/register")
def register():
    payload = request.get_json(silent=True) or {}
    nome = str(payload.get("nome", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    senha = str(payload.get("senha", ""))

    if len(nome) < 2:
        return json_error("Informe um nome válido.")
    if "@" not in email or len(email) < 5:
        return json_error("Informe um e-mail válido.")
    if len(senha) < 6:
        return json_error("A senha precisa ter pelo menos 6 caracteres.")

    senha_hash = generate_password_hash(senha)
    conn = get_db_connection()
    try:
        existing = run_query(
            conn,
            "SELECT id FROM usuarios WHERE email = %s",
            (email,),
            fetch="one",
        )
        if existing:
            return json_error("Já existe uma conta com esse e-mail.", 409)

        result = run_query(
            conn,
            """
            INSERT INTO usuarios (nome, email, senha_hash)
            VALUES (%s, %s, %s)
            """,
            (nome, email, senha_hash),
        )
        session["user_id"] = int(result["lastrowid"])
        user = run_query(
            conn,
            "SELECT id, nome, email, criado_em FROM usuarios WHERE id = %s",
            (session["user_id"],),
            fetch="one",
        )
        user["id"] = int(user["id"])
        user["criado_em"] = user["criado_em"].isoformat() if hasattr(user["criado_em"], "isoformat") else user["criado_em"]
        return jsonify({"user": user}), 201
    finally:
        conn.close()


@app.post("/api/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    senha = str(payload.get("senha", ""))

    if not email or not senha:
        return json_error("Informe e-mail e senha.")

    conn = get_db_connection()
    try:
        user = run_query(
            conn,
            "SELECT id, nome, email, senha_hash, criado_em FROM usuarios WHERE email = %s",
            (email,),
            fetch="one",
        )
        if not user or not check_password_hash(user["senha_hash"], senha):
            return json_error("Credenciais inválidas.", 401)

        session["user_id"] = int(user["id"])
        return jsonify(
            {
                "user": {
                    "id": int(user["id"]),
                    "nome": user["nome"],
                    "email": user["email"],
                    "criado_em": user["criado_em"].isoformat() if hasattr(user["criado_em"], "isoformat") else user["criado_em"],
                }
            }
        )
    finally:
        conn.close()


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/catalog")
def catalog():
    user_id, error = require_login()
    if error:
        return error

    conn = get_db_connection()
    try:
        favorite_ids, comments = load_user_state(conn, user_id)
        movies = [serialize_movie(movie, favorite_ids, comments) for movie in get_tom_hanks_catalog()]
        favorites = [movie for movie in movies if movie["is_favorite"]]
        return jsonify(
            {
                "user_id": user_id,
                "movies": movies,
                "favorites": favorites,
                "stats": {
                    "favorite_count": len(favorites),
                    "comment_count": len(comments),
                },
            }
        )
    finally:
        conn.close()


@app.get("/api/favorites")
def favorites():
    user_id, error = require_login()
    if error:
        return error

    conn = get_db_connection()
    try:
        rows = run_query(
            conn,
            """
            SELECT id, tmdb_movie_id, titulo, poster_path, criado_em
            FROM favoritos
            WHERE usuario_id = %s
            ORDER BY criado_em DESC
            """,
            (user_id,),
            fetch="all",
        )
        payload = []
        for row in rows:
            payload.append(
                {
                    "id": int(row["id"]),
                    "tmdb_movie_id": int(row["tmdb_movie_id"]),
                    "title": row["titulo"],
                    "poster_path": row["poster_path"],
                    "poster_url": normalize_poster_path(row["poster_path"]),
                    "criado_em": row["criado_em"].isoformat() if hasattr(row["criado_em"], "isoformat") else row["criado_em"],
                }
            )
        return jsonify({"favorites": payload})
    finally:
        conn.close()


@app.post("/api/favorites")
def create_favorite():
    user_id, error = require_login()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    movie_id = payload.get("tmdb_movie_id")
    if movie_id is None:
        return json_error("Informe o filme a favoritar.")

    try:
        movie_id = int(movie_id)
    except (TypeError, ValueError):
        return json_error("tmdb_movie_id inválido.")

    try:
        movie = get_movie_details(movie_id)
    except Exception as exc:
        return json_error(f"Não foi possível carregar o filme da TMDB: {exc}", 502)

    conn = get_db_connection()
    try:
        run_query(
            conn,
            """
            INSERT INTO favoritos (usuario_id, tmdb_movie_id, titulo, poster_path)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                titulo = VALUES(titulo),
                poster_path = VALUES(poster_path)
            """,
            (user_id, movie_id, movie["title"], movie.get("poster_path")),
        )
        return jsonify(
            {
                "ok": True,
                "favorite": {
                    "tmdb_movie_id": movie_id,
                    "title": movie["title"],
                    "poster_path": movie.get("poster_path"),
                    "poster_url": movie.get("poster_url"),
                },
            }
        ), 201
    finally:
        conn.close()


@app.delete("/api/favorites/<int:movie_id>")
def delete_favorite(movie_id: int):
    user_id, error = require_login()
    if error:
        return error

    conn = get_db_connection()
    try:
        result = run_query(
            conn,
            "DELETE FROM favoritos WHERE usuario_id = %s AND tmdb_movie_id = %s",
            (user_id, movie_id),
        )
        return jsonify({"ok": True, "deleted": result["rowcount"] > 0})
    finally:
        conn.close()


@app.get("/api/comments")
def list_comments():
    user_id, error = require_login()
    if error:
        return error

    movie_id_raw = request.args.get("movie_id")
    conn = get_db_connection()
    try:
        if movie_id_raw:
            try:
                movie_id = int(movie_id_raw)
            except (TypeError, ValueError):
                return json_error("movie_id inválido.")
            rows = run_query(
                conn,
                """
                SELECT id, tmdb_movie_id, texto, criado_em
                FROM comentarios
                WHERE usuario_id = %s AND tmdb_movie_id = %s
                ORDER BY criado_em DESC, id DESC
                """,
                (user_id, movie_id),
                fetch="all",
            )
        else:
            rows = run_query(
                conn,
                """
                SELECT id, tmdb_movie_id, texto, criado_em
                FROM comentarios
                WHERE usuario_id = %s
                ORDER BY criado_em DESC, id DESC
                """,
                (user_id,),
                fetch="all",
            )

        comments = [
            {
                "id": int(row["id"]),
                "tmdb_movie_id": int(row["tmdb_movie_id"]),
                "texto": row["texto"],
                "criado_em": row["criado_em"].isoformat() if hasattr(row["criado_em"], "isoformat") else row["criado_em"],
            }
            for row in rows
        ]
        return jsonify({"comments": comments})
    finally:
        conn.close()


@app.post("/api/comments")
def create_comment():
    user_id, error = require_login()
    if error:
        return error

    payload = request.get_json(silent=True) or {}
    texto = str(payload.get("texto", "")).strip()
    movie_id = payload.get("tmdb_movie_id")
    if movie_id is None:
        return json_error("Informe o filme comentado.")

    try:
        movie_id = int(movie_id)
    except (TypeError, ValueError):
        return json_error("tmdb_movie_id inválido.")

    if not texto:
        return json_error("Escreva um comentário antes de salvar.")

    if len(texto) > 4000:
        return json_error("O comentário é muito longo.")

    conn = get_db_connection()
    try:
        result = run_query(
            conn,
            """
            INSERT INTO comentarios (usuario_id, tmdb_movie_id, texto)
            VALUES (%s, %s, %s)
            """,
            (user_id, movie_id, texto),
        )
        return jsonify(
            {
                "ok": True,
                "comment": {
                    "id": int(result["lastrowid"]),
                    "tmdb_movie_id": movie_id,
                    "texto": texto,
                },
            }
        ), 201
    finally:
        conn.close()


@app.delete("/api/comments/<int:comment_id>")
def delete_comment(comment_id: int):
    user_id, error = require_login()
    if error:
        return error

    conn = get_db_connection()
    try:
        result = run_query(
            conn,
            "DELETE FROM comentarios WHERE id = %s AND usuario_id = %s",
            (comment_id, user_id),
        )
        return jsonify({"ok": True, "deleted": result["rowcount"] > 0})
    finally:
        conn.close()


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path: str):
    if path.startswith("api/"):
        return json_error("Not found", 404)

    if path:
        candidate = STATIC_DIR / path
        if candidate.is_file():
            return send_from_directory(STATIC_DIR, path)

    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return send_from_directory(STATIC_DIR, "index.html")

    return jsonify(
        {
            "message": "Frontend build not found. Build the Angular app into backend/static.",
            "hint": "Use the Dockerfile or copy the Angular browser dist folder to backend/static.",
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "0") == "1")
