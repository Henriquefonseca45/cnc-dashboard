import React, { useEffect, useMemo, useState } from "react";
import { api, getErrMsg } from "./api";
import "./ProgramadorAuditHistory.css";


const ACTION_LABELS = {
  ARQUIVO_IMPORTADO: "Importação",
  ARQUIVO_EXCLUIDO: "Exclusão",
  PRIORIDADE_ALTERADA: "Prioridade",
  CNC_ADICIONADA: "CNC adicionada",
  CNC_REMOVIDA: "CNC removida",
  ADICIONADO_FILA: "Adicionado à fila",
  REMOVIDO_FILA: "Removido da fila",
  PLANO_MOVIMENTADO: "Movimentação",
  FILA_REORDENADA: "Fila reordenada",
  DOWNLOAD_ARQUIVO: "Download",
};


function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}


function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(" · ") || "—";
  if (typeof value === "object") {
    return Object.entries(value).map(([key, item]) => `${key}: ${displayValue(item)}`).join(" | ");
  }
  return String(value);
}


function actionDetails(item) {
  if (item.cnc_origem && item.cnc_destino && item.cnc_origem !== item.cnc_destino) {
    return `${item.cnc_origem} → ${item.cnc_destino}`;
  }
  if (item.valor_anterior !== null && item.valor_novo !== null) {
    return `${displayValue(item.valor_anterior)} → ${displayValue(item.valor_novo)}`;
  }
  return displayValue(item.valor_novo || item.metadata);
}


const EMPTY_FILTERS = { data_inicio: "", data_fim: "", usuario_id: "", acao: "", cnc: "", arquivo: "", remessa: "" };


