from datetime import datetime
from backend.db import get_conn

def main():
    conn = get_conn()
    cur = conn.cursor()

    # =========================
    # TABELA MAQUINAS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS maquinas (
        id TEXT PRIMARY KEY,
        nome TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PARADA',
        status_desde TEXT,
        arquivo_pendente_id INTEGER
    )
    """)

    # =========================
    # TABELA ARQUIVOS DXF
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS arquivos_dxf (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        path TEXT NOT NULL,
        criado_em TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'DISPONIVEL',
        deleted_em TEXT
    )
    """)

    # =========================
    # TABELA FILA_ITENS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fila_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maquina_id TEXT NOT NULL,
        arquivo_id INTEGER NOT NULL,
        posicao INTEGER NOT NULL,
        status TEXT NOT NULL,
        criado_em TEXT NOT NULL,
        started_em TEXT,
        finalizado_em TEXT,
        tempo_estimado_seg INTEGER,
        tempo_inicio_em TEXT,
        tempo_pausado_seg INTEGER DEFAULT 0,
        tempo_pausa_inicio_em TEXT,
        FOREIGN KEY(maquina_id) REFERENCES maquinas(id),
        FOREIGN KEY(arquivo_id) REFERENCES arquivos_dxf(id)
    )
    """)

    # =========================
    # TABELA HISTORICO_STATUS (LEGADO)
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS historico_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maquina_id TEXT,
        status TEXT,
        inicio TEXT,
        fim TEXT,
        duracao_segundos INTEGER
    )
    """)

    # =========================
    # NOVA TABELA LOG DE STATUS
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS maquina_status_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maquina_id TEXT NOT NULL,
        status TEXT NOT NULL,
        motivo TEXT,
        inicio_em TEXT NOT NULL,
        fim_em TEXT,
        criado_em TEXT NOT NULL
    )
    """)

    # =========================
    # TABELA USUARIOS (AUTH)
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      nome TEXT NOT NULL,
      login TEXT NOT NULL UNIQUE,
      senha TEXT NOT NULL,
      nivel TEXT NOT NULL DEFAULT 'OPERADOR',
      maquina_id TEXT,
      criado_em TEXT NOT NULL
    )
    """)

    # =========================
    # TABELA LOGS_OPERACAO
    # =========================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs_operacao (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        maquina_id TEXT,
        arquivo_id INTEGER,
        acao TEXT NOT NULL,
        extra TEXT,
        data_hora TEXT NOT NULL
    )
    """)
    cur.execute("""
CREATE TABLE IF NOT EXISTS chat_mensagens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id TEXT NOT NULL,
    autor TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
)
""")
    cur.execute("""
CREATE TABLE IF NOT EXISTS material_solicitacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id TEXT NOT NULL,
    item_id INTEGER,
    arquivo_nome TEXT,
    material TEXT,
    status TEXT NOT NULL DEFAULT 'ABERTA',
    criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    atendido_em TEXT
)
""")

    maquinas = [
        ("CNC01", "CNC 01"),
        ("CNC02", "CNC 02"),
        ("CNC03", "CNC 03"),
        ("CNC04", "CNC 04"),
        ("CNC05", "CNC 05"),
        ("CNC06", "CNC 06"),
        ("CNC07", "CNC 07"),
    ]

    now = datetime.now().isoformat(timespec="seconds")

    for mid, nome in maquinas:
        cur.execute("""
        INSERT OR IGNORE INTO maquinas (id, nome, status, status_desde)
        VALUES (?, ?, 'PARADA', ?)
        """, (mid, nome, now))

    # cria log aberto inicial se não existir
    for mid, _nome in maquinas:
        aberta = cur.execute(
            """
            SELECT id
            FROM maquina_status_log
            WHERE maquina_id = ? AND fim_em IS NULL
            LIMIT 1
            """,
            (mid,),
        ).fetchone()

        maq = cur.execute(
            "SELECT status, status_desde FROM maquinas WHERE id = ?",
            (mid,),
        ).fetchone()

        if maq and not aberta:
            cur.execute(
                """
                INSERT INTO maquina_status_log
                (maquina_id, status, motivo, inicio_em, fim_em, criado_em)
                VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (
                    mid,
                    maq["status"] or "PARADA",
                    None,
                    maq["status_desde"] or now,
                    now,
                ),
            )

    # admin
    cur.execute("""
    INSERT OR IGNORE INTO usuarios (id, nome, login, senha, nivel, maquina_id, criado_em)
    VALUES (1, 'Administrador', 'admin', 'admin123', 'ADMIN', NULL, ?)
    """, (now,))

    operadores = [
        ("Operador CNC01", "op01", "123", "OPERADOR", "CNC01"),
        ("Operador CNC02", "op02", "123", "OPERADOR", "CNC02"),
        ("Operador CNC03", "op03", "123", "OPERADOR", "CNC03"),
        ("Operador CNC04", "op04", "123", "OPERADOR", "CNC04"),
        ("Operador CNC05", "op05", "123", "OPERADOR", "CNC05"),
        ("Operador CNC06", "op06", "123", "OPERADOR", "CNC06"),
        ("Operador CNC07", "op07", "123", "OPERADOR", "CNC07"),
    ]
    for nome, login, senha, nivel, maquina_id in operadores:
        cur.execute("""
        INSERT OR IGNORE INTO usuarios (nome, login, senha, nivel, maquina_id, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (nome, login, senha, nivel, maquina_id, now))

    conn.commit()
    conn.close()

    print("✅ Banco atualizado com log de status para dashboard.")

if __name__ == "__main__":
    main()
