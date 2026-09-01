from __future__ import annotations

import sqlite3


PRIORITIES = {"normal", "medium", "high"}


class PlanClassificationError(ValueError):
    pass


def ensure_plan_classification_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(arquivos_dxf)")}
    if "priority" not in columns:
        conn.execute("ALTER TABLE arquivos_dxf ADD COLUMN priority TEXT NOT NULL DEFAULT 'normal'")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS arquivo_cnc_compatibilidade (
            arquivo_id INTEGER NOT NULL,
            cnc_id TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (arquivo_id, cnc_id),
            FOREIGN KEY (arquivo_id) REFERENCES arquivos_dxf(id),
            FOREIGN KEY (cnc_id) REFERENCES maquinas(id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_arquivo_cnc_compatibilidade_cnc "
        "ON arquivo_cnc_compatibilidade(cnc_id, arquivo_id)"
    )


def normalize_priority(value: str | None) -> str:
    priority = str(value or "normal").strip().lower()
    if priority not in PRIORITIES:
        raise PlanClassificationError("Prioridade inválida. Use normal, medium ou high.")
    return priority


def production_cnc_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row["id"]).strip().upper()
        for row in conn.execute("SELECT id FROM maquinas WHERE id GLOB 'CNC[0-9]*'")
    }


def validate_compatible_cnc_ids(conn: sqlite3.Connection, values) -> list[str]:
    ids = list(dict.fromkeys(str(value or "").strip().upper() for value in (values or []) if str(value or "").strip()))
    if not ids:
        raise PlanClassificationError("Selecione pelo menos um CNC compatível para este plano.")
    invalid = [cnc_id for cnc_id in ids if cnc_id not in production_cnc_ids(conn)]
    if invalid:
        raise PlanClassificationError(f"CNC compatível inválida: {', '.join(invalid)}.")
    return ids


def set_plan_classification(conn: sqlite3.Connection, arquivo_id: int, priority, compatible_cnc_ids) -> dict:
    ensure_plan_classification_schema(conn)
    plan = conn.execute("SELECT id FROM arquivos_dxf WHERE id = ?", (arquivo_id,)).fetchone()
    if not plan:
        raise PlanClassificationError("Plano não encontrado.")
    normalized_priority = normalize_priority(priority)
    cnc_ids = validate_compatible_cnc_ids(conn, compatible_cnc_ids)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fila_itens'").fetchone():
        active_cncs = [row["maquina_id"] for row in conn.execute("""
            SELECT DISTINCT maquina_id FROM fila_itens
            WHERE arquivo_id = ? AND status IN ('AGUARDANDO','PROGRAMANDO','EM_EXECUCAO','BAIXADO')
        """, (arquivo_id,))]
        missing_active = [cnc_id for cnc_id in active_cncs if cnc_id not in cnc_ids]
        if missing_active:
            raise PlanClassificationError(
                f"Mantenha a CNC ativa na compatibilidade: {', '.join(missing_active)}."
            )
    conn.execute("UPDATE arquivos_dxf SET priority = ? WHERE id = ?", (normalized_priority, arquivo_id))
    conn.execute("DELETE FROM arquivo_cnc_compatibilidade WHERE arquivo_id = ?", (arquivo_id,))
    conn.executemany(
        "INSERT INTO arquivo_cnc_compatibilidade (arquivo_id, cnc_id) VALUES (?, ?)",
        [(arquivo_id, cnc_id) for cnc_id in cnc_ids],
    )
    return {"arquivo_id": arquivo_id, "priority": normalized_priority, "compatible_cnc_ids": cnc_ids}


def classifications_by_plan(conn: sqlite3.Connection, arquivo_ids) -> dict[int, list[dict]]:
    ids = [int(value) for value in arquivo_ids]
    if not ids:
        return {}
    ensure_plan_classification_schema(conn)
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"""
        SELECT c.arquivo_id, c.cnc_id, m.nome AS cnc_nome
        FROM arquivo_cnc_compatibilidade c
        JOIN maquinas m ON m.id = c.cnc_id
        WHERE c.arquivo_id IN ({placeholders})
        ORDER BY c.arquivo_id, c.cnc_id
    """, ids).fetchall()
    result: dict[int, list[dict]] = {arquivo_id: [] for arquivo_id in ids}
    for row in rows:
        result[int(row["arquivo_id"])].append({"id": row["cnc_id"], "nome": row["cnc_nome"]})
    return result


def plan_is_compatible_with(conn: sqlite3.Connection, arquivo_id: int, cnc_id: str) -> bool:
    ensure_plan_classification_schema(conn)
    count = conn.execute(
        "SELECT COUNT(*) AS total FROM arquivo_cnc_compatibilidade WHERE arquivo_id = ?", (arquivo_id,)
    ).fetchone()["total"]
    if not count:  # Legacy plans imported before classification remain unrestricted.
        return True
    return conn.execute(
        "SELECT 1 FROM arquivo_cnc_compatibilidade WHERE arquivo_id = ? AND cnc_id = ?",
        (arquivo_id, str(cnc_id or "").strip().upper()),
    ).fetchone() is not None
