from datetime import datetime, timezone
import unittest

from backend.cnc_assistant import normalize_machine, normalize_status, readable_duration_since


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


if __name__ == "__main__":
    unittest.main()
