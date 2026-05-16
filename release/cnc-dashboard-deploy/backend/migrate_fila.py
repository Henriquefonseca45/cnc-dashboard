from backend.db import get_conn
from datetime import datetime

def main():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fila_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        maquina_id TEXT NOT NULL,
        arquivo_id INTEGER NOT NULL,
        posicao INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'AGUARDANDO',
        criado_em TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()
    print("OK: fila_itens criada/garantida.")

if __name__ == "__main__":
    main()
