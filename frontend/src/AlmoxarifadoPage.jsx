import React, { useEffect, useMemo, useState } from "react";
import { History, MessageSquare, Monitor, RefreshCw } from "lucide-react";
import { http } from "./http";
import { getErrMsg } from "./api";
import AlmoxarifadoChatPage from "./AlmoxarifadoChatPage.jsx";
import "./AlmoxarifadoPage.css";

const CNC_IDS = ["CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07"];

function fmtDate(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return value;
  }
}

function todayValue() {
  return new Date().toISOString().slice(0, 10);
}

function fmtHHMMSS(totalSec) {
  const sec = Math.max(0, Math.floor(Number(totalSec) || 0));
  const hh = String(Math.floor(sec / 3600)).padStart(2, "0");
  const mm = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function statusLabel(status) {
  const st = String(status || "").toUpperCase();
  if (st === "ENTREGUE") return "ENTREGUE";
  if (st === "CANCELADA_SEM_MATERIAL") return "SEM MATERIAL";
  if (st === "CANCELADA") return "CANCELADA";
  if (st === "EM_SEPARACAO") return "EM SEPARACAO";
  return "ABERTA";
}

function statusClass(status) {
  const st = String(status || "").toUpperCase();
  if (st === "ENTREGUE") return "delivered";
  if (st === "CANCELADA_SEM_MATERIAL") return "noMaterial";
  if (st === "CANCELADA") return "canceled";
  if (st === "EM_SEPARACAO") return "separating";
  return "open";
}

function machineCardClass(status) {
  const st = String(status || "").toUpperCase();
  if (st.includes("USINANDO")) return "machineRunning";
  if (st.includes("EMPILHADEIRA")) return "machineMaterialWait";
  return "";
}

function isUsinandoMachineStatus(status = "") {
  const st = String(status || "").toUpperCase();
  return (
    st.includes("USIN") ||
    st.includes("CORT") ||
    st.includes("DETALHE CNC") ||
    st === "RNC" ||
    (st.includes("ABERTURA") && st.includes("MATERIAL"))
  );
}

function calcTempoRestanteArquivo(item, machineStatus, nowMs) {
  const total = Number(item?.tempo_estimado_seg || 0);
  if (!total || total <= 0) return null;

  const startMs = Date.parse(item?.tempo_inicio_em || "");
  if (!startMs) return null;

  const pausedAccum = Math.max(0, Number(item?.tempo_pausado_seg || 0));
  const pauseStartMs = Date.parse(item?.tempo_pausa_inicio_em || "");
  let effectiveNow = nowMs;

  if (!isUsinandoMachineStatus(machineStatus)) {
    effectiveNow = item?.tempo_pausa_inicio_em && pauseStartMs ? pauseStartMs : startMs + pausedAccum * 1000;
  }

  const elapsed = Math.floor((effectiveNow - startMs) / 1000);
  const effectiveElapsed = Math.max(0, elapsed - pausedAccum);
  return Math.max(0, total - effectiveElapsed);
}

function extractEspessuraLabel(text = "") {
  const raw = String(text || "");
  const numberedSpecialMatch = /\b(\d+(?:[,.]\d+)?\s*(?:EX|MDF))\b/i.exec(raw);
  if (numberedSpecialMatch) return numberedSpecialMatch[1].replace(/\s+/g, "").toUpperCase();

  const namedMatch = /\b(EX|MDF|RNC|DETALHE)\b/i.exec(raw);
  if (namedMatch) return namedMatch[1].toUpperCase();

  const codeMatch = /\b(\d+(?:[,.]\d+)?\s*(?:TX|KP|AD))\b/i.exec(raw);
  if (codeMatch) return codeMatch[1].replace(/\s+/g, "").toUpperCase();

  const mmMatch = /(\d+(?:[,.]\d+)?)\s*mm\b/i.exec(raw);
  if (mmMatch) return `${mmMatch[1].replace(",", ".")}mm`;

  return "Sem espessura";
}

function buildRequestSummary(items = []) {
  const map = new Map();

  for (const item of items || []) {
    const label = extractEspessuraLabel(`${item.material || ""} ${item.arquivo_nome || ""}`);
    map.set(label, (map.get(label) || 0) + 1);
  }

  return Array.from(map.entries())
    .map(([label, count]) => ({
      label,
      count,
      sort: label === "Sem espessura" ? Number.MAX_SAFE_INTEGER : Number.parseFloat(label),
    }))
    .sort((a, b) => {
      const aSort = Number.isFinite(a.sort) ? a.sort : 900000;
      const bSort = Number.isFinite(b.sort) ? b.sort : 900000;
      return aSort - bSort || a.label.localeCompare(b.label);
    });
}

function materialDate(req) {
  const st = String(req?.status || "").toUpperCase();
  if (st === "ENTREGUE") return `Entregue: ${fmtDate(req.entregue_em || req.atendido_em)}`;
  if (st === "CANCELADA_SEM_MATERIAL") return `Cancelada: ${fmtDate(req.cancelado_em || req.atualizado_em)} - SEM MATERIAL`;
  if (st === "CANCELADA") return `Cancelada: ${fmtDate(req.cancelado_em || req.atualizado_em)}`;
  if (st === "EM_SEPARACAO") return `Separando: ${fmtDate(req.em_separacao_em || req.atualizado_em)}`;
  return `Solicitado: ${fmtDate(req.criado_em)}`;
}

function requestAgeLabel(req, nowMs) {
  const start = Date.parse(req?.criado_em || "");
  if (!start) return "-- min";
  const min = Math.max(0, Math.floor((nowMs - start) / 60000));
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${m}min` : `${h}h`;
}

function isActiveMaterial(req) {
  return ["ABERTA", "AGUARDANDO_ALMOXARIFADO", "EM_SEPARACAO"].includes(String(req?.status || "").toUpperCase());
}

export function AlmoxarifadoCardsView({ tv = false }) {
  const [machines, setMachines] = useState([]);
  const [queues, setQueues] = useState({});
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(new Date());
  const [nowTick, setNowTick] = useState(Date.now());

  async function loadData(silent = false) {
    if (!silent) setLoading(true);
    try {
      const machineRes = await http.get("/maquinas");
      const machineList = (Array.isArray(machineRes.data) ? machineRes.data : []).filter((m) =>
        CNC_IDS.includes(String(m.id || "").toUpperCase())
      );
      const queuePairs = await Promise.all(
        machineList.map(async (machine) => {
          const res = await http.get(`/fila/${machine.id}`).catch(() => ({ data: [] }));
          return [machine.id, Array.isArray(res.data) ? res.data : []];
        })
      );
      const reqRes = await http.get(tv ? "/api/material/solicitacoes/tv" : "/api/material/solicitacoes/cards", {
        params: { limit: 500 },
      });

      setMachines(machineList);
      setQueues(Object.fromEntries(queuePairs));
      setRequests(Array.isArray(reqRes.data) ? reqRes.data : []);
      setUpdatedAt(new Date());
      setError("");
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      if (!silent) setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    const t = setInterval(() => loadData(true), tv ? 10000 : 5000);
    return () => clearInterval(t);
  }, [tv]);

  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const counts = useMemo(() => {
    return requests.reduce(
      (acc, req) => {
        const st = String(req.status || "").toUpperCase();
        if (isActiveMaterial(req)) acc.pendentes += 1;
        if (st === "EM_SEPARACAO") acc.separacao += 1;
        if (st === "CANCELADA_SEM_MATERIAL") acc.semMaterial += 1;
        return acc;
      },
      { pendentes: 0, separacao: 0, semMaterial: 0 }
    );
  }, [requests]);

  const requestsByMachine = useMemo(() => {
    const grouped = {};
    for (const req of requests) {
      const id = String(req.maquina_id || "").toUpperCase();
      grouped[id] = grouped[id] || [];
      grouped[id].push(req);
    }
    for (const id of Object.keys(grouped)) {
      grouped[id].sort((a, b) => {
        const aActive = isActiveMaterial(a);
        const bActive = isActiveMaterial(b);
        if (aActive !== bActive) return aActive ? -1 : 1;
        const at = Date.parse(aActive ? a.criado_em : a.cancelado_em || a.entregue_em || a.atualizado_em || a.criado_em || "") || 0;
        const bt = Date.parse(bActive ? b.criado_em : b.cancelado_em || b.entregue_em || b.atualizado_em || b.criado_em || "") || 0;
        return aActive ? at - bt : bt - at;
      });
    }
    return grouped;
  }, [requests]);

  const cardMachines = machines.length ? machines : CNC_IDS.map((id) => ({ id, nome: id, status: "-" }));
  const priorityRequests = useMemo(() => {
    return requests
      .filter(isActiveMaterial)
      .slice()
      .sort((a, b) => {
        const at = Date.parse(a.criado_em || "") || 0;
        const bt = Date.parse(b.criado_em || "") || 0;
        return at - bt || Number(a.id || 0) - Number(b.id || 0);
      })
      .slice(0, 3);
  }, [requests]);

  return (
    <section className={tv ? "almoxTvPage" : "almoxCardsPage"}>
      {!tv ? (
        <header className="almoxCardsHeader">
        <div>
          <h1>Painel Almoxarifado - Solicitações de Material</h1>
          <span>
            Pendentes: {counts.pendentes} | Em separação: {counts.separacao} | Sem material: {counts.semMaterial} | Última atualização: {updatedAt.toLocaleTimeString("pt-BR")}
          </span>
        </div>
          <button onClick={() => loadData()} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "Atualizando..." : "Atualizar"}
          </button>
        </header>
      ) : null}

      {error && !tv ? <div className="almoxCardsError">{error}</div> : null}

      <div className={tv ? "almoxTvGrid" : "almoxCardsGrid"}>
        {tv ? (
          <div className="almoxTvPriorityCard">
            <div className="almoxTvPriorityTitle">Ordem de prioridade</div>
            {priorityRequests.length === 0 ? (
              <div className="almoxTvPriorityEmpty">Nenhuma solicitação aberta.</div>
            ) : (
              priorityRequests.map((req, index) => (
                <div key={req.id} className="almoxTvPriorityItem">
                  <div className="almoxTvPriorityRank">{index + 1}º</div>
                  <div className="almoxTvPriorityInfo">
                    <strong>{req.maquina_id || "-"}</strong>
                    <b>{req.material || "Material não informado"}</b>
                    <span>
                      Solicitação #{req.id} · {fmtDate(req.criado_em)}
                    </span>
                  </div>
                  <em>{requestAgeLabel(req, nowTick)}</em>
                </div>
              ))
            )}
          </div>
        ) : null}
        {cardMachines.map((machine) => {
          const queue = queues[machine.id] || [];
          const current = queue.find((item) => String(item.status || "").toUpperCase() === "EM_EXECUCAO");
          const next = queue.filter((item) => String(item.status || "").toUpperCase() !== "EM_EXECUCAO").slice(0, tv ? 3 : 2);
          const machineRequests = requestsByMachine[machine.id] || [];
          const visibleRequests = tv ? machineRequests.filter(isActiveMaterial) : machineRequests;
          const materialList = visibleRequests.slice(0, 2);
          const totalMaterials = visibleRequests.length;
          const toneClass = machineCardClass(machine.status);
          const tempoRestante = calcTempoRestanteArquivo(current, machine.status, nowTick);

          return (
            <article key={machine.id} className={`${tv ? "almoxTvCard" : "almoxCncCard"} ${toneClass}`}>
              <div className="almoxCardHeader">
                <div>
                  <strong>{machine.id}</strong>
                  <em>{tempoRestante == null ? "--:--:--" : fmtHHMMSS(tempoRestante)}</em>
                  <small>{machine.nome || machine.id}</small>
                </div>
                <span>{machine.status || "-"}</span>
              </div>

              <div className="almoxCardBlock">
                <b>Arquivo atual</b>
                <p title={current?.arquivo_nome || ""}>{current?.arquivo_nome || "Nenhum arquivo em execução"}</p>
              </div>

              <div className="almoxCardBlock">
                <b>Próximos na fila</b>
                {next.length === 0 ? (
                  <p>Fila vazia</p>
                ) : (
                  next.map((item) => <p key={item.id} title={item.arquivo_nome}>{item.posicao}. {item.arquivo_nome}</p>)
                )}
              </div>

              <div className="almoxMaterials">
                <div className="almoxMaterialsTitle">
                  <b>Solicitações de Material</b>
                  <span>{totalMaterials}</span>
                </div>
                {materialList.length === 0 ? (
                  <p className="almoxEmptyMaterial">Sem solicitações</p>
                ) : (
                  materialList.map((req) => (
                    <div key={req.id} className={`almoxMaterialItem ${statusClass(req.status)}`}>
                      <div>
                        <strong title={req.material}>{req.material || "Material não informado"}</strong>
                        <p title={req.arquivo_nome}>{req.arquivo_nome || "Arquivo não informado"}</p>
                        <small>{materialDate(req)}</small>
                      </div>
                      <span>{statusLabel(req.status)}</span>
                    </div>
                  ))
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function AlmoxarifadoHistoryView() {
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedLabel, setSelectedLabel] = useState("");
  const [dateStart, setDateStart] = useState(todayValue);
  const [dateEnd, setDateEnd] = useState(todayValue);

  async function loadHistory() {
    setLoading(true);
    try {
      const res = await http.get("/api/material/solicitacoes", {
        params: {
          status: "ENTREGUE",
          data_inicial: dateStart || undefined,
          data_final: dateEnd || dateStart || undefined,
          limit: 5000,
        },
      });
      setRequests(Array.isArray(res.data) ? res.data : []);
      setError("");
    } catch (err) {
      setError(getErrMsg(err));
      setRequests([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  const requestSummary = useMemo(() => buildRequestSummary(requests), [requests]);
  const filteredRequests = useMemo(() => {
    const base = selectedLabel
      ? requests.filter((req) => extractEspessuraLabel(`${req.material || ""} ${req.arquivo_nome || ""}`) === selectedLabel)
      : requests;

    return base.slice().sort((a, b) => {
      const at = Date.parse(a.entregue_em || a.atendido_em || a.atualizado_em || a.criado_em || "") || 0;
      const bt = Date.parse(b.entregue_em || b.atendido_em || b.atualizado_em || b.criado_em || "") || 0;
      return bt - at;
    });
  }, [requests, selectedLabel]);

  return (
    <section className="almoxCardsPage">
      <header className="almoxCardsHeader">
        <div>
          <h1>Histórico de solicitações</h1>
          <span>
            {selectedLabel ? `Entregues da espessura ${selectedLabel}` : "Use o período para ver tudo que foi entregue naquela data."}
          </span>
        </div>
        <div className="almoxHistoryFilters">
          <label>
            Início
            <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
          </label>
          <label>
            Fim
            <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
          </label>
          <button onClick={loadHistory} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "Buscando..." : "Buscar entregues"}
          </button>
        </div>
      </header>

      {error ? <div className="almoxCardsError">{error}</div> : null}

      <div className="almoxRequestHistory">
        <div className="almoxRequestHistoryTop">
          <div className="almoxRequestHistoryTitle">Solicitações por espessura</div>
          {selectedLabel ? (
            <button onClick={() => setSelectedLabel("")}>Mostrar todas</button>
          ) : null}
        </div>
        <div className="almoxRequestHistoryGrid">
          {requestSummary.length === 0 ? (
            <div className="almoxEmptyMaterial">Nenhuma solicitação registrada.</div>
          ) : (
            requestSummary.map((item) => (
              <button
                key={item.label}
                className={`almoxRequestChip ${selectedLabel === item.label ? "active" : ""}`}
                onClick={() => setSelectedLabel(item.label)}
              >
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </button>
            ))
          )}
        </div>
      </div>

      <div className="almoxHistoryList">
        {filteredRequests.length === 0 ? (
          <div className="almoxEmptyMaterial">
            {loading ? "Carregando solicitações..." : "Nenhuma chapa encontrada para esse filtro."}
          </div>
        ) : (
          filteredRequests.map((req) => (
            <div key={req.id} className={`almoxHistoryRow ${statusClass(req.status)}`}>
              <div className="almoxHistoryMain">
                <strong>{req.material || "Material não informado"}</strong>
                <span>{req.arquivo_nome || "Arquivo não informado"}</span>
                <small>{materialDate(req)}</small>
              </div>
              <div className="almoxHistoryMeta">
                <span>{req.maquina_id || "-"}</span>
                <span className={`almoxHistoryStatus ${statusClass(req.status)}`}>{statusLabel(req.status)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export default function AlmoxarifadoPage() {
  const [tab, setTab] = useState("chat");

  return (
    <main className="almoxPage">
      <header className="almoxPageHeader">
        <div>
          <p>Almoxarifado</p>
          <h1>Solicitações de Material</h1>
        </div>
        <div className="almoxTabs">
          <button className={tab === "cards" ? "active" : ""} onClick={() => setTab("cards")}>
            <Monitor size={16} />
            Cards
          </button>
          <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
            <MessageSquare size={16} />
            Chat Solicitações
          </button>
          <button className={tab === "historico" ? "active" : ""} onClick={() => setTab("historico")}>
            <History size={16} />
            Histórico
          </button>
        </div>
      </header>

      {tab === "cards" ? (
        <AlmoxarifadoCardsView />
      ) : tab === "historico" ? (
        <AlmoxarifadoHistoryView />
      ) : (
        <AlmoxarifadoChatPage embedded basePath="/almoxarifado" />
      )}
    </main>
  );
}
