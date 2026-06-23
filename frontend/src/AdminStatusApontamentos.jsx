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

  const headers = useMemo(() => ({
    "x-user-role": "ADMIN",
    "x-user-name": "Admin",
  }), []);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
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
      setError("Informe o motivo da invalidação.");
      return;
    }
    if (!modalRow?.id || saving) return;

    setSaving(true);
    setError("");
    try {
      await http.post(
        `/api/admin/status-apontamentos/${modalRow.id}/invalidar`,
        { motivo: clean },
        { headers }
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
            <p>Administração</p>
            <h1>Apontamentos de Status</h1>
            <span>Visualize e invalide apontamentos incorretos sem apagar o histórico.</span>
          </div>
          <button onClick={loadRows} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "Atualizando..." : "Atualizar"}
          </button>
        </header>

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
            Situação
            <select value={filters.situacao} onChange={(e) => setFilter("situacao", e.target.value)}>
              <option value="todos">Todos</option>
              <option value="validos">Válidos</option>
              <option value="invalidados">Invalidados</option>
            </select>
          </label>
          <button className="adminStatusSearch" onClick={loadRows} disabled={loading}>
            <Search size={16} />
            Filtrar
          </button>
        </div>

        {error ? <div className="adminStatusAlert error">{error}</div> : null}
        {success ? <div className="adminStatusAlert success">{success}</div> : null}

        <div className="adminStatusTableWrap">
          <table className="adminStatusTable">
            <thead>
              <tr>
                <th>CNC</th>
                <th>Operador</th>
                <th>Status</th>
                <th>Início</th>
                <th>Fim</th>
                <th>Duração</th>
                <th>Observação</th>
                <th>Situação</th>
                <th>Motivo invalidação</th>
                <th>Invalidado por</th>
                <th>Invalidado em</th>
                <th>Ação</th>
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
                        {row.invalidado ? "Invalidado" : "Válido"}
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
              Tem certeza que deseja invalidar este apontamento? Ele não será apagado, apenas desconsiderado dos dashboards e relatórios.
            </p>
            <div className="adminStatusModalSummary">
              {modalRow.cnc} · {modalRow.status} · {fmtDate(modalRow.inicio_em)}
            </div>
            <label>
              Motivo da invalidação
              <textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Explique o motivo..." />
            </label>
            <div className="adminStatusModalActions">
              <button onClick={() => setModalRow(null)} disabled={saving}>Cancelar</button>
              <button className="danger" onClick={confirmInvalidar} disabled={saving}>
                {saving ? "Invalidando..." : "Confirmar invalidação"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
