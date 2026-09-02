from __future__ import annotations

import json
from typing import Any

from backend.programador_auth import (
    create_or_update_user,
    ensure_programador_auth_schema,
    hash_password,
    revoke_user_sessions,
    user_payload,
    utc_iso,
)


MANAGED_ROLES = {"programador", "lider"}


def ensure_programador_admin_schema(conn) -> None:
    ensure_programador_auth_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS programador_admin_auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acao TEXT NOT NULL,
            dev_id INTEGER NOT NULL,
            dev_nome_snapshot TEXT NOT NULL,
            dev_login_snapshot TEXT NOT NULL,
            usuario_id INTEGER NOT NULL,
            usuario_nome_snapshot TEXT NOT NULL,
            usuario_login_snapshot TEXT NOT NULL,
            valores_anteriores TEXT,
            valores_novos TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_admin_audit_usuario ON programador_admin_auditoria(usuario_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_admin_audit_data ON programador_admin_auditoria(created_at DESC)")
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_programador_admin_audit_no_update
        BEFORE UPDATE ON programador_admin_auditoria
        BEGIN SELECT RAISE(ABORT, 'A auditoria administrativa é imutável'); END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_programador_admin_audit_no_delete
        BEFORE DELETE ON programador_admin_auditoria
        BEGIN SELECT RAISE(ABORT, 'A auditoria administrativa é imutável'); END
        """
    )


def _managed_user(conn, usuario_id: int):
    row = conn.execute(
        """
        SELECT id, nome, login, role, ativo, must_change_password,
               password_changed_at, last_login_at, created_by, criado_em, updated_at
        FROM usuarios WHERE id = ? AND role IN ('programador', 'lider')
        """,
        (usuario_id,),
    ).fetchone()
    if not row:
        raise LookupError("Usuário da Programação não encontrado.")
    return row


def _snapshot(row: Any) -> dict:
    return {
        "nome": row["nome"], "login": row["login"], "role": row["role"],
        "ativo": bool(row["ativo"]), "must_change_password": bool(row["must_change_password"]),
    }


def _audit(conn, *, acao: str, dev: dict, target: Any, before: dict | None = None, after: dict | None = None) -> None:
    # Senhas e hashes nunca entram nos snapshots administrativos.
    conn.execute(
        """
        INSERT INTO programador_admin_auditoria
            (acao, dev_id, dev_nome_snapshot, dev_login_snapshot, usuario_id,
             usuario_nome_snapshot, usuario_login_snapshot, valores_anteriores,
             valores_novos, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            acao, dev["id"], dev["nome"], dev["login"], target["id"], target["nome"], target["login"],
            json.dumps(before, ensure_ascii=False, sort_keys=True) if before is not None else None,
            json.dumps(after, ensure_ascii=False, sort_keys=True) if after is not None else None,
            utc_iso(),
        ),
    )


def serialize_admin_user(row: Any) -> dict:
    item = user_payload(row)
    item.update({
        "created_by": row["created_by"],
        "criado_em": row["criado_em"],
        "updated_at": row["updated_at"],
        "first_access_status": "pendente" if bool(row["must_change_password"]) else "concluido",
    })
    return item


