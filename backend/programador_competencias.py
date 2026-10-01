from __future__ import annotations

from datetime import datetime, timezone
import unicodedata

from backend.programador_audit import record_programador_audit


NIVEIS = (
    {"nivel": 0, "nome": "Não iniciado", "descricao": "Ainda não realizou esta operação."},
    {"nivel": 1, "nome": "Em treinamento", "descricao": "Realiza acompanhado e com conferência completa."},
    {"nivel": 2, "nome": "Com apoio", "descricao": "Realiza sozinho e consulta nos casos fora do padrão."},
    {"nivel": 3, "nome": "Autônomo", "descricao": "Realiza sozinho, inclusive nas exceções."},
    {"nivel": 4, "nome": "Referência", "descricao": "Ensina e resolve dúvidas da operação."},
)

COLABORADORES = (
    {"id": "matheus", "nome": "Matheus"}, {"id": "paulo", "nome": "Paulo"},
    {"id": "dirley", "nome": "Dirley"}, {"id": "lucas", "nome": "Lucas"},
    {"id": "bruno", "nome": "Bruno"}, {"id": "aleixo", "nome": "Aleixo"},
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


def _normalized(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", str(value or "").strip().lower())
                   if unicodedata.category(char) != "Mn")


def resolve_colaborador(actor: dict) -> dict | None:
    login = _normalized(actor.get("login"))
    first_name = _normalized(actor.get("nome")).split(" ", 1)[0]
    matches = [person for person in COLABORADORES if person["id"] in {login, first_name}]
    return matches[0] if len(matches) == 1 else None


def ensure_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS programador_competencias (
            colaborador_id TEXT NOT NULL, operacao_id TEXT NOT NULL,
            nivel INTEGER NOT NULL CHECK(nivel BETWEEN 0 AND 4), atualizado_em TEXT NOT NULL,
            atualizado_por_usuario_id INTEGER, atualizado_por_nome TEXT NOT NULL,
            autoavaliacao_nivel INTEGER CHECK(autoavaliacao_nivel BETWEEN 0 AND 4),
            autoavaliado_em TEXT, autoavaliado_por_usuario_id INTEGER,
            nivel_validado INTEGER CHECK(nivel_validado BETWEEN 0 AND 4),
            status_validacao TEXT NOT NULL DEFAULT 'PENDENTE', revisado_em TEXT,
            revisado_por_usuario_id INTEGER, revisado_por_nome TEXT,
            PRIMARY KEY (colaborador_id, operacao_id)
        )
    """)
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(programador_competencias)")}
    migrations = {
        "autoavaliacao_nivel": "INTEGER CHECK(autoavaliacao_nivel BETWEEN 0 AND 4)",
        "autoavaliado_em": "TEXT", "autoavaliado_por_usuario_id": "INTEGER",
        "nivel_validado": "INTEGER CHECK(nivel_validado BETWEEN 0 AND 4)",
        "status_validacao": "TEXT NOT NULL DEFAULT 'PENDENTE'", "revisado_em": "TEXT",
        "revisado_por_usuario_id": "INTEGER", "revisado_por_nome": "TEXT",
    }
    for name, definition in migrations.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE programador_competencias ADD COLUMN {name} {definition}")
    conn.execute("""
        UPDATE programador_competencias
        SET autoavaliacao_nivel = COALESCE(autoavaliacao_nivel, nivel),
            autoavaliado_em = COALESCE(autoavaliado_em, atualizado_em),
            autoavaliado_por_usuario_id = COALESCE(autoavaliado_por_usuario_id, atualizado_por_usuario_id),
            status_validacao = COALESCE(status_validacao, 'PENDENTE')
        WHERE autoavaliacao_nivel IS NULL
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS programador_competencias_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT, colaborador_id TEXT NOT NULL,
            operacao_id TEXT NOT NULL, nivel_anterior INTEGER,
            nivel_novo INTEGER NOT NULL CHECK(nivel_novo BETWEEN 0 AND 4),
            alterado_em TEXT NOT NULL, alterado_por_usuario_id INTEGER,
            alterado_por_nome TEXT NOT NULL, evento TEXT NOT NULL DEFAULT 'AUTOAVALIACAO'
        )
    """)
    history_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(programador_competencias_historico)")}
    if "evento" not in history_columns:
        conn.execute("ALTER TABLE programador_competencias_historico ADD COLUMN evento TEXT NOT NULL DEFAULT 'AUTOAVALIACAO'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_competencias_historico_data ON programador_competencias_historico(alterado_em DESC)")


def _validate(operacao_id: str, nivel: int) -> tuple[str, int]:
    operation = str(operacao_id or "").strip().lower()
    if operation not in _OPERACOES:
        raise CompetenciaError("Operação inválida.")
    if isinstance(nivel, bool) or not isinstance(nivel, int) or not 0 <= nivel <= 4:
        raise CompetenciaError("O nível deve estar entre 0 e 4.")
    return operation, nivel


def _assessment(row) -> dict:
    return {
        "autoavaliacaoNivel": row["autoavaliacao_nivel"], "nivelValidado": row["nivel_validado"],
        "status": row["status_validacao"], "autoavaliadoEm": row["autoavaliado_em"],
        "revisadoEm": row["revisado_em"], "revisadoPor": row["revisado_por_nome"],
    }


def get_matrix(conn, actor: dict) -> dict:
    ensure_schema(conn)
    can_review = str(actor.get("role") or "").lower() == "lider"
    current_person = resolve_colaborador(actor)
    visible_ids = set(_COLABORADORES) if can_review else ({current_person["id"]} if current_person else set())
    assessments = {person_id: {} for person_id in visible_ids}
    for row in conn.execute("SELECT * FROM programador_competencias ORDER BY colaborador_id, operacao_id"):
        if row["colaborador_id"] in visible_ids and row["operacao_id"] in _OPERACOES:
            assessments[row["colaborador_id"]][row["operacao_id"]] = _assessment(row)
    return {
        "colaboradores": list(COLABORADORES) if can_review else ([current_person] if current_person else []),
        "colaboradorAtual": current_person, "operacoes": list(OPERACOES), "niveis": list(NIVEIS),
        "avaliacoes": assessments, "podeRevisar": can_review,
    }


def _validate_self_changes(changes: list[dict]) -> list[tuple[str, int]]:
    if not isinstance(changes, list) or not changes:
        raise CompetenciaError("Informe ao menos uma competência para salvar.")
    if len(changes) > len(OPERACOES):
        raise CompetenciaError("Quantidade de alterações inválida.")
    validated = [_validate(change.get("operacao_id"), change.get("nivel")) for change in changes]
    if len({operation for operation, _level in validated}) != len(validated):
        raise CompetenciaError("A mesma competência foi informada mais de uma vez.")
    return validated


def _history(conn, person, operation, previous, level, actor, event, timestamp):
    conn.execute("""
        INSERT INTO programador_competencias_historico
            (colaborador_id, operacao_id, nivel_anterior, nivel_novo, alterado_em,
             alterado_por_usuario_id, alterado_por_nome, evento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (person, operation, previous, level, timestamp, actor.get("id"),
          str(actor.get("nome") or "Sistema"), event))


