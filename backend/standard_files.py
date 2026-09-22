from __future__ import annotations

from datetime import datetime


def ensure_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS arquivos_padrao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL COLLATE NOCASE UNIQUE,
            path TEXT NOT NULL,
            criado_em TEXT NOT NULL,
            criado_por_usuario_id INTEGER,
            criado_por_nome_snapshot TEXT,
            ativo INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_arquivos_padrao_ativo_nome ON arquivos_padrao(ativo, nome)")


def list_files(conn) -> list[dict]:
    ensure_schema(conn)
    return [dict(row) for row in conn.execute(
        """
        SELECT id, nome, criado_em, criado_por_nome_snapshot
        FROM arquivos_padrao
        WHERE ativo=1
        ORDER BY nome COLLATE NOCASE, id
        """
    )]


def insert_file(conn, name: str, path: str, actor: dict) -> int:
    ensure_schema(conn)
    cursor = conn.execute(
        """
        INSERT INTO arquivos_padrao(nome,path,criado_em,criado_por_usuario_id,criado_por_nome_snapshot)
        VALUES(?,?,?,?,?)
        """,
        (name, path, datetime.now().isoformat(timespec="seconds"), actor.get("id"), actor.get("nome")),
    )
    return int(cursor.lastrowid)


def delete_file(conn, file_id: int) -> bool:
    ensure_schema(conn)
    row = conn.execute("SELECT * FROM arquivos_padrao WHERE id=? AND ativo=1", (file_id,)).fetchone()
    if not row:
        return False
    now_tag = datetime.now().strftime("%Y%m%d%H%M%S_%f")
    conn.execute(
        "UPDATE arquivos_padrao SET ativo=0, nome=? WHERE id=?",
        (f"__excluido_{file_id}_{now_tag}__{row['nome']}", file_id),
    )
    return True
