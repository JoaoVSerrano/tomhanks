from __future__ import annotations

import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from flask import Flask, jsonify, request, session
from prometheus_flask_exporter import PrometheusMetrics
from sqlalchemy import delete, select
from werkzeug.security import check_password_hash, generate_password_hash

from auth_service.database import session_scope, upgrade_database
from auth_service.models import ResetToken, User


app = Flask(__name__)
app.secret_key = os.getenv('AUTH_SECRET_KEY', 'auth-dev-secret-change-me')
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.getenv('SESSION_COOKIE_SECURE', '0') == '1',
)
metrics = PrometheusMetrics(app)

AUTH_PORT = int(os.getenv('AUTH_PORT', '3000'))


def json_error(message: str, status: int = 400):
    return jsonify({'error': message}), status


# ---------------------------------------------------------------------------
# Log de auditoria — envia evento ao log-service (fire-and-forget)
# ---------------------------------------------------------------------------

def log_service_url() -> str:
    return os.getenv('LOG_SERVICE_URL', 'http://log-service:4000')


def log_event(
    acao: str,
    usuario_id: int | None = None,
    detalhe: str = '',
) -> None:
    """Envia evento de auditoria ao log-service. Nunca propaga erros."""
    import requests as _requests
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        if ip:
            ip = ip.split(',')[0].strip()
        _requests.post(
            f'{log_service_url()}/log',
            json={
                'usuario_id': usuario_id,
                'acao': acao,
                'detalhe': detalhe,
                'ip': ip,
            },
            headers={'X-Internal-Token': INTERNAL_TOKEN},
            timeout=3,
        )
    except Exception as exc:
        app.logger.warning('log-service indisponível (evento=%s): %s', acao, exc)


# ---------------------------------------------------------------------------
# CORS (permite chamadas do catálogo via rede interna e do frontend)
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
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type,X-Internal-Token'
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,DELETE,OPTIONS'
        response.headers['Vary'] = 'Origin'
    return response


@app.route('/<path:_path>', methods=['OPTIONS'])
def preflight(_path: str):
    return ('', 204)


# ---------------------------------------------------------------------------
# Segurança de chamadas internas (catálogo → auth-service)
# ---------------------------------------------------------------------------

INTERNAL_TOKEN = os.getenv('INTERNAL_TOKEN', '')


def require_internal_token():
    """Verifica se a requisição vem do catálogo (rede interna)."""
    token = request.headers.get('X-Internal-Token', '')
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        return json_error('Acesso não autorizado.', 403)
    return None


# ---------------------------------------------------------------------------
# Schema / inicialização
# ---------------------------------------------------------------------------

@app.before_request
def initialize():
    if request.method == 'OPTIONS':
        return None
    if not getattr(app, '_schema_ready', False):
        app._schema_ready = True
        try:
            upgrade_database()
            ensure_configured_admin()
        except Exception:
            app.logger.exception('Falha ao garantir schema do banco.')
    return None


# ---------------------------------------------------------------------------
# Envio de e-mail via Mailtrap (dev) ou Brevo (produção)
# ---------------------------------------------------------------------------

def send_reset_email(to_email: str, to_name: str, reset_link: str) -> None:
    """Envia o e-mail de recuperação de senha."""
    smtp_host = os.getenv('SMTP_HOST', 'sandbox.smtp.mailtrap.io')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_encryption = os.getenv('SMTP_ENCRYPTION', 'starttls').strip().lower()
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_pass = os.getenv('SMTP_PASS', '')
    from_email = os.getenv('SMTP_FROM', 'noreply@tomhanks.local')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Recuperação de senha — Catálogo Tom Hanks'
    msg['From'] = from_email
    msg['To'] = to_email

    text_body = (
        f'Olá, {to_name}!\n\n'
        f'Recebemos uma solicitação para redefinir a senha da sua conta.\n\n'
        f'Clique no link abaixo (válido por 30 minutos):\n{reset_link}\n\n'
        f'Se você não solicitou a redefinição, ignore este e-mail.'
    )
    html_body = f"""
    <html><body style="font-family:sans-serif;max-width:540px;margin:auto;padding:24px">
      <h2 style="color:#1a1a2e">Recuperação de senha</h2>
      <p>Olá, <strong>{to_name}</strong>!</p>
      <p>Recebemos uma solicitação para redefinir a senha da sua conta no
         <strong>Catálogo Tom Hanks</strong>.</p>
      <p>
        <a href="{reset_link}"
           style="display:inline-block;background:#e94560;color:#fff;padding:12px 24px;
                  border-radius:6px;text-decoration:none;font-weight:bold">
          Redefinir minha senha
        </a>
      </p>
      <p style="color:#888;font-size:13px">
        Este link expira em <strong>30 minutos</strong>.<br>
        Se você não solicitou a redefinição, ignore este e-mail.
      </p>
    </body></html>
    """

    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    smtp_cls = smtplib.SMTP_SSL if smtp_encryption == 'ssl' else smtplib.SMTP
    with smtp_cls(smtp_host, smtp_port, timeout=20) as server:
        if smtp_encryption == 'starttls':
            server.ehlo()
            server.starttls()
            server.ehlo()   # re-anuncia capacidades após upgrade TLS
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to_email], msg.as_string())


