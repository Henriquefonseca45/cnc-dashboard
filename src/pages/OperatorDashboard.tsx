import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:18000";
const CNC_IDS = ["CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07"] as const;

type Maquina = {
  id: string;
  nome?: string;
  status?: string;
  status_desde?: string;
};

type FilaItem = {
  id: number;
  maquina_id?: string;
  arquivo_id?: number;
  posicao?: number;
  status?: string;
  criado_em?: string;

  arquivo_nome?: string; // (se vier do backend)
  nome?: string; // fallback
  material?: string;
  tempo_estimado_min?: number;
};

type HistoricoItem = {
  id: number;
  arquivo_nome?: string;
  nome?: string;
  finalizado_em?: string;
  criado_em?: string;
};

function fmtDate(iso?: string) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function pillClass(label: string) {
  const base = "px-3 py-1 rounded-full text-xs font-semibold border";
  if (label === "Usinando") return `${base} bg-emerald-600/20 text-emerald-300 border-emerald-600/30`;
  if (label === "Na Fila") return `${base} bg-slate-600/20 text-slate-200 border-slate-500/30`;
  if (label === "Baixado") return `${base} bg-sky-600/20 text-sky-200 border-sky-500/30`;
  if (label === "Concluído") return `${base} bg-emerald-600/20 text-emerald-300 border-emerald-600/30`;
  return `${base} bg-slate-700/30 text-slate-200 border-slate-600/30`;
}

function StatusPill({ label }: { label: string }) {
  return <span className={pillClass(label)}>{label}</span>;
}

