import React, { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Moon, Sun, WifiOff, Wrench } from "lucide-react";
import { http } from "./http";
import { useAppTheme } from "./theme";
import { buildMaintenanceCards, elapsedFromServer, formatElapsed, maintenanceCardTone } from "./maintenanceTvUtils";
import "./MaintenanceTvPage.css";

const POLL_MS = 4000;
const MAX_QUEUE_ITEMS = 3;

function formatStart(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(new Date(value)).replace(",", " às");
}

export default function MaintenanceTvPage() {
  const { themeMode, toggleThemeMode } = useAppTheme("dark");
  const [machines, setMachines] = useState([]);
  const [calls, setCalls] = useState([]);
  const [clientNow, setClientNow] = useState(Date.now());
  const [connected, setConnected] = useState(true);
  const [lastSync, setLastSync] = useState(null);
  const serverOffsetRef = useRef(0);
  const loadingRef = useRef(false);

  async function loadData() {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const [machineRes, maintenanceRes] = await Promise.all([
        http.get("/maquinas"),
        http.get("/api/maintenance/active"),
      ]);
      const receivedAt = Date.now();
      const serverMs = Date.parse(maintenanceRes.data?.serverNow || "");
      if (Number.isFinite(serverMs)) serverOffsetRef.current = serverMs - receivedAt;
      setMachines(Array.isArray(machineRes.data) ? machineRes.data : []);
      setCalls(Array.isArray(maintenanceRes.data?.items) ? maintenanceRes.data.items : []);
      setConnected(true);
      setLastSync(receivedAt);
    } catch (error) {
      console.error("Falha ao sincronizar manutenção:", error);
      setConnected(false);
    } finally {
      loadingRef.current = false;
    }
  }

  useEffect(() => {
    loadData();
    let timer = null;
    const schedule = () => {
      clearInterval(timer);
      if (!document.hidden) timer = setInterval(loadData, POLL_MS);
    };
    const onVisibility = () => {
      schedule();
      if (!document.hidden) loadData();
    };
    const onOnline = () => loadData();
    const onOffline = () => setConnected(false);
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setClientNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const sortedCalls = useMemo(
    () => calls.slice().sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt) || Number(a.id) - Number(b.id)),
    [calls]
  );
  const cards = useMemo(() => buildMaintenanceCards(machines, calls), [machines, calls]);
  const columns = Math.max(1, Math.ceil((cards.length + 1) / 2));
  const elapsed = (startedAt) => formatElapsed(elapsedFromServer(startedAt, serverOffsetRef.current, clientNow));

  return (
    <main className={`maintenanceTv maintenanceTv--${themeMode}`}>
      <header className="maintenanceTv__toolbar">
        <div>
          <Wrench size={18} />
          <strong>MANUTENÇÃO CNC</strong>
          <span>{calls.length} {calls.length === 1 ? "chamado ativo" : "chamados ativos"}</span>
        </div>
        <div className="maintenanceTv__actions">
          {!connected ? <span className="maintenanceTv__offline"><WifiOff size={14} /> Sem comunicação</span> : null}
          <span className="maintenanceTv__sync">{lastSync ? `Atualizado ${new Date(lastSync).toLocaleTimeString("pt-BR")}` : "Sincronizando…"}</span>
          <button type="button" onClick={toggleThemeMode} aria-label="Alternar tema">
            {themeMode === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      <section className="maintenanceTv__grid" style={{ "--maintenance-columns": columns }}>
        <article className="maintenanceQueueCard">
          <div className="maintenanceQueueCard__title">
            <span>FILA DE MANUTENÇÃO</span><b>{sortedCalls.length}</b>
          </div>
          <div className="maintenanceQueueCard__items">
            {sortedCalls.length === 0 ? (
              <div className="maintenanceQueueCard__empty"><Wrench size={28} /><span>Nenhuma manutenção ativa</span></div>
            ) : sortedCalls.slice(0, MAX_QUEUE_ITEMS).map((call, index) => (
              <div className="maintenanceQueueItem" key={call.id}>
                <strong>{index + 1}</strong>
                <div><b>{call.cncName || call.cncId}</b><span>{String(call.type || "Manutenção").toUpperCase()}</span><small>{call.workOrder}</small></div>
                <em>Aberta há {elapsed(call.startedAt)}</em>
              </div>
            ))}
          </div>
          {sortedCalls.length > MAX_QUEUE_ITEMS ? <div className="maintenanceQueueCard__more">+ {sortedCalls.length - MAX_QUEUE_ITEMS} chamados</div> : null}
        </article>

        {cards.map((machine) => {
          const call = machine.maintenance;
          return (
            <article className={`maintenanceMachineCard ${maintenanceCardTone(machine)}`} key={machine.id}>
              <div className={`maintenanceMachineCard__head ${call ? "has-maintenance" : ""}`}>
                <strong>{machine.id}</strong>
                {call ? (
                  <div className="maintenanceMachineCard__type" title={call.type || "Manutenção"}>
                    <small>TIPO</small>
                    <b>{call.type || "Manutenção"}</b>
                  </div>
                ) : null}
                {call ? <time>{elapsed(call.startedAt)}</time> : <span>{machine.status || "—"}</span>}
              </div>
              {call ? (
                <>
                  <div className="maintenanceMachineCard__badge"><Wrench size={14} /> MANUTENÇÃO</div>
                  <dl>
                    {call.workOrder ? <div><dt>ORDEM DE SERVIÇO</dt><dd className="work-order">{call.workOrder}</dd></div> : null}
                    <div><dt>INÍCIO</dt><dd>{formatStart(call.startedAt)}</dd></div>
                  </dl>
                  {call.openingNotes ? <p title={call.openingNotes}>{call.openingNotes}</p> : null}
                </>
              ) : (
                <div className="maintenanceMachineCard__idle"><Wrench size={30} /><strong>Nenhuma manutenção ativa</strong><span>Status atual: {machine.status || "Não informado"}</span></div>
              )}
            </article>
          );
        })}
        {!connected ? <div className="maintenanceTv__stale"><AlertTriangle size={15} /> Dados mantidos enquanto a conexão é restabelecida</div> : null}
      </section>
    </main>
  );
}
