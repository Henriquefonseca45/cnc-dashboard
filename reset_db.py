import sqlite3

DB = r"C:\Users\servi\cnc-dashboard\cnc.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# listar tabelas
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = [r[0] for r in cur.fetchall()]
print("TABELAS:", tables)

# limpar fila e histórico (ajustamos depois que você ver os nomes)
candidatas = [
    "fila",
    "agente_baixados",
    "agente_downloads",
    "downloads",
    "historico_operador",
    "historico",
    "logs_operador",
    "eventos",
]

for t in candidatas:
    if t in tables:
        cur.execute(f"DELETE FROM {t};")
        print("Limpou:", t)

# reset status máquinas (opcional, mas recomendado)
if "maquinas" in tables:
    cur.execute("UPDATE maquinas SET status='PARADA', status_desde=CURRENT_TIMESTAMP;")
    print("Resetou: maquinas -> PARADA")

conn.commit()
conn.close()
print("OK ✅")