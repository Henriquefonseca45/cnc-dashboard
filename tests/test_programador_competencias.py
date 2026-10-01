import sqlite3
import unittest

from backend.programador_competencias import (
    COLABORADORES, OPERACOES, CompetenciaError, ensure_schema, get_matrix,
    resolve_colaborador, review_levels, set_self_levels,
)

MATHEUS = {"id": 7, "nome": "Matheus da Silva", "login": "matheus", "role": "programador"}
PAULO = {"id": 8, "nome": "Paulo", "login": "paulo", "role": "programador"}
LEADER = {"id": 9, "nome": "Líder CNC", "login": "lider", "role": "lider"}


class ProgramadorCompetenciasTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        self.conn.executemany("INSERT INTO usuarios (id) VALUES (?)", [(7,), (8,), (9,)])
        ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_catalog_and_user_link(self):
        matrix = get_matrix(self.conn, LEADER)
        self.assertEqual([p["nome"] for p in matrix["colaboradores"]], [
            "Matheus", "Paulo", "Dirley", "Lucas", "Bruno", "Aleixo",
        ])
        self.assertEqual(len(matrix["operacoes"]), 18)
        self.assertEqual(len([item for item in matrix["operacoes"] if item["categoria"] == "desenho"]), 12)
        self.assertEqual(len([item for item in matrix["operacoes"] if item["categoria"] == "programacao"]), 6)
        self.assertEqual([level["nivel"] for level in matrix["niveis"]], [0, 1, 2, 3, 4])
        self.assertEqual(resolve_colaborador(MATHEUS)["id"], "matheus")

    def test_user_only_sees_and_updates_own_assessment(self):
        result = set_self_levels(self.conn, [
            {"operacao_id": "zig-zag", "nivel": 3},
            {"operacao_id": "montagem", "nivel": 2},
        ], MATHEUS)
        self.assertEqual(result["colaboradores"], [{"id": "matheus", "nome": "Matheus"}])
        self.assertEqual(result["avaliacoes"]["matheus"]["zig-zag"]["autoavaliacaoNivel"], 3)
        self.assertEqual(result["avaliacoes"]["matheus"]["zig-zag"]["status"], "PENDENTE")
        self.assertNotIn("paulo", result["avaliacoes"])

    def test_leader_confirms_or_adjusts_and_only_validated_level_counts(self):
        set_self_levels(self.conn, [{"operacao_id": "zig-zag", "nivel": 4}], MATHEUS)
        pending = get_matrix(self.conn, LEADER)["avaliacoes"]["matheus"]["zig-zag"]
        self.assertIsNone(pending["nivelValidado"])
        validated = review_levels(self.conn, [
            {"colaborador_id": "matheus", "operacao_id": "zig-zag", "nivel": 3},
        ], LEADER)["avaliacoes"]["matheus"]["zig-zag"]
        self.assertEqual(validated["autoavaliacaoNivel"], 4)
        self.assertEqual(validated["nivelValidado"], 3)
        self.assertEqual(validated["status"], "VALIDADO")

    def test_new_self_assessment_returns_validation_to_pending(self):
        set_self_levels(self.conn, [{"operacao_id": "montagem", "nivel": 2}], MATHEUS)
        review_levels(self.conn, [{"colaborador_id": "matheus", "operacao_id": "montagem", "nivel": 2}], LEADER)
        result = set_self_levels(self.conn, [{"operacao_id": "montagem", "nivel": 3}], MATHEUS)
        item = result["avaliacoes"]["matheus"]["montagem"]
        self.assertEqual(item["status"], "PENDENTE")
        self.assertEqual(item["nivelValidado"], 2)

    def test_programmer_cannot_review_and_unlinked_user_cannot_assess(self):
        set_self_levels(self.conn, [{"operacao_id": "zig-zag", "nivel": 1}], PAULO)
        with self.assertRaisesRegex(CompetenciaError, "Somente o líder"):
            review_levels(self.conn, [{"colaborador_id": "paulo", "operacao_id": "zig-zag", "nivel": 1}], MATHEUS)
        with self.assertRaisesRegex(CompetenciaError, "não está vinculado"):
            set_self_levels(self.conn, [{"operacao_id": "zig-zag", "nivel": 1}], {"id": 10, "nome": "Outro", "login": "outro", "role": "programador"})

    def test_history_distinguishes_self_assessment_and_leader_validation(self):
        set_self_levels(self.conn, [{"operacao_id": "zig-zag", "nivel": 3}], MATHEUS)
        review_levels(self.conn, [{"colaborador_id": "matheus", "operacao_id": "zig-zag", "nivel": 3}], LEADER)
        events = [row[0] for row in self.conn.execute("SELECT evento FROM programador_competencias_historico ORDER BY id")]
        self.assertEqual(events, ["AUTOAVALIACAO", "VALIDACAO_LIDER"])
        actions = [row[0] for row in self.conn.execute("SELECT acao FROM programador_auditoria ORDER BY id")]
        self.assertEqual(actions, ["COMPETENCIA_AUTOAVALIADA", "COMPETENCIA_VALIDADA"])

    def test_catalog_ids_are_unique(self):
        self.assertEqual(len({item["id"] for item in COLABORADORES}), len(COLABORADORES))
        self.assertEqual(len({item["id"] for item in OPERACOES}), len(OPERACOES))
        self.assertIn("programacao-zig-zag", {item["id"] for item in OPERACOES})
        self.assertIn("zig-zag", {item["id"] for item in OPERACOES})

    def test_first_version_rows_migrate_to_pending_self_assessment(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE programador_competencias (
                colaborador_id TEXT, operacao_id TEXT, nivel INTEGER,
                atualizado_em TEXT, atualizado_por_usuario_id INTEGER,
                atualizado_por_nome TEXT, PRIMARY KEY(colaborador_id, operacao_id)
            )
        """)
        conn.execute("""
            CREATE TABLE programador_competencias_historico (
                id INTEGER PRIMARY KEY, colaborador_id TEXT, operacao_id TEXT,
                nivel_anterior INTEGER, nivel_novo INTEGER, alterado_em TEXT,
                alterado_por_usuario_id INTEGER, alterado_por_nome TEXT
            )
        """)
        conn.execute("INSERT INTO programador_competencias VALUES ('matheus','zig-zag',2,'2026-10-01T12:00:00Z',7,'Matheus')")
        ensure_schema(conn)
        item = get_matrix(conn, LEADER)["avaliacoes"]["matheus"]["zig-zag"]
        self.assertEqual(item["autoavaliacaoNivel"], 2)
        self.assertEqual(item["status"], "PENDENTE")
        self.assertIsNone(item["nivelValidado"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