def set_self_levels(conn, changes: list[dict], actor: dict) -> dict:
    person = resolve_colaborador(actor)
    if not person:
        raise CompetenciaError("Seu usuário não está vinculado a uma pessoa da matriz.")
    ensure_schema(conn)
    actor_name = str(actor.get("nome") or person["nome"])
    for operation, level in _validate_self_changes(changes):
        previous_row = conn.execute(
            "SELECT autoavaliacao_nivel FROM programador_competencias WHERE colaborador_id=? AND operacao_id=?",
            (person["id"], operation)).fetchone()
        previous = previous_row["autoavaliacao_nivel"] if previous_row else None
        if previous == level:
            continue
        timestamp = _now()
        conn.execute("""
            INSERT INTO programador_competencias
                (colaborador_id, operacao_id, nivel, atualizado_em, atualizado_por_usuario_id,
                 atualizado_por_nome, autoavaliacao_nivel, autoavaliado_em,
                 autoavaliado_por_usuario_id, status_validacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDENTE')
            ON CONFLICT(colaborador_id, operacao_id) DO UPDATE SET
                nivel=excluded.nivel, atualizado_em=excluded.atualizado_em,
                atualizado_por_usuario_id=excluded.atualizado_por_usuario_id,
                atualizado_por_nome=excluded.atualizado_por_nome,
                autoavaliacao_nivel=excluded.autoavaliacao_nivel,
                autoavaliado_em=excluded.autoavaliado_em,
                autoavaliado_por_usuario_id=excluded.autoavaliado_por_usuario_id,
                status_validacao='PENDENTE'
        """, (person["id"], operation, level, timestamp, actor.get("id"), actor_name,
              level, timestamp, actor.get("id")))
        _history(conn, person["id"], operation, previous, level, actor, "AUTOAVALIACAO", timestamp)
        record_programador_audit(
            conn, actor, "COMPETENCIA_AUTOAVALIADA", entidade_tipo="competencia",
            entidade_id=f"{person['id']}|{operation}", valor_anterior=previous, valor_novo=level,
            metadata={"colaborador": person["nome"], "operacao": _OPERACOES[operation]["nome"]})
    return get_matrix(conn, actor)


