import { useCallback, useEffect, useRef, useState } from 'react';
import { api, getErrMsg } from './api';
import { priorityLabel } from './planClassification';
import PlanClassificationModal from './PlanClassificationModal';
import './CncFeeding.css';

const formatDate = (value) => value ? new Date(value).toLocaleString('pt-BR') : '—';

export default function CncFeeding() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const [modal, setModal] = useState(null);
  const [movePlan, setMovePlan] = useState(null);
  const [destination, setDestination] = useState('');
  const [updated, setUpdated] = useState(null);
  const sequence = useRef(0);
  const mutating = useRef(false);
  const input = useRef(null);

  const load = useCallback(async () => {
    const request = ++sequence.current;
    try {
      const response = await api.get('/programador/alimentacao');
      if (request !== sequence.current) return;
      setData(response.data); setUpdated(new Date()); setError('');
    } catch (e) { if (request === sequence.current) setError(getErrMsg(e)); }
  }, []);

  useEffect(() => {
    const requestTracker = sequence;
    load();
    const timer = setInterval(() => { if (!document.hidden && !mutating.current) load(); }, 10000);
    return () => { clearInterval(timer); requestTracker.current++; };
  }, [load]);

  async function mutate(operation) {
    if (mutating.current) return;
    mutating.current = true; sequence.current++; setBusy(true); setError('');
    try {
      await operation(); setModal(null); setMovePlan(null); await load();
    } catch (e) { setError(getErrMsg(e)); }
    finally { mutating.current = false; setBusy(false); }
  }

  async function download(plan) {
    const id = plan.arquivo_id || plan.id;
    setDownloading(id); setError('');
    try {
      const response = await api.get(`/arquivos/${id}/download`, { responseType: 'blob' });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = url; link.download = plan.arquivo_nome || plan.nome;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError('Não foi possível baixar o arquivo. Verifique se ele está disponível e tente novamente.');
    } finally { setDownloading(null); }
  }

  function edit(plan) {
    setError('');
    setModal({ id: plan.arquivo_id || plan.id, mode: 'edit', items: [{
      name: plan.arquivo_nome || plan.nome, priority: plan.priority,
      compatible_cnc_ids: plan.compatible_cnc_ids,
    }] });
  }

  function classify(items) {
    return mutate(async () => {
      if (modal.mode === 'edit') {
        await api.put(`/arquivos/${modal.id}/classification`, { priority: items[0].priority, compatible_cnc_ids: items[0].compatible_cnc_ids });
      } else {
        const body = new FormData();
        items.forEach((item) => body.append('files', item.file));
        body.append('classifications', JSON.stringify(items.map(({ name, priority, compatible_cnc_ids }) => ({ name, priority, compatible_cnc_ids }))));
        await api.post('/arquivos/upload-classified', body);
      }
    });
  }

  function renderPlan(plan, waiting = false) {
    const id = plan.arquivo_id || plan.id;
    const executing = plan.status === 'EM_EXECUCAO';
    return <article className={`feedingPlan ${plan.deslocado_por_prioridade ? 'feedingDisplaced' : ''}`} key={id}>
      {!waiting && <div className="feedingSlot">{plan.slot}</div>}
      <strong>{plan.arquivo_nome || plan.nome}</strong>
      <div className="feedingActions"><button className="pgBtn pgBtnGhost" disabled={downloading !== null} onClick={() => download(plan)}>{downloading === id ? 'Baixando...' : 'Baixar arquivo'}</button></div>
      <div className="feedingBadges">
        <span className={`feedingPriority feedingPriority-${plan.priority}`}>{priorityLabel(plan.priority)}</span>
        <span>{plan.programado ? '🔒 Programado' : 'Programado: NÃO'}</span>
      </div>
      <small>CNCs permitidas: {plan.compatible_cnc_ids.join(', ') || 'Legado — classifique o plano'}</small>
      {waiting && <small>Entrada: {formatDate(plan.criado_em)} · {plan.alimentacao_pausada ? 'Distribuição pausada manualmente' : 'Aguardando vaga compatível'}</small>}
      {!executing && <div className="feedingActions">
        <button className="pgBtn pgBtnGhost" disabled={busy} onClick={() => { setMovePlan(plan); setDestination(''); setError(''); }}>Mover plano</button>
        <button className="pgBtn pgBtnGhost" disabled={busy} onClick={() => edit(plan)}>Classificação</button>
        <button className="pgBtn pgBtnGhost" disabled={busy} onClick={() => {
          if (plan.programado && !window.confirm('Retirar a proteção Programado? O automático poderá deslocar este plano.')) return;
          mutate(() => api.put(`/programador/alimentacao/${id}/programado`, { programado: !plan.programado }));
        }}>{plan.programado ? 'Desproteger' : 'Marcar Programado'}</button>
        {waiting && !!plan.alimentacao_pausada && <button className="pgBtn pgBtnPrimary" disabled={busy} onClick={() => mutate(() => api.post(`/programador/alimentacao/${id}/retomar`))}>Retomar automático</button>}
      </div>}
    </article>;
  }

  return <section className="feedingPage" aria-label="Alimentação CNC">
    <header className="feedingHeader"><div><h2>Alimentação CNC</h2><p>Distribuição semiautomática dos planos</p></div>
      <div className="feedingActions"><small>{updated && `Atualizado ${updated.toLocaleTimeString('pt-BR')}`}</small>
        <button className="pgBtn pgBtnGhost" disabled={busy} onClick={load}>Atualizar</button>
        <button className="pgBtn pgBtnPrimary" disabled={busy} onClick={() => input.current.click()}>Importar planos</button></div>
      <input ref={input} type="file" accept=".dxf" multiple hidden onChange={(event) => {
        const files = Array.from(event.target.files || []);
        event.target.value = '';
        if (files.length) { setError(''); setModal({ mode: 'import', items: files.map((file) => ({ name: file.name, file })) }); }
      }} />
    </header>
    <p className="feedingNotice">Usinando e Programado ficam protegidos. O terceiro plano existe somente por deslocamento de prioridade. CNCs desligadas, em manutenção ou sem operador não recebem novas reservas automáticas.</p>
    {error && <div className="feedingError" role="alert">{error}</div>}
    {!data ? <p>Carregando filas…</p> : <>
      <section className="feedingSection"><h3>Planos aguardando <span>({data.waiting.length})</span></h3>
        <div className="feedingWaiting">{data.waiting.length ? data.waiting.map((p) => renderPlan(p, true)) : <p>Nenhum plano aguardando distribuição.</p>}</div>
      </section>
      <div className="feedingMachines">{data.machines.map((machine) => <section className="feedingMachine" key={machine.id}>
        <header><h3>{machine.id}</h3><span>{machine.items.length}/3 posições</span></header>
        <p>{machine.status} · {machine.operador_nome || 'Sem operador'}</p>
        {machine.bloqueio && <div className="feedingNotice">Automático indisponível: {machine.bloqueio}. Reservas existentes preservadas.</div>}
        {machine.aviso && <div className="feedingNotice">{machine.aviso}</div>}
        {machine.items.length ? machine.items.map((p) => renderPlan(p)) : <p className="feedingEmpty">Sem planos reservados</p>}
      </section>)}</div>
      <section className="feedingSection"><h3>Últimas movimentações</h3>
        <div className="feedingHistory">{data.history.length ? data.history.map((entry) => <div key={entry.id}>
          <time>{formatDate(entry.created_at)}</time><strong>{entry.arquivo_nome_snapshot}</strong>
          <span>{entry.acao.replace('ALIMENTACAO_', '').replaceAll('_', ' ')} · {entry.cnc_origem || 'Geral'} → {entry.cnc_destino || 'Geral'}</span>
          <small>{entry.metadata?.motivo || entry.usuario_nome_snapshot}</small>
        </div>) : <p>Nenhuma movimentação registrada.</p>}</div>
      </section>
    </>}
    {modal && <PlanClassificationModal key={`${modal.mode}-${modal.id || 'upload'}`} files={modal.items} machines={data?.machines || []} mode={modal.mode} saving={busy} error={error} onCancel={() => !busy && setModal(null)} onConfirm={classify} />}
    {movePlan && <div className="feedingOverlay"><form className="feedingMove" role="dialog" aria-modal="true" aria-labelledby="feeding-move-title" onSubmit={(event) => {
      event.preventDefault(); mutate(() => api.post(`/programador/alimentacao/${movePlan.arquivo_id || movePlan.id}/mover`, { cnc_id: destination || null }));
    }}><h3 id="feeding-move-title">Mover plano</h3><p>{movePlan.arquivo_nome || movePlan.nome}</p>
      <label>Destino<select value={destination} onChange={(event) => setDestination(event.target.value)}>
        <option value="">Geral — pausar distribuição automática</option>
        {(movePlan.compatible_cnc_ids || []).map((cnc) => <option key={cnc} value={cnc}>{cnc}</option>)}
      </select></label>
      <p>Movimentações manuais respeitam compatibilidade e vagas. O início do corte continua com o operador.</p>
      {error && <div role="alert" className="feedingError">{error}</div>}
      <div className="feedingActions"><button type="button" className="pgBtn pgBtnGhost" disabled={busy} onClick={() => setMovePlan(null)}>Voltar</button><button className="pgBtn pgBtnPrimary" disabled={busy}>Confirmar movimento</button></div>
    </form></div>}
  </section>;
}
