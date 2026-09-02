from http.cookies import SimpleCookie
from pathlib import Path
import json
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from fastapi import HTTPException, Response

import backend.db as database
import backend.main as main
from backend.programador_admin import (
    create_user, ensure_programador_admin_schema, list_users, reset_user_password,
    set_user_active, update_user,
)
from backend.programador_auth import (
    SESSION_COOKIE_NAME, authenticate_programador, complete_first_access,
    create_or_update_user, create_session, resolve_session, verify_password,
)


def request_with(token=None):
    return SimpleNamespace(cookies={SESSION_COOKIE_NAME: token} if token else {})


class ProgramadorDevAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = database.DB_PATH
        database.DB_PATH = Path(self.tmp.name) / "dev-admin.db"
        conn = database.get_conn()
        ensure_programador_admin_schema(conn)
        self.dev = create_or_update_user(conn, nome="Henrique DEV", login="henrique.dev", password="Dev-forte-01", role="dev")
        self.programador = create_or_update_user(conn, nome="João Silva", login="joao", password="Senha-forte-01", role="programador")
        self.lider = create_or_update_user(conn, nome="Maria Souza", login="maria", password="Senha-forte-02", role="lider")
        conn.commit(); conn.close()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def connect(self):
        return database.get_conn()

    def temp_user(self, role="programador", suffix="novo"):
        conn = self.connect(); conn.execute("BEGIN")
        user = create_user(conn, dev=self.dev, nome=f"Usuário {suffix}", login=suffix, password="Temporaria-01", role=role)
        conn.commit(); conn.close()
        return user

    def login_token(self, login, password):
        response = Response()
        result = main.programador_login(main.ProgramadorLoginRequest(login=login, senha=password), response)
        cookie = SimpleCookie(); cookie.load(response.headers["set-cookie"])
        return result, cookie[SESSION_COOKIE_NAME].value

    # 1
    def test_dev_acessa_administracao(self):
        _, token = self.login_token("henrique.dev", "Dev-forte-01")
        self.assertEqual(main.require_dev(request_with(token))["role"], "dev")

    # 2
    def test_programador_nao_acessa_administracao(self):
        _, token = self.login_token("joao", "Senha-forte-01")
        with self.assertRaises(HTTPException) as ctx: main.require_dev(request_with(token))
        self.assertEqual(ctx.exception.status_code, 403)

    # 3
    def test_lider_nao_acessa_administracao(self):
        _, token = self.login_token("maria", "Senha-forte-02")
        with self.assertRaises(HTTPException) as ctx: main.require_dev(request_with(token))
        self.assertEqual(ctx.exception.status_code, 403)

    # 4
    def test_dev_cria_programador(self):
        user = self.temp_user("programador", "novo.programador")
        self.assertEqual(user["role"], "programador"); self.assertTrue(user["must_change_password"])

    # 5
    def test_dev_cria_lider(self):
        user = self.temp_user("lider", "novo.lider")
        self.assertEqual(user["role"], "lider"); self.assertTrue(user["must_change_password"])

    # 6
    def test_login_com_senha_inicial(self):
        self.temp_user(suffix="inicial")
        conn = self.connect(); self.assertIsNotNone(authenticate_programador(conn, "inicial", "Temporaria-01")); conn.close()

    # 7
    def test_login_informa_primeiro_acesso_obrigatorio(self):
        self.temp_user(suffix="redirecionar")
        result, _ = self.login_token("redirecionar", "Temporaria-01")
        self.assertTrue(result["requires_password_change"])

    # 8
    def test_primeiro_acesso_bloqueia_api_operacional(self):
        self.temp_user(suffix="bloqueado")
        _, token = self.login_token("bloqueado", "Temporaria-01")
        with self.assertRaises(HTTPException) as ctx: main.require_programador_auth(request_with(token))
        self.assertEqual(ctx.exception.status_code, 403)

    # 9
    def test_cria_nova_senha(self):
        user = self.temp_user(suffix="troca")
        conn = self.connect(); token, _ = create_session(conn, user["id"])
        updated = complete_first_access(conn, usuario_id=user["id"], new_password="Definitiva-02", current_token=token)
        conn.commit(); conn.close()
        self.assertFalse(updated["must_change_password"]); self.assertTrue(updated["password_changed_at"])

    # 10
    def test_login_com_senha_definitiva(self):
        user = self.temp_user(suffix="definitiva")
        conn = self.connect(); complete_first_access(conn, usuario_id=user["id"], new_password="Definitiva-02", current_token=None); conn.commit()
        self.assertIsNotNone(authenticate_programador(conn, "definitiva", "Definitiva-02")); conn.close()

    # 11
    def test_senha_temporaria_antiga_deixa_de_funcionar(self):
        user = self.temp_user(suffix="antiga")
        conn = self.connect(); complete_first_access(conn, usuario_id=user["id"], new_password="Definitiva-02", current_token=None); conn.commit()
        self.assertIsNone(authenticate_programador(conn, "antiga", "Temporaria-01")); conn.close()

    # 12
    def test_dev_redefine_senha_e_revoga_sessao(self):
        conn = self.connect(); token, _ = create_session(conn, self.programador["id"])
        updated = reset_user_password(conn, dev=self.dev, usuario_id=self.programador["id"], temporary_password="Temporaria-99")
        conn.commit(); self.assertTrue(updated["must_change_password"]); self.assertIsNone(resolve_session(conn, token)); conn.close()

    # 13
    def test_redefinicao_cria_novo_bloqueio_de_troca(self):
        conn = self.connect(); reset_user_password(conn, dev=self.dev, usuario_id=self.programador["id"], temporary_password="Temporaria-99"); conn.commit(); conn.close()
        _, token = self.login_token("joao", "Temporaria-99")
        with self.assertRaises(HTTPException): main.require_programador_auth(request_with(token))

    # 14
    def test_desativacao_revoga_sessoes(self):
        conn = self.connect(); token, _ = create_session(conn, self.programador["id"])
        set_user_active(conn, dev=self.dev, usuario_id=self.programador["id"], active=False); conn.commit()
        self.assertIsNone(resolve_session(conn, token)); conn.close()

    # 15
    def test_usuario_inativo_nao_faz_login(self):
        conn = self.connect(); set_user_active(conn, dev=self.dev, usuario_id=self.programador["id"], active=False); conn.commit()
        self.assertIsNone(authenticate_programador(conn, "joao", "Senha-forte-01")); conn.close()

    # 16
    def test_reativacao_libera_novo_login(self):
        conn = self.connect(); set_user_active(conn, dev=self.dev, usuario_id=self.programador["id"], active=False)
        set_user_active(conn, dev=self.dev, usuario_id=self.programador["id"], active=True); conn.commit()
        self.assertIsNotNone(authenticate_programador(conn, "joao", "Senha-forte-01")); conn.close()

    # 17
    def test_altera_programador_para_lider(self):
        conn = self.connect(); user = update_user(conn, dev=self.dev, usuario_id=self.programador["id"], nome="João Silva", login="joao", role="lider"); conn.commit(); conn.close()
        self.assertEqual(user["role"], "lider")

    # 18
    def test_altera_lider_para_programador(self):
        conn = self.connect(); user = update_user(conn, dev=self.dev, usuario_id=self.lider["id"], nome="Maria Souza", login="maria", role="programador"); conn.commit(); conn.close()
        self.assertEqual(user["role"], "programador")

    # 19
    def test_acoes_administrativas_sao_auditadas(self):
        user = self.temp_user(suffix="auditado")
        conn = self.connect(); update_user(conn, dev=self.dev, usuario_id=user["id"], nome="Auditado", login="auditado", role="lider")
        reset_user_password(conn, dev=self.dev, usuario_id=user["id"], temporary_password="Outra-temp-03")
        set_user_active(conn, dev=self.dev, usuario_id=user["id"], active=False); set_user_active(conn, dev=self.dev, usuario_id=user["id"], active=True); conn.commit()
        actions = {row[0] for row in conn.execute("SELECT acao FROM programador_admin_auditoria")}; conn.close()
        self.assertTrue({"USUARIO_CRIADO", "PERFIL_ALTERADO", "SENHA_REDEFINIDA", "USUARIO_DESATIVADO", "USUARIO_ATIVADO"}.issubset(actions))

    # 20
    def test_auditoria_nao_registra_senhas_nem_hashes(self):
        secret = "NaoPodeLogar-8274"; conn = self.connect()
        user = create_user(conn, dev=self.dev, nome="Sem Senha", login="sem.senha", password=secret, role="programador")
        reset_user_password(conn, dev=self.dev, usuario_id=user["id"], temporary_password="NovaNaoLogar-8275"); conn.commit()
        dump = json.dumps([dict(row) for row in conn.execute("SELECT * FROM programador_admin_auditoria")]); conn.close()
        self.assertNotIn(secret, dump); self.assertNotIn("NovaNaoLogar-8275", dump); self.assertNotIn("scrypt$", dump)


if __name__ == "__main__":
    unittest.main()