def review_levels(conn, changes: list[dict], actor: dict) -> dict:
    if str(actor.get("role") or "").lower() != "lider":
        raise CompetenciaError("Somente o líder pode validar competências.")
    if not isinstance(changes, list) or not changes:
        raise CompetenciaError("Informe ao menos uma competência para validar.")
    if len(changes) > len(COLABORADORES) * len(OPERACOES):
        raise CompetenciaError("Quantidade de validações inválida.")
    seen, validated = set(), []
    for change in changes:
        person = str(change.get("colaborador_id") or "").strip().lower()
        operation, level = _validate(change.get("operacao_id"), change.get("nivel"))
        if person not in _COLABORADORES:
            raise CompetenciaError("Colaborador inválido.")
        if (person, operation) in seen:
            raise CompetenciaError("A mesma competência foi informada mais de uma vez.")
        seen.add((person, operation)); validated.append((person, operation, level))
    ensure_schema(conn)
    for person, operation, level in validated:
        row = conn.execute("SELECT * FROM programador_competencias WHERE colaborador_id=? AND operacao_id=?",
                           (person, operation)).fetchone()
        if not row or row["autoavaliacao_nivel"] is None:
            raise CompetenciaError(f"{_COLABORADORES[person]['nome']} ainda não avaliou esta operação.")
        previous, timestamp = row["nivel_validado"], _now()
        conn.execute("""
            UPDATE programador_competencias SET nivel_validado=?, status_validacao='VALIDADO',
                revisado_em=?, revisado_por_usuario_id=?, revisado_por_nome=?
            WHERE colaborador_id=? AND operacao_id=?
        """, (level, timestamp, actor.get("id"), str(actor.get("nome") or "Líder"), person, operation))
        _history(conn, person, operation, previous, level, actor, "VALIDACAO_LIDER", timestamp)
        record_programador_audit(
            conn, actor, "COMPETENCIA_VALIDADA", entidade_tipo="competencia",
            entidade_id=f"{person}|{operation}", valor_anterior=previous, valor_novo=level,
            metadata={"colaborador": _COLABORADORES[person]["nome"],
                      "operacao": _OPERACOES[operation]["nome"], "autoavaliacao": row["autoavaliacao_nivel"]})
    return get_matrix(conn, actor)
