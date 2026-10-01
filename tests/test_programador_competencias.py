import sqlite3
import unittest

from backend.programador_competencias import (
    COLABORADORES,
    OPERACOES,
    CompetenciaError,
    ensure_schema,
    get_matrix,
    set_levels,
)


ACTOR = {"id": 7, "nome": "Programador teste", "role": "programador"}


class ProgramadorCompetenciasTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY)")
        self.conn.execute("INSERT INTO usuarios (id) VALUES (7)")
        ensure_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_matrix_has_requested_people_operations_and_five_levels(self):
        matrix = get_matrix(self.conn)
        self.assertEqual([p["nome"] for p in matrix["colaboradores"]], [
            "Matheus", "Paulo", "Dirley", "Lucas", "Bruno", "Aleixo",
        ])
        self.assertEqual(len(matrix["operacoes"]), 12)
        self.assertEqual(matrix["operacoes"][-1]["nome"], "Suporte CF")
        self.assertEqual([level["nivel"] for level in matrix["niveis"]], [0, 1, 2, 3, 4])

    def test_save_is_shared_persistent_and_audited(self):
        result = set_levels(self.conn, [
            {"colaborador_id": "matheus", "operacao_id": "zig-zag", "nivel": 3},
            {"colaborador_id": "paulo", "operacao_id": "zig-zag", "nivel": 4},
        ], ACTOR)
        self.conn.commit()
        self.assertEqual(result["avaliacoes"]["matheus"]["zig-zag"]["nivel"], 3)
        self.assertEqual(get_matrix(self.conn)["avaliacoes"]["paulo"]["zig-zag"]["nivel"], 4)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM programador_competencias_historico").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM programador_auditoria").fetchone()[0], 2)

    def test_second_save_preserves_history(self):
        set_levels(self.conn, [{"colaborador_id": "lucas", "operacao_id": "montagem", "nivel": 1}], ACTOR)
        set_levels(self.conn, [{"colaborador_id": "lucas", "operacao_id": "montagem", "nivel": 2}], ACTOR)
        history = self.conn.execute(
            "SELECT nivel_anterior, nivel_novo FROM programador_competencias_historico ORDER BY id"
        ).fetchall()
        self.assertEqual([tuple(row) for row in history], [(None, 1), (1, 2)])

    def test_invalid_values_are_rejected_before_writing(self):
        with self.assertRaises(CompetenciaError):
            set_levels(self.conn, [{"colaborador_id": "outro", "operacao_id": "zig-zag", "nivel": 3}], ACTOR)
        with self.assertRaises(CompetenciaError):
            set_levels(self.conn, [{"colaborador_id": "matheus", "operacao_id": "zig-zag", "nivel": 5}], ACTOR)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM programador_competencias").fetchone()[0], 0)

    def test_catalog_ids_are_unique(self):
        self.assertEqual(len({item["id"] for item in COLABORADORES}), len(COLABORADORES))
        self.assertEqual(len({item["id"] for item in OPERACOES}), len(OPERACOES))


if __name__ == "__main__":
    unittest.main()
