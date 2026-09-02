from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
from typing import Any

from backend.db import get_conn


PROGRAMADOR_ROLES = {"programador", "lider"}
AUTH_ROLES = PROGRAMADOR_ROLES | {"dev"}
SESSION_COOKIE_NAME = "cnc_programador_session"
SESSION_HOURS = max(1, int(os.environ.get("CNC_PROGRAMADOR_SESSION_HOURS", "12")))
PASSWORD_N = 2**14
PASSWORD_R = 8
PASSWORD_P = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


def normalize_role(value: str | None) -> str:
    role = str(value or "").strip().lower()
    if role not in AUTH_ROLES:
        raise ValueError("Perfil inválido. Use programador, lider ou dev.")
    return role


def _encode_password(raw: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(raw.encode("utf-8"), salt=salt, n=PASSWORD_N, r=PASSWORD_R, p=PASSWORD_P, dklen=32)
    return f"scrypt${PASSWORD_N}${PASSWORD_R}${PASSWORD_P}${salt.hex()}${derived.hex()}"


def hash_password(password: str) -> str:
    raw = str(password or "")
    if len(raw) < 8:
        raise ValueError("A senha deve possuir pelo menos 8 caracteres.")
    if not re.search(r"[A-Za-zÀ-ÿ]", raw) or not re.search(r"\d", raw):
        raise ValueError("A senha deve conter letras e números.")
    return _encode_password(raw)


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        algorithm, n, r, p, salt_hex, expected_hex = str(encoded or "").split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            str(password or "").encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(expected_hex)),
        )
        return hmac.compare_digest(actual, bytes.fromhex(expected_hex))
    except (TypeError, ValueError):
        return False


def _column_names(conn, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_programador_auth_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            login TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL DEFAULT '',
            nivel TEXT NOT NULL DEFAULT 'OPERADOR',
            maquina_id TEXT,
            criado_em TEXT NOT NULL
        )
        """
    )
    columns = _column_names(conn, "usuarios")
    additions = {
        "senha_hash": "ALTER TABLE usuarios ADD COLUMN senha_hash TEXT",
        "role": "ALTER TABLE usuarios ADD COLUMN role TEXT",
        "ativo": "ALTER TABLE usuarios ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1",
        "updated_at": "ALTER TABLE usuarios ADD COLUMN updated_at TEXT",
        "must_change_password": "ALTER TABLE usuarios ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0",
        "password_changed_at": "ALTER TABLE usuarios ADD COLUMN password_changed_at TEXT",
        "last_login_at": "ALTER TABLE usuarios ADD COLUMN last_login_at TEXT",
        "created_by": "ALTER TABLE usuarios ADD COLUMN created_by INTEGER",
    }
    for column, ddl in additions.items():
        if column not in columns:
            conn.execute(ddl)

    # Remove senhas legadas em texto puro. O campo `senha` é mantido vazio somente
    # por compatibilidade estrutural com instalações antigas.
    legacy_rows = conn.execute(
        "SELECT id, senha FROM usuarios WHERE COALESCE(senha_hash, '') = '' AND COALESCE(senha, '') <> ''"
    ).fetchall()
    for row in legacy_rows:
        password_hash = _encode_password(str(row["senha"]))
        conn.execute(
            "UPDATE usuarios SET senha_hash = ?, senha = '', updated_at = ? WHERE id = ?",
            (password_hash, utc_iso(), row["id"]),
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS programador_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_sessions_usuario ON programador_sessions(usuario_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_sessions_expira ON programador_sessions(expires_at)")


def user_payload(row: Any) -> dict:
    return {
        "id": int(row["id"]),
        "nome": row["nome"],
        "login": row["login"],
        "role": str(row["role"] or "").lower(),
        "ativo": bool(row["ativo"]),
        "must_change_password": bool(row["must_change_password"]),
        "password_changed_at": row["password_changed_at"],
        "last_login_at": row["last_login_at"],
    }


def authenticate_programador(conn, login: str, password: str) -> dict | None:
    ensure_programador_auth_schema(conn)
    normalized_login = str(login or "").strip().lower()
    row = conn.execute(
        """
        SELECT id, nome, login, senha_hash, role, ativo,
               must_change_password, password_changed_at, last_login_at
        FROM usuarios
        WHERE LOWER(login) = ?
        LIMIT 1
        """,
        (normalized_login,),
    ).fetchone()
    if not row or not bool(row["ativo"]):
        return None
    if str(row["role"] or "").lower() not in AUTH_ROLES:
        return None
    if not verify_password(password, row["senha_hash"]):
        return None
    return user_payload(row)


def create_session(conn, usuario_id: int) -> tuple[str, str]:
    ensure_programador_auth_schema(conn)
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = utc_now()
    expires_at = now + timedelta(hours=SESSION_HOURS)
    conn.execute(
        """
        INSERT INTO programador_sessions
            (usuario_id, token_hash, created_at, expires_at, last_seen_at, revoked_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (usuario_id, token_hash, utc_iso(now), utc_iso(expires_at), utc_iso(now)),
    )
    return token, utc_iso(expires_at)


