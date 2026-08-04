import sqlite3
import unittest

import backend.main as main


class DashboardTimezoneTests(unittest.TestCase):
    def test_dashboard_accepts_status_events_with_server_timezone(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE maquinas (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                status TEXT NOT NULL,
                status_desde TEXT,
                operador_nome TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE maquina_status_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                maquina_id TEXT NOT NULL,
                status TEXT NOT NULL,
                motivo TEXT,
                inicio_em TEXT NOT NULL,
                fim_em TEXT,
                criado_em TEXT NOT NULL,
                invalidado INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO maquinas VALUES ('CNC01', 'CNC 01', 'MANUTENÇÃO', '2026-08-04T08:00:00-03:00', 'Operador')"
        )
        conn.execute(
            """
            INSERT INTO maquina_status_log
            (maquina_id, status, motivo, inicio_em, fim_em, criado_em, invalidado)
            VALUES ('CNC01', 'MANUTENÇÃO', 'MANUTENCAO',
                    '2026-08-04T08:00:00-03:00', '2026-08-04T09:00:00-03:00',
                    '2026-08-04T08:00:00-03:00', 0)
            """
        )

        original_get_conn = main.get_conn
        main.get_conn = lambda: conn
        try:
            payload = main.dashboard_indicadores(
                data="2026-08-04",
                data_inicio=None,
                data_fim=None,
                usar_snapshot=False,
            )
        finally:
            main.get_conn = original_get_conn

        self.assertEqual(payload["totals"]["manutencao"]["tempo_seg"], 3600)
        self.assertEqual(payload["per_machine"][0]["manutencao_min"], 60.0)


if __name__ == "__main__":
    unittest.main()