def smtp_is_configured() -> bool:
    return bool(os.getenv('SMTP_HOST') and os.getenv('SMTP_USER') and os.getenv('SMTP_PASS'))


def should_expose_reset_link() -> bool:
    return os.getenv('PASSWORD_RESET_EXPOSE_LINK', '0') == '1'


def ensure_configured_admin() -> None:
    email = os.getenv('AUTH_ADMIN_EMAIL', '').strip().lower()
    password = os.getenv('AUTH_ADMIN_PASSWORD', '')
    name = os.getenv('AUTH_ADMIN_NAME', 'Administrador').strip() or 'Administrador'

    if not email or not password:
        return

    if '@' not in email or len(email) < 5:
        app.logger.warning('AUTH_ADMIN_EMAIL inválido; admin inicial não será criado.')
        return
    if len(password) < 6:
        app.logger.warning('AUTH_ADMIN_PASSWORD precisa ter pelo menos 6 caracteres; admin inicial não será criado.')
        return

    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            if user.role != 'admin':
                user.role = 'admin'
            return

        db.add(
            User(
                nome=name,
                email=email,
                senha_hash=generate_password_hash(password),
                role='admin',
            )
        )


# ---------------------------------------------------------------------------
# Rotas de saúde & Readiness
# ---------------------------------------------------------------------------

@app.get('/health')
def health():
    database_ok = False
    minio_ok = False
    try:
        with session_scope() as db:
            db.execute(select(1))
        database_ok = True
    except Exception as exc:
        app.logger.error('Banco de dados (MariaDB) indisponível em healthcheck: %s', exc)

    try:
        client = get_minio_client()
        if client is not None:
            client.list_buckets()
            minio_ok = True
    except Exception as exc:
        app.logger.error('MinIO indisponível em healthcheck: %s', exc)

    healthy = database_ok and minio_ok
    payload = {
        'status': 'healthy' if healthy else 'unhealthy',
        'service': 'auth-service',
        'database': 'connected' if database_ok else 'disconnected',
        'minio': 'connected' if minio_ok else 'disconnected',
    }
    return jsonify(payload), 200 if healthy else 503


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

@app.post('/register')
def register():
    payload = request.get_json(silent=True) or {}
    nome = str(payload.get('nome', '')).strip()
    email = str(payload.get('email', '')).strip().lower()
    senha = str(payload.get('senha', ''))
    role = 'usuario'

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

        user = User(nome=nome, email=email, senha_hash=senha_hash, role=role)
        db.add(user)
        db.flush()
        db.refresh(user)
        session['user_id'] = int(user.id)
        return jsonify({'user': serialize_user_dict(user)}), 201


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@app.post('/login')
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
        return jsonify({'user': serialize_user_dict(user)})


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@app.post('/logout')
def logout():
    session.clear()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Me (quem sou eu — chamado pelo catálogo via rede interna)
# ---------------------------------------------------------------------------

@app.get('/me')
def me():
    user_id = session.get('user_id')
    if user_id is None:
        return json_error('Não autenticado.', 401)

    with session_scope() as db:
        user = db.get(User, int(user_id))
        if not user:
            session.clear()
            return json_error('Sessão expirada.', 401)

        return jsonify({'user': serialize_user_dict(user)})


# ---------------------------------------------------------------------------
# Verificar usuário por ID (chamado internamente pelo catálogo)
# ---------------------------------------------------------------------------