def revoke_session(conn, token: str | None) -> None:
    if not token:
        return
    ensure_programador_auth_schema(conn)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn.execute(
        "UPDATE programador_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
        (utc_iso(), token_hash),
    )


def resolve_session(conn, token: str | None) -> dict | None:
    if not token:
        return None
    ensure_programador_auth_schema(conn)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = conn.execute(
        """
        SELECT u.id, u.nome, u.login, u.role, u.ativo,
               u.must_change_password, u.password_changed_at, u.last_login_at,
               s.id AS session_id, s.expires_at, s.last_seen_at
        FROM programador_sessions s
        JOIN usuarios u ON u.id = s.usuario_id
        WHERE s.token_hash = ? AND s.revoked_at IS NULL
        LIMIT 1
        """,
        (token_hash,),
    ).fetchone()
    if not row or not bool(row["ativo"]):
        return None
    if str(row["role"] or "").lower() not in AUTH_ROLES:
        return None
    try:
        expires_at = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if expires_at <= utc_now():
        conn.execute("UPDATE programador_sessions SET revoked_at = ? WHERE id = ?", (utc_iso(), row["session_id"]))
        conn.commit()
        return None
    conn.execute("UPDATE programador_sessions SET last_seen_at = ? WHERE id = ?", (utc_iso(), row["session_id"]))
    conn.commit()
    return user_payload(row)


def session_user_from_request(request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    conn = get_conn()
    try:
        return resolve_session(conn, token)
    finally:
        conn.close()


def revoke_user_sessions(conn, usuario_id: int, *, except_token: str | None = None) -> None:
    ensure_programador_auth_schema(conn)
    params: list[Any] = [utc_iso(), usuario_id]
    sql = "UPDATE programador_sessions SET revoked_at = ? WHERE usuario_id = ? AND revoked_at IS NULL"
    if except_token:
        sql += " AND token_hash <> ?"
        params.append(hashlib.sha256(except_token.encode("utf-8")).hexdigest())
    conn.execute(sql, params)


def mark_last_login(conn, usuario_id: int) -> str:
    value = utc_iso()
    conn.execute("UPDATE usuarios SET last_login_at = ? WHERE id = ?", (value, usuario_id))
    return value


def complete_first_access(conn, *, usuario_id: int, new_password: str, current_token: str | None) -> dict:
    ensure_programador_auth_schema(conn)
    row = conn.execute(
        "SELECT id, senha_hash, must_change_password FROM usuarios WHERE id = ? AND ativo = 1",
        (usuario_id,),
    ).fetchone()
    if not row or not bool(row["must_change_password"]):
        raise ValueError("A troca de senha não está pendente para este usuário.")
    if verify_password(new_password, row["senha_hash"]):
        raise ValueError("A nova senha não pode ser igual à senha temporária.")
    password_hash = hash_password(new_password)
    now = utc_iso()
    conn.execute(
        "UPDATE usuarios SET senha_hash = ?, must_change_password = 0, password_changed_at = ?, updated_at = ? WHERE id = ?",
        (password_hash, now, now, usuario_id),
    )
    revoke_user_sessions(conn, usuario_id, except_token=current_token)
    updated = conn.execute(
        "SELECT id, nome, login, role, ativo, must_change_password, password_changed_at, last_login_at FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()
    return user_payload(updated)


def create_or_update_user(
    conn, *, nome: str, login: str, password: str, role: str, ativo: bool = True,
    must_change_password: bool = False, created_by: int | None = None,
) -> dict:
    ensure_programador_auth_schema(conn)
    role_value = normalize_role(role)
    nome_value = str(nome or "").strip()
    login_value = str(login or "").strip().lower()
    if not nome_value or not login_value:
        raise ValueError("Nome e login são obrigatórios.")
    password_hash = hash_password(password)
    now = utc_iso()
    existing = conn.execute("SELECT id, role FROM usuarios WHERE LOWER(login) = ?", (login_value,)).fetchone()
    if existing:
        if str(existing["role"] or "").lower() not in AUTH_ROLES:
            raise ValueError("Este login já pertence a um usuário de outro módulo.")
        conn.execute(
            """
            UPDATE usuarios
            SET nome = ?, senha = '', senha_hash = ?, nivel = ?, role = ?, ativo = ?,
                must_change_password = ?, password_changed_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (nome_value, password_hash, role_value.upper(), role_value, int(ativo), int(must_change_password), now, existing["id"]),
        )
        user_id = existing["id"]
    else:
        cursor = conn.execute(
            """
            INSERT INTO usuarios
                (nome, login, senha, senha_hash, nivel, role, ativo, maquina_id, criado_em, updated_at,
                 must_change_password, password_changed_at, last_login_at, created_by)
            VALUES (?, ?, '', ?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL, ?)
            """,
            (nome_value, login_value, password_hash, role_value.upper(), role_value, int(ativo), now, now,
             int(must_change_password), created_by),
        )
        user_id = cursor.lastrowid
    row = conn.execute(
        "SELECT id, nome, login, role, ativo, must_change_password, password_changed_at, last_login_at FROM usuarios WHERE id = ?",
        (user_id,),
    ).fetchone()
    return user_payload(row)
