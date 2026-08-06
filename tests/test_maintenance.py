from concurrent.futures import ThreadPoolExecutor
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.maintenance import (
    MaintenanceError,
    change_machine_status,
    close_orphaned_maintenance_calls,
    ensure_maintenance_schema,
)


ACTOR = {"id": 7, "name": "Operador Teste", "role": "OPERADOR"}


class MaintenanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "maintenance.db"
        conn = self.connect()
        conn.execute(
            "CREATE TABLE maquinas (id TEXT PRIMARY KEY, nome TEXT NOT NULL, status TEXT NOT NULL, status_desde TEXT)"
        )
        conn.execute("INSERT INTO maquinas VALUES ('CNC01', 'CNC 01', 'OCIOSA', '2026-08-04T08:00:00-03:00')")
        ensure_maintenance_schema(conn)
        conn.commit()
        self.type_id = conn.execute("SELECT id FROM maintenance_types ORDER BY display_order LIMIT 1").fetchone()[0]
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def start(self, **overrides):
        values = {
            "maintenance_type_id": self.type_id,
            "work_order": "OS-2026-00154",
            "opening_notes": "Falha no eixo",
            "now_factory": lambda: "2026-08-04T09:00:00-03:00",
            "require_new_maintenance_for_start": True,
        }
        values.update(overrides)
        return change_machine_status(self.connect, "CNC01", "MANUTENÇÃO", ACTOR, **values)

    def finish(self, **overrides):
        values = {
            "closing_notes": "Equipamento liberado",
            "now_factory": lambda: "2026-08-04T10:02:03-03:00",
            "require_open_maintenance_for_finish": True,
        }
        values.update(overrides)
        return change_machine_status(self.connect, "CNC01", "OCIOSA", ACTOR, **values)

    def rows(self, query, params=()):
        conn = self.connect()
        result = [dict(row) for row in conn.execute(query, params).fetchall()]
        conn.close()
        return result

    def test_rejects_start_without_type(self):
        with self.assertRaisesRegex(MaintenanceError, "Tipo"):
            self.start(maintenance_type_id=None)

    def test_rejects_start_without_work_order(self):
        with self.assertRaisesRegex(MaintenanceError, "Ordem"):
            self.start(work_order="  ")

    def test_requires_responsible_authorized_user(self):
        with self.assertRaises(MaintenanceError) as missing:
            change_machine_status(self.connect, "CNC01", "MANUTENÇÃO", {}, maintenance_type_id=self.type_id, work_order="1")
        self.assertEqual(missing.exception.status_code, 422)
        with self.assertRaises(MaintenanceError) as denied:
            change_machine_status(self.connect, "CNC01", "MANUTENÇÃO", {"name": "TV", "role": "TV"}, maintenance_type_id=self.type_id, work_order="1")
        self.assertEqual(denied.exception.status_code, 403)

    def test_open_call_and_machine_status_are_committed_together(self):
        result = self.start()
        self.assertEqual(result["machine"]["status"], "MANUTENÇÃO")
        calls = self.rows("SELECT * FROM cnc_maintenance_calls")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["status"], "OPEN")
        self.assertEqual(calls[0]["started_at"], "2026-08-04T09:00:00-03:00")

    def test_rolls_back_call_when_status_side_effect_fails(self):
        def fail(*_args):
            raise RuntimeError("snapshot failed")
        with self.assertRaises(RuntimeError):
            self.start(legacy_hook=fail)
        self.assertEqual(self.rows("SELECT * FROM cnc_maintenance_calls"), [])
        self.assertEqual(self.rows("SELECT status FROM maquinas")[0]["status"], "OCIOSA")

    def test_work_order_preserves_leading_zeroes_and_trims_edges(self):
        self.start(work_order="  000154  ")
        self.assertEqual(self.rows("SELECT work_order FROM cnc_maintenance_calls")[0]["work_order"], "000154")

    def test_duplicate_start_does_not_create_second_call(self):
        self.start()
        with self.assertRaises(MaintenanceError) as duplicate:
            self.start()
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertEqual(len(self.rows("SELECT id FROM cnc_maintenance_calls")), 1)

    def test_regularizes_legacy_maintenance_without_resetting_original_status_time(self):
        conn = self.connect()
        conn.execute(
            "UPDATE maquinas SET status = 'MANUTENÇÃO', status_desde = '2026-08-04T07:30:00-03:00' WHERE id = 'CNC01'"
        )
        conn.commit()
        conn.close()
        result = self.start()
        self.assertTrue(result["status_unchanged"])
        self.assertEqual(result["machine"]["status_desde"], "2026-08-04T07:30:00-03:00")
        self.assertEqual(len(self.rows("SELECT id FROM cnc_maintenance_calls WHERE status = 'OPEN'")), 1)
        events = self.rows("SELECT event_type FROM maintenance_audit_events ORDER BY id")
        self.assertEqual([row["event_type"] for row in events], ["MAINTENANCE_OPENED"])

    def test_concurrent_start_creates_only_one_call(self):
        def attempt(_):
            try:
                self.start()
                return "ok"
            except MaintenanceError as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count(409), 1)
        self.assertEqual(len(self.rows("SELECT id FROM cnc_maintenance_calls")), 1)

    def test_finish_saves_duration_removes_active_and_preserves_history(self):
        self.start()
        result = self.finish()
        self.assertEqual(result["maintenance"]["durationSeconds"], 3723)
        self.assertEqual(self.rows("SELECT * FROM cnc_maintenance_calls WHERE status='OPEN'"), [])
        closed = self.rows("SELECT * FROM cnc_maintenance_calls WHERE status='CLOSED'")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["duration_seconds"], 3723)
        self.assertEqual(closed[0]["finished_by_name"], ACTOR["name"])

    def test_regular_status_change_closes_maintenance_automatically(self):
        self.start()
        result = change_machine_status(
            self.connect,
            "CNC01",
            "SETUP",
            ACTOR,
            now_factory=lambda: "2026-08-04T10:02:03-03:00",
        )
        self.assertEqual(result["machine"]["status"], "SETUP")
        self.assertEqual(result["maintenance"]["durationSeconds"], 3723)
        self.assertEqual(self.rows("SELECT * FROM cnc_maintenance_calls WHERE status='OPEN'"), [])

    def test_legacy_maintenance_without_open_call_can_change_status(self):
        conn = self.connect()
        conn.execute("UPDATE maquinas SET status = 'MANUTENÇÃO' WHERE id = 'CNC01'")
        conn.commit()
        conn.close()
        result = change_machine_status(
            self.connect,
            "CNC01",
            "OCIOSA",
            ACTOR,
            now_factory=lambda: "2026-08-04T10:02:03-03:00",
        )
        self.assertEqual(result["machine"]["status"], "OCIOSA")
        self.assertIsNone(result["maintenance"])

    def test_orphaned_open_call_is_closed_when_machine_has_another_status(self):
        self.start()
        conn = self.connect()
        conn.execute("UPDATE maquinas SET status = 'USINANDO' WHERE id = 'CNC01'")
        closed = close_orphaned_maintenance_calls(
            conn,
            now_factory=lambda: "2026-08-04T10:02:03-03:00",
        )
        conn.commit()
        conn.close()

        self.assertEqual(closed, 1)
        self.assertEqual(self.rows("SELECT * FROM cnc_maintenance_calls WHERE status='OPEN'"), [])
        call = self.rows("SELECT * FROM cnc_maintenance_calls WHERE status='CLOSED'")[0]
        self.assertEqual(call["duration_seconds"], 3723)
        self.assertEqual(call["finished_by_name"], "Sistema")
        events = self.rows("SELECT event_type FROM maintenance_audit_events ORDER BY id")
        self.assertEqual(events[-1]["event_type"], "MAINTENANCE_CLOSED_AUTOMATICALLY")

    def test_duplicate_finish_is_rejected(self):
        self.start()
        self.finish()
        with self.assertRaises(MaintenanceError) as duplicate:
            self.finish()
        self.assertEqual(duplicate.exception.status_code, 409)

    def test_audit_records_required_events_with_server_time(self):
        self.start()
        self.finish()
        events = self.rows("SELECT event_type, created_at FROM maintenance_audit_events ORDER BY id")
        self.assertEqual([row["event_type"] for row in events], [
            "MAINTENANCE_OPENED", "MACHINE_STATUS_CHANGED", "MAINTENANCE_CLOSED", "MACHINE_STATUS_CHANGED"
        ])
        self.assertEqual(events[0]["created_at"], "2026-08-04T09:00:00-03:00")


if __name__ == "__main__":
    unittest.main()