export default function ProgramadorAuditHistory() {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [applied, setApplied] = useState(EMPTY_FILTERS);
  const [options, setOptions] = useState({ users: [], actions: [] });
  const [data, setData] = useState({ items: [], total: 0, page: 1, pages: 1, page_size: 50 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const queryKey = useMemo(() => JSON.stringify(applied), [applied]);

  async function load(page = 1) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "50" });
      Object.entries(applied).forEach(([key, value]) => { if (String(value || "").trim()) params.set(key, value); });
      const response = await api.get(`/programador/auditoria?${params.toString()}`);
      setData(response.data);
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(1); }, [queryKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    api.get("/programador/auditoria/opcoes").then((response) => setOptions(response.data)).catch(() => {});
  }, []);

  async function openDetail(item) {
    setDetailLoading(true);
    setDetail(item);
    setTimeline([]);
    try {
      const calls = [api.get(`/programador/auditoria/${item.id}`)];
      if (item.arquivo_id) calls.push(api.get(`/programador/auditoria/plano/${item.arquivo_id}`));
      const responses = await Promise.all(calls);
      setDetail(responses[0].data);
      setTimeline(responses[1]?.data || []);
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      setDetailLoading(false);
    }
  }

  function submit(event) {
    event.preventDefault();
    setApplied({ ...filters });
  }

  function clear() {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
  }

  return (
    <main className="programadorAuditPage">
      <section className="programadorAuditHeading">
        <div><span>AUDITORIA</span><h1>Histórico de Movimentações</h1><p>Acompanhe as alterações realizadas pelos usuários da Programação.</p></div>
        <strong>{data.total} registro(s)</strong>
      </section>

      <form className="programadorAuditFilters" onSubmit={submit}>
        <label>De<input type="date" value={filters.data_inicio} onChange={(event) => setFilters({ ...filters, data_inicio: event.target.value })} /></label>
        <label>Até<input type="date" value={filters.data_fim} onChange={(event) => setFilters({ ...filters, data_fim: event.target.value })} /></label>
        <label>Programador<select value={filters.usuario_id} onChange={(event) => setFilters({ ...filters, usuario_id: event.target.value })}><option value="">Todos</option>{options.users.map((user) => <option key={`${user.id}-${user.nome}`} value={user.id || ""}>{user.nome}</option>)}</select></label>
        <label>Ação<select value={filters.acao} onChange={(event) => setFilters({ ...filters, acao: event.target.value })}><option value="">Todas</option>{options.actions.map((action) => <option key={action} value={action}>{ACTION_LABELS[action] || action}</option>)}</select></label>
        <label>CNC<input placeholder="Ex.: CNC03" value={filters.cnc} onChange={(event) => setFilters({ ...filters, cnc: event.target.value })} /></label>
        <label>Arquivo / Plano<input placeholder="Nome ou OP" value={filters.arquivo} onChange={(event) => setFilters({ ...filters, arquivo: event.target.value })} /></label>
        <label>Remessa<input placeholder="Data ou identificação" value={filters.remessa} onChange={(event) => setFilters({ ...filters, remessa: event.target.value })} /></label>
        <div className="programadorAuditFilterActions"><button type="button" onClick={clear}>Limpar</button><button type="submit">Filtrar</button></div>
      </form>

      {error ? <div className="programadorAuditError" role="alert">{error}</div> : null}
      <section className="programadorAuditTableWrap">
        <table>
          <thead><tr><th>Data/hora</th><th>Usuário</th><th>Ação</th><th>Arquivo / Plano</th><th>Detalhes</th><th>CNC</th></tr></thead>
          <tbody>
            {!loading && data.items.length === 0 ? <tr><td colSpan="6" className="programadorAuditEmpty">Nenhuma movimentação encontrada.</td></tr> : null}
            {data.items.map((item) => (
              <tr key={item.id} onClick={() => openDetail(item)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter") openDetail(item); }}>
                <td>{formatDateTime(item.created_at)}</td>
                <td><strong>{item.usuario_nome_snapshot}</strong><small>{item.usuario_role_snapshot === "lider" ? "Líder" : "Programador"}</small></td>
                <td><span className={`programadorAuditBadge action-${item.acao.toLowerCase()}`}>{ACTION_LABELS[item.acao] || item.acao}</span></td>
                <td>{item.arquivo_nome_snapshot || "—"}</td>
                <td className="programadorAuditDetails">{actionDetails(item)}</td>
                <td>{item.cnc_destino || item.cnc_origem || "—"}</td>
              </tr>
            ))}
            {loading ? <tr><td colSpan="6" className="programadorAuditEmpty">Carregando histórico...</td></tr> : null}
          </tbody>
        </table>
      </section>

      <div className="programadorAuditPagination">
        <button disabled={loading || data.page <= 1} onClick={() => load(data.page - 1)}>Anterior</button>
        <span>Página {data.page} de {data.pages}</span>
        <button disabled={loading || data.page >= data.pages} onClick={() => load(data.page + 1)}>Próxima</button>
      </div>

      {detail ? (
        <div className="programadorAuditOverlay" onClick={() => setDetail(null)}>
          <article className="programadorAuditModal" onClick={(event) => event.stopPropagation()}>
            <button className="programadorAuditClose" onClick={() => setDetail(null)} aria-label="Fechar">×</button>
            <span className="programadorAuditModalEyebrow">DETALHES DA ATIVIDADE</span>
            <h2>{ACTION_LABELS[detail.acao] || detail.acao}</h2>
            {detailLoading ? <p>Carregando...</p> : (
              <>
                <dl>
                  <div><dt>Usuário</dt><dd>{detail.usuario_nome_snapshot}</dd></div>
                  <div><dt>Perfil</dt><dd>{detail.usuario_role_snapshot === "lider" ? "Líder" : "Programador"}</dd></div>
                  <div><dt>Data</dt><dd>{formatDateTime(detail.created_at)}</dd></div>
                  <div><dt>Plano</dt><dd>{detail.arquivo_nome_snapshot || "—"}</dd></div>
                  <div><dt>Antes</dt><dd>{displayValue(detail.valor_anterior || detail.cnc_origem)}</dd></div>
                  <div><dt>Depois</dt><dd>{displayValue(detail.valor_novo || detail.cnc_destino)}</dd></div>
                </dl>
                {detail.metadata ? <div className="programadorAuditTechnical"><strong>Informações técnicas</strong><p>{displayValue(detail.metadata)}</p></div> : null}
                {timeline.length ? <section className="programadorAuditTimeline"><h3>Histórico do plano</h3>{timeline.map((event) => <div key={event.id}><time>{formatDateTime(event.created_at)}</time><span>{event.usuario_nome_snapshot} — {ACTION_LABELS[event.acao] || event.acao}</span></div>)}</section> : null}
              </>
            )}
          </article>
        </div>
      ) : null}
    </main>
  );
}
