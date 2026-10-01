from __future__ import annotations

from datetime import datetime, timezone

from backend.programador_audit import record_programador_audit


NIVEIS = (
    {"nivel": 0, "nome": "Não iniciado", "descricao": "Ainda não realizou esta operação."},
    {"nivel": 1, "nome": "Em treinamento", "descricao": "Realiza acompanhado e com conferência completa."},
    {"nivel": 2, "nome": "Com apoio", "descricao": "Realiza sozinho e consulta nos casos fora do padrão."},
    {"nivel": 3, "nome": "Autônomo", "descricao": "Realiza sozinho, inclusive nas exceções."},
    {"nivel": 4, "nome": "Referência", "descricao": "Ensina e resolve dúvidas da operação."},
)

COLABORADORES = (
    {"id": "matheus", "nome": "Matheus"},
    {"id": "paulo", "nome": "Paulo"},
    {"id": "dirley", "nome": "Dirley"},
    {"id": "lucas", "nome": "Lucas"},
    {"id": "bruno", "nome": "Bruno"},
    {"id": "aleixo", "nome": "Aleixo"},
)

OPERACOES = (
    {"id": "zig-zag", "nome": "Zig Zag"},
    {"id": "papelao-geral-cnc", "nome": "Papelão geral CNC"},
    {"id": "papelao-emma", "nome": "Papelão EMMA"},
    {"id": "montagem", "nome": "Montagem"},
    {"id": "calco-nucleo", "nome": "Calço de núcleo"},
    {"id": "anel-prensagem", "nome": "Anel de prensagem"},
    {"id": "anel-equipotencial", "nome": "Anel equipotencial"},
    {"id": "tijolinho", "nome": "Tijolinho"},
    {"id": "gabaritos", "nome": "Gabaritos"},
    {"id": "moldados-mini-angulo", "nome": "Moldados e mini angulo"},
    {"id": "suporte-cnc", "nome": "Suporte CNC"},
    {"id": "suporte-cf", "nome": "Suporte CF"},
)

_COLABORADORES = {item["id"]: item for item in COLABORADORES}
_OPERACOES = {item["id"]: item for item in OPERACOES}


class CompetenciaError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS programador_competencias (
            colaborador_id TEXT NOT NULL,
            operacao_id TEXT NOT NULL,
            nivel INTEGER NOT NULL CHECK(nivel BETWEEN 0 AND 4),
            atualizado_em TEXT NOT NULL,
            atualizado_por_usuario_id INTEGER,
            atualizado_por_nome TEXT NOT NULL,
            PRIMARY KEY (colaborador_id, operacao_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS programador_competencias_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            colaborador_id TEXT NOT NULL,
            operacao_id TEXT NOT NULL,
            nivel_anterior INTEGER,
            nivel_novo INTEGER NOT NULL CHECK(nivel_novo BETWEEN 0 AND 4),
            alterado_em TEXT NOT NULL,
            alterado_por_usuario_id INTEGER,
            alterado_por_nome TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_competencias_historico_data "
        "ON programador_competencias_historico(alterado_em DESC)"
    )


def _validate(colaborador_id: str, operacao_id: str, nivel: int) -> tuple[str, str, int]:
    person = str(colaborador_id or "").strip().lower()
    operation = str(operacao_id or "").strip().lower()
    if person not in _COLABORADORES:
        raise CompetenciaError("Colaborador inválido.")
    if operation not in _OPERACOES:
        raise CompetenciaError("Operação inválida.")
    if isinstance(nivel, bool) or not isinstance(nivel, int) or nivel < 0 or nivel > 4:
        raise CompetenciaError("O nível deve estar entre 0 e 4.")
    return person, operation, nivel


def get_matrix(conn) -> dict:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT * FROM programador_competencias ORDER BY colaborador_id, operacao_id"
    ).fetchall()
    assessments: dict[str, dict[str, dict]] = {person["id"]: {} for person in COLABORADORES}
    for raw in rows:
        row = dict(raw)
        if row["colaborador_id"] not in _COLABORADORES or row["operacao_id"] not in _OPERACOES:
            continue
        assessments[row["colaborador_id"]][row["operacao_id"]] = {
            "nivel": row["nivel"],
            "atualizadoEm": row["atualizado_em"],
            "atualizadoPor": row["atualizado_por_nome"],
        }
    return {
        "colaboradores": list(COLABORADORES),
        "operacoes": list(OPERACOES),
        "niveis": list(NIVEIS),
        "avaliacoes": assessments,
    }


def set_level(conn, colaborador_id: str, operacao_id: str, nivel: int, actor: dict) -> dict:
    person, operation, level = _validate(colaborador_id, operacao_id, nivel)
    ensure_schema(conn)
    previous_row = conn.execute(
        "SELECT nivel FROM programador_competencias WHERE colaborador_id = ? AND operacao_id = ?",
        (person, operation),
    ).fetchone()
    previous = previous_row["nivel"] if previous_row else None
    if previous == level:
        return get_matrix(conn)["avaliacoes"][person][operation]

    timestamp = _now()
    actor_name = str(actor.get("nome") or "Sistema")
    conn.execute(
        """
        INSERT INTO programador_competencias
            (colaborador_id, operacao_id, nivel, atualizado_em,
             atualizado_por_usuario_id, atualizado_por_nome)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(colaborador_id, operacao_id) DO UPDATE SET
            nivel = excluded.nivel,
            atualizado_em = excluded.atualizado_em,
            atualizado_por_usuario_id = excluded.atualizado_por_usuario_id,
            atualizado_por_nome = excluded.atualizado_por_nome
        """,
        (person, operation, level, timestamp, actor.get("id"), actor_name),
    )
    conn.execute(
        """
        INSERT INTO programador_competencias_historico
            (colaborador_id, operacao_id, nivel_anterior, nivel_novo, alterado_em,
             alterado_por_usuario_id, alterado_por_nome)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (person, operation, previous, level, timestamp, actor.get("id"), actor_name),
    )
    record_programador_audit(
        conn,
        actor,
        "COMPETENCIA_ATUALIZADA",
        entidade_tipo="competencia",
        entidade_id=f"{person}|{operation}",
        valor_anterior=previous,
        valor_novo=level,
        metadata={
            "colaborador": _COLABORADORES[person]["nome"],
            "operacao": _OPERACOES[operation]["nome"],
        },
    )
    return {"nivel": level, "atualizadoEm": timestamp, "atualizadoPor": actor_name}


def set_levels(conn, changes: list[dict], actor: dict) -> dict:
    if not isinstance(changes, list) or not changes:
        raise CompetenciaError("Informe ao menos uma competência para salvar.")
    if len(changes) > len(COLABORADORES) * len(OPERACOES):
        raise CompetenciaError("Quantidade de alterações inválida.")
    seen = set()
    validated = []
    for change in changes:
        person, operation, level = _validate(
            change.get("colaborador_id"), change.get("operacao_id"), change.get("nivel")
        )
        key = (person, operation)
        if key in seen:
            raise CompetenciaError("A mesma competência foi informada mais de uma vez.")
        seen.add(key)
        validated.append((person, operation, level))
    for person, operation, level in validated:
        set_level(conn, person, operation, level, actor)
    return get_matrix(conn)

