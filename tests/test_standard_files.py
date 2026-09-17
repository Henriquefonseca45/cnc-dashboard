import asyncio
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from backend import db, init_db, main


class StandardFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = db.DB_PATH
        self.old_dxf = main.DXF_DIR
        self.old_standard = main.STANDARD_DXF_DIR
        root = Path(self.tmp.name)
        db.DB_PATH = root / "standard.db"
        main.DXF_DIR = root / "dxf"
        main.STANDARD_DXF_DIR = root / "standard"
        main.DXF_DIR.mkdir()
        main.STANDARD_DXF_DIR.mkdir()
        with redirect_stdout(StringIO()):
            init_db.main()
        self.actor = {"id": None, "nome": "Programador teste", "login": "teste", "role": "programador"}
        self.request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})

    def tearDown(self):
        db.DB_PATH = self.old_db
        main.DXF_DIR = self.old_dxf
        main.STANDARD_DXF_DIR = self.old_standard
        self.tmp.cleanup()

    def upload(self, name="detalhe-padrao.dxf"):
        return asyncio.run(main.upload_standard_file(
            UploadFile(filename=name, file=BytesIO(b"0\nEOF\n")), self.actor
        ))

    def test_programador_uploads_and_library_keeps_file_after_queueing(self):
        uploaded = self.upload()
        self.assertEqual([item["nome"] for item in main.get_standard_files()["items"]], ["detalhe-padrao.dxf"])
        result = main.queue_standard_file(
            uploaded["id"], main.StandardFileQueueRequest(priority="high", cnc_id="CNC02"), self.request
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(main.get_standard_files()["items"]), 1)
        conn = db.get_conn()
        try:
            queued = conn.execute(
                """SELECT a.nome,a.priority,q.maquina_id FROM arquivos_dxf a
                   JOIN fila_itens q ON q.arquivo_id=a.id WHERE a.id=?""", (result["arquivo_id"],)
            ).fetchone()
            compatible = conn.execute(
                "SELECT cnc_id FROM arquivo_cnc_compatibilidade WHERE arquivo_id=?", (result["arquivo_id"],)
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(dict(queued), {"nome": "detalhe-padrao.dxf", "priority": "high", "maquina_id": "CNC02"})
        self.assertEqual([row["cnc_id"] for row in compatible], ["CNC02"])

    def test_facilitador_can_queue_standard_file(self):
        uploaded = self.upload("recorrente.dxf")
        result = main.queue_standard_file(
            uploaded["id"], main.StandardFileQueueRequest(priority="medium", cnc_id="CNC03"), self.request
        )
        self.assertEqual(result["maquina_id"], "CNC03")

    def test_duplicate_standard_name_is_rejected_without_orphan_file(self):
        self.upload("repetido.dxf")
        with self.assertRaises(HTTPException) as context:
            self.upload("repetido.dxf")
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(len(list(main.STANDARD_DXF_DIR.iterdir())), 1)

    def test_invalid_machine_does_not_create_production_copy(self):
        uploaded = self.upload()
        with self.assertRaises(HTTPException) as context:
            main.queue_standard_file(
                uploaded["id"], main.StandardFileQueueRequest(priority="normal", cnc_id="CNC99"), self.request
            )
        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(list(main.DXF_DIR.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
