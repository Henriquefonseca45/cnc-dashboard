import sqlite3
import unittest

import backend.main as main


class DashboardTimezoneTests(unittest.TestCase):
    def test_dashboard_endpoint_accepts_existing_status_events_with_timezone(self):
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
            "INSERT INTO maquinas VALUES ('CNC01', 'CNC 01', 'PARADA', '2026-08-04T09:00:00-03:00', 'Operador')"
        )
        conn.execute(
            """
            INSERT INTO maquina_status_log
            (maquina_id, status, motivo, inicio_em, fim_em, criado_em, invalidado)
            VALUES ('CNC01', 'PARADA', 'PARADA',
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

        self.assertEqual(payload["totals"]["parada"]["tempo_seg"], 3600)
        self.assertEqual(payload["per_machine"][0]["parada_min"], 60.0)

    def test_special_reason_does_not_become_an_invalid_general_bucket(self):
        self.assertEqual(main._dashboard_bucket_from_status("RNC", None), "usinando")
        self.assertEqual(main._dashboard_bucket_from_status("ABERTURA MATERIAL", None), "usinando")
        self.assertEqual(main._dashboard_bucket_from_status("PARADA", "RNC"), "parada")
        self.assertEqual(main._dashboard_special_bucket_from_status("PARADA", "RNC"), "rnc")


if __name__ == "__main__":
    unittest.main()
