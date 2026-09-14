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
THICKNESS_PATTERN = re.compile(r'(?<!\w)(\d+(?:[,.]\d+)?)\s*(?:EX|MDF|TX|KP|AD|MM)\b', re.IGNORECASE)


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
    if 'ordem_manual' not in queue_columns:
        conn.execute('ALTER TABLE fila_itens ADD COLUMN ordem_manual INTEGER')
    if 'programado' not in columns:
        conn.execute("UPDATE arquivos_dxf SET programado=1 WHERE id IN (SELECT arquivo_id FROM fila_itens WHERE status IN ('PROGRAMANDO','BAIXADO','EM_EXECUCAO'))")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_feeding_queue ON fila_itens(maquina_id,status,posicao)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_feeding_pool ON arquivos_dxf(alimentacao_cnc,alimentacao_pausada,status)')
    # Upgrade old guards once. Queues no longer have a fixed capacity limit.
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='feeding_guard_v3_insert'").fetchone():
        return
    for version in ('', '_v2', '_v3'):
        for event in ('insert', 'update'):
            conn.execute(f'DROP TRIGGER IF EXISTS feeding_guard{version}_{event}')
    for event in ('INSERT', 'UPDATE'):
        admission = '1' if event == 'INSERT' else f'(OLD.status NOT IN {ACTIVE_SQL} OR OLD.maquina_id<>NEW.maquina_id OR OLD.arquivo_id<>NEW.arquivo_id)'
        conn.execute(f"""
            CREATE TRIGGER IF NOT EXISTS feeding_guard_v3_{event.lower()}
            BEFORE {event} ON fila_itens
            WHEN NEW.status IN {ACTIVE_SQL}
            BEGIN
                SELECT CASE WHEN {admission} AND EXISTS(SELECT 1 FROM fila_itens WHERE arquivo_id=NEW.arquivo_id
                    AND status IN {ACTIVE_SQL} AND id<>NEW.id)
                    THEN RAISE(ABORT,'Plano já reservado em outra posição.') END;
                SELECT CASE WHEN NEW.status='EM_EXECUCAO' AND EXISTS(SELECT 1 FROM fila_itens
                    WHERE maquina_id=NEW.maquina_id AND status='EM_EXECUCAO' AND id<>NEW.id)
                    THEN RAISE(ABORT,'Já existe plano usinando nesta CNC.') END;
                SELECT CASE WHEN {admission} AND NOT EXISTS(SELECT 1 FROM arquivo_cnc_compatibilidade WHERE arquivo_id=NEW.arquivo_id AND cnc_id=NEW.maquina_id)
                    AND EXISTS(SELECT 1 FROM arquivos_dxf WHERE id=NEW.arquivo_id AND alimentacao_cnc=1)
                    THEN RAISE(ABORT,'CNC não autorizada para este plano.') END;
            END
        """)


def managed(conn, arquivo_id):
    row = conn.execute('SELECT alimentacao_cnc FROM arquivos_dxf WHERE id=?', (arquivo_id,)).fetchone()
    return bool(row and row[0])


