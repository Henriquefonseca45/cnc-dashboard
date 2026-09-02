import asyncio
from contextlib import redirect_stdout
from http.cookies import SimpleCookie
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

try:
    from fastapi import HTTPException, Response, UploadFile
    import backend.db as database
    import backend.init_db as init_db
    import backend.main as main
    import backend.programador_auth as auth
except ModuleNotFoundError as exc:
    main = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


def fake_request(token=None, headers=None):
    cookies = {auth.SESSION_COOKIE_NAME: token} if token else {}
    return SimpleNamespace(cookies=cookies, headers=headers or {}, client=SimpleNamespace(host="testclient"))


@unittest.skipIf(main is None, f"Dependências do backend indisponíveis: {IMPORT_ERROR}")
class ProgramadorApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        self.original_dxf_dir = main.DXF_DIR
        database.DB_PATH = Path(self.tmp.name) / "api.db"
        main.DXF_DIR = Path(self.tmp.name) / "dxf"
        main.DXF_DIR.mkdir()
        with redirect_stdout(StringIO()):
            init_db.main()
        conn = database.get_conn()
        self.programador = auth.create_or_update_user(
            conn, nome="João Silva", login="joao", password="Senha-forte-01", role="programador"
        )
        self.lider = auth.create_or_update_user(
            conn, nome="Maria Souza", login="maria", password="Senha-forte-02", role="lider"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        main.DXF_DIR = self.original_dxf_dir
        self.tmp.cleanup()

    def login(self, login="joao", senha="Senha-forte-01"):
        response = Response()
        result = main.programador_login(main.ProgramadorLoginRequest(login=login, senha=senha), response)
        cookie = SimpleCookie()
        cookie.load(response.headers["set-cookie"])
        return result, cookie[auth.SESSION_COOKIE_NAME].value, response.headers["set-cookie"]

    def audit_actions(self):
        conn = database.get_conn()
        rows = conn.execute("SELECT acao FROM programador_auditoria ORDER BY id").fetchall()
        conn.close()
        return [row["acao"] for row in rows]

    def test_unauthenticated_access_is_401(self):
        with self.assertRaises(HTTPException) as ctx:
            main.require_programador_auth(fake_request())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_login_cookie_is_http_only_and_refresh_resolves_session(self):
        result, token, header = self.login()
        self.assertEqual(result["user"]["role"], "programador")
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=lax", header)
        first = main.require_programador_auth(fake_request(token))
        second = main.require_programador_auth(fake_request(token))
        self.assertEqual(first["id"], second["id"])

    def test_wrong_password_and_inactive_user_are_rejected(self):
        with self.assertRaises(HTTPException) as wrong:
            self.login(senha="Senha-errada")
        self.assertEqual(wrong.exception.status_code, 401)
        conn = database.get_conn()
        conn.execute("UPDATE usuarios SET ativo=0 WHERE login='joao'")
        conn.commit()
        conn.close()
        with self.assertRaises(HTTPException) as inactive:
            self.login()
        self.assertEqual(inactive.exception.status_code, 401)

    def test_logout_revokes_cookie_session(self):
        _, token, _ = self.login()
        response = Response()
        main.programador_logout(fake_request(token), response)
        with self.assertRaises(HTTPException):
            main.require_programador_auth(fake_request(token))
        self.assertIn("Max-Age=0", response.headers["set-cookie"])

    def test_programador_is_forbidden_from_history_even_with_spoofed_role_header(self):
        _, token, _ = self.login()
        request = fake_request(token, headers={"x-user-role": "LIDER", "x-user-id": str(self.lider["id"])})
        user = main.require_programador_auth(request)
        self.assertEqual(user["id"], self.programador["id"])
        with self.assertRaises(HTTPException) as ctx:
            main.require_lider(request)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_lider_can_access_history_and_operational_dependency(self):
        _, token, _ = self.login("maria", "Senha-forte-02")
        self.assertEqual(main.require_programador_auth(fake_request(token))["role"], "lider")
        self.assertEqual(main.require_lider(fake_request(token))["id"], self.lider["id"])

    def test_import_classification_queue_move_and_delete_generate_audit(self):
        upload = UploadFile(filename="48572.dxf", file=BytesIO(b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"))
        metadata = json.dumps([{
            "name": "48572.dxf", "priority": "normal", "compatible_cnc_ids": ["CNC01", "CNC02"]
        }])
        imported = asyncio.run(main.upload_classified_plans([upload], metadata, self.programador))
        arquivo_id = imported["items"][0]["id"]
        conn = database.get_conn()
        created = conn.execute(
            "SELECT criado_por_usuario_id, criado_por_nome_snapshot FROM arquivos_dxf WHERE id=?", (arquivo_id,)
        ).fetchone()
        conn.close()
        self.assertEqual(created["criado_por_usuario_id"], self.programador["id"])
        self.assertEqual(created["criado_por_nome_snapshot"], "João Silva")
        main.update_plan_classification(
            arquivo_id,
            main.PlanClassificationRequest(priority="high", compatible_cnc_ids=["CNC01", "CNC02", "CNC03"]),
            self.programador,
        )
        added = main.add_fila("CNC01", main.AddFilaRequest(arquivo_id=arquivo_id), self.programador)
        moved = main.mover_item_para_outra_cnc(
            added["item_id"], "CNC02", main.MoveFilaItemRequest(manter_status=False), self.programador
        )
        main.fila_item_to_pool(moved["item_id_novo"], self.programador)
        main.excluir_arquivo(arquivo_id, self.programador)
        actions = self.audit_actions()
        for expected in (
            "ARQUIVO_IMPORTADO", "PRIORIDADE_ALTERADA", "CNC_ADICIONADA",
            "ADICIONADO_FILA", "PLANO_MOVIMENTADO", "REMOVIDO_FILA", "ARQUIVO_EXCLUIDO",
        ):
            self.assertIn(expected, actions)

        conn = database.get_conn()
        move = conn.execute("SELECT * FROM programador_auditoria WHERE acao='PLANO_MOVIMENTADO'").fetchone()
        self.assertEqual(move["usuario_id"], self.programador["id"])
        self.assertEqual(move["usuario_nome_snapshot"], "João Silva")
        self.assertEqual((move["cnc_origem"], move["cnc_destino"]), ("CNC01", "CNC02"))
        conn.close()

    def test_audit_list_is_filtered_paginated_and_lider_only(self):
        conn = database.get_conn()
        for index in range(55):
            main.record_programador_audit(
                conn, self.programador, "DOWNLOAD_ARQUIVO", arquivo_id=index + 1,
                arquivo_nome=f"plano-{index + 1}.dxf", cnc_destino="CNC03",
            )
        conn.commit()
        conn.close()
        result = main.programador_auditoria_lista(
            data_inicio=None, data_fim=None, usuario_id=self.programador["id"],
            acao="DOWNLOAD_ARQUIVO", cnc="CNC03", arquivo="plano", remessa=None,
            page=2, page_size=50, _user=self.lider,
        )
        self.assertEqual(result["total"], 55)
        self.assertEqual(len(result["items"]), 5)
        self.assertEqual(result["pages"], 2)


if __name__ == "__main__":
    unittest.main()
