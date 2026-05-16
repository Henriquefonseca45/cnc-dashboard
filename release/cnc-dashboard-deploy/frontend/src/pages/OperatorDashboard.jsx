import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import {
  RefreshCw,
  Plus,
  FileText,
  MoreVertical,
  Download,
  CheckCircle2,
  Activity,
  Clock3,
  User2,
  Wrench,
  Play,
  X,
} from "lucide-react";

const API = import.meta.env.VITE_API_URL || "";
const CNC_IDS = ["CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07"];

function cn(...s) {
  return s.filter(Boolean).join(" ");
}

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function StatusPill({ label }) {
  const base =
    "px-2.5 py-0.5 rounded-full text-[10px] font-medium border whitespace-nowrap";

  const cls =
    label === "Usinando"
      ? "bg-emerald-500/10 text-emerald-200 border-emerald-500/20"
      : label === "Programado"
      ? "bg-sky-500/10 text-sky-200 border-sky-500/20"
      : label === "Concluído"
      ? "bg-emerald-500/10 text-emerald-200 border-emerald-500/20"
      : label === "Cancelado"
      ? "bg-red-500/10 text-red-200 border-red-500/20"
      : label === "Baixado"
      ? "bg-sky-500/10 text-sky-200 border-sky-500/20"
      : "bg-slate-500/10 text-slate-200 border-slate-500/20";

  return <span className={cn(base, cls)}>{label}</span>;
}

function Shell({ children }) {
  return (
    <div className="min-h-screen text-slate-100 bg-[#050914]">
      <div className="pointer-events-none fixed inset-0">
        <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[900px] h-[420px] bg-emerald-500/10 blur-[110px]" />
        <div className="absolute top-28 left-10 w-[520px] h-[320px] bg-sky-500/8 blur-[110px]" />
      </div>
      {children}
    </div>
  );
}

function Topbar({ onRefresh }) {
  return (
    <div className="sticky top-0 z-20 border-b border-white/5 bg-[#050914]/70 backdrop-blur">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/12 border border-emerald-500/20 flex items-center justify-center">
            <span className="text-sm font-bold text-emerald-200">CN</span>
          </div>
          <div className="leading-tight">
            <div className="text-lg font-semibold">Painel do Operador</div>
            <div className="text-xs text-slate-400">Controle CNC</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onRefresh}
            className="h-10 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 inline-flex items-center"
            title="Atualizar"
          >
            <RefreshCw size={16} className="opacity-80" />
          </button>

          <button className="h-10 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold inline-flex items-center gap-2">
            <Plus size={16} />
            Novo Arquivo
          </button>
        </div>
      </div>
    </div>
  );
}

function Card({ title, right, children }) {
  return (
    <div className="rounded-2xl bg-[#0b1224]/55 border border-white/8 shadow-[0_20px_50px_-40px_rgba(0,0,0,0.9)] backdrop-blur">
      <div className="px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="text-[10px] font-semibold tracking-[0.20em] text-slate-200/85">
          {title}
        </div>
        {right}
      </div>
      <div className="px-5 pb-4">{children}</div>
    </div>
  );
}

function StatBox({ icon, label, value }) {
  return (
    <div className="rounded-2xl bg-black/20 border border-white/5 p-4">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-400">
        <span className="opacity-80">{icon}</span>
        {label}
      </div>
      <div className="mt-2 font-semibold truncate">{value}</div>
    </div>
  );
}

function Row({ title, subtitle, leftIcon, right }) {
  return (
    <div className="rounded-2xl bg-black/20 border border-white/5 p-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
          {leftIcon}
        </div>
        <div className="min-w-0">
          <div className="font-semibold truncate">{title}</div>
          <div className="text-xs text-slate-400 truncate">{subtitle}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">{right}</div>
    </div>
  );
}