@app.get('/internal/users/<int:user_id>')
def get_user_internal(user_id: int):
    err = require_internal_token()
    if err:
        return err

    with session_scope() as db:
        user = db.get(User, user_id)
        if not user:
            return json_error('Usuário não encontrado.', 404)

        return jsonify({'user': serialize_user_dict(user)})


# ---------------------------------------------------------------------------
# Helpers para Perfil e Object Storage (MinIO)
# ---------------------------------------------------------------------------

def get_minio_client():
    from minio import Minio
    raw_endpoint = os.getenv('MINIO_ENDPOINT', 'minio:9000')
    access_key = os.getenv('MINIO_ACCESS_KEY', 'minioadmin')
    secret_key = os.getenv('MINIO_SECRET_KEY', 'minioadmin')

    endpoint = raw_endpoint.split('://')[-1] if '://' in raw_endpoint else raw_endpoint
    try:
        return Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=False,
        )
    except Exception as exc:
        app.logger.error('Erro ao conectar no MinIO: %s', exc)
        return None


def serialize_user_dict(user: User) -> dict[str, Any]:
    avatar_url = None
    if getattr(user, 'avatar_key', None):
        avatar_url = f"/api/profile/avatar/{user.avatar_key}"

    return {
        'id': int(user.id),
        'nome': user.nome,
        'email': user.email,
        'role': user.role,
        'bio': getattr(user, 'bio', '') or '',
        'avatar_key': getattr(user, 'avatar_key', None),
        'avatar_url': avatar_url,
        'criado_em': user.criado_em.isoformat() if hasattr(user.criado_em, 'isoformat') else str(user.criado_em) if user.criado_em else None,
    }


# ---------------------------------------------------------------------------
# Perfil de Usuário & Upload (Atividade 6)
# ---------------------------------------------------------------------------

@app.get('/users/<int:target_id>')
def get_user_profile(target_id: int):
    with session_scope() as db:
        user = db.get(User, target_id)
        if not user:
            return json_error('Usuário não encontrado.', 404)
        return jsonify({'user': serialize_user_dict(user)})


@app.put('/users/<int:target_id>')
def update_user_profile(target_id: int):
    current_user_id = session.get('user_id')
    if not current_user_id:
        return json_error('Faça login para continuar.', 401)

    if int(current_user_id) != target_id:
        log_event(
            '403_editar_perfil',
            usuario_id=int(current_user_id),
            detalhe=f'tentativa_editar_usuario_id={target_id}',
        )
        return json_error('Você não tem permissão para editar este perfil.', 403)

    payload = request.get_json(silent=True) or {}
    nome = str(payload.get('nome', '')).strip()
    bio = str(payload.get('bio', '')).strip()

    if len(nome) < 2:
        return json_error('O nome deve ter pelo menos 2 caracteres.')

    if len(bio) > 500:
        return json_error('A bio não pode exceder 500 caracteres.')

    with session_scope() as db:
        user = db.get(User, target_id)
        if not user:
            return json_error('Usuário não encontrado.', 404)

        user.nome = nome
        user.bio = bio
        db.flush()

        log_event('perfil_atualizado', usuario_id=target_id, detalhe=f'nome={nome}')
        return jsonify({'ok': True, 'user': serialize_user_dict(user)})


