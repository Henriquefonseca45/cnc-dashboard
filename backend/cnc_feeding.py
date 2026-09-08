"""Semiautomatic reservations on the existing queue. Call mutations in BEGIN IMMEDIATE."""
from datetime import datetime
import re
import unicodedata

from backend.programador_audit import record_programador_audit, decode_audit_row
from backend.plan_classification import ensure_plan_classification_schema

ACTIVE = ('AGUARDANDO', 'PROGRAMANDO', 'BAIXADO', 'EM_EXECUCAO')
ACTIVE_SQL = "('AGUARDANDO','PROGRAMANDO','BAIXADO','EM_EXECUCAO')"
RANK = {'high': 0, 'medium': 1, 'normal': 2}
SYSTEM = {'id': None, 'nome': 'Alimentação CNC', 'role': 'sistema'}


class FeedingError(ValueError):
    pass


def ensure_schema(conn):
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(arquivos_dxf)')}
    if not columns:
        return
    ensure_plan_classification_schema(conn)
    for name in ('alimentacao_cnc', 'programado', 'alimentacao_pausada'):
        if name not in columns:
            conn.execute(f'ALTER TABLE arquivos_dxf ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
    queue_columns = {r['name'] for r in conn.execute('PRAGMA table_info(fila_itens)')}
    if not queue_columns:
        return
    if 'deslocado_por_prioridade' not in queue_columns:
        conn.execute('ALTER TABLE fila_itens ADD COLUMN deslocado_por_prioridade INTEGER NOT NULL DEFAULT 0')
    if 'programado' not in columns:
        conn.execute("UPDATE arquivos_dxf SET programado=1 WHERE id IN (SELECT arquivo_id FROM fila_itens WHERE status IN ('PROGRAMANDO','BAIXADO','EM_EXECUCAO'))")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_feeding_queue ON fila_itens(maquina_id,status,posicao)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_feeding_pool ON arquivos_dxf(alimentacao_cnc,alimentacao_pausada,status)')
    # Protect new managed queues even when an older endpoint is called directly.
    for event in ('INSERT', 'UPDATE'):
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS feeding_guard_{event.lower()}
            BEFORE {event} ON fila_itens
            WHEN NEW.status IN {ACTIVE_SQL} AND (
                EXISTS(SELECT 1 FROM arquivos_dxf WHERE id=NEW.arquivo_id AND alimentacao_cnc=1)
                OR EXISTS(SELECT 1 FROM fila_itens q JOIN arquivos_dxf a ON a.id=q.arquivo_id
                          WHERE q.maquina_id=NEW.maquina_id AND q.status IN {ACTIVE_SQL} AND a.alimentacao_cnc=1))
            BEGIN
                SELECT CASE WHEN EXISTS(SELECT 1 FROM fila_itens WHERE arquivo_id=NEW.arquivo_id
                    AND status IN {ACTIVE_SQL} AND id<>NEW.id)
                    THEN RAISE(ABORT,'Plano já reservado em outra posição.') END;
                SELECT CASE WHEN (SELECT COUNT(*) FROM fila_itens WHERE maquina_id=NEW.maquina_id
                    AND status IN {ACTIVE_SQL} AND id<>NEW.id)>=3
                    THEN RAISE(ABORT,'CNC lotada: limite absoluto de 3 planos.') END;
                SELECT CASE WHEN (SELECT COUNT(*) FROM fila_itens WHERE maquina_id=NEW.maquina_id
                    AND status IN {ACTIVE_SQL} AND id<>NEW.id)=2 AND NEW.deslocado_por_prioridade=0
                    AND NOT EXISTS(SELECT 1 FROM fila_itens WHERE maquina_id=NEW.maquina_id
                                   AND status IN {ACTIVE_SQL} AND id<>NEW.id AND deslocado_por_prioridade=1)
                    THEN RAISE(ABORT,'Terceiro plano somente por deslocamento de prioridade.') END;
                SELECT CASE WHEN NEW.status='EM_EXECUCAO' AND EXISTS(SELECT 1 FROM fila_itens
                    WHERE maquina_id=NEW.maquina_id AND status='EM_EXECUCAO' AND id<>NEW.id)
                    THEN RAISE(ABORT,'Já existe plano usinando nesta CNC.') END;
                SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM arquivo_cnc_compatibilidade WHERE arquivo_id=NEW.arquivo_id AND cnc_id=NEW.maquina_id)
                    AND EXISTS(SELECT 1 FROM arquivos_dxf WHERE id=NEW.arquivo_id AND alimentacao_cnc=1)
                    THEN RAISE(ABORT,'CNC não autorizada para este plano.') END;
            END
        """)


def managed(conn, arquivo_id):
    row = conn.execute('SELECT alimentacao_cnc FROM arquivos_dxf WHERE id=?', (arquivo_id,)).fetchone()
    return bool(row and row[0])


def queue(conn, cnc):
    return [dict(r) for r in conn.execute(f"""
        SELECT q.*, a.nome AS arquivo_nome, a.priority, a.programado, a.alimentacao_cnc
        FROM fila_itens q JOIN arquivos_dxf a ON a.id=q.arquivo_id
        WHERE q.maquina_id=? AND q.status IN {ACTIVE_SQL}
        ORDER BY CASE WHEN q.status='EM_EXECUCAO' THEN 0 ELSE 1 END, q.posicao, q.id
    """, (cnc,))]


def protected(item):
    return bool(item['programado'] or item['status'] in ('PROGRAMANDO', 'BAIXADO', 'EM_EXECUCAO'))


def unavailable(machine):
    status = unicodedata.normalize('NFKD', machine.get('status') or '').encode('ascii', 'ignore').decode().upper()
    if 'DESLIG' in status:
        return 'CNC desligada'
    if 'MANUT' in status:
        return 'CNC em manutenção'
    if 'FALTA' in status and 'OPER' in status or 'SEM OPER' in status or not str(machine.get('operador_nome') or '').strip():
        return 'CNC sem operador'
    return None


def machines(conn):
    return [dict(r) for r in conn.execute('SELECT * FROM maquinas ORDER BY id') if re.fullmatch(r'CNC\d+', r['id'])]


def audit(conn, action, item, *, source=None, destination=None, before=None, after=None, reason=None, actor=None):
    record_programador_audit(conn, actor or SYSTEM, 'ALIMENTACAO_' + action,
        arquivo_id=item.get('arquivo_id', item.get('id')), arquivo_nome=item.get('arquivo_nome', item.get('nome')),
        entidade_tipo='alimentacao_cnc', entidade_id=item.get('id'), cnc_origem=source, cnc_destino=destination,
        valor_anterior=before, valor_novo=after, metadata={'motivo': reason} if reason else None)


def reconcile(conn, cnc):
    items = queue(conn, cnc)
    # Existing long queues are visible, never silently evicted or renamed as displaced.
    if not any(x['alimentacao_cnc'] for x in items) or len(items) > 3:
        return
    waiting = [x for x in items if x['status'] != 'EM_EXECUCAO']
    for item in items:
        pos = 0 if item['status'] == 'EM_EXECUCAO' else waiting.index(item) + 1
        # After completion, the head waits for operator start; displaced becomes next.
        displaced = int(bool(item['deslocado_por_prioridade']) and pos > 1 and len(items) == 3)
        if item['deslocado_por_prioridade'] and not displaced:
            audit(conn, 'PROMOVIDO', item, source=cnc, destination=cnc,
                  before={'deslocado': True}, after={'deslocado': False, 'posicao': pos})
        conn.execute('UPDATE fila_itens SET posicao=?,deslocado_por_prioridade=? WHERE id=?', (pos, displaced, item['id']))


def pool(conn):
    return [dict(r) for r in conn.execute(f"""
        SELECT a.* FROM arquivos_dxf a WHERE a.alimentacao_cnc=1 AND a.status='DISPONIVEL'
        AND NOT EXISTS(SELECT 1 FROM fila_itens q WHERE q.arquivo_id=a.id AND q.status IN {ACTIVE_SQL})
        AND NOT EXISTS(SELECT 1 FROM arquivos_dxf other JOIN fila_itens q ON q.arquivo_id=other.id
                       WHERE LOWER(TRIM(other.nome))=LOWER(TRIM(a.nome)) AND q.status IN {ACTIVE_SQL})
        ORDER BY CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.criado_em, a.id
    """)]


def compatibility(conn, arquivo_id):
    return [r[0] for r in conn.execute('SELECT cnc_id FROM arquivo_cnc_compatibilidade WHERE arquivo_id=? ORDER BY cnc_id', (arquivo_id,))]


def distribute(conn):
    """Priority/FIFO, prefer empty slots and protect single-choice peers. No timer worker."""
    all_machines = machines(conn)
    for m in all_machines:
        reconcile(conn, m['id'])
    eligible = {m['id'] for m in all_machines if not unavailable(m)}
    waiting = [p for p in pool(conn) if not p['alimentacao_pausada']]
    choices = {p['id']: set(compatibility(conn, p['id'])) & eligible for p in waiting}
    for plan in waiting:
        if conn.execute(f"SELECT 1 FROM fila_itens q JOIN arquivos_dxf a ON a.id=q.arquivo_id WHERE LOWER(TRIM(a.nome))=LOWER(TRIM(?)) AND q.status IN {ACTIVE_SQL}", (plan['nome'],)).fetchone():
            continue
        candidates = []
        for cnc in choices[plan['id']]:
            items = queue(conn, cnc)
            running = any(x['status'] == 'EM_EXECUCAO' for x in items)
            pending = [x for x in items if x['status'] != 'EM_EXECUCAO']
            if not pending and len(items) < 2:
                mode = 0
            elif running and len(items) == 2 and len(pending) == 1 and not protected(pending[0]) and RANK[plan['priority']] < RANK.get(pending[0]['priority'], 2):
                mode = 1
            else:
                continue
            # Do not reverse FIFO: choose a different machine for the older flexible plan.
            exclusive = sum(1 for p in waiting if p['id'] != plan['id'] and p['priority'] == plan['priority'] and choices[p['id']] == {cnc})
            candidates.append((mode, exclusive, len(items), cnc, pending))
        if not candidates:
            continue
        mode, _, _, cnc, pending = min(candidates, key=lambda c: c[:4])
        if mode:
            old = pending[0]
            conn.execute('UPDATE fila_itens SET posicao=2,deslocado_por_prioridade=1 WHERE id=?', (old['id'],))
            audit(conn, 'DESLOCADO', old, source=cnc, destination=cnc,
                  before={'posicao': old['posicao']}, after={'posicao': 2, 'deslocado': True}, reason=f"Prioridade superior do plano {plan['nome']}")
        conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES(?,?,1,'AGUARDANDO',?)",
                     (cnc, plan['id'], datetime.now().isoformat(timespec='seconds')))
        audit(conn, 'RESERVADO', plan, destination=cnc, after={'posicao': 1}, reason='Vaga compatível' if not mode else 'Prioridade superior')
        choices[plan['id']] = set()


def validate_start(conn, cnc, item_id):
    items = queue(conn, cnc)
    item = next((x for x in items if x['id'] == item_id), None)
    if not item:
        raise FeedingError('Item não pertence à fila ativa desta CNC.')
    if any(x['alimentacao_cnc'] for x in items):
        pending = [x for x in items if x['status'] != 'EM_EXECUCAO']
        if item['status'] != 'EM_EXECUCAO' and (not pending or pending[0]['id'] != item_id):
            raise FeedingError('Somente o primeiro plano aguardando pode ser preparado ou iniciado.')
    return item


def set_programmed(conn, arquivo_id, value, actor=None):
    item = conn.execute('SELECT * FROM arquivos_dxf WHERE id=?', (arquivo_id,)).fetchone()
    if not item or item['status'] != 'DISPONIVEL':
        raise FeedingError('Plano não disponível.')
    executing = conn.execute("SELECT 1 FROM fila_itens WHERE arquivo_id=? AND status='EM_EXECUCAO'", (arquivo_id,)).fetchone()
    if executing:
        raise FeedingError('Não altere a programação de um plano usinando.')
    conn.execute('UPDATE arquivos_dxf SET programado=? WHERE id=?', (int(value), arquivo_id))
    # Explicit unprotect also clears the legacy programming condition, not downloads.
    if not value:
        conn.execute("UPDATE fila_itens SET status='AGUARDANDO' WHERE arquivo_id=? AND status IN ('PROGRAMANDO','BAIXADO')", (arquivo_id,))
    audit(conn, 'PROGRAMADO', dict(item), before=bool(item['programado']), after=value, actor=actor)
    distribute(conn)


def move(conn, arquivo_id, destination, actor=None):
    plan = conn.execute('SELECT * FROM arquivos_dxf WHERE id=?', (arquivo_id,)).fetchone()
    if not plan or plan['status'] != 'DISPONIVEL':
        raise FeedingError('Plano não disponível.')
    plan = dict(plan)
    current = conn.execute(f'SELECT * FROM fila_itens WHERE arquivo_id=? AND status IN {ACTIVE_SQL}', (arquivo_id,)).fetchone()
    if current and current['status'] == 'EM_EXECUCAO':
        raise FeedingError('Não é permitido mover um plano usinando.')
    source = current['maquina_id'] if current else None
    if destination == source and destination:
        return {'item_id': current['id'], 'maquina_id': destination}
    if destination:
        if destination not in compatibility(conn, arquivo_id):
            raise FeedingError(f'Este plano não está habilitado para a {destination}.')
        items = queue(conn, destination)
        if len(items) >= 3:
            raise FeedingError('CNC lotada: limite absoluto de 3 planos.')
        if any(x['status'] != 'EM_EXECUCAO' for x in items):
            raise FeedingError('A posição Próximo está ocupada. O terceiro plano só pode surgir por deslocamento automático.')
    if current:
        if destination:
            conn.execute('UPDATE fila_itens SET maquina_id=?,posicao=1,deslocado_por_prioridade=0 WHERE id=?', (destination, current['id']))
        else:
            conn.execute('DELETE FROM fila_itens WHERE id=?', (current['id'],))
    elif destination:
        cursor = conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES(?,?,1,'AGUARDANDO',?)", (destination, arquivo_id, datetime.now().isoformat(timespec='seconds')))
    conn.execute('UPDATE arquivos_dxf SET alimentacao_pausada=? WHERE id=?', (int(destination is None), arquivo_id))
    audit(conn, 'MOVIDO_MANUALMENTE', plan, source=source, destination=destination, actor=actor,
          reason='Reserva manual' if destination else 'Aguardando com distribuição pausada pelo programador')
    record_programador_audit(conn, actor or SYSTEM,
        'PLANO_MOVIMENTADO' if source and destination else 'ADICIONADO_FILA' if destination else 'REMOVIDO_FILA',
        arquivo_id=arquivo_id, arquivo_nome=plan['nome'], cnc_origem=source, cnc_destino=destination)
    if source:
        reconcile(conn, source)
    distribute(conn)
    item_id = current['id'] if current and destination else (cursor.lastrowid if not current and destination else None)
    return {'item_id': item_id, 'item_id_novo': item_id, 'maquina_id': destination, 'arquivo_id': arquivo_id, 'arquivo_nome': plan['nome']}


def snapshot(conn):
    result = []
    for m in machines(conn):
        items = queue(conn, m['id'])
        pending = [x for x in items if x['status'] != 'EM_EXECUCAO']
        running = any(x['status'] == 'EM_EXECUCAO' for x in items)
        for item in items:
            item['programado'] = protected(item)
            item['compatible_cnc_ids'] = compatibility(conn, item['arquivo_id'])
            item['slot'] = ('USINANDO' if item['status'] == 'EM_EXECUCAO' else
                            'DESLOCADO POR PRIORIDADE' if item['deslocado_por_prioridade'] else
                            'AGUARDANDO INÍCIO' if not running and pending[0]['id'] == item['id'] else 'PRÓXIMO')
        warning = 'Fila anterior à alimentação: regularize manualmente ou aguarde o consumo.' if len(items) > 2 and not any(x['deslocado_por_prioridade'] for x in items) else None
        result.append({**m, 'bloqueio': unavailable(m), 'aviso': warning, 'items': items})
    waiting = pool(conn)
    for plan in waiting:
        plan['compatible_cnc_ids'] = compatibility(conn, plan['id'])
    history = [decode_audit_row(r) for r in conn.execute("SELECT * FROM programador_auditoria WHERE entidade_tipo='alimentacao_cnc' ORDER BY id DESC LIMIT 100")]
    return {'machines': result, 'waiting': waiting, 'history': history}
