from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.maintenance import MaintenanceError, change_machine_status, ensure_maintenance_schema
from backend.morning_status_confirmation import (
    confirm_morning_status, get_pending_morning_status, process_morning_status_confirmations,
)

ACTOR = {"id": None, "name": "YURI", "role": "OPERADOR"}


class MorningStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "morning.db"
        conn = self.connect()
        conn.execute("CREATE TABLE maquinas (id TEXT PRIMARY KEY, nome TEXT, status TEXT, status_desde TEXT, operador_nome TEXT)")
        for cnc, status in [("CNC01", "DESLIGADA"), ("CNC02", "SETUP"), ("CNC_TESTE", "SETUP")]:
            conn.execute("INSERT INTO maquinas VALUES (?, ?, ?, '2026-08-30T23:24:00-03:00', 'DANIEL')", (cnc, cnc, status))
        ensure_maintenance_schema(conn)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def at(self, time, date="2026-08-31"):
        return datetime.fromisoformat(f"{date}T{time}-03:00")

    def process(self, time="05:05:00", date="2026-08-31", **kwargs):
        return process_morning_status_confirmations(self.connect, now=self.at(time, date), **kwargs)

    def pending(self, cnc="CNC01"):
        return get_pending_morning_status(self.connect, cnc, now=self.at("05:06:00"))

    def rows(self, sql):
        conn = self.connect()
        try:
            return [dict(row) for row in conn.execute(sql)]
        finally:
            conn.close()

    def answer(self, status="SETUP", time="05:14:59", cnc="CNC01", **kwargs):
        return confirm_morning_status(self.connect, cnc, self.pending(cnc)["id"], status, ACTOR,
                                      now=self.at(time), **kwargs)

    def test_prompt_starts_at_0505_including_off_machines_not_test_machine(self):
        self.assertEqual(self.process("05:04:59")["created"], 0)
        self.assertEqual(self.process()["created"], 2)
        self.assertEqual(self.pending()["status"], "DESLIGADA")
        self.assertIsNotNone(self.pending("CNC02"))
        self.assertIsNone(self.pending("CNC_TESTE"))
        self.assertEqual(self.process()["created"], 0)

    def test_weekdays_only(self):
        for date in ["2026-08-29", "2026-08-30"]:
            self.assertEqual(self.process(date=date)["created"], 0)
            self.assertEqual(self.process("05:15:00", date=date)["auto_absent"], 0)
        for date in ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]:
            self.assertEqual(self.process(date=date)["created"], 2)

    def test_fallback_at_0515_once_and_clears_operator(self):
        self.process()
        self.assertEqual(self.process("05:14:59")["auto_absent"], 0)
        self.assertEqual(self.process("05:15:00")["auto_absent"], 2)
        self.assertEqual(self.process("05:15:01")["auto_absent"], 0)
        machine = self.rows("SELECT * FROM maquinas WHERE id = 'CNC01'")[0]
        self.assertEqual(machine["status"], "FALTA DE OPERADOR")
        self.assertEqual(machine["status_desde"], "2026-08-31T05:15:00-03:00")
        self.assertEqual(machine["operador_nome"], "")

    def test_answer_saves_operator_and_protects_status(self):
        self.process()
        self.answer()
        self.assertIsNone(self.pending())
        self.process("05:15:00")
        machine = self.rows("SELECT * FROM maquinas WHERE id = 'CNC01'")[0]
        self.assertEqual(machine["status"], "SETUP")
        self.assertEqual(machine["operador_nome"], "YURI")

    def test_same_status_answer_does_not_reset_status_since(self):
        self.process()
        self.assertTrue(self.answer(status="DESLIGADA")["status_unchanged"])
        self.process("05:15:00")
        machine = self.rows("SELECT * FROM maquinas WHERE id = 'CNC01'")[0]
        self.assertEqual(machine["status"], "DESLIGADA")
        self.assertEqual(machine["status_desde"], "2026-08-30T23:24:00-03:00")

    def test_late_answer_rejected(self):
        self.process()
        with self.assertRaisesRegex(MaintenanceError, "prazo"):
            self.answer(time="05:15:00")
        self.assertIsNotNone(self.pending())

    def test_manual_change_counts_as_response(self):
        self.process()
        change_machine_status(self.connect, "CNC01", "SETUP", ACTOR,
                              now_factory=lambda: self.at("05:10:00").isoformat())
        self.assertEqual(self.process("05:15:00")["auto_absent"], 1)
        self.assertIsNone(self.pending())
        self.assertEqual(self.rows("SELECT status FROM maquinas WHERE id = 'CNC01'")[0]["status"], "SETUP")

    def test_changed_machine_cannot_be_overwritten_by_stale_response(self):
        self.process()
        change_machine_status(self.connect, "CNC01", "SETUP", ACTOR)
        with self.assertRaisesRegex(MaintenanceError, "já foi alterado"):
            self.answer(status="DESLIGADA")

    def test_maintenance_validation_rolls_back_confirmation_and_operator(self):
        self.process()
        with self.assertRaises(MaintenanceError):
            self.answer(status="MANUTENÇÃO")
        self.assertIsNotNone(self.pending())
        self.assertEqual(self.rows("SELECT operador_nome FROM maquinas WHERE id = 'CNC01'")[0]["operador_nome"], "DANIEL")
        type_id = self.rows("SELECT id FROM maintenance_types WHERE name LIKE 'Mec%'")[0]["id"]
        with self.assertRaisesRegex(MaintenanceError, "Ordem"):
            self.answer(status="MANUTENÇÃO", maintenance_type_id=type_id)
        self.assertIsNotNone(self.pending())

    def test_lubrication_without_os_and_timeout_closes_existing_maintenance(self):
        self.process()
        type_id = self.rows("SELECT id FROM maintenance_types WHERE name LIKE 'Lubrifica%'")[0]["id"]
        self.answer(status="MANUTENÇÃO", maintenance_type_id=type_id)
        self.assertEqual(self.rows("SELECT status FROM cnc_maintenance_calls")[0]["status"], "OPEN")
        self.process(date="2026-09-01")
        self.process("05:15:00", date="2026-09-01")
        self.assertEqual(self.rows("SELECT status FROM cnc_maintenance_calls")[0]["status"], "CLOSED")

    def test_hook_failure_rolls_back_everything_and_retries(self):
        self.process()
        def failing_hook(*_args):
            raise RuntimeError("Simulated history failure")
        with self.assertLogs("backend.morning_status_confirmation", level="ERROR"):
            self.assertEqual(self.process("05:15:00", legacy_hook=failing_hook)["auto_absent"], 0)
        self.assertIsNotNone(self.pending())
        self.assertEqual(self.rows("SELECT status FROM maquinas WHERE id = 'CNC01'")[0]["status"], "DESLIGADA")
        self.assertEqual(self.process("05:15:01")["auto_absent"], 2)

    def test_restart_recovers_pending_but_does_not_invent_missed_prompts(self):
        self.assertEqual(self.process("08:00:00")["created"], 0)
        self.process()
        self.assertEqual(self.process("05:16:00")["auto_absent"], 2)

    def test_friday_pending_is_not_applied_on_weekend(self):
        self.process(date="2026-08-28")
        self.assertEqual(self.process("05:15:00", date="2026-08-29")["auto_absent"], 0)
        self.assertEqual({row["action"] for row in self.rows("SELECT action FROM morning_status_confirmations")}, {"EXPIRED"})

    def test_duplicate_workers_apply_one_transition_per_machine(self):
        self.process()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.process("05:15:00"), range(2)))
        self.assertEqual(sum(result["auto_absent"] for result in results), 2)

    def test_duplicate_response_rejected(self):
        self.process()
        confirmation_id = self.pending()["id"]
        self.answer()
        with self.assertRaises(MaintenanceError):
            confirm_morning_status(self.connect, "CNC01", confirmation_id, "OCIOSA", ACTOR, now=self.at("05:14:59"))

    def test_response_hook_failure_keeps_prompt_and_previous_status(self):
        self.process()
        def fail(*_args):
            raise RuntimeError("Arquivo incompatível")
        with self.assertRaises(RuntimeError):
            self.answer(status="USINANDO", legacy_hook=fail)
        self.assertIsNotNone(self.pending())
        self.assertEqual(self.rows("SELECT status FROM maquinas WHERE id = 'CNC01'")[0]["status"], "DESLIGADA")

    def test_response_and_timeout_race_never_overwrites_successful_confirmation(self):
        self.process()
        confirmation_id = self.pending()["id"]
        def answer():
            try:
                confirm_morning_status(self.connect, "CNC01", confirmation_id, "SETUP", ACTOR, now=self.at("05:14:59"))
                return True
            except MaintenanceError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            response = pool.submit(answer)
            timeout = pool.submit(self.process, "05:15:00")
            confirmed = response.result()
            timeout.result()
        machine = self.rows("SELECT status FROM maquinas WHERE id = 'CNC01'")[0]
        self.assertEqual(machine["status"], "SETUP" if confirmed else "FALTA DE OPERADOR")

    def test_invalid_status_or_actor_does_not_consume_response(self):
        self.process()
        with self.assertRaises(MaintenanceError):
            self.answer(status="INVALIDO")
        with self.assertRaises(MaintenanceError):
            confirm_morning_status(self.connect, "CNC01", self.pending()["id"], "SETUP", {}, now=self.at("05:10:00"))
        self.assertIsNotNone(self.pending())


if __name__ == "__main__":
    unittest.main()
