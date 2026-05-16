from backend.db import get_conn

def main():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS historico_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maquina_id TEXT NOT NULL,
        status TEXT NOT NULL,
        inicio TEXT NOT NULL,
        fim TEXT,
        duracao_segundos INTEGER
    )
    """)

    conn.commit()
    conn.close()
    print("Tabela historico_status criada com sucesso.")

if __name__ == "__main__":
    main()