@app.post('/users/<int:target_id>/avatar')
def upload_user_avatar(target_id: int):
    current_user_id = session.get('user_id')
    if not current_user_id:
        return json_error('Faça login para continuar.', 401)

    if int(current_user_id) != target_id:
        log_event(
            '403_upload_avatar',
            usuario_id=int(current_user_id),
            detalhe=f'tentativa_upload_usuario_id={target_id}',
        )
        return json_error('Você não tem permissão para editar este perfil.', 403)

    if 'avatar' not in request.files and 'file' not in request.files:
        return json_error('Nenhum arquivo de foto enviado.', 400)

    file_obj = request.files.get('avatar') or request.files.get('file')
    if not file_obj or not file_obj.filename:
        return json_error('Arquivo inválido ou sem nome.', 400)

    filename = file_obj.filename.lower()
    allowed_exts = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
    if not any(filename.endswith(ext) for ext in allowed_exts):
        return json_error('Formato de arquivo não permitido. Use PNG, JPG, WEBP ou GIF.', 400)

    content_type = file_obj.content_type or ''
    if content_type and not content_type.startswith('image/'):
        return json_error('O arquivo enviado precisa ser uma imagem válida.', 400)

    # Check file size (max 5 MB)
    file_obj.seek(0, os.SEEK_END)
    file_size = file_obj.tell()
    file_obj.seek(0)

    if file_size > 5 * 1024 * 1024:
        return json_error('O tamanho da imagem excede o limite de 5MB.', 400)
    if file_size == 0:
        return json_error('O arquivo enviado está vazio.', 400)

    ext = filename.rsplit('.', 1)[-1] if '.' in filename else 'jpg'
    object_key = f'avatar_{target_id}_{int(datetime.now().timestamp())}.{ext}'
    bucket_name = os.getenv('MINIO_BUCKET_NAME', 'tomhanks-avatars')

    client = get_minio_client()
    if not client:
        return json_error('Serviço de armazenamento de objetos (MinIO) indisponível.', 503)

    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
                    }
                ]
            }
            import json
            try:
                client.set_bucket_policy(bucket_name, json.dumps(policy))
            except Exception:
                pass

        client.put_object(
            bucket_name,
            object_key,
            file_obj,
            length=file_size,
            content_type=content_type or f'image/{ext}',
        )
    except Exception as exc:
        app.logger.error('Erro no upload para MinIO: %s', exc)
        return json_error('Falha ao armazenar arquivo no MinIO.', 500)

    with session_scope() as db:
        user = db.get(User, target_id)
        if not user:
            return json_error('Usuário não encontrado.', 404)
        user.avatar_key = object_key
        db.flush()
        user_dict = serialize_user_dict(user)

    log_event('avatar_atualizado', usuario_id=target_id, detalhe=f'key={object_key} size={file_size}')
    return jsonify({'ok': True, 'user': user_dict})


# ---------------------------------------------------------------------------
# Helper de autorização — verifica role admin via sessão
# ---------------------------------------------------------------------------

def require_admin():
    """Verifica se o usuário autenticado tem role 'admin'.

    Retorna (user, None) em caso de sucesso ou (None, resposta_erro) se não
    autenticado (401) ou sem permissão (403).
    """
    user_id = session.get('user_id')
    if user_id is None:
        return None, json_error('Não autenticado.', 401)

    with session_scope() as db:
        user = db.get(User, int(user_id))
        if not user:
            session.clear()
            return None, json_error('Sessão expirada.', 401)
        if user.role != 'admin':
            return None, json_error(
                'Acesso negado. Apenas administradores podem executar esta ação.', 403
            )
        return user, None


# ---------------------------------------------------------------------------
# Admin — listar todos os usuários
# ---------------------------------------------------------------------------

@app.get('/admin/users')
def admin_list_users():
    _, err = require_admin()
    if err:
        return err

    with session_scope() as db:
        users = db.scalars(select(User).order_by(User.id)).all()
        return jsonify({
            'users': [
                {
                    'id': int(u.id),
                    'nome': u.nome,
                    'email': u.email,
                    'role': u.role,
                    'criado_em': u.criado_em.isoformat() if hasattr(u.criado_em, 'isoformat') else u.criado_em,
                }
                for u in users
            ]
        })


# ---------------------------------------------------------------------------
# Admin — promover / rebaixar role de um usuário
# ---------------------------------------------------------------------------

@app.post('/admin/users/<int:target_id>/role')
def admin_change_role(target_id: int):
    admin_user, err = require_admin()
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    new_role = str(payload.get('role', '')).strip().lower()

    if new_role not in ('usuario', 'admin'):
        return json_error("Role inválida. Use 'usuario' ou 'admin'.")

    with session_scope() as db:
        target = db.get(User, target_id)
        if not target:
            return json_error('Usuário não encontrado.', 404)

        old_role = target.role
        target.role = new_role

        app.logger.info(
            'Admin %s (id=%s) alterou role de usuário %s de %s para %s',
            admin_user.email, admin_user.id, target.email, old_role, new_role,
        )

        return jsonify({
            'ok': True,
            'user': {
                'id': int(target.id),
                'nome': target.nome,
                'email': target.email,
                'role': target.role,
            },
        })


# ---------------------------------------------------------------------------
# Esqueci minha senha — solicitar link
# ---------------------------------------------------------------------------

