from backend.db import get_conn
from backend.maintenance import ensure_maintenance_schema


def main():
    conn = get_conn()
    try:
        ensure_maintenance_schema(conn)
        conn.commit()
    finally:
        conn.close()
    print("Estrutura de manutenção criada/atualizada com sucesso.")


if __name__ == "__main__":
    main()
