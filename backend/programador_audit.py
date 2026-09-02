from __future__ import annotations

from datetime import date, datetime, time, timezone
import json
from typing import Any
from zoneinfo import ZoneInfo


def audit_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_programador_audit_schema(conn) -> None:
    arquivos_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='arquivos_dxf'"
    ).fetchone()
    if arquivos_table:
        arquivo_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(arquivos_dxf)").fetchall()}
        if "criado_por_usuario_id" not in arquivo_columns:
            conn.execute("ALTER TABLE arquivos_dxf ADD COLUMN criado_por_usuario_id INTEGER")
        if "criado_por_nome_snapshot" not in arquivo_columns:
            conn.execute("ALTER TABLE arquivos_dxf ADD COLUMN criado_por_nome_snapshot TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS programador_auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            usuario_nome_snapshot TEXT NOT NULL,
            usuario_role_snapshot TEXT NOT NULL,
            acao TEXT NOT NULL,
            arquivo_id INTEGER,
            arquivo_nome_snapshot TEXT,
            entidade_tipo TEXT,
            entidade_id TEXT,
            cnc_origem TEXT,
            cnc_destino TEXT,
            valor_anterior TEXT,
            valor_novo TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_auditoria_data ON programador_auditoria(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_auditoria_usuario ON programador_auditoria(usuario_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_auditoria_arquivo ON programador_auditoria(arquivo_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_programador_auditoria_acao ON programador_auditoria(acao, created_at DESC)")
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS programador_auditoria_no_update
        BEFORE UPDATE ON programador_auditoria
        BEGIN
            SELECT RAISE(ABORT, 'programador_auditoria is append-only');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS programador_auditoria_no_delete
        BEFORE DELETE ON programador_auditoria
        BEGIN
            SELECT RAISE(ABORT, 'programador_auditoria is append-only');
        END
        """
    )


def _json_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def record_programador_audit(
    conn,
    user: dict,
    action: str,
    *,
    arquivo_id: int | None = None,
    arquivo_nome: str | None = None,
    entidade_tipo: str | None = "arquivo",
    entidade_id: str | int | None = None,
    cnc_origem: str | None = None,
    cnc_destino: str | None = None,
    valor_anterior: Any = None,
    valor_novo: Any = None,
    metadata: Any = None,
) -> int:
    ensure_programador_audit_schema(conn)
    cursor = conn.execute(
        """
        INSERT INTO programador_auditoria (
            usuario_id, usuario_nome_snapshot, usuario_role_snapshot, acao,
            arquivo_id, arquivo_nome_snapshot, entidade_tipo, entidade_id,
            cnc_origem, cnc_destino, valor_anterior, valor_novo, metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.get("id"),
            str(user.get("nome") or "Sistema / legado"),
            str(user.get("role") or "sistema"),
            str(action or "").upper(),
            arquivo_id,
            arquivo_nome,
            entidade_tipo,
            str(entidade_id) if entidade_id is not None else None,
            cnc_origem,
            cnc_destino,
            _json_value(valor_anterior),
            _json_value(valor_novo),
            _json_value(metadata),
            audit_utc_iso(),
        ),
    )
    return int(cursor.lastrowid)


def decode_audit_row(row) -> dict:
    item = dict(row)
    for field in ("valor_anterior", "valor_novo", "metadata"):
        raw = item.get(field)
        if raw is None:
            continue
        try:
            item[field] = json.loads(raw)
        except (TypeError, ValueError):
            pass
    return item


def _date_boundary(value: str | None, *, end: bool) -> str | None:
    if not value:
        return None
    parsed = date.fromisoformat(value)
    local = datetime.combine(parsed, time.max if end else time.min, tzinfo=ZoneInfo("America/Sao_Paulo"))
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def list_programador_audit(
    conn,
    *,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    usuario_id: int | None = None,
    acao: str | None = None,
    cnc: str | None = None,
    arquivo: str | None = None,
    remessa: str | None = None,
    arquivo_id: int | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    ensure_programador_audit_schema(conn)
    filters: list[str] = []
    params: list[Any] = []
    start = _date_boundary(data_inicio, end=False)
    finish = _date_boundary(data_fim, end=True)
    if start:
        filters.append("created_at >= ?")
        params.append(start)
    if finish:
        filters.append("created_at <= ?")
        params.append(finish)
    if usuario_id:
        filters.append("usuario_id = ?")
        params.append(int(usuario_id))
    if acao:
        filters.append("acao = ?")
        params.append(str(acao).strip().upper())
    if cnc:
        filters.append("(UPPER(COALESCE(cnc_origem, '')) = ? OR UPPER(COALESCE(cnc_destino, '')) = ?)")
        normalized_cnc = str(cnc).strip().upper()
        params.extend((normalized_cnc, normalized_cnc))
    if arquivo_id:
        filters.append("arquivo_id = ?")
        params.append(int(arquivo_id))
    if arquivo:
        filters.append("LOWER(COALESCE(arquivo_nome_snapshot, '')) LIKE ?")
        params.append(f"%{str(arquivo).strip().lower()}%")
    if remessa:
        filters.append("LOWER(COALESCE(metadata, '') || ' ' || COALESCE(valor_anterior, '') || ' ' || COALESCE(valor_novo, '')) LIKE ?")
        params.append(f"%{str(remessa).strip().lower()}%")

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(page_size or 50), 100))
    total = int(conn.execute(f"SELECT COUNT(*) FROM programador_auditoria {where}", tuple(params)).fetchone()[0])
    rows = conn.execute(
        f"""
        SELECT * FROM programador_auditoria
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [safe_size, (safe_page - 1) * safe_size]),
    ).fetchall()
    return {
        "items": [decode_audit_row(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_size,
        "pages": max(1, (total + safe_size - 1) // safe_size),
    }


def audit_filter_options(conn) -> dict:
    ensure_programador_audit_schema(conn)
    users = conn.execute(
        """
        SELECT a.usuario_id AS id, a.usuario_nome_snapshot AS nome
        FROM programador_auditoria a
        WHERE a.usuario_id IS NOT NULL
          AND a.id = (
              SELECT MAX(b.id)
              FROM programador_auditoria b
              WHERE b.usuario_id = a.usuario_id
          )
        ORDER BY a.usuario_nome_snapshot
        """
    ).fetchall()
    actions = conn.execute("SELECT DISTINCT acao FROM programador_auditoria ORDER BY acao").fetchall()
    return {
        "users": [dict(row) for row in users],
        "actions": [row["acao"] for row in actions],
    }
