import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from fastapi import HTTPException, UploadFile
from backend import cnc_feeding as feeding, db, init_db, main


class CncFeedingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path, self.old_dxf = db.DB_PATH, main.DXF_DIR
        db.DB_PATH = Path(self.tmp.name) / 'feeding.db'
        main.DXF_DIR = Path(self.tmp.name) / 'dxf'
        main.DXF_DIR.mkdir()
        with redirect_stdout(StringIO()):
            init_db.main()
        self.actor = {'id': None, 'nome': 'Programador teste', 'role': 'programador'}
        self.number = 0
        with db.get_conn() as conn:
            main._ensure_maquinas_cols(conn)
            conn.execute("UPDATE maquinas SET status='PARADA',operador_nome='Operador teste' WHERE id IN ('CNC01','CNC02')")
        conn.close()

    def tearDown(self):
        db.DB_PATH, main.DXF_DIR = self.old_path, self.old_dxf
        self.tmp.cleanup()

    def upload(self, priority='normal', cncs=None, name=None):
        self.number += 1
        name = name or f'plano-{self.number}.dxf'
        result = asyncio.run(main.upload_classified_plans(
            [UploadFile(filename=name, file=BytesIO(b'0\nEOF\n'))],
            json.dumps([{'name': name, 'priority': priority, 'compatible_cnc_ids': cncs or ['CNC01']}]), self.actor))
        return result['items'][0]['id']

    def rows(self, cnc='CNC01'):
        conn = db.get_conn()
        try:
            return feeding.queue(conn, cnc)
        finally:
            conn.close()

    def start(self, plan, cnc='CNC01'):
        item = next(x for x in self.rows(cnc) if x['arquivo_id'] == plan)
        conn = db.get_conn()
        conn.execute('UPDATE fila_itens SET tempo_estimado_seg=60 WHERE id=?', (item['id'],))
        conn.commit(); conn.close()
        main.set_status_fila_item(cnc, main.FilaStatusRequest(id=item['id'], status='USINANDO'))
        return item['id']

    def normal_queue(self, priority='normal'):
        first = self.upload()
        item = self.start(first)
        second = self.upload(priority)
        return first, item, second

    def overview(self):
        return main.feeding_overview(self.actor)

    def test_normal_medium_high_import(self):
        for priority in ('normal', 'medium', 'high'):
            plan = self.upload(priority, ['CNC03'])
            self.assertEqual(next(p for p in self.overview()['waiting'] if p['id'] == plan)['priority'], priority)

    def test_empty_queue_is_zero_without_legacy_warning(self):
        machine = next(m for m in self.overview()['machines'] if m['id'] == 'CNC01')
        self.assertEqual(machine['items'], [])
        self.assertFalse(machine['inconsistente'])
        self.assertFalse(machine['lotada'])

    def test_reserves_only_compatible_cnc(self):
        plan = self.upload(cncs=['CNC02'])
        self.assertFalse(self.rows())
        self.assertEqual(self.rows('CNC02')[0]['arquivo_id'], plan)

    def test_idle_cnc_waits_for_operator_start(self):
        self.upload(); self.upload()
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['status'], 'AGUARDANDO')
        self.assertEqual(len(self.overview()['waiting']), 1)

    def test_normal_queue_is_one_running_one_next(self):
        self.normal_queue(); self.upload()
        self.assertEqual([x['status'] for x in self.rows()], ['EM_EXECUCAO', 'AGUARDANDO'])
        self.assertEqual(len(self.overview()['waiting']), 1)

    def test_facilitator_next_plans_matches_official_waiting_queue(self):
        conn = db.get_conn()
        conn.execute("UPDATE maquinas SET status='DESLIGADA' WHERE id='CNC01'")
        conn.commit()
        conn.close()
        self.upload(name='plano 20KP.dxf')
        self.upload(name='plano 80KP.dxf')
        official = self.overview()['waiting']
        facilitator = main.facilitador_proximos_planos()['items']
        self.assertEqual([item['id'] for item in facilitator], [item['id'] for item in official])
        self.assertEqual(facilitator[0]['compatible_cnc_ids'], official[0]['compatible_cnc_ids'])

    def test_facilitator_download_is_restricted_to_official_waiting_queue(self):
        conn = db.get_conn()
        conn.execute("UPDATE maquinas SET status='DESLIGADA' WHERE id='CNC01'")
        conn.commit()
        conn.close()
        waiting_plan = self.upload(name='plano aguardando.dxf')

        response = main.facilitador_download_proximo_plano(waiting_plan)
        self.assertTrue(Path(response.path).is_file())
        self.assertEqual(response.filename, 'plano aguardando.dxf')

        conn = db.get_conn()
        conn.execute("UPDATE arquivos_dxf SET status='CANCELADO' WHERE id=?", (waiting_plan,))
        conn.commit()
        conn.close()

        with self.assertRaises(HTTPException) as context:
            main.facilitador_download_proximo_plano(waiting_plan)
        self.assertEqual(context.exception.status_code, 404)

    def test_higher_priority_displaces_without_returning_to_pool(self):
        first, _, second = self.normal_queue()
        third = self.upload('high')
        self.assertEqual([x['arquivo_id'] for x in self.rows()], [first, third, second])
        self.assertEqual(self.rows()[2]['deslocado_por_prioridade'], 1)
        self.assertEqual(self.rows()[2]['maquina_id'], 'CNC01')
        self.assertFalse(self.overview()['waiting'])

    def test_medium_displaces_normal(self):
        _, _, second = self.normal_queue()
        self.upload('medium')
        self.assertEqual(self.rows()[2]['arquivo_id'], second)

    def test_equal_priority_keeps_fifo(self):
        _, _, second = self.normal_queue('high')
        third = self.upload('high')
        self.assertEqual(self.rows()[1]['arquivo_id'], second)
        self.assertEqual(self.overview()['waiting'][0]['id'], third)

    def test_normal_priority_prefers_greater_thickness_when_entry_time_matches(self):
        conn = db.get_conn()
        try:
            conn.execute("UPDATE maquinas SET status='DESLIGADA' WHERE id='CNC01'")
            conn.commit()
        finally:
            conn.close()
        thin = self.upload(name='09 - 09 - 2026 - 01 - 20KP RANCAN.dxf')
        thick = self.upload(name='09 - 09 - 2026 - 02 - 80KP RANCAN.dxf')
        middle = self.upload(name='09 - 09 - 2026 - 03 - 40KP RANCAN.dxf')
        conn = db.get_conn()
        conn.execute(
            "UPDATE arquivos_dxf SET criado_em='2026-09-09T08:00:00' WHERE id IN (?,?,?)",
            (thin, thick, middle),
        )
        conn.commit()
        conn.close()
        self.assertEqual([p['id'] for p in self.overview()['waiting']], [thick, middle, thin])

    def test_normal_priority_prefers_oldest_before_greater_thickness(self):
        conn = db.get_conn()
        conn.execute("UPDATE maquinas SET status='DESLIGADA' WHERE id='CNC01'")
        conn.commit()
        conn.close()
        older_thin = self.upload(name='plano antigo 20KP.dxf')
        newer_thick = self.upload(name='plano novo 80KP.dxf')
        conn = db.get_conn()
        conn.execute("UPDATE arquivos_dxf SET criado_em='2026-09-09T07:00:00' WHERE id=?", (older_thin,))
        conn.execute("UPDATE arquivos_dxf SET criado_em='2026-09-09T08:00:00' WHERE id=?", (newer_thick,))
        conn.commit()
        conn.close()
        self.assertEqual([p['id'] for p in self.overview()['waiting']], [older_thin, newer_thick])

    def test_normal_without_thickness_keeps_fifo_after_numbered_plans(self):
        conn = db.get_conn()
        try:
            conn.execute("UPDATE maquinas SET status='DESLIGADA' WHERE id='CNC01'")
            conn.commit()
        finally:
            conn.close()
        first_unknown = self.upload(name='plano sem medida 1.dxf')
        numbered = self.upload(name='plano 18MDF.dxf')
        second_unknown = self.upload(name='plano sem medida 2.dxf')
        conn = db.get_conn()
        conn.execute(
            "UPDATE arquivos_dxf SET criado_em='2026-09-09T08:00:00' WHERE id IN (?,?,?)",
            (first_unknown, numbered, second_unknown),
        )
        conn.commit()
        conn.close()
        self.assertEqual(
            [p['id'] for p in self.overview()['waiting']],
            [numbered, first_unknown, second_unknown],
        )

    def test_programmed_is_flag_and_blocks_displacement(self):
        _, _, second = self.normal_queue()
        item_id = self.rows()[1]['id']
        main.set_status_fila_item('CNC01', main.FilaStatusRequest(id=item_id, status='PROGRAMADO'))
        self.assertEqual(self.rows()[1]['status'], 'AGUARDANDO')
        self.assertTrue(self.rows()[1]['programado'])
        third = self.upload('high')
        self.assertEqual(self.rows()[1]['arquivo_id'], second)
        self.assertEqual(self.overview()['waiting'][0]['id'], third)

    def test_fourth_stays_waiting_even_with_higher_priority(self):
        self.normal_queue(); self.upload('medium')
        fourth = self.upload('high')
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.overview()['waiting'][0]['id'], fourth)

    def test_tries_other_compatible_cnc_when_full(self):
        self.normal_queue(); self.upload('medium')
        fourth = self.upload('high', ['CNC01', 'CNC02'])
        self.assertEqual(self.rows('CNC02')[0]['arquivo_id'], fourth)

    def test_completion_promotes_without_faking_machine_start(self):
        _, item, second = self.normal_queue()
        third = self.upload('high')
        machine = next(m for m in self.overview()['machines'] if m['id'] == 'CNC01')
        self.assertEqual([x['slot'] for x in machine['items']], ['USINANDO', 'PRÓXIMO', 'DESLOCADO POR PRIORIDADE'])
        self.assertTrue(machine['lotada'])
        self.upload('normal')  # A waiting candidate must not refill the exceptional third slot.
        main.set_status_fila_item('CNC01', main.FilaStatusRequest(id=item, status='CONCLUIDO'))
        self.assertEqual([x['arquivo_id'] for x in self.rows()], [third, second])
        self.assertTrue(all(not x['deslocado_por_prioridade'] for x in self.rows()))
        self.assertTrue(all(x['status'] == 'AGUARDANDO' for x in self.rows()))
        machine = next(m for m in self.overview()['machines'] if m['id'] == 'CNC01')
        self.assertEqual([x['slot'] for x in machine['items']], ['AGUARDANDO INÍCIO', 'PRÓXIMO'])
        self.start(third)
        self.assertEqual([x['status'] for x in self.rows()], ['EM_EXECUCAO', 'AGUARDANDO'])

    def test_agent_completion_also_refills(self):
        _, item, second = self.normal_queue()
        main.agente_cortado('CNC01', item, main.CortadoRequest())
        self.assertEqual(self.rows()[0]['arquivo_id'], second)

    def test_manual_move_validates_compatibility(self):
        plan = self.upload()
        with self.assertRaises(HTTPException):
            main.feeding_move(plan, main.FeedingMoveRequest(cnc_id='CNC02'), self.actor)
        self.assertEqual(self.rows()[0]['arquivo_id'], plan)

    def test_manual_move_and_pool_pause_resume(self):
        plan = self.upload(cncs=['CNC01', 'CNC02'])
        main.feeding_move(plan, main.FeedingMoveRequest(cnc_id='CNC02'), self.actor)
        self.assertEqual(self.rows('CNC02')[0]['arquivo_id'], plan)
        main.feeding_move(plan, main.FeedingMoveRequest(), self.actor)
        self.assertFalse(self.rows('CNC02'))
        self.assertTrue(self.overview()['waiting'][0]['alimentacao_pausada'])
        main.feeding_resume(plan, self.actor)
        self.assertEqual(len(self.rows()) + len(self.rows('CNC02')), 1)

    def test_manual_cannot_create_third_normal_or_fourth(self):
        self.normal_queue()
        extra = self.upload()
        with self.assertRaises(HTTPException):
            main.add_fila('CNC01', main.AddFilaRequest(arquivo_id=extra), self.actor)
        self.upload('high')
        with self.assertRaises(HTTPException):
            main.feeding_move(extra, main.FeedingMoveRequest(cnc_id='CNC01'), self.actor)

    def test_running_cannot_be_moved_or_replaced(self):
        first, _, _ = self.normal_queue()
        with self.assertRaises(HTTPException):
            main.feeding_move(first, main.FeedingMoveRequest(), self.actor)
        self.upload('high')
        self.assertEqual(self.rows()[0]['arquivo_id'], first)

    def test_displaced_cannot_start_or_download_before_next(self):
        self.normal_queue(); self.upload('high')
        item = self.rows()[2]['id']
        for fn in (lambda: main.agente_executar('CNC01', item), lambda: main.agente_download_fila('CNC01', item),
                   lambda: main.set_status_fila_item('CNC01', main.FilaStatusRequest(id=item, status='USINANDO'))):
            with self.assertRaises(HTTPException):
                fn()

    def test_pending_cannot_be_completed_or_changed_using_wrong_cnc(self):
        self.upload(); item = self.rows()[0]['id']
        for cnc in ('CNC01', 'CNC02'):
            with self.assertRaises(HTTPException):
                main.set_status_fila_item(cnc, main.FilaStatusRequest(id=item, status='CONCLUIDO'))

    def test_unavailable_states_block_new_reservations(self):
        for status, operator in [('DESLIGADA', 'Yuri'), ('MANUTENÇÃO', 'Yuri'), ('FALTA OPERADOR', 'Yuri'), ('PARADA', '')]:
            with db.get_conn() as conn:
                conn.execute('UPDATE maquinas SET status=?,operador_nome=? WHERE id=?', (status, operator, 'CNC01'))
            conn.close()
            self.upload()
            self.assertFalse(self.rows())

    def test_operator_assignment_triggers_distribution(self):
        main.set_operador_maquina('CNC01', main.OperadorPayload(nome=''))
        plan = self.upload()
        self.assertFalse(self.rows())
        main.set_operador_maquina('CNC01', main.OperadorPayload(nome='DANIEL'))
        self.assertEqual(self.rows()[0]['arquivo_id'], plan)

    def test_unavailability_preserves_existing_reservations(self):
        first = self.upload()
        main.set_operador_maquina('CNC01', main.OperadorPayload(nome=''))
        self.upload('high')
        self.assertEqual(self.rows()[0]['arquivo_id'], first)

    def test_priority_change_reanalyzes_waiting_pool(self):
        self.normal_queue()
        third = self.upload()
        main.update_plan_classification(third, main.PlanClassificationRequest(priority='high', compatible_cnc_ids=['CNC01']), self.actor)
        self.assertEqual(self.rows()[1]['arquivo_id'], third)

    def test_compatibility_change_releases_waiting_plan(self):
        plan = self.upload(cncs=['CNC03'])
        main.update_plan_classification(plan, main.PlanClassificationRequest(priority='normal', compatible_cnc_ids=['CNC02']), self.actor)
        self.assertEqual(self.rows('CNC02')[0]['arquivo_id'], plan)

    def test_batch_preserves_exclusive_machine_and_fifo(self):
        files = [UploadFile(filename=n, file=BytesIO(b'0\nEOF\n')) for n in ('flex.dxf', 'exclusive.dxf')]
        result = asyncio.run(main.upload_classified_plans(files, json.dumps([
            {'priority': 'high', 'compatible_cnc_ids': ['CNC01', 'CNC02']},
            {'priority': 'high', 'compatible_cnc_ids': ['CNC01']},
        ]), self.actor))
        self.assertEqual(self.rows()[0]['arquivo_id'], result['items'][1]['id'])
        self.assertEqual(self.rows('CNC02')[0]['arquivo_id'], result['items'][0]['id'])

    def test_reads_persisted_same_queue_and_audit_after_reload(self):
        self.normal_queue(); self.upload('high')
        api_queue = main.get_fila_db('CNC01', False)
        screen_queue = next(m['items'] for m in self.overview()['machines'] if m['id'] == 'CNC01')
        self.assertEqual([x['id'] for x in api_queue], [x['id'] for x in screen_queue])
        self.assertEqual(screen_queue, next(m['items'] for m in self.overview()['machines'] if m['id'] == 'CNC01'))
        self.assertIn('ALIMENTACAO_DESLOCADO', [x['acao'] for x in self.overview()['history']])

    def test_concurrent_uploads_never_duplicate_slots(self):
        barrier = threading.Barrier(2)
        def upload(index):
            barrier.wait()
            return asyncio.run(main.upload_classified_plans(
                [UploadFile(filename=f'concurrent-{index}.dxf', file=BytesIO(b'0\nEOF\n'))],
                json.dumps([{'priority': 'high', 'compatible_cnc_ids': ['CNC01']}]), self.actor))
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(upload, (1, 2)))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.overview()['waiting']), 1)

    def test_concurrent_manual_reservations_same_plan(self):
        plan = self.upload(cncs=['CNC01', 'CNC02'])
        main.feeding_move(plan, main.FeedingMoveRequest(), self.actor)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda cnc: main.feeding_move(plan, main.FeedingMoveRequest(cnc_id=cnc), self.actor), ['CNC01', 'CNC02']))
        self.assertEqual(len(self.rows()) + len(self.rows('CNC02')), 1)

    def test_migration_is_idempotent(self):
        plan = self.upload()
        conn = db.get_conn()
        feeding.ensure_schema(conn); feeding.ensure_schema(conn)
        conn.commit(); conn.close()
        self.assertEqual(self.rows()[0]['arquivo_id'], plan)

    def legacy_queue(self, count):
        conn = db.get_conn()
        for name in ('feeding_guard_v2_insert', 'feeding_guard_v2_update'):
            conn.execute(f'DROP TRIGGER {name}')
        ids = []
        for index in range(count):
            plan = conn.execute("INSERT INTO arquivos_dxf(nome,path,status,criado_em) VALUES(?,?,'DISPONIVEL','2026-09-01')",
                                (f'legacy-{index}.dxf', f'legacy-{index}.dxf')).lastrowid
            ids.append(conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES('CNC01',?,?,'AGUARDANDO','2026-09-01')", (plan, index)).lastrowid)
        feeding.ensure_schema(conn)
        conn.commit(); conn.close()
        return ids

    def test_legacy_excess_is_reported_preserved_and_can_be_consumed(self):
        ids = self.legacy_queue(5)
        before = self.rows()
        self.upload('high')
        self.assertEqual(self.rows(), before)
        overview = self.overview()
        self.assertEqual(overview['legacy_summary'], {'cncs_acima_limite': 1, 'itens_nessas_cncs': 5, 'itens_excedentes': 2})
        machine = next(m for m in overview['machines'] if m['id'] == 'CNC01')
        self.assertTrue(machine['inconsistente'])
        self.assertEqual(sum(x['slot'] == 'PRÓXIMO' for x in machine['items']), 0)
        self.assertTrue(all('LEGADO' in x['slot'] for x in machine['items'][1:]))
        conn = db.get_conn()
        conn.execute("UPDATE fila_itens SET status='EM_EXECUCAO' WHERE id=?", (ids[0],))
        conn.execute("UPDATE fila_itens SET status='CORTADO' WHERE id=?", (ids[0],))
        conn.commit(); conn.close()
        self.assertEqual(len(self.rows()), 4)

    def test_database_blocks_fourth_legacy_insert_and_reactivation(self):
        self.legacy_queue(3)
        conn = db.get_conn()
        plan = conn.execute("INSERT INTO arquivos_dxf(nome,path,status,criado_em) VALUES('extra.dxf','extra.dxf','DISPONIVEL','2026-09-01')").lastrowid
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'limite absoluto'):
            conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES('CNC01',?,4,'AGUARDANDO','2026-09-01')", (plan,))
        item = conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES('CNC01',?,4,'CANCELADO','2026-09-01')", (plan,)).lastrowid
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'limite absoluto'):
            conn.execute("UPDATE fila_itens SET status='AGUARDANDO' WHERE id=?", (item,))
        conn.execute("UPDATE fila_itens SET maquina_id='CNC02',status='AGUARDANDO' WHERE id=?", (item,))
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'limite absoluto'):
            conn.execute("UPDATE fila_itens SET maquina_id='CNC01' WHERE id=?", (item,))
        conn.rollback(); conn.close()

    def test_database_blocks_normal_third_on_unmanaged_queue(self):
        self.legacy_queue(2)
        conn = db.get_conn()
        plan = conn.execute("INSERT INTO arquivos_dxf(nome,path,status,criado_em) VALUES('third.dxf','third.dxf','DISPONIVEL','2026-09-01')").lastrowid
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'Terceiro plano'):
            conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES('CNC01',?,3,'AGUARDANDO','2026-09-01')", (plan,))
        conn.rollback(); conn.close()


if __name__ == '__main__':
    unittest.main()
