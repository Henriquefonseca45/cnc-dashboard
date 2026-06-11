from datetime import datetime
from backend.db import get_conn

def log_action(
    usuario_id: int | None,
    acao: str,
    maquina_id: str | None = None,
    arquivo_id: int | None = None,
    extra: str | None = None,
):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO logs_operacao (usuario_id, maquina_id, arquivo_id, acao, extra, data_hora)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                usuario_id,
                maquina_id,
                arquivo_id,
                acao,
                extra,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        # não derruba o sistema por causa de log
        pass