export default function OperatorDashboard() {
  const [cnc, setCnc] = useState("CNC01");

  const [maquinas, setMaquinas] = useState([]);
  const [fila, setFila] = useState([]);
  const [historico, setHistorico] = useState([]);

  const [executando, setExecutando] = useState(null);
  const [loading, setLoading] = useState(false);

  const [menuOpenId, setMenuOpenId] = useState(null);

  const maquinaAtual = useMemo(
    () => maquinas.find((m) => m.id === cnc),
    [maquinas, cnc]
  );

  function toggleMenu(id) {
    setMenuOpenId((prev) => (prev === id ? null : id));
  }

  useEffect(() => {
    function close() {
      setMenuOpenId(null);
    }
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  async function carregarTudo() {
    setLoading(true);
    try {
      const [mRes, fRes, hRes] = await Promise.all([
        axios.get(`${API}/maquinas`),
        axios.get(`${API}/fila/${cnc}`, { params: { include_done: false } }),
        axios.get(`${API}/historico/${cnc}`),
      ]);

      const maquinasData = mRes.data || [];
      const filaData = fRes.data || [];
      const histData = hRes.data || [];

      setMaquinas(maquinasData);
      setFila(filaData);
      setHistorico(histData);

      const atual = filaData.find(
        (x) => String(x.status || "").toUpperCase() === "USINANDO"
      );
      setExecutando(atual || null);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    carregarTudo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cnc]);

  async function baixarArquivo(item) {
    const arquivoId = item.arquivo_id ?? item.id;
    window.open(`${API}/agente/${cnc}/download/${arquivoId}`, "_blank");

    try {
      await axios.post(`${API}/agente/${cnc}/baixado`, { arquivo_id: arquivoId });
    } catch {}
    carregarTudo();
  }

  // ✅ REGRA DO SEU FLUXO
  // PROGRAMADO: só muda pill
  // USINANDO: vira executando + arquivo atual
  // CONCLUIDO/CANCELADO: sai da fila e vai pro histórico
  async function setItemStatus(item, novoStatus) {
    const beforeStatus = item.status;

    // UI instantânea
    setFila((prev) => {
      let next = prev.map((x) => {
        if (novoStatus === "USINANDO") {
          // garante 1 usinando
          if (
            x.id !== item.id &&
            String(x.status || "").toUpperCase() === "USINANDO"
          ) {
            return { ...x, status: "PROGRAMADO" };
          }
        }
        if (x.id === item.id) return { ...x, status: novoStatus };
        return x;
      });

      if (novoStatus === "CONCLUIDO" || novoStatus === "CANCELADO") {
        next = next.filter((x) => x.id !== item.id);
      }
      return next;
    });

    if (novoStatus === "USINANDO") {
      setExecutando({ ...item, status: "USINANDO" });
    }

    if ((novoStatus === "CONCLUIDO" || novoStatus === "CANCELADO") && executando?.id === item.id) {
      setExecutando(null);
    }

    if (novoStatus === "CONCLUIDO" || novoStatus === "CANCELADO") {
      setHistorico((prev) => [
        {
          id: item.id,
          arquivo_nome: item.arquivo_nome || item.nome,
          nome: item.nome,
          status: novoStatus,
          finalizado_em: new Date().toISOString(),
          criado_em: item.criado_em,
          material: item.material,
        },
        ...prev,
      ]);
    }

    try {
      // ✅ persistência
      await axios.post(`${API}/fila/${cnc}/status`, { id: item.id, status: novoStatus });

      // concluiu/cancelou: recarrega pra pegar do banco certinho
      if (novoStatus === "CONCLUIDO" || novoStatus === "CANCELADO") {
        carregarTudo();
      }
    } catch (e) {
      console.error(e);
      carregarTudo(); // rollback seguro
    } finally {
      setMenuOpenId(null);
    }
  }

  return (
    <Shell>
      <Topbar onRefresh={carregarTudo} />

      <div className="relative max-w-6xl mx-auto px-6 py-8">
        <div className="flex flex-wrap items-center gap-2 mb-6">
          {CNC_IDS.map((id) => (
            <button
              key={id}
              onClick={() => setCnc(id)}
              className={cn(
                "h-10 px-4 rounded-xl text-sm border transition",
                id === cnc
                  ? "bg-emerald-600/18 border-emerald-600/25 text-emerald-200"
                  : "bg-white/5 border-white/10 text-slate-200 hover:bg-white/10"
              )}
            >
              {id.replace("CNC", "CNC-")}
            </button>
          ))}
          {loading && (
            <span className="text-xs text-slate-400 ml-2">carregando…</span>
          )}
        </div>

        <div className="grid grid-cols-12 gap-6 items-start">
          {/* ESQUERDA */}
          <div className="col-span-12 md:col-span-4">
            <Card
              title={cnc.replace("CNC", "CNC-")}
              right={
                <span className="px-3 py-1 rounded-xl bg-white/5 border border-white/10 text-xs text-slate-200">
                  {maquinaAtual?.status || "—"}
                </span>
              }
            >
              <div className="grid grid-cols-2 gap-3">
                <StatBox
                  icon={<User2 size={14} className="text-slate-300" />}
                  label="Operador"
                  value={"—"}
                />
                <StatBox
                  icon={<FileText size={14} className="text-slate-300" />}
                  label="Arquivo atual"
                  value={executando?.arquivo_nome || executando?.nome || "—"}
                />
              </div>

              <div className="mt-5">
                <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">
                  Alterar status
                </div>

                <select className="w-full h-11 rounded-xl bg-white/5 border border-white/10 px-3 text-sm outline-none">
                  <option>Ociosa</option>
                  <option>Operando</option>
                  <option>Parada</option>
                  <option>Manutenção</option>
                </select>

                {/* botões podem continuar, mas o fluxo principal é pelo menu ⋮ */}
                <div className="grid grid-cols-2 gap-2 mt-4">
                  <button
                    className="h-12 px-4 rounded-xl bg-sky-600 hover:bg-sky-500 text-sm font-semibold transition"
                    onClick={() => {
                      // padrão: executar próximo = colocar o primeiro item em USINANDO
                      const first = fila[0];
                      if (first) setItemStatus(first, "USINANDO");
                    }}
                  >
                    Executar Próximo
                  </button>

                  <button
                    className="h-12 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold transition"
                    disabled={!executando?.id}
                    onClick={() => executando?.id && setItemStatus(executando, "CONCLUIDO")}
                  >
                    Cortado
                  </button>
                </div>
              </div>
            </Card>
          </div>

          {/* CENTRO - FILA */}
          <div className="col-span-12 md:col-span-5">
            <Card
              title="FILA DE ARQUIVOS"
              right={
                <span className="px-3 py-1 rounded-xl bg-white/5 border border-white/10 text-xs">
                  {fila.length} itens
                </span>
              }
            >
              <div className="space-y-3">
                {fila.map((item) => {
                  const st = String(item.status || "").toUpperCase();
                  const label =
                    st === "USINANDO"
                      ? "Usinando"
                      : st === "PROGRAMADO"
                      ? "Programado"
                      : st === "CONCLUIDO"
                      ? "Concluído"
                      : st === "CANCELADO"
                      ? "Cancelado"
                      : st === "BAIXADO"
                      ? "Baixado"
                      : "Na Fila";

                  const title =
                    item.arquivo_nome || item.nome || `Arquivo #${item.id}`;
                  const subtitle = [
                    item.material || "—",
                    item.tempo_estimado_min ? `${item.tempo_estimado_min}min` : "",
                  ]
                    .filter(Boolean)
                    .join(" • ");

                  return (
                    <Row
                      key={item.id}
                      leftIcon={<FileText size={18} className="text-slate-200/85" />}
                      title={title}
                      subtitle={subtitle}
                      right={
                        <>
                          <StatusPill label={label} />

                          <button
                            onClick={() => baixarArquivo(item)}
                            className="h-10 w-10 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center"
                            title="Baixar"
                          >
                            <Download size={16} className="text-slate-200/85" />
                          </button>

                          {/* MENU ⋮ */}
                          <div className="relative" onClick={(e) => e.stopPropagation()}>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleMenu(item.id);
                              }}
                              className="h-10 w-10 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center"
                              title="Opções"
                            >
                              <MoreVertical size={16} className="text-slate-200/75" />
                            </button>

                            {menuOpenId === item.id && (
                              <div
                                className="absolute right-0 mt-2 w-56 rounded-2xl bg-[#0b1224]/95 border border-white/10 shadow-[0_25px_60px_-40px_rgba(0,0,0,0.9)] backdrop-blur p-2 z-50"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <button
                                  onClick={() => setItemStatus(item, "PROGRAMADO")}
                                  className="w-full px-3 py-2 rounded-xl hover:bg-white/5 flex items-center gap-3 text-sm"
                                >
                                  <Wrench size={16} className="text-slate-300" />
                                  Programado
                                </button>

                                <button
                                  onClick={() => setItemStatus(item, "USINANDO")}
                                  className="w-full px-3 py-2 rounded-xl hover:bg-white/5 flex items-center gap-3 text-sm"
                                >
                                  <Play size={16} className="text-emerald-200" />
                                  Usinando
                                </button>

                                <button
                                  onClick={() => setItemStatus(item, "CONCLUIDO")}
                                  className="w-full px-3 py-2 rounded-xl hover:bg-white/5 flex items-center gap-3 text-sm"
                                >
                                  <CheckCircle2 size={16} className="text-emerald-200" />
                                  Concluído
                                </button>

                                <div className="h-px bg-white/10 my-2" />

                                <button
                                  onClick={() => setItemStatus(item, "CANCELADO")}
                                  className="w-full px-3 py-2 rounded-xl hover:bg-white/5 flex items-center gap-3 text-sm text-red-300"
                                >
                                  <X size={16} className="text-red-300" />
                                  Cancelar
                                </button>
                              </div>
                            )}
                          </div>
                        </>
                      }
                    />
                  );
                })}

                {fila.length === 0 && (
                  <div className="text-sm text-slate-400 py-10 text-center">
                    Sem itens na fila.
                  </div>
                )}
              </div>
            </Card>
          </div>

          {/* DIREITA - HISTÓRICO */}
          <div className="col-span-12 md:col-span-3">
            <Card title="HISTÓRICO DE CORTE">
              {historico.length === 0 ? (
                <div className="min-h-[170px] flex items-center justify-center text-sm text-slate-400">
                  Sem histórico ainda.
                </div>
              ) : (
                <div className="space-y-3 max-h-[340px] overflow-auto pr-1">
                  {historico.slice(0, 50).map((h) => {
                    const hs = String(h.status || "").toUpperCase();
                    const hLabel = hs === "CANCELADO" ? "Cancelado" : "Concluído";

                    return (
                      <Row
                        key={h.id}
                        leftIcon={
                          hs === "CANCELADO" ? (
                            <X size={18} className="text-red-200/90" />
                          ) : (
                            <CheckCircle2 size={18} className="text-emerald-200/90" />
                          )
                        }
                        title={h.arquivo_nome || h.nome || `#${h.id}`}
                        subtitle={fmtDate(h.finalizado_em || h.criado_em)}
                        right={<StatusPill label={hLabel} />}
                      />
                    );
                  })}
                </div>
              )}
            </Card>
          </div>

          {/* ARQUIVO EM EXECUÇÃO - abaixo do card esquerdo */}
          <div className="col-span-12 md:col-span-4">
            <Card title="ARQUIVO EM EXECUÇÃO">
              <div className="rounded-2xl bg-black/20 border border-white/5 p-4">
                {!executando ? (
                  <div className="text-sm text-slate-400 py-10 text-center">
                    Nenhum arquivo em execução.
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                      <Activity size={18} className="text-emerald-200/90" />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="font-bold truncate">
                        {executando.arquivo_nome || executando.nome}
                      </div>

                      <div className="text-xs text-slate-400 mt-1 inline-flex items-center gap-2">
                        <Clock3 size={14} className="opacity-80" />
                        <span>
                          {(executando.material || "—") +
                            " • Est. " +
                            (executando.tempo_estimado_min ?? 45) +
                            " min"}
                        </span>
                      </div>

                      <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-emerald-500/80 to-emerald-300/80 transition-all duration-500"
                          style={{ width: "100%" }}
                        />
                      </div>

                      <div className="mt-1 text-[11px] text-slate-400 flex justify-between">
                        <span>Em execução…</span>
                        <span>100%</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-4 text-xs text-slate-400">
                Regra: o item só deve sair da fila quando marcar{" "}
                <b>Concluído</b> ou <b>Cancelado</b>.
              </div>
            </Card>
          </div>
        </div>
      </div>
    </Shell>
  );
}