from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.plan_classification import (
    PlanClassificationError,
    classifications_by_plan,
    ensure_plan_classification_schema,
    normalize_priority,
    plan_is_compatible_with,
    set_plan_classification,
)


class PlanClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "plans.db"
        conn = self.connect()
        conn.execute("CREATE TABLE maquinas (id TEXT PRIMARY KEY, nome TEXT)")
        conn.executemany("INSERT INTO maquinas VALUES (?, ?)", [
            ("CNC01", "Router 01"), ("CNC02", "Router 02"), ("CNC03", "Router 03"), ("CNC_TESTE", "Teste"),
        ])
        conn.execute("CREATE TABLE arquivos_dxf (id INTEGER PRIMARY KEY, nome TEXT, criado_em TEXT)")
        conn.execute("CREATE TABLE fila_itens (arquivo_id INTEGER, maquina_id TEXT, status TEXT)")
        conn.executemany("INSERT INTO arquivos_dxf VALUES (?, ?, ?)", [
            (1, "normal.dxf", "2026-09-01T08:00:00"),
            (2, "alta-antiga.dxf", "2026-09-01T07:00:00"),
            (3, "alta-nova.dxf", "2026-09-01T09:00:00"),
        ])
        ensure_plan_classification_schema(conn)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_migration_adds_normal_default_and_relationship_table(self):
        conn = self.connect()
        self.assertEqual(conn.execute("SELECT priority FROM arquivos_dxf WHERE id=1").fetchone()[0], "normal")
        self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='arquivo_cnc_compatibilidade'").fetchone())
        conn.close()

    def test_requires_valid_priority(self):
        self.assertEqual(normalize_priority(None), "normal")
        self.assertEqual(normalize_priority("HIGH"), "high")
        with self.assertRaisesRegex(PlanClassificationError, "Prioridade"):
            normalize_priority("urgente")

    def test_requires_at_least_one_production_cnc(self):
        conn = self.connect()
        with self.assertRaisesRegex(PlanClassificationError, "pelo menos um CNC"):
            set_plan_classification(conn, 1, "normal", [])
        with self.assertRaisesRegex(PlanClassificationError, "inválida"):
            set_plan_classification(conn, 1, "normal", ["CNC_TESTE"])
        conn.close()

    def test_saves_multiple_cnc_ids_and_persists_priority(self):
        conn = self.connect()
        result = set_plan_classification(conn, 1, "medium", ["cnc03", "CNC01", "CNC03"])
        conn.commit()
        self.assertEqual(result["compatible_cnc_ids"], ["CNC03", "CNC01"])
        self.assertEqual(conn.execute("SELECT priority FROM arquivos_dxf WHERE id=1").fetchone()[0], "medium")
        compatible = classifications_by_plan(conn, [1])[1]
        self.assertEqual([item["id"] for item in compatible], ["CNC01", "CNC03"])
        conn.close()

    def test_edit_replaces_priority_and_compatibility(self):
        conn = self.connect()
        set_plan_classification(conn, 1, "medium", ["CNC01", "CNC02"])
        set_plan_classification(conn, 1, "high", ["CNC03"])
        conn.commit()
        self.assertEqual(conn.execute("SELECT priority FROM arquivos_dxf WHERE id=1").fetchone()[0], "high")
        self.assertEqual([item["id"] for item in classifications_by_plan(conn, [1])[1]], ["CNC03"])
        conn.close()

    def test_compatibility_blocks_other_cnc_but_legacy_plan_remains_allowed(self):
        conn = self.connect()
        self.assertTrue(plan_is_compatible_with(conn, 1, "CNC02"))
        set_plan_classification(conn, 1, "normal", ["CNC01", "CNC03"])
        self.assertTrue(plan_is_compatible_with(conn, 1, "CNC03"))
        self.assertFalse(plan_is_compatible_with(conn, 1, "CNC02"))
        conn.close()

    def test_edit_cannot_remove_cnc_with_active_queue_item(self):
        conn = self.connect()
        set_plan_classification(conn, 1, "normal", ["CNC01", "CNC02"])
        conn.execute("INSERT INTO fila_itens VALUES (1, 'CNC02', 'AGUARDANDO')")
        with self.assertRaisesRegex(PlanClassificationError, "Mantenha a CNC ativa"):
            set_plan_classification(conn, 1, "high", ["CNC01"])
        conn.close()

    def test_priority_order_keeps_oldest_first_inside_each_priority(self):
        conn = self.connect()
        set_plan_classification(conn, 2, "high", ["CNC01"])
        set_plan_classification(conn, 3, "high", ["CNC01"])
        ordered = [row["id"] for row in conn.execute("""
            SELECT id FROM arquivos_dxf
            ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     criado_em ASC, id ASC
        """)]
        self.assertEqual(ordered, [2, 3, 1])
        conn.close()


if __name__ == "__main__":
    unittest.main()