@app.post('/forgot-password')
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get('email', '')).strip().lower()

    if '@' not in email or len(email) < 5:
        return json_error('Informe um e-mail válido.')

    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == email))

        # Sempre retorna 200 para não revelar se o e-mail existe
        if not user:
            return jsonify({'ok': True, 'message': 'Se o e-mail estiver cadastrado, você receberá um link em breve.'})

        # Invalida tokens anteriores do usuário
        db.execute(delete(ResetToken).where(ResetToken.usuario_id == user.id))

        token_value = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        expira_em = now + timedelta(minutes=30)

        token = ResetToken(
            token=token_value,
            usuario_id=user.id,
            criado_em=now,
            expira_em=expira_em,
            usado=False,
        )
        db.add(token)
        db.flush()

        frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:8080')
        reset_link = f'{frontend_url}/reset-password?token={token_value}'

        if smtp_is_configured():
            try:
                send_reset_email(user.email, user.nome, reset_link)
                app.logger.info('E-mail de recuperação enviado para %s', user.email)
            except Exception as exc:
                app.logger.exception('Falha ao enviar e-mail de recuperação: %s', exc)
                if should_expose_reset_link():
                    app.logger.warning(
                        'Usando link de recuperação de desenvolvimento para %s após falha no SMTP: %s',
                        user.email,
                        reset_link,
                    )
                else:
                    return json_error('Não foi possível enviar o e-mail. Tente novamente mais tarde.', 503)
        else:
            if should_expose_reset_link():
                app.logger.warning('SMTP não configurado; link de recuperação para %s: %s', user.email, reset_link)
            else:
                app.logger.warning('SMTP não configurado; e-mail de recuperação não enviado para %s', user.email)

    payload = {'ok': True, 'message': 'Se o e-mail estiver cadastrado, você receberá um link em breve.'}
    if user and should_expose_reset_link():
        payload['reset_link'] = reset_link
    return jsonify(payload)


# ---------------------------------------------------------------------------
# Esqueci minha senha — redefinir senha com token
# ---------------------------------------------------------------------------

@app.post('/reset-password')
def reset_password():
    payload = request.get_json(silent=True) or {}
    token_value = str(payload.get('token', '')).strip()
    nova_senha = str(payload.get('nova_senha', ''))

    if not token_value:
        return json_error('Token não informado.')
    if len(nova_senha) < 6:
        return json_error('A nova senha precisa ter pelo menos 6 caracteres.')

    with session_scope() as db:
        token = db.scalar(select(ResetToken).where(ResetToken.token == token_value))

        if not token:
            return json_error('Link inválido ou expirado.', 400)

        now = datetime.now(timezone.utc)

        # Garante timezone-aware para comparação
        expira_em = token.expira_em
        if expira_em.tzinfo is None:
            expira_em = expira_em.replace(tzinfo=timezone.utc)

        if token.usado:
            return json_error('Este link já foi utilizado. Solicite um novo.', 400)

        if now > expira_em:
            return json_error('Este link expirou. Solicite um novo.', 400)

        user = db.get(User, token.usuario_id)
        if not user:
            return json_error('Usuário não encontrado.', 404)

        user.senha_hash = generate_password_hash(nova_senha)
        token.usado = True

    return jsonify({'ok': True, 'message': 'Senha redefinida com sucesso.'})


# ---------------------------------------------------------------------------
# Verificar token (para o frontend checar se o link ainda é válido)
# ---------------------------------------------------------------------------

@app.get('/reset-password/check')
def check_reset_token():
    token_value = request.args.get('token', '').strip()
    if not token_value:
        return json_error('Token não informado.')

    with session_scope() as db:
        token = db.scalar(select(ResetToken).where(ResetToken.token == token_value))
        if not token:
            return json_error('Token inválido.', 400)

        now = datetime.now(timezone.utc)
        expira_em = token.expira_em
        if expira_em.tzinfo is None:
            expira_em = expira_em.replace(tzinfo=timezone.utc)

        if token.usado or now > expira_em:
            return json_error('Token expirado ou já utilizado.', 400)

        return jsonify({'ok': True, 'expira_em': expira_em.isoformat()})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=AUTH_PORT, debug=os.getenv('AUTH_DEBUG', '0') == '1')
