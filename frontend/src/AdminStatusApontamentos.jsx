import React, { useEffect, useMemo, useState } from "react";
import { RefreshCw, Search, ShieldAlert, X } from "lucide-react";
import { http } from "./http";
import { getErrMsg } from "./api";
import "./AdminStatusApontamentos.css";

const CNC_IDS = ["", "CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07", "CNC_TESTE"];

function fmtDate(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return value;
  }
}

function fmtDuration(sec) {
  const total = Math.max(0, Math.floor(Number(sec) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}min`;
  if (m > 0) return `${m}min ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

export default function AdminStatusApontamentos() {
  const [activeTab, setActiveTab] = useState("apontamentos");
  const [filters, setFilters] = useState({
    data_inicio: "",
    data_fim: "",
    cnc: "",
    operador: "",
    status: "",
    situacao: "todos",
  });
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [modalRow, setModalRow] = useState(null);
  const [motivo, setMotivo] = useState("");
  const [saving, setSaving] = useState(false);
  const [auditFilters, setAuditFilters] = useState({
    cnc: "CNC01",
    data_inicio: "",
    data_fim: "",
    ip: "",
  });
  const [auditRows, setAuditRows] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);

  const headers = useMemo(() => ({
    "x-user-role": "ADMIN",
    "x-user-name": "Admin",
  }), []);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function setAuditFilter(key, value) {
    setAuditFilters((prev) => ({ ...prev, [key]: value }));
  }

  async function loadRows() {
    setLoading(true);
    setError("");
    try {
      const params = {};
      for (const [key, value] of Object.entries(filters)) {
        if (value) params[key] = value;
      }
      const res = await http.get("/api/admin/status-apontamentos", { params, headers });
      setRows(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(getErrMsg(err));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadAuditRows() {
    const cncList = auditFilters.cnc
      ? [auditFilters.cnc]
      : CNC_IDS.filter((id) => id && id !== "CNC_TESTE");

    setAuditLoading(true);
    setError("");
    try {
      const params = { limit: 100 };
      if (auditFilters.data_inicio) params.data_inicio = auditFilters.data_inicio;
      if (auditFilters.data_fim) params.data_fim = auditFilters.data_fim;
      if (auditFilters.ip) params.ip = auditFilters.ip;

      const responses = await Promise.all(
        cncList.map((cnc) => http.get(`/api/cncs/${cnc}/queue-audit`, { params, headers })),
      );
      const merged = responses
        .flatMap((res) => (Array.isArray(res.data) ? res.data : []))
        .sort((a, b) => String(b.criado_em || "").localeCompare(String(a.criado_em || "")));
      setAuditRows(merged);
    } catch (err) {
      setError(getErrMsg(err));
      setAuditRows([]);
    } finally {
      setAuditLoading(false);
    }
  }

  useEffect(() => {
    loadRows();
  }, []);

  function openInvalidar(row) {
    setModalRow(row);
    setMotivo("");
    setSuccess("");
    setError("");
  }

  async function confirmInvalidar() {
    const clean = String(motivo || "").trim();
    if (!clean) {
      setError("Informe o motivo da invalidacao.");
      return;
    }
    if (!modalRow?.id || saving) return;

    setSaving(true);
    setError("");
    try {
      await http.post(
        `/api/admin/status-apontamentos/${modalRow.id}/invalidar`,
        { motivo: clean },
        { headers },
      );
      setSuccess("Apontamento invalidado com sucesso.");
      setModalRow(null);
      setMotivo("");
      await loadRows();
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="adminStatusPage">
      <section className="adminStatusShell">
        <header className="adminStatusHeader">
          <div>
            <p>Administracao</p>
            <h1>Apontamentos de Status</h1>
            <span>Visualize, invalide apontamentos e acompanhe rastreamentos da fila.</span>
          </div>
          <button onClick={activeTab === "rastreamento" ? loadAuditRows : loadRows} disabled={loading || auditLoading}>
            <RefreshCw size={16} />
            {loading || auditLoading ? "Atualizando..." : "Atualizar"}
          </button>
        </header>

        <div className="adminStatusTabs">
          <button className={activeTab === "apontamentos" ? "active" : ""} onClick={() => setActiveTab("apontamentos")}>
            Apontamentos
          </button>
          <button
            className={activeTab === "rastreamento" ? "active" : ""}
            onClick={() => {
              setActiveTab("rastreamento");
              if (auditRows.length === 0) loadAuditRows();
            }}
          >
            Rastreamento
          </button>
        </div>

        {error ? <div className="adminStatusAlert error">{error}</div> : null}
        {success ? <div className="adminStatusAlert success">{success}</div> : null}

        {activeTab === "apontamentos" ? (
          <>
            <div className="adminStatusFilters">
              <label>
                Data inicial
                <input type="date" value={filters.data_inicio} onChange={(e) => setFilter("data_inicio", e.target.value)} />
              </label>
              <label>
                Data final
                <input type="date" value={filters.data_fim} onChange={(e) => setFilter("data_fim", e.target.value)} />
              </label>
              <label>
                CNC
                <select value={filters.cnc} onChange={(e) => setFilter("cnc", e.target.value)}>
                  {CNC_IDS.map((id) => <option key={id || "todas"} value={id}>{id || "Todas"}</option>)}
                </select>
              </label>
              <label>
                Operador
                <input value={filters.operador} onChange={(e) => setFilter("operador", e.target.value)} placeholder="Nome do operador" />
              </label>
              <label>
                Status
                <input value={filters.status} onChange={(e) => setFilter("status", e.target.value)} placeholder="Ex.: SETUP" />
              </label>
              <label>
                Situacao
                <select value={filters.situacao} onChange={(e) => setFilter("situacao", e.target.value)}>
                  <option value="todos">Todos</option>
                  <option value="validos">Validos</option>
                  <option value="invalidados">Invalidados</option>
                </select>
              </label>
              <button className="adminStatusSearch" onClick={loadRows} disabled={loading}>
                <Search size={16} />
                Filtrar
              </button>
            </div>

            <div className="adminStatusTableWrap">
              <table className="adminStatusTable">
                <thead>
                  <tr>
                    <th>CNC</th>
                    <th>Operador</th>
                    <th>Status</th>
                    <th>Inicio</th>
                    <th>Fim</th>
                    <th>Duracao</th>
                    <th>Observacao</th>
                    <th>Situacao</th>
                    <th>Motivo invalidacao</th>
                    <th>Invalidado por</th>
                    <th>Invalidado em</th>
                    <th>Acao</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td colSpan={12} className="adminStatusEmpty">
                        {loading ? "Carregando apontamentos..." : "Nenhum apontamento encontrado."}
                      </td>
                    </tr>
                  ) : (
                    rows.map((row) => (
                      <tr key={row.id} className={row.invalidado ? "invalidated" : ""}>
                        <td>{row.cnc || "-"}</td>
                        <td>{row.operador || "-"}</td>
                        <td><strong>{row.status || "-"}</strong></td>
                        <td>{fmtDate(row.inicio_em)}</td>
                        <td>{fmtDate(row.fim_em)}</td>
                        <td>{fmtDuration(row.duracao_seg)}</td>
                        <td>{row.observacao || "-"}</td>
                        <td>
                          <span className={`adminStatusBadge ${row.invalidado ? "bad" : "ok"}`}>
                            {row.invalidado ? "Invalidado" : "Valido"}
                          </span>
                        </td>
                        <td>{row.motivo_invalidacao || "-"}</td>
                        <td>{row.invalidado_por || "-"}</td>
                        <td>{fmtDate(row.invalidado_em)}</td>
                        <td>
                          {row.invalidado ? (
                            <span className="adminStatusMuted">Invalidado</span>
                          ) : (
                            <button className="adminStatusInvalidate" onClick={() => openInvalidar(row)}>
                              Invalidar
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <>
            <div className="adminStatusFilters">
              <label>
                CNC
                <select value={auditFilters.cnc} onChange={(e) => setAuditFilter("cnc", e.target.value)}>
                  {CNC_IDS.filter((id) => id !== "CNC_TESTE").map((id) => (
                    <option key={id || "todas-audit"} value={id}>{id || "Todas"}</option>
                  ))}
                </select>
              </label>
              <label>
                Data inicial
                <input type="date" value={auditFilters.data_inicio} onChange={(e) => setAuditFilter("data_inicio", e.target.value)} />
              </label>
              <label>
                Data final
                <input type="date" value={auditFilters.data_fim} onChange={(e) => setAuditFilter("data_fim", e.target.value)} />
              </label>
              <label>
                IP
                <input value={auditFilters.ip} onChange={(e) => setAuditFilter("ip", e.target.value)} placeholder="Ex.: 192.168.1.35" />
              </label>
              <button className="adminStatusSearch" onClick={loadAuditRows} disabled={auditLoading}>
                <Search size={16} />
                Filtrar
              </button>
            </div>

            <div className="adminStatusTableWrap">
              <table className="adminStatusTable audit">
                <thead>
                  <tr>
                    <th>Data e hora</th>
                    <th>CNC</th>
                    <th>Arquivo</th>
                    <th>Movimentacao</th>
                    <th>IP</th>
                  </tr>
                </thead>
                <tbody>
                  {auditRows.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="adminStatusEmpty">
                        {auditLoading ? "Carregando rastreamento..." : "Nenhum registro de rastreamento encontrado."}
                      </td>
                    </tr>
                  ) : (
                    auditRows.map((row) => (
                      <tr key={row.id}>
                        <td>{fmtDate(row.criado_em)}</td>
                        <td><strong>{row.cnc_id || "-"}</strong></td>
                        <td>{row.arquivo_nome || row.arquivo_id || "-"}</td>
                        <td>Posicao {row.posicao_anterior ?? "-"} -> {row.posicao_nova ?? "-"}</td>
                        <td>{row.ip_origem || "-"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {modalRow ? (
        <div className="adminStatusModalOverlay" onClick={() => !saving && setModalRow(null)}>
          <div className="adminStatusModal" onClick={(e) => e.stopPropagation()}>
            <button className="adminStatusClose" onClick={() => setModalRow(null)} disabled={saving}>
              <X size={18} />
            </button>
            <ShieldAlert size={34} className="adminStatusModalIcon" />
            <h2>Invalidar apontamento de status</h2>
            <p>
              Tem certeza que deseja invalidar este apontamento? Ele nao sera apagado, apenas desconsiderado dos dashboards e relatorios.
            </p>
            <div className="adminStatusModalSummary">
              {modalRow.cnc} - {modalRow.status} - {fmtDate(modalRow.inicio_em)}
            </div>
            <label>
              Motivo da invalidacao
              <textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Explique o motivo..." />
            </label>
            <div className="adminStatusModalActions">
              <button onClick={() => setModalRow(null)} disabled={saving}>Cancelar</button>
              <button className="danger" onClick={confirmInvalidar} disabled={saving}>
                {saving ? "Invalidando..." : "Confirmar invalidacao"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
