from datetime import datetime, timezone
import unittest

from backend.cnc_assistant import normalize_machine, normalize_status, readable_duration_since, stale_status


class CncAssistantTests(unittest.TestCase):
    def test_normalize_common_statuses(self):
        self.assertEqual(normalize_status("USINANDO"), "usinando")
        self.assertEqual(normalize_status("EM_EXECUCAO"), "usinando")
        self.assertEqual(normalize_status("MANUTENCAO"), "manutencao")
        self.assertEqual(normalize_status("PARADA"), "parada_nao_programada")
        self.assertEqual(normalize_status("PARADA PROGRAMADA"), "parada_programada")
        self.assertEqual(normalize_status("DESLIGADA"), "desligada")
        self.assertEqual(normalize_status("SEM COMUNICACAO"), "sem_comunicacao")

    def test_normalize_machine_uses_real_fields(self):
        machine = normalize_machine(
            {
                "id": "cnc01",
                "nome": "CNC 01",
                "status": "PARADA",
                "status_desde": "2026-07-09T07:25:00-03:00",
                "operador_nome": "",
            },
            arquivo_atual="SUPORTE-125.mpr",
            ultima_comunicacao="2026-07-09T08:45:20-03:00",
        )

        data = machine.as_dict(now=datetime(2026, 7, 9, 8, 45, 0, tzinfo=timezone.utc))
        self.assertEqual(data["id"], "CNC01")
        self.assertEqual(data["status"], "parada_nao_programada")
        self.assertEqual(data["arquivo_atual"], "SUPORTE-125.mpr")
        self.assertIsNone(data["operador"])
        self.assertEqual(data["motivo_parada"], "PARADA")
        self.assertEqual(data["ultima_comunicacao"], "2026-07-09T08:45:20-03:00")

    def test_readable_duration_minutes_hours_days(self):
        now = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(readable_duration_since("2026-07-09T11:35:00+00:00", now), "25min")
        self.assertEqual(readable_duration_since("2026-07-09T09:45:00+00:00", now), "2h15min")
        self.assertEqual(readable_duration_since("2026-07-07T10:00:00+00:00", now), "2 dias e 2h")
        self.assertEqual(readable_duration_since(None, now), "nao informado")

    def test_stale_status_recent_communication_is_updated(self):
        now = datetime(2026, 7, 9, 13, 44, 33)
        self.assertFalse(stale_status("2026-07-09T13:43:35", now))

    def test_stale_status_exact_limit_is_updated(self):
        now = datetime(2026, 7, 9, 13, 44, 33)
        self.assertFalse(stale_status("2026-07-09T13:39:33", now))

    def test_stale_status_above_limit_is_stale(self):
        now = datetime(2026, 7, 9, 13, 44, 33)
        self.assertTrue(stale_status("2026-07-09T13:39:32", now))

    def test_stopped_machine_for_hours_but_recent_communication_is_updated(self):
        machine = normalize_machine(
            {
                "id": "CNC02",
                "nome": "CNC 02",
                "status": "PARADA",
                "status_desde": "2026-07-09T08:00:00",
                "operador_nome": "",
            },
            ultima_comunicacao="2026-07-09T13:43:35",
        )
        data = machine.as_dict(now=datetime(2026, 7, 9, 13, 44, 33))
        self.assertEqual(data["status"], "parada_nao_programada")
        self.assertFalse(data["dados_desatualizados"])

    def test_running_machine_without_recent_communication_is_stale(self):
        machine = normalize_machine(
            {
                "id": "CNC03",
                "nome": "CNC 03",
                "status": "USINANDO",
                "status_desde": "2026-07-09T13:44:00",
                "operador_nome": "",
            },
            ultima_comunicacao="2026-07-09T13:30:00",
        )
        data = machine.as_dict(now=datetime(2026, 7, 9, 13, 44, 33))
        self.assertEqual(data["status"], "usinando")
        self.assertTrue(data["dados_desatualizados"])

    def test_machine_without_communication_is_indeterminate(self):
        machine = normalize_machine(
            {
                "id": "CNC04",
                "nome": "CNC 04",
                "status": "PARADA",
                "status_desde": "2026-07-09T08:00:00",
                "operador_nome": "",
            },
            ultima_comunicacao=None,
        )
        data = machine.as_dict(now=datetime(2026, 7, 9, 13, 44, 33))
        self.assertIsNone(data["ultima_comunicacao"])
        self.assertIsNone(data["dados_desatualizados"])


if __name__ == "__main__":
    unittest.main()
