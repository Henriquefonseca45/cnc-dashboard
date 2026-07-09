import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import backend.main as main
    from fastapi import HTTPException
except ModuleNotFoundError as exc:
    main = None
    HTTPException = Exception
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def fake_request(headers=None, host="testclient"):
    return SimpleNamespace(headers=headers or {}, client=SimpleNamespace(host=host))


@unittest.skipIf(main is None, f"Dependencias do backend indisponiveis: {IMPORT_ERROR}")
class QueueAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "audit-test.db"
        self.original_get_conn = main.get_conn

        def get_test_conn():
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn

        main.get_conn = get_test_conn
        self._create_base_data()

    def tearDown(self):
        main.get_conn = self.original_get_conn
        self.tmp.cleanup()

    def _create_base_data(self):
        conn = main.get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE maquinas (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PARADA',
                status_desde TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE arquivos_dxf (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                path TEXT NOT NULL,
                criado_em TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'DISPONIVEL'
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE fila_itens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                maquina_id TEXT NOT NULL,
                arquivo_id INTEGER NOT NULL,
                posicao INTEGER NOT NULL,
                status TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
            """
        )
        cur.execute("INSERT INTO maquinas (id, nome, status) VALUES ('CNC01', 'CNC 01', 'PARADA')")
        for idx, nome in enumerate(("A.dxf", "B.dxf", "C.dxf"), start=1):
            cur.execute(
                "INSERT INTO arquivos_dxf (id, nome, path, criado_em) VALUES (?, ?, ?, '2026-07-09T08:00:00')",
                (idx, nome, f"/tmp/{nome}"),
            )
            cur.execute(
                "INSERT INTO fila_itens (id, maquina_id, arquivo_id, posicao, status, criado_em) VALUES (?, 'CNC01', ?, ?, 'AGUARDANDO', '2026-07-09T08:00:00')",
                (idx, idx, idx),
            )
        conn.commit()
        conn.close()

    def _audit_rows(self):
        conn = main.get_conn()
        rows = conn.execute("SELECT * FROM cnc_queue_audit ORDER BY id").fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def _reorder(self, ids, headers=None, host="testclient"):
        return main.reorder_fila(
            "CNC01",
            main.ReorderFilaRequest(ordered_item_ids=ids),
            fake_request(headers=headers, host=host),
        )

    def test_obter_ip_cliente_priority(self):
        self.assertEqual(main.obter_ip_cliente(fake_request(host="192.168.1.35")), "192.168.1.35")
        self.assertEqual(
            main.obter_ip_cliente(fake_request(headers={"x-forwarded-for": "192.168.1.35, 172.18.0.1"})),
            "192.168.1.35",
        )
        self.assertEqual(
            main.obter_ip_cliente(fake_request(headers={"x-real-ip": "2001:db8::35"})),
            "2001:db8::35",
        )
        self.assertEqual(main.obter_ip_cliente(SimpleNamespace(headers={}, client=None)), "desconhecido")

    def test_reorder_uses_request_client_host_when_no_proxy_header(self):
        result = self._reorder([2, 1, 3], host="192.168.1.35")
        self.assertTrue(result["ok"])
        rows = self._audit_rows()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["ip_origem"], "192.168.1.35")

    def test_reorder_uses_first_forwarded_for_ip(self):
        result = self._reorder([2, 1, 3], headers={"x-forwarded-for": "192.168.1.35, 172.18.0.1"})
        self.assertTrue(result["ok"])
        rows = self._audit_rows()
        self.assertEqual(rows[0]["ip_origem"], "192.168.1.35")

    def test_reorder_uses_real_ip_when_forwarded_for_is_missing(self):
        result = self._reorder([2, 1, 3], headers={"x-real-ip": "2001:db8::35"})
        self.assertTrue(result["ok"])
        rows = self._audit_rows()
        self.assertEqual(rows[0]["ip_origem"], "2001:db8::35")

    def test_reorder_saves_real_previous_and_new_positions(self):
        result = self._reorder([3, 1, 2])
        self.assertTrue(result["ok"])
        rows = self._audit_rows()
        moved = {row["arquivo_nome"]: (row["posicao_anterior"], row["posicao_nova"]) for row in rows}
        self.assertEqual(moved["C.dxf"], (3, 1))
        self.assertEqual(moved["A.dxf"], (1, 2))
        self.assertEqual(moved["B.dxf"], (2, 3))

    def test_reorder_failure_does_not_save_audit(self):
        with self.assertRaises(HTTPException):
            self._reorder([])
        conn = main.get_conn()
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cnc_queue_audit'"
        ).fetchone()
        rows = []
        if table:
            rows = conn.execute("SELECT * FROM cnc_queue_audit").fetchall()
        conn.close()
        self.assertEqual(len(rows), 0)

    def test_queue_audit_route_filters_by_cnc_and_permission_helper_blocks_operator(self):
        self._reorder([2, 1, 3])
        with self.assertRaises(HTTPException):
            main._require_queue_audit_viewer(x_user_role="OPERADOR")

        data = main.api_cnc_queue_audit(
            "1",
            limit=20,
            data_inicio=None,
            data_fim=None,
            ip=None,
            _user={"role": "PROGRAMADOR"},
        )
        self.assertTrue(data)
        self.assertEqual(data[0]["cnc_id"], "CNC01")


if __name__ == "__main__":
    unittest.main()
