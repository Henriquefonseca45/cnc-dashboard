from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.programador_auth import (
    authenticate_programador,
    create_or_update_user,
    create_session,
    ensure_programador_auth_schema,
    hash_password,
    normalize_role,
    resolve_session,
    revoke_session,
    verify_password,
)
from backend.programador_audit import (
    audit_filter_options,
    ensure_programador_audit_schema,
    list_programador_audit,
    record_programador_audit,
)


class ProgramadorAuthAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "programador.db"
        conn = self.connect()
        conn.execute(
            """
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL, login TEXT NOT NULL UNIQUE, senha TEXT NOT NULL,
                nivel TEXT NOT NULL DEFAULT 'OPERADOR', maquina_id TEXT, criado_em TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO usuarios (nome, login, senha, nivel, criado_em) VALUES ('Legado', 'legado', '123', 'OPERADOR', '2026-09-01')"
        )
        ensure_programador_auth_schema(conn)
        ensure_programador_audit_schema(conn)
        self.programador = create_or_update_user(
            conn, nome="João Silva", login="joao", password="Senha-forte-01", role="programador"
        )
        self.lider = create_or_update_user(
            conn, nome="Maria Souza", login="maria", password="Senha-forte-02", role="lider"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_migrates_legacy_plaintext_password_out_of_database(self):
        conn = self.connect()
        row = conn.execute("SELECT senha, senha_hash FROM usuarios WHERE login='legado'").fetchone()
        self.assertEqual(row["senha"], "")
        self.assertNotIn("123", row["senha_hash"])
        self.assertTrue(verify_password("123", row["senha_hash"]))
        conn.close()

    def test_password_hash_is_scrypt_salted_and_enforces_new_password_policy(self):
        first = hash_password("Senha-forte-03")
        second = hash_password("Senha-forte-03")
        self.assertTrue(first.startswith("scrypt$"))
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("Senha-forte-03", first))
        self.assertFalse(verify_password("outra-senha", first))
        with self.assertRaisesRegex(ValueError, "8 caracteres"):
            hash_password("curta")

    def test_roles_use_stable_internal_values(self):
        self.assertEqual(normalize_role("LIDER"), "lider")
        self.assertEqual(normalize_role("Programador"), "programador")
        with self.assertRaises(ValueError):
            normalize_role("admin")

    def test_valid_programador_and_lider_can_authenticate(self):
        conn = self.connect()
        self.assertEqual(authenticate_programador(conn, "JOAO", "Senha-forte-01")["role"], "programador")
        self.assertEqual(authenticate_programador(conn, "maria", "Senha-forte-02")["role"], "lider")
        conn.close()

    def test_wrong_password_is_rejected(self):
        conn = self.connect()
        self.assertIsNone(authenticate_programador(conn, "joao", "Senha-errada"))
        conn.close()

    def test_inactive_user_is_rejected_and_legacy_role_cannot_enter(self):
        conn = self.connect()
        conn.execute("UPDATE usuarios SET ativo=0 WHERE login='joao'")
        conn.commit()
        self.assertIsNone(authenticate_programador(conn, "joao", "Senha-forte-01"))
        self.assertIsNone(authenticate_programador(conn, "legado", "123"))
        conn.close()

    def test_cannot_take_over_login_from_another_module(self):
        conn = self.connect()
        with self.assertRaisesRegex(ValueError, "outro módulo"):
            create_or_update_user(
                conn, nome="Outro", login="legado", password="Senha-forte-09", role="lider"
            )
        conn.close()

    def test_server_session_survives_new_connection_and_logout_revokes_it(self):
        conn = self.connect()
        token, expires = create_session(conn, self.programador["id"])
        conn.commit()
        conn.close()
        self.assertTrue(expires)

        conn = self.connect()
        self.assertEqual(resolve_session(conn, token)["login"], "joao")
        revoke_session(conn, token)
        conn.commit()
        self.assertIsNone(resolve_session(conn, token))
        conn.close()

    def test_role_is_read_from_database_on_every_session_resolution(self):
        conn = self.connect()
        token, _ = create_session(conn, self.programador["id"])
        conn.execute("UPDATE usuarios SET role='lider' WHERE id=?", (self.programador["id"],))
        conn.commit()
        self.assertEqual(resolve_session(conn, token)["role"], "lider")
        conn.close()

    def test_audit_preserves_user_and_file_snapshots(self):
        conn = self.connect()
        audit_id = record_programador_audit(
            conn, self.programador, "ARQUIVO_IMPORTADO", arquivo_id=42,
            arquivo_nome="48572.dxf", entidade_id=42, valor_novo={"priority": "normal"},
        )
        conn.execute("UPDATE usuarios SET nome='João Renomeado' WHERE id=?", (self.programador["id"],))
        conn.commit()
        row = conn.execute("SELECT * FROM programador_auditoria WHERE id=?", (audit_id,)).fetchone()
        self.assertEqual(row["usuario_nome_snapshot"], "João Silva")
        self.assertEqual(row["arquivo_nome_snapshot"], "48572.dxf")
        conn.close()

    def test_audit_is_append_only(self):
        conn = self.connect()
        audit_id = record_programador_audit(conn, self.programador, "DOWNLOAD_ARQUIVO", arquivo_id=1)
        conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE programador_auditoria SET acao='ALTERADO' WHERE id=?", (audit_id,))
        conn.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM programador_auditoria WHERE id=?", (audit_id,))
        conn.close()

    def test_audit_rolls_back_with_business_transaction(self):
        conn = self.connect()
        conn.execute("BEGIN")
        record_programador_audit(conn, self.programador, "PLANO_MOVIMENTADO", arquivo_id=10)
        conn.rollback()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM programador_auditoria").fetchone()[0], 0)
        conn.close()

    def test_filters_and_pagination_are_server_side(self):
        conn = self.connect()
        record_programador_audit(conn, self.programador, "ARQUIVO_IMPORTADO", arquivo_id=10, arquivo_nome="48560.dxf", cnc_destino="CNC01")
        record_programador_audit(conn, self.lider, "PRIORIDADE_ALTERADA", arquivo_id=11, arquivo_nome="48565.dxf", valor_anterior="normal", valor_novo="high")
        record_programador_audit(conn, self.programador, "PLANO_MOVIMENTADO", arquivo_id=12, arquivo_nome="48572.dxf", cnc_origem="CNC01", cnc_destino="CNC03")
        conn.commit()
        filtered = list_programador_audit(conn, usuario_id=self.programador["id"], cnc="cnc03", arquivo="48572", page=1, page_size=1)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["acao"], "PLANO_MOVIMENTADO")
        paged = list_programador_audit(conn, page=2, page_size=2)
        self.assertEqual(paged["total"], 3)
        self.assertEqual(paged["page"], 2)
        self.assertEqual(len(paged["items"]), 1)
        conn.close()

    def test_filter_options_come_from_immutable_snapshots(self):
        conn = self.connect()
        record_programador_audit(conn, self.programador, "ARQUIVO_EXCLUIDO", arquivo_id=9)
        conn.commit()
        options = audit_filter_options(conn)
        self.assertEqual(options["users"][0]["nome"], "João Silva")
        self.assertEqual(options["actions"], ["ARQUIVO_EXCLUIDO"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
