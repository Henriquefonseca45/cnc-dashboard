import React, { useEffect, useMemo, useState } from "react";
import { MessageSquare, Monitor, RefreshCw } from "lucide-react";
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

function materialDate(req) {
  const st = String(req?.status || "").toUpperCase();
  if (st === "ENTREGUE") return `Entregue: ${fmtDate(req.entregue_em || req.atendido_em)}`;
  if (st === "CANCELADA_SEM_MATERIAL") return `Cancelada: ${fmtDate(req.cancelado_em || req.atualizado_em)} - SEM MATERIAL`;
  if (st === "CANCELADA") return `Cancelada: ${fmtDate(req.cancelado_em || req.atualizado_em)}`;
  if (st === "EM_SEPARACAO") return `Separando: ${fmtDate(req.em_separacao_em || req.atualizado_em)}`;
  return `Solicitado: ${fmtDate(req.criado_em)}`;
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

  return (
    <section className={tv ? "almoxTvPage" : "almoxCardsPage"}>
      <header className={tv ? "almoxTvHeader" : "almoxCardsHeader"}>
        <div>
          <h1>Painel Almoxarifado - Solicitações de Material</h1>
          <span>
            Pendentes: {counts.pendentes} | Em separação: {counts.separacao} | Sem material: {counts.semMaterial} | Última atualização: {updatedAt.toLocaleTimeString("pt-BR")}
          </span>
        </div>
        {!tv ? (
          <button onClick={() => loadData()} disabled={loading}>
            <RefreshCw size={16} />
            {loading ? "Atualizando..." : "Atualizar"}
          </button>
        ) : null}
      </header>

      {error && !tv ? <div className="almoxCardsError">{error}</div> : null}

      <div className={tv ? "almoxTvGrid" : "almoxCardsGrid"}>
        {cardMachines.map((machine) => {
          const queue = queues[machine.id] || [];
          const current = queue.find((item) => String(item.status || "").toUpperCase() === "EM_EXECUCAO");
          const next = queue.filter((item) => String(item.status || "").toUpperCase() !== "EM_EXECUCAO").slice(0, tv ? 2 : 3);
          const materialList = (requestsByMachine[machine.id] || []).slice(0, 3);
          const totalMaterials = (requestsByMachine[machine.id] || []).length;

          return (
            <article key={machine.id} className={tv ? "almoxTvCard" : "almoxCncCard"}>
              <div className="almoxCardHeader">
                <div>
                  <strong>{machine.id}</strong>
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
        </div>
      </header>

      {tab === "cards" ? <AlmoxarifadoCardsView /> : <AlmoxarifadoChatPage embedded basePath="/almoxarifado" />}
    </main>
  );
}
