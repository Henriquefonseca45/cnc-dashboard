import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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
  const [actionMenu, setActionMenu] = useState(null);
  const [updated, setUpdated] = useState(null);
  const [density, setDensity] = useState(() => {
    try { return localStorage.getItem('cnc_feeding_density') === 'normal' ? 'normal' : 'compact'; }
    catch { return 'compact'; }
  });
  const sequence = useRef(0);
  const mutating = useRef(false);
  const input = useRef(null);
  const actionMenuRef = useRef(null);

  useEffect(() => {
    if (!actionMenu) return undefined;
    const menu = actionMenuRef.current;
    menu?.querySelector('button')?.focus();
    const closeOutside = (event) => {
      if (!menu?.contains(event.target) && !actionMenu.anchor.contains(event.target)) setActionMenu(null);
    };
    const closeViewport = () => setActionMenu(null);
    const closeOrNavigate = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        actionMenu.anchor.focus();
        setActionMenu(null);
      } else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && menu?.contains(document.activeElement)) {
        event.preventDefault();
        const buttons = Array.from(menu.querySelectorAll('button:not(:disabled)'));
        const current = buttons.indexOf(document.activeElement);
        const step = event.key === 'ArrowDown' ? 1 : -1;
        buttons[(current + step + buttons.length) % buttons.length]?.focus();
      }
    };
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('keydown', closeOrNavigate);
    window.addEventListener('resize', closeViewport);
    window.addEventListener('scroll', closeViewport, true);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('keydown', closeOrNavigate);
      window.removeEventListener('resize', closeViewport);
      window.removeEventListener('scroll', closeViewport, true);
    };
  }, [actionMenu]);

  function openActionMenu(plan, event) {
    const anchor = event.currentTarget;
    if (actionMenu?.id === (plan.arquivo_id || plan.id)) { setActionMenu(null); return; }
    const rect = anchor.getBoundingClientRect();
    const width = 220;
    const canDelete = !plan.arquivo_id;
    const actionCount = 3 + Number(Boolean(plan.alimentacao_pausada)) + Number(canDelete);
    const height = 12 + actionCount * 40;
    const below = rect.bottom + 6;
    setActionMenu({
      id: plan.arquivo_id || plan.id, plan, anchor,
      left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)),
      top: below + height <= window.innerHeight - 8 ? below : Math.max(8, rect.top - height - 6),
    });
  }

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
      await operation(); setModal(null); setMovePlan(null); setActionMenu(null); await load();
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

  function openImport(filesValue) {
    if (busy) return;
    const files = Array.from(filesValue || []);
    if (!files.length) return;
    const invalid = files.find((file) => !String(file?.name || '').toLowerCase().endsWith('.dxf'));
    if (invalid) {
      setError(`Arquivo inválido: "${invalid.name}". Envie apenas arquivos DXF.`);
      return;
    }
    setError('');
    setModal({ mode: 'import', items: files.map((file) => ({ name: file.name, file })) });
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
    return <article className={`feedingPlan ${waiting ? 'feedingWaitingRow' : ''} ${executing ? 'feedingRunning' : ''} ${plan.deslocado_por_prioridade ? 'feedingDisplaced' : ''}`} key={id}>
      <div className="feedingPlanIdentity">
      {!waiting && <div className="feedingSlot">{plan.slot}</div>}
      <strong title={plan.arquivo_nome || plan.nome}>{plan.arquivo_nome || plan.nome}</strong>
      </div>
      <div className="feedingBadges">
        <span className={`feedingPriority feedingPriority-${plan.priority}`}>{priorityLabel(plan.priority)}</span>
        <span>{plan.programado ? '🔒 Programado' : 'Programado: NÃO'}</span>
      </div>
      <small className="feedingCompatibility" title={`CNCs permitidas: ${plan.compatible_cnc_ids.join(', ') || 'Legado — classifique o plano'}`}>CNCs: {plan.compatible_cnc_ids.join(', ') || 'Legado — classifique o plano'}</small>
      {waiting && <small className="feedingEntry" title={plan.alimentacao_pausada ? 'Distribuição pausada manualmente' : 'Aguardando vaga compatível'}>Entrada: {formatDate(plan.criado_em)}{plan.alimentacao_pausada ? ' · Pausado' : ''}</small>}
      <div className="feedingPlanControls">
      <button className="pgBtn pgBtnGhost" aria-label={`Baixar arquivo ${plan.arquivo_nome || plan.nome}`} disabled={downloading !== null} onClick={() => download(plan)}>{downloading === id ? 'Baixando...' : 'Baixar arquivo'}</button>
      {!executing && <button type="button" className="feedingMoreButton" aria-label="Mais ações" aria-haspopup="menu" aria-expanded={actionMenu?.id === id} disabled={busy} onClick={(event) => openActionMenu(plan, event)}>•••</button>}
      </div>
    </article>;
  }

  return <section className={`feedingPage feedingDensity-${density}`} aria-label="Alimentação CNC">
    <header className="feedingHeader"><div><h2>Alimentação CNC</h2><p>Distribuição semiautomática dos planos</p></div>
      <div className="feedingActions"><small>{updated && `Atualizado ${updated.toLocaleTimeString('pt-BR')}`}</small>
        <div className="feedingDensity" role="group" aria-label="Visualização da fila"><span>Visualização</span>{[['normal', 'Normal'], ['compact', 'Compacta']].map(([value, label]) => <button key={value} type="button" aria-pressed={density === value} onClick={() => {
          setDensity(value);
          try { localStorage.setItem('cnc_feeding_density', value); } catch { /* Preference is optional. */ }
        }}>{label}</button>)}</div>
        <button className="pgBtn pgBtnGhost" disabled={busy} onClick={load}>Atualizar</button></div>
      <input ref={input} type="file" accept=".dxf" multiple hidden onChange={(event) => {
        const files = Array.from(event.target.files || []);
        event.target.value = '';
        openImport(files);
      }} />
    </header>
    <div
      className={`feedingUploadDrop ${busy ? 'isBusy' : ''}`}
      role="button"
      tabIndex={busy ? -1 : 0}
      aria-disabled={busy}
      aria-label="Importar planos DXF"
      onClick={() => !busy && input.current?.click()}
      onKeyDown={(event) => {
        if (!busy && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          input.current?.click();
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (!busy) event.dataTransfer.dropEffect = 'copy';
      }}
      onDrop={(event) => {
        event.preventDefault();
        openImport(event.dataTransfer.files);
      }}
    >
      <span aria-hidden="true">＋</span>
      <strong>{busy ? 'Importando planos…' : 'Arraste arquivos DXF aqui'}</strong>
      <small>ou clique para selecionar</small>
    </div>
    <p className="feedingNotice">As filas não possuem limite fixo. Usinando e Programado ficam protegidos. CNCs desligadas, em manutenção ou sem operador não recebem novas reservas automáticas.</p>
    {error && <div className="feedingError" role="alert">{error}</div>}
    {!data ? <p>Carregando filas…</p> : <>
      <section className="feedingSection"><h3>Planos aguardando <span>({data.waiting.length})</span></h3>
        <div className="feedingWaiting">{data.waiting.length ? data.waiting.map((p) => renderPlan(p, true)) : <p>Nenhum plano aguardando distribuição.</p>}</div>
      </section>
      <div className="feedingMachines">{data.machines.map((machine) => <section className="feedingMachine" key={machine.id}>
        <header><h3>{machine.id}</h3><span>{machine.items.length} plano(s) na fila</span></header>
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
    {actionMenu && createPortal(<div ref={actionMenuRef} className="feedingActionMenu" role="menu" aria-label={`Ações de ${actionMenu.plan.arquivo_nome || actionMenu.plan.nome}`} style={{ left: actionMenu.left, top: actionMenu.top }}>
      <button role="menuitem" disabled={busy} onClick={() => { setActionMenu(null); setMovePlan(actionMenu.plan); setDestination(''); setError(''); }}>Mover plano</button>
      <button role="menuitem" disabled={busy} onClick={() => { setActionMenu(null); edit(actionMenu.plan); }}>Classificação</button>
      <button role="menuitem" disabled={busy} onClick={() => {
        const plan = actionMenu.plan;
        if (plan.programado && !window.confirm('Retirar a proteção Programado? O automático poderá deslocar este plano.')) return;
        mutate(() => api.put(`/programador/alimentacao/${plan.arquivo_id || plan.id}/programado`, { programado: !plan.programado }));
      }}>{actionMenu.plan.programado ? 'Liberar reordenação' : 'Marcar Programado'}</button>
      {!!actionMenu.plan.alimentacao_pausada && <button role="menuitem" disabled={busy} onClick={() => mutate(() => api.post(`/programador/alimentacao/${actionMenu.plan.arquivo_id || actionMenu.plan.id}/retomar`))}>Retomar automático</button>}
      {!actionMenu.plan.arquivo_id && <button role="menuitem" className="feedingDeleteAction" disabled={busy} onClick={() => {
        const plan = actionMenu.plan;
        const name = plan.nome || 'este plano';
        if (!window.confirm(`Excluir definitivamente o plano "${name}"? Esta ação não pode ser desfeita.`)) return;
        mutate(() => api.delete(`/arquivos/${plan.id}`));
      }}>Excluir plano</button>}
    </div>, document.body)}
  </section>;
}