export default function OperatorDashboard() {
  const [cnc, setCnc] = useState<(typeof CNC_IDS)[number]>("CNC01");
  const [maquinas, setMaquinas] = useState<Maquina[]>([]);
  const [fila, setFila] = useState<FilaItem[]>([]);
  const [historico, setHistorico] = useState<HistoricoItem[]>([]);
  const [executando, setExecutando] = useState<FilaItem | null>(null);
  const [loading, setLoading] = useState(false);

  const maquinaAtual = useMemo(() => maquinas.find((m) => m.id === cnc), [maquinas, cnc]);

  async function carregarTudo() {
    setLoading(true);
    try {
      const [mRes, fRes, hRes] = await Promise.all([
        axios.get<Maquina[]>(`${API}/maquinas`),
        axios.get<FilaItem[]>(`${API}/fila/${cnc}`, { params: { include_done: false } }),
        // Se você não tiver /historico/{cnc}, troque por /fila/{cnc}?include_done=true e filtre.
        axios.get<HistoricoItem[]>(`${API}/historico/${cnc}`),
      ]);

      const maquinasData = mRes.data || [];
      const filaData = fRes.data || [];
      const histData = hRes.data || [];

      setMaquinas(maquinasData);
      setFila(filaData);
      setHistorico(histData);

      // Inferir arquivo em execução: item com status USINANDO
      const atual = filaData.find((x) => String(x.status || "").toUpperCase() === "USINANDO");
      setExecutando(atual || null);
    } catch (e) {
      console.error(e);
      // aqui você pode colocar toast/alert se quiser
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    carregarTudo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cnc]);

  // ========= AÇÕES =========
  async function puxarProximo() {
    // IMPORTANTE: este endpoint deve APENAS mudar status para USINANDO/EM_EXECUCAO
    // e retornar o item. NÃO remover da fila aqui.
    const res = await axios.post<FilaItem>(`${API}/fila/${cnc}/puxar_proximo`);
    const item = res.data;

    setFila((prev) => prev.map((x) => (x.id === item.id ? { ...x, ...item } : x)));
    setExecutando(item);
  }

  async function marcarCortado(itemId: number) {
    // Aqui sim: finaliza. Pode remover da fila pendente.
    await axios.post(`${API}/fila/${cnc}/cortado`, { id: itemId });

    setFila((prev) => prev.filter((x) => x.id !== itemId));
    setExecutando((prev) => (prev?.id === itemId ? null : prev));

    // Atualiza histórico
    carregarTudo();
  }

  async function baixarArquivo(item: FilaItem) {
    const arquivoId = item.arquivo_id ?? item.id;
    window.open(`${API}/agente/${cnc}/download/${arquivoId}`, "_blank");

    // se você tem esse endpoint:
    try {
      await axios.post(`${API}/agente/${cnc}/baixado`, { arquivo_id: arquivoId });
    } catch {
      // se não existir, não quebra a UI
    }

    carregarTudo();
  }

  return (
    <div className="min-h-screen bg-[#050914] text-slate-100">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-gradient-to-b from-[#0b1224] to-[#050914] border-b border-white/5">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center font-bold">
              CN
            </div>
            <div>
              <div className="text-lg font-semibold">Painel do Operador</div>
              <div className="text-xs text-slate-400 -mt-0.5">Controle CNC</div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={carregarTudo}
              className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-sm"
              title="Atualizar"
            >
              ⟲
            </button>
            <button className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold">
              + Novo Arquivo
            </button>
          </div>
        </div>
      </div>

      {/* Conteúdo */}
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Seletor CNC */}
        <div className="flex flex-wrap items-center gap-2 mb-6">
          {CNC_IDS.map((id) => (
            <button
              key={id}
              onClick={() => setCnc(id)}
              className={[
                "px-3 py-2 rounded-xl text-sm border",
                id === cnc
                  ? "bg-emerald-600/20 border-emerald-600/30 text-emerald-200"
                  : "bg-white/5 border-white/10 text-slate-200 hover:bg-white/10",
              ].join(" ")}
            >
              {id.replace("CNC", "CNC-")}
            </button>
          ))}
          {loading && <span className="text-xs text-slate-400 ml-2">carregando…</span>}
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Esquerda */}
          <div className="col-span-12 md:col-span-4">
            <div className="rounded-2xl bg-white/5 border border-white/10 p-5">
              <div className="flex items-center justify-between">
                <div className="text-xl font-bold">{cnc.replace("CNC", "CNC-")}</div>
                <div className="px-3 py-1 rounded-xl bg-white/5 border border-white/10 text-xs text-slate-200">
                  {maquinaAtual?.status || "—"}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 mt-5">
                <div className="rounded-2xl bg-black/20 border border-white/5 p-4">
                  <div className="text-[10px] uppercase tracking-wider text-slate-400">Operador</div>
                  <div className="mt-2 font-semibold">—</div>
                </div>

                <div className="rounded-2xl bg-black/20 border border-white/5 p-4">
                  <div className="text-[10px] uppercase tracking-wider text-slate-400">Arquivo atual</div>
                  <div className="mt-2 font-semibold truncate">
                    {executando?.arquivo_nome || executando?.nome || "—"}
                  </div>
                </div>
              </div>

              <div className="mt-5">
                <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">Alterar status</div>
                <select
                  className="w-full rounded-xl bg-white/5 border border-white/10 px-3 py-2 text-sm outline-none"
                  defaultValue={maquinaAtual?.status || "OCIOSA"}
                >
                  <option value="OCIOSA">Ociosa</option>
                  <option value="PARADA">Parada</option>
                  <option value="USINANDO">Usinando</option>
                  <option value="MANUTENCAO">Manutenção</option>
                </select>

                <div className="flex gap-2 mt-4">
                  <button
                    onClick={puxarProximo}
                    className="flex-1 px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-sm font-semibold"
                  >
                    Executar Próximo
                  </button>
                  <button
                    disabled={!executando?.id}
                    onClick={() => executando?.id && marcarCortado(executando.id)}
                    className="flex-1 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold"
                  >
                    Cortado
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Centro: fila */}
          <div className="col-span-12 md:col-span-5">
            <div className="rounded-2xl bg-white/5 border border-white/10 p-5">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold tracking-wider text-slate-200">FILA DE ARQUIVOS</div>
                <div className="px-3 py-1 rounded-xl bg-white/5 border border-white/10 text-xs text-slate-200">
                  {fila.length} itens
                </div>
              </div>

              <div className="mt-4 space-y-3">
                {fila.map((item) => {
                  const st = String(item.status || "").toUpperCase();
                  const label = st === "USINANDO" ? "Usinando" : st === "BAIXADO" ? "Baixado" : "Na Fila";

                  return (
                    <div
                      key={item.id}
                      className="rounded-2xl bg-black/20 border border-white/5 p-4 flex items-center justify-between gap-3"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
                          📄
                        </div>
                        <div className="min-w-0">
                          <div className="font-semibold truncate">
                            {item.arquivo_nome || item.nome || `Arquivo #${item.id}`}
                          </div>
                          <div className="text-xs text-slate-400">
                            {item.material || "—"}
                            {item.tempo_estimado_min ? ` • ${item.tempo_estimado_min}min` : ""}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        <StatusPill label={label} />
                        <button
                          onClick={() => baixarArquivo(item)}
                          className="px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs"
                          title="Baixar"
                        >
                          ⬇
                        </button>
                      </div>
                    </div>
                  );
                })}

                {fila.length === 0 && (
                  <div className="text-sm text-slate-400 py-8 text-center">Sem itens na fila.</div>
                )}
              </div>
            </div>
          </div>

          {/* Direita: histórico */}
          <div className="col-span-12 md:col-span-3">
            <div className="rounded-2xl bg-white/5 border border-white/10 p-5">
              <div className="text-sm font-semibold tracking-wider text-slate-200">HISTÓRICO DE CORTE</div>

              <div className="mt-4 space-y-3">
                {historico.slice(0, 6).map((h) => (
                  <div
                    key={h.id}
                    className="rounded-2xl bg-black/20 border border-white/5 p-4 flex items-center justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <div className="font-semibold truncate">{h.arquivo_nome || h.nome || `#${h.id}`}</div>
                      <div className="text-xs text-slate-400">{fmtDate(h.finalizado_em || h.criado_em)}</div>
                    </div>
                    <StatusPill label="Concluído" />
                  </div>
                ))}

                {historico.length === 0 && (
                  <div className="text-sm text-slate-400 py-8 text-center">Sem histórico ainda.</div>
                )}
              </div>
            </div>
          </div>

          {/* Em execução */}
          <div className="col-span-12 md:col-span-5">
            <div className="rounded-2xl bg-white/5 border border-white/10 p-5">
              <div className="text-sm font-semibold tracking-wider text-slate-200">ARQUIVO EM EXECUÇÃO</div>

              <div className="mt-4 rounded-2xl bg-black/20 border border-white/5 p-4">
                {!executando ? (
                  <div className="text-sm text-slate-400 py-6 text-center">Nenhum arquivo em execução.</div>
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-2xl bg-emerald-600/20 border border-emerald-600/30 flex items-center justify-center">
                      📄
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="font-bold truncate">{executando.arquivo_nome || executando.nome}</div>
                      <div className="text-xs text-slate-400 mt-1">
                        {executando.material || "—"} • Est. {executando.tempo_estimado_min ?? 45} min
                      </div>

                      <div className="mt-3 h-2 rounded-full bg-white/10 overflow-hidden">
                        <div className="h-full w-[100%] bg-emerald-500/70" />
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
                Regra: o item <b>só sai da fila</b> quando marcar <b>Cortado</b>.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}