def list_users(conn, *, search: str = "", role: str | None = None, status: str | None = None) -> dict:
    ensure_programador_admin_schema(conn)
    clauses = ["role IN ('programador', 'lider')"]
    params: list[Any] = []
    term = str(search or "").strip().lower()
    if term:
        clauses.append("(LOWER(nome) LIKE ? OR LOWER(login) LIKE ?)")
        params.extend([f"%{term}%", f"%{term}%"])
    if role:
        if role not in MANAGED_ROLES:
            raise ValueError("Filtro de perfil inválido.")
        clauses.append("role = ?")
        params.append(role)
    if status:
        status_clauses = {
            "ativo": "ativo = 1", "inativo": "ativo = 0",
            "primeiro_acesso": "must_change_password = 1",
        }
        if status not in status_clauses:
            raise ValueError("Filtro de situação inválido.")
        clauses.append(status_clauses[status])
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""SELECT id, nome, login, role, ativo, must_change_password, password_changed_at,
                    last_login_at, created_by, criado_em, updated_at
             FROM usuarios WHERE {where} ORDER BY nome COLLATE NOCASE, id""",
        params,
    ).fetchall()
    summary = conn.execute(
        """SELECT COUNT(*) total, SUM(CASE WHEN role = 'programador' THEN 1 ELSE 0 END) programadores,
                  SUM(CASE WHEN role = 'lider' THEN 1 ELSE 0 END) lideres,
                  SUM(CASE WHEN must_change_password = 1 THEN 1 ELSE 0 END) primeiro_acesso
           FROM usuarios WHERE role IN ('programador', 'lider')"""
    ).fetchone()
    return {
        "items": [serialize_admin_user(row) for row in rows],
        "summary": {key: int(summary[key] or 0) for key in ("total", "programadores", "lideres", "primeiro_acesso")},
    }


def create_user(conn, *, dev: dict, nome: str, login: str, password: str, role: str) -> dict:
    ensure_programador_admin_schema(conn)
    if role not in MANAGED_ROLES:
        raise ValueError("A tela DEV permite criar somente Programador ou Líder.")
    if conn.execute("SELECT 1 FROM usuarios WHERE LOWER(login) = LOWER(?)", (login.strip(),)).fetchone():
        raise ValueError("Este login já está em uso.")
    created = create_or_update_user(
        conn, nome=nome, login=login, password=password, role=role,
        must_change_password=True, created_by=dev["id"],
    )
    target = _managed_user(conn, created["id"])
    _audit(conn, acao="USUARIO_CRIADO", dev=dev, target=target, after=_snapshot(target))
    return serialize_admin_user(target)


def update_user(conn, *, dev: dict, usuario_id: int, nome: str, login: str, role: str) -> dict:
    ensure_programador_admin_schema(conn)
    if role not in MANAGED_ROLES:
        raise ValueError("O perfil deve ser Programador ou Líder.")
    nome_value, login_value = str(nome or "").strip(), str(login or "").strip().lower()
    if not nome_value or not login_value:
        raise ValueError("Nome e login são obrigatórios.")
    target = _managed_user(conn, usuario_id)
    before = _snapshot(target)
    duplicate = conn.execute("SELECT id FROM usuarios WHERE LOWER(login) = ? AND id <> ?", (login_value, usuario_id)).fetchone()
    if duplicate:
        raise ValueError("Este login já está em uso.")
    conn.execute(
        "UPDATE usuarios SET nome = ?, login = ?, nivel = ?, role = ?, updated_at = ? WHERE id = ?",
        (nome_value, login_value, role.upper(), role, utc_iso(), usuario_id),
    )
    updated = _managed_user(conn, usuario_id)
    action = "PERFIL_ALTERADO" if before["role"] != role else "USUARIO_EDITADO"
    _audit(conn, acao=action, dev=dev, target=updated, before=before, after=_snapshot(updated))
    return serialize_admin_user(updated)


def set_user_active(conn, *, dev: dict, usuario_id: int, active: bool) -> dict:
    ensure_programador_admin_schema(conn)
    target = _managed_user(conn, usuario_id)
    before = _snapshot(target)
    conn.execute("UPDATE usuarios SET ativo = ?, updated_at = ? WHERE id = ?", (int(active), utc_iso(), usuario_id))
    if not active:
        revoke_user_sessions(conn, usuario_id)
    updated = _managed_user(conn, usuario_id)
    _audit(conn, acao="USUARIO_ATIVADO" if active else "USUARIO_DESATIVADO", dev=dev, target=updated, before=before, after=_snapshot(updated))
    return serialize_admin_user(updated)


def reset_user_password(conn, *, dev: dict, usuario_id: int, temporary_password: str) -> dict:
    ensure_programador_admin_schema(conn)
    target = _managed_user(conn, usuario_id)
    before = _snapshot(target)
    password_hash = hash_password(temporary_password)
    conn.execute(
        """UPDATE usuarios SET senha = '', senha_hash = ?, must_change_password = 1,
                  password_changed_at = NULL, updated_at = ? WHERE id = ?""",
        (password_hash, utc_iso(), usuario_id),
    )
    revoke_user_sessions(conn, usuario_id)
    updated = _managed_user(conn, usuario_id)
    _audit(conn, acao="SENHA_REDEFINIDA", dev=dev, target=updated, before=before, after=_snapshot(updated))
    return serialize_admin_user(updated)


def list_admin_audit(conn, *, limit: int = 100) -> list[dict]:
    ensure_programador_admin_schema(conn)
    rows = conn.execute(
        "SELECT * FROM programador_admin_auditoria ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
    ).fetchall()
    return [dict(row) for row in rows]