def queue(conn, cnc):
    return [dict(r) for r in conn.execute(f"""
        SELECT q.*, a.nome AS arquivo_nome, a.priority, a.programado, a.alimentacao_cnc,
               a.criado_em AS arquivo_criado_em
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
    if not any(x['alimentacao_cnc'] for x in items):
        return
    waiting = sorted(
        (x for x in items if x['status'] != 'EM_EXECUCAO'),
        key=lambda x: (
            0 if x['status'] == 'BAIXADO' else 1,
            0 if x['ordem_manual'] is not None else 1,
            int(x['ordem_manual']) if x['ordem_manual'] is not None else queue_order(x),
        ),
    )
    for position, item in enumerate(waiting, start=1):
        conn.execute('UPDATE fila_itens SET posicao=?,deslocado_por_prioridade=0 WHERE id=?', (position, item['id']))
    for item in items:
        if item['status'] == 'EM_EXECUCAO':
            conn.execute('UPDATE fila_itens SET posicao=0,deslocado_por_prioridade=0 WHERE id=?', (item['id'],))


def plan_thickness(name):
    """Return the numeric thickness encoded in a plan filename, when present."""
    match = THICKNESS_PATTERN.search(str(name or ''))
    if not match:
        return None
    try:
        return float(match.group(1).replace(',', '.'))
    except ValueError:
        return None


def pool_order(plan):
    priority = str(plan.get('priority') or 'normal').lower()
    thickness = plan_thickness(plan.get('nome')) if priority == 'normal' else None
    created_at = str(plan.get('criado_em') or '')
    # Every priority is FIFO. For normal plans received together, prefer the greatest thickness.
    thickness_group = 0 if thickness is not None else 1
    thickness_order = -thickness if thickness is not None else 0
    return (RANK.get(priority, 2), created_at, thickness_group, thickness_order,
            int(plan.get('id') or 0))


def queue_order(item):
    return pool_order({
        'id': item.get('arquivo_id') or item.get('id'),
        'nome': item.get('arquivo_nome') or item.get('nome'),
        'priority': item.get('priority'),
        'criado_em': item.get('arquivo_criado_em') or item.get('criado_em'),
    })


def pool(conn):
    plans = [dict(r) for r in conn.execute(f"""
        SELECT a.* FROM arquivos_dxf a WHERE a.alimentacao_cnc=1 AND a.status='DISPONIVEL'
        AND NOT EXISTS(SELECT 1 FROM fila_itens q WHERE q.arquivo_id=a.id AND q.status IN {ACTIVE_SQL})
        AND NOT EXISTS(SELECT 1 FROM arquivos_dxf other JOIN fila_itens q ON q.arquivo_id=other.id
                       WHERE LOWER(TRIM(other.nome))=LOWER(TRIM(a.nome)) AND q.status IN {ACTIVE_SQL})
        ORDER BY CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, a.criado_em, a.id
    """)]
    return sorted(plans, key=pool_order)


def compatibility(conn, arquivo_id):
    return [r[0] for r in conn.execute('SELECT cnc_id FROM arquivo_cnc_compatibilidade WHERE arquivo_id=? ORDER BY cnc_id', (arquivo_id,))]


def distribute(conn):
    """Assign every compatible plan and keep each CNC ordered by the official priorities."""
    all_machines = machines(conn)
    for m in all_machines:
        reconcile(conn, m['id'])
    # A fila representa trabalho futuro: o status atual da CNC não impede a reserva.
    eligible = {m['id'] for m in all_machines}
    waiting = [p for p in pool(conn) if not p['alimentacao_pausada']]
    choices = {p['id']: set(compatibility(conn, p['id'])) & eligible for p in waiting}
    for plan in waiting:
        if conn.execute(f"SELECT 1 FROM fila_itens q JOIN arquivos_dxf a ON a.id=q.arquivo_id WHERE LOWER(TRIM(a.nome))=LOWER(TRIM(?)) AND q.status IN {ACTIVE_SQL}", (plan['nome'],)).fetchone():
            continue
        candidates = list(choices[plan['id']])
        if not candidates:
            continue
        def candidate_score(candidate):
            exclusive_demand = sum(
                1 for other in waiting
                if other['id'] != plan['id'] and choices.get(other['id']) == {candidate}
            )
            return (exclusive_demand, len(queue(conn, candidate)), candidate)

        cnc = min(candidates, key=candidate_score)
        next_position = 1 + sum(1 for item in queue(conn, cnc) if item['status'] != 'EM_EXECUCAO')
        conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES(?,?,?,'AGUARDANDO',?)",
                     (cnc, plan['id'], next_position, datetime.now().isoformat(timespec='seconds')))
        reconcile(conn, cnc)
        audit(conn, 'RESERVADO', plan, destination=cnc, after={'posicao': next_position}, reason='Distribuição automática por compatibilidade e prioridade')
        choices[plan['id']] = set()


def reorder(conn, cnc, ordered_item_ids, actor=None):
    """Persist a facilitator override for pending plans on one CNC."""
    if cnc not in {machine['id'] for machine in machines(conn)}:
        raise FeedingError('CNC não encontrada.')
    items = queue(conn, cnc)
    pending = [item for item in items if item['status'] != 'EM_EXECUCAO']
    current_ids = [int(item['id']) for item in pending]
    wanted = [int(item_id) for item_id in ordered_item_ids]
    if len(wanted) != len(current_ids) or set(wanted) != set(current_ids):
        raise FeedingError('A fila mudou. Atualize a tela e tente novamente.')
    if not all(item['alimentacao_cnc'] for item in pending):
        raise FeedingError('A reordenação do Facilitador requer planos classificados.')
    downloaded = [int(item['id']) for item in pending if item['status'] == 'BAIXADO']
    if wanted[:len(downloaded)] != downloaded:
        raise FeedingError('O plano já baixado deve permanecer no início da fila.')
    if wanted == current_ids:
        return {'maquina_id': cnc, 'ordered_item_ids': wanted}
    for position, item_id in enumerate(wanted, start=1):
        conn.execute('UPDATE fila_itens SET ordem_manual=? WHERE id=? AND maquina_id=?', (position, item_id, cnc))
    reconcile(conn, cnc)
    audit(conn, 'ORDEM_MANUAL', {'id': None}, source=cnc, destination=cnc,
          before=current_ids, after=wanted, actor=actor)
    return {'maquina_id': cnc, 'ordered_item_ids': wanted}


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
        destination_position = max((int(x.get('posicao') or 0) for x in items), default=0) + 1
    if current:
        if destination:
            conn.execute('UPDATE fila_itens SET maquina_id=?,posicao=?,deslocado_por_prioridade=0,ordem_manual=NULL WHERE id=?',
                         (destination, destination_position, current['id']))
        else:
            conn.execute('DELETE FROM fila_itens WHERE id=?', (current['id'],))
    elif destination:
        cursor = conn.execute("INSERT INTO fila_itens(maquina_id,arquivo_id,posicao,status,criado_em) VALUES(?,?,?,'AGUARDANDO',?)",
                              (destination, arquivo_id, destination_position, datetime.now().isoformat(timespec='seconds')))
    conn.execute('UPDATE arquivos_dxf SET alimentacao_pausada=? WHERE id=?', (int(destination is None), arquivo_id))
    audit(conn, 'MOVIDO_MANUALMENTE', plan, source=source, destination=destination, actor=actor,
          reason='Reserva manual' if destination else 'Aguardando com distribuição pausada pelo programador')
    record_programador_audit(conn, actor or SYSTEM,
        'PLANO_MOVIMENTADO' if source and destination else 'ADICIONADO_FILA' if destination else 'REMOVIDO_FILA',
        arquivo_id=arquivo_id, arquivo_nome=plan['nome'], cnc_origem=source, cnc_destino=destination)
    if source:
        reconcile(conn, source)
    if destination:
        reconcile(conn, destination)
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
                            'AGUARDANDO INÍCIO' if not running and pending[0]['id'] == item['id'] else 'PRÓXIMO')
        result.append({**m, 'bloqueio': unavailable(m), 'aviso': None, 'inconsistente': False,
                       'excedentes': 0, 'lotada': False, 'items': items})
    waiting = pool(conn)
    for plan in waiting:
        plan['compatible_cnc_ids'] = compatibility(conn, plan['id'])
    history = [decode_audit_row(r) for r in conn.execute("SELECT * FROM programador_auditoria WHERE entidade_tipo='alimentacao_cnc' ORDER BY id DESC LIMIT 100")]
    return {'machines': result, 'waiting': waiting, 'history': history,
            'legacy_summary': {'cncs_acima_limite': 0, 'itens_nessas_cncs': 0, 'itens_excedentes': 0}}
