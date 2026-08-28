from datetime import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.status_confirmation import (
    confirm_current_status,
    get_pending_status_confirmation,
    process_status_confirmations,
)


class StatusConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "status-confirmation.db"
        conn = self.connect()
        conn.execute(
            "CREATE TABLE maquinas (id TEXT PRIMARY KEY, status TEXT, status_desde TEXT, operador_nome TEXT)"
        )
        conn.execute("INSERT INTO maquinas VALUES ('CNC01', 'SETUP', '2026-08-28T22:30:00-03:00', 'YURI')")
        conn.execute("INSERT INTO maquinas VALUES ('CNC02', 'DESLIGADA', '2026-08-28T22:00:00-03:00', '')")
        conn.execute("INSERT INTO maquinas VALUES ('CNC_TESTE', 'SETUP', '2026-08-28T22:30:00-03:00', 'TESTE')")
        conn.commit()
        conn.close()
        self.shutdowns = []

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def shutdown(self, cnc_id):
        self.shutdowns.append(cnc_id)
        conn = self.connect()
        conn.execute("UPDATE maquinas SET status = 'DESLIGADA', operador_nome = '' WHERE id = ?", (cnc_id,))
        conn.commit()
        conn.close()

    def test_creates_prompt_only_from_2319_for_active_real_cncs(self):
        before = datetime.fromisoformat("2026-08-28T23:18:59-03:00")
        process_status_confirmations(self.connect, self.shutdown, now=before)
        self.assertIsNone(get_pending_status_confirmation(self.connect, "CNC01", now=before))

        prompt_time = datetime.fromisoformat("2026-08-28T23:19:00-03:00")
        process_status_confirmations(self.connect, self.shutdown, now=prompt_time)
        pending = get_pending_status_confirmation(self.connect, "CNC01", now=prompt_time)
        self.assertEqual(pending["status"], "SETUP")
        self.assertIsNone(get_pending_status_confirmation(self.connect, "CNC02", now=prompt_time))
        self.assertIsNone(get_pending_status_confirmation(self.connect, "CNC_TESTE", now=prompt_time))

    def test_confirmation_before_deadline_prevents_shutdown(self):
        prompt_time = datetime.fromisoformat("2026-08-28T23:19:00-03:00")
        process_status_confirmations(self.connect, self.shutdown, now=prompt_time)
        result = confirm_current_status(
            self.connect,
            "CNC01",
            "YURI",
            now=datetime.fromisoformat("2026-08-28T23:23:59-03:00"),
        )
        self.assertTrue(result["ok"])
        process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-28T23:24:00-03:00"),
        )
        self.assertEqual(self.shutdowns, [])

    def test_unconfirmed_machine_is_shutdown_at_deadline(self):
        process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-28T23:19:00-03:00"),
        )
        result = process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-28T23:24:00-03:00"),
        )
        self.assertEqual(result["auto_shutdown"], 1)
        self.assertEqual(self.shutdowns, ["CNC01"])

    def test_manual_status_change_cancels_pending_shutdown(self):
        process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-28T23:19:00-03:00"),
        )
        conn = self.connect()
        conn.execute(
            "UPDATE maquinas SET status = 'USINANDO', status_desde = '2026-08-28T23:21:00-03:00' WHERE id = 'CNC01'"
        )
        conn.commit()
        conn.close()
        process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-28T23:24:00-03:00"),
        )
        self.assertEqual(self.shutdowns, [])

    def test_pending_shutdown_is_recovered_after_server_restart(self):
        process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-28T23:19:00-03:00"),
        )
        result = process_status_confirmations(
            self.connect,
            self.shutdown,
            now=datetime.fromisoformat("2026-08-29T00:05:00-03:00"),
        )
        self.assertEqual(result["auto_shutdown"], 1)
        self.assertEqual(self.shutdowns, ["CNC01"])


if __name__ == "__main__":
    unittest.main()
