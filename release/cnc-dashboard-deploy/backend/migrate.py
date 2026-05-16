from backend.db import get_conn

def main():
    conn = get_conn()
    cur = conn.cursor()

    # Tenta adicionar a coluna (se já existir, ignora)
    try:
        cur.execute("ALTER TABLE maquinas ADD COLUMN arquivo_pendente_id INTEGER")
        conn.commit()
        print("OK: coluna arquivo_pendente_id criada.")
    except Exception as e:
        print("INFO: não criou (provavelmente já existe):", e)

    # Mostra colunas atuais para confirmar
    cols = cur.execute("PRAGMA table_info(maquinas)").fetchall()
    print("COLUNAS maquinas:")
    for c in cols:
        # c = (cid, name, type, notnull, dflt_value, pk)
        print(" -", c[1], c[2])

    conn.close()

if __name__ == "__main__":
    main()
