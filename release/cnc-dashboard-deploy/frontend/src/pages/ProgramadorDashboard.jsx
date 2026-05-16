import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";

const API_URL = import.meta.env.VITE_API_URL || "";
const CNC_IDS = ["CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07"];

const LS_THEME = "cnc_theme";

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function fmtTempo(seg) {
  if (seg == null) return "";
  const s = Math.max(0, Number(seg) || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h <= 0) return `${m}m`;
  return `${h}h ${m}m`;
}

function loadTheme() {
  const v = localStorage.getItem(LS_THEME);
  return v === "dark" ? "dark" : "light";
}

function StatusBadge({ status, colors }) {
  const s = (status || "").toUpperCase();
  const isRun = s.includes("EXEC") || s.includes("USIN") || s.includes("RUN") || s.includes("ROD");
  const isStop = s.includes("PAR") || s.includes("STOP") || s.includes("OCIOS");

  const bg = isRun ? colors.badgeRunBg : isStop ? colors.badgeStopBg : colors.badgeNeutralBg;
  const fg = isRun ? colors.badgeRunFg : isStop ? colors.badgeStopFg : colors.badgeNeutralFg;
  const bd = isRun ? colors.badgeRunBd : isStop ? colors.badgeStopBd : colors.badgeNeutralBd;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 800,
        background: bg,
        color: fg,
        border: `1px solid ${bd}`,
        textTransform: "uppercase",
        letterSpacing: 0.4,
      }}
      title={`Status: ${status || "-"}`}
    >
      <span style={{ width: 8, height: 8, borderRadius: 999, background: fg, opacity: 0.9 }} />
      {status || "-"}
    </span>
  );
}

function Button({ children, onClick, disabled, variant = "primary", title, colors }) {
  const isPrimary = variant === "primary";
  const isGhost = variant === "ghost";

  const bg = isPrimary ? colors.btnPrimaryBg : isGhost ? "transparent" : colors.btnSecondaryBg;
  const fg = isPrimary ? colors.btnPrimaryFg : colors.btnSecondaryFg;
  const bd = isPrimary ? colors.btnPrimaryBd : colors.btnSecondaryBd;

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        appearance: "none",
        border: `1px solid ${bd}`,
        background: bg,
        color: fg,
        padding: "8px 10px",
        borderRadius: 10,
        fontWeight: 800,
        fontSize: 13,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {children}
    </button>
  );
}

function Card({ children, colors }) {
  return (
    <div
      style={{
        border: `1px solid ${colors.cardBorder}`,
        borderRadius: 16,
        background: colors.cardBg,
        boxShadow: colors.cardShadow,
      }}
    >
      {children}
    </div>
  );
}

function colorForPos(pos) {
  if (pos === 1) return { bg: "#E9FBEE", bd: "#BCECC8", tag: "VERDE (travado)" };
  if (pos === 2) return { bg: "#FFECEC", bd: "#FFC7C7", tag: "VERMELHO (travado)" };
  return { bg: "#EAF2FF", bd: "#C7DBFF", tag: "AZUL (editável)" };
}

export default function ProgramadorDashboard() {
  // Theme
  const [theme, setTheme] = useState(() => loadTheme());

  const colors = useMemo(() => {
    const dark = theme === "dark";
    return {
      pageBg: dark
        ? "linear-gradient(180deg, #0B1220 0%, #070B12 100%)"
        : "linear-gradient(180deg, #F8FAFC 0%, #F3F4F6 100%)",
      text: dark ? "#E5E7EB" : "#111827",
      muted: dark ? "#9CA3AF" : "#6B7280",

      cardBg: dark ? "#0F172A" : "#FFFFFF",
      cardBorder: dark ? "#1F2937" : "#E5E7EB",
      cardShadow: dark ? "0 10px 25px rgba(0,0,0,0.35)" : "0 10px 25px rgba(0,0,0,0.06)",

      inputBg: dark ? "#0B1220" : "#FFFFFF",
      inputBd: dark ? "#334155" : "#E5E7EB",

      itemBg: dark ? "#0B1220" : "#FFFFFF",
      itemBd: dark ? "#1F2937" : "#E5E7EB",

      dropBg: dark ? "#0B1220" : "#F9FAFB",
      dropBd: dark ? "#334155" : "#D1D5DB",
      dropOverOutline: dark ? "#E5E7EB" : "#111827",

      btnPrimaryBg: dark ? "#E5E7EB" : "#111827",
      btnPrimaryFg: dark ? "#111827" : "#FFFFFF",
      btnPrimaryBd: dark ? "#E5E7EB" : "#111827",

      btnSecondaryBg: dark ? "#0B1220" : "#FFFFFF",
      btnSecondaryFg: dark ? "#E5E7EB" : "#111827",
      btnSecondaryBd: dark ? "#334155" : "#D1D5DB",

      badgeRunBg: dark ? "#052E1A" : "#E9FBEE",
      badgeRunFg: dark ? "#34D399" : "#0F7A2F",
      badgeRunBd: dark ? "#064E2A" : "#BCECC8",

      badgeStopBg: dark ? "#3A0B0B" : "#FFECEC",
      badgeStopFg: dark ? "#FCA5A5" : "#B42318",
      badgeStopBd: dark ? "#5B1111" : "#FFC7C7",

      badgeNeutralBg: dark ? "#111827" : "#F2F3F5",
      badgeNeutralFg: dark ? "#E5E7EB" : "#444",
      badgeNeutralBd: dark ? "#334155" : "#E1E3E8",
    };
  }, [theme]);

  // Data
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  const [arquivos, setArquivos] = useState([]);
  const [overview, setOverview] = useState([]);
  const [filas, setFilas] = useState({});
  const [nextMap, setNextMap] = useState({}); // { CNC01: {...} }

  const [search, setSearch] = useState("");
  const [dragging, setDragging] = useState(null); // {type:'fila_item', maquina_id, item}

  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    localStorage.setItem(LS_THEME, theme);
  }, [theme]);

  async function fetchArquivos() {
    const { data } = await axios.get(`${API_URL}/arquivos`);
    setArquivos(Array.isArray(data) ? data : []);
  }

  async function fetchOverview() {
    const { data } = await axios.get(`${API_URL}/painel/overview`);
    setOverview(Array.isArray(data) ? data : []);
  }

  async function fetchFila(maquinaId) {
    const { data } = await axios.get(`${API_URL}/fila/${maquinaId}?include_done=true`);
    setFilas((prev) => ({
      ...prev,
      [maquinaId]: Array.isArray(data) ? data : [],
    }));
  }

  async function fetchNext(maquinaId) {
    const { data } = await axios.get(`${API_URL}/agente/${maquinaId}/next`);
    setNextMap((prev) => ({ ...prev, [maquinaId]: data || null }));
  }

  async function refreshAll() {
    setLoading(true);
    try {
      await Promise.all([
        fetchArquivos(),
        fetchOverview(),
        ...CNC_IDS.flatMap((id) => [fetchFila(id), fetchNext(id)]),
      ]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refreshAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => {
      // refresh leve: overview + filas + next
      Promise.all([fetchOverview(), ...CNC_IDS.flatMap((id) => [fetchFila(id), fetchNext(id)])]).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh]);

  const filteredArquivos = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return arquivos;
    return arquivos.filter((a) => (a.nome || "").toLowerCase().includes(q));
  }, [arquivos, search]);

  const overviewMap = useMemo(() => {
    const m = new Map();
    for (const x of overview) m.set(x.id, x);
    return m;
  }, [overview]);

  async function handleUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".dxf")) {
      alert("Envie apenas arquivos .dxf");
      e.target.value = "";
      return;
    }

    const fd = new FormData();
    fd.append("file", file);

    setUploading(true);
    try {
      await axios.post(`${API_URL}/arquivos/upload`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await fetchArquivos();
    } catch (err) {
      console.error(err);
      alert("Erro no upload. Veja o console.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  // ========= DnD reordenação (somente AZUIS) =========
  function onDragStartFilaItem(maquina_id, item) {
    // trava no UI
    if ((item.posicao ?? 999) <= 2) return;
    setDragging({ type: "fila_item", maquina_id, item });
  }

  async function reorderBlueWithinCnc(maquinaId, fromBlueIndex, toBlueIndex) {
    const all = (filas[maquinaId] || [])
      .filter((it) => it.status === "AGUARDANDO" || it.status === "PROGRAMANDO")
      .sort((a, b) => (a.posicao ?? 0) - (b.posicao ?? 0));

    const locked = all.slice(0, 2);
    const blue = all.slice(2);

    if (fromBlueIndex < 0 || toBlueIndex < 0 || fromBlueIndex >= blue.length || toBlueIndex >= blue.length) return;

    const [moved] = blue.splice(fromBlueIndex, 1);
    blue.splice(toBlueIndex, 0, moved);

    const newOrder = [...locked, ...blue].map((x) => x.id);

    // UI otimista
    setFilas((prev) => {
      const currentAll = (prev[maquinaId] || []).slice();
      const done = currentAll.filter((it) => !["AGUARDANDO", "PROGRAMANDO"].includes(it.status));
      const reordered = [...locked, ...blue].map((x, idx) => ({ ...x, posicao: idx + 1 }));
      return { ...prev, [maquinaId]: [...reordered, ...done].sort((a, b) => (a.posicao ?? 0) - (b.posicao ?? 0)) };
    });

    try {
      await axios.post(`${API_URL}/fila/${maquinaId}/reorder`, { ordem: newOrder });
      await Promise.all([fetchFila(maquinaId), fetchNext(maquinaId), fetchOverview()]);
    } catch (err) {
      console.error(err);
      alert("Erro ao reordenar (provável trava). Recarregando...");
      await fetchFila(maquinaId);
    }
  }

  async function removeFilaItem(item) {
    if ((item.posicao ?? 999) <= 2) {
      alert("Travado: posição 1 e 2 não podem ser removidas.");
      return;
    }
    if (item.status !== "AGUARDANDO") {
      alert(`Só remove AGUARDANDO (status atual=${item.status}).`);
      return;
    }
    if (!confirm("Remover este item da fila?")) return;

    try {
      await axios.delete(`${API_URL}/fila/item/${item.id}`);
      await Promise.all([fetchFila(item.maquina_id), fetchNext(item.maquina_id), fetchOverview()]);
    } catch (err) {
      console.error(err);
      alert("Erro ao remover item. Veja o console.");
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        background: colors.pageBg,
        padding: 16,
        fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial",
        color: colors.text,
      }}
    >
      <Card colors={colors}>
        <div style={{ padding: 14, display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 16, fontWeight: 950 }}>Programação CNC</div>
            <div style={{ fontSize: 12, color: colors.muted }}>
              Execução vem do Agente • Fila viva (verde/vermelho travados) • Azul editável
            </div>
          </div>

          <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
            <Button variant="ghost" colors={colors} onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
              {theme === "dark" ? "☀️ Claro" : "🌙 Escuro"}
            </Button>

            <Button
              variant="ghost"
              colors={colors}
              onClick={() => setAutoRefresh((v) => !v)}
              title="Auto-refresh a cada 3s"
            >
              {autoRefresh ? "⏱️ Auto ON" : "⛔ Auto OFF"}
            </Button>

            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar arquivo..."
              style={{
                padding: "10px 12px",
                borderRadius: 12,
                border: `1px solid ${colors.inputBd}`,
                outline: "none",
                minWidth: 260,
                background: colors.inputBg,
                color: colors.text,
              }}
            />

            <label
              style={{
                padding: "8px 12px",
                borderRadius: 12,
                border: `1px solid ${colors.btnSecondaryBd}`,
                background: colors.btnSecondaryBg,
                color: colors.btnSecondaryFg,
                fontWeight: 900,
                cursor: uploading ? "not-allowed" : "pointer",
                opacity: uploading ? 0.65 : 1,
              }}
              title="Enviar DXF"
            >
              {uploading ? "Enviando..." : "Upload DXF"}
              <input type="file" accept=".dxf" onChange={handleUpload} disabled={uploading} style={{ display: "none" }} />
            </label>

            <Button onClick={refreshAll} disabled={loading || uploading} colors={colors}>
              {loading ? "Atualizando..." : "Atualizar"}
            </Button>
          </div>
        </div>
      </Card>

      <div style={{ height: 12 }} />

      <div style={{ display: "grid", gridTemplateColumns: "380px 1fr", gap: 14 }}>
        {/* Biblioteca */}
        <Card colors={colors}>
          <div style={{ padding: 14 }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 950 }}>Biblioteca</div>
                <div style={{ fontSize: 12, color: colors.muted }}>Arraste para a fila usando o botão “Adicionar” (por enquanto)</div>
              </div>
              <div style={{ fontSize: 12, color: colors.muted }}>{filteredArquivos.length} arquivos</div>
            </div>

            <div style={{ height: 12 }} />

            <div style={{ maxHeight: "calc(100vh - 170px)", overflow: "auto", paddingRight: 4 }}>
              {filteredArquivos.length === 0 ? (
                <div style={{ padding: 12, color: colors.muted }}>Nenhum arquivo.</div>
              ) : (
                filteredArquivos.map((a) => (
                  <div
                    key={a.id}
                    style={{
                      border: `1px solid ${colors.itemBd}`,
                      borderRadius: 14,
                      padding: 12,
                      marginBottom: 10,
                      background: colors.itemBg,
                    }}
                  >
                    <div style={{ fontWeight: 950, fontSize: 13 }}>{a.nome}</div>
                    <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>
                      ID: {a.id} • {fmtDate(a.criado_em)} • {a.status}
                    </div>
                    <div style={{ height: 8 }} />
                    <div style={{ display: "flex", gap: 8 }}>
                      {CNC_IDS.slice(0, 3).map((mid) => (
                        <Button
                          key={mid}
                          variant="secondary"
                          colors={colors}
                          onClick={async () => {
                            try {
                              await axios.post(`${API_URL}/fila/${mid}/add`, { arquivo_id: a.id });
                              await Promise.all([fetchFila(mid), fetchNext(mid), fetchOverview()]);
                            } catch (e) {
                              console.error(e);
                              alert("Erro ao adicionar na fila.");
                            }
                          }}
                          title={`Adicionar em ${mid}`}
                        >
                          + {mid}
                        </Button>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div style={{ marginTop: 10, fontSize: 12, color: colors.muted }}>API: {API_URL}</div>
          </div>
        </Card>

        {/* CNCs */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(280px, 1fr))", gap: 12 }}>
          {CNC_IDS.map((mid) => {
            const m = overviewMap.get(mid) || { id: mid, nome: mid, status: "-", tempo_segundos: null, fila_qtd: 0 };

            const next = nextMap[mid] || null;
            const exec =
              next && next.pendente && next.status === "EM_EXECUCAO"
                ? { nome: next.arquivo_nome, fila_item_id: next.fila_item_id, download_url: next.download_url }
                : null;

            const all = (filas[mid] || []).slice().sort((a, b) => (a.posicao ?? 0) - (b.posicao ?? 0));
            const filaProg = all.filter((it) => it.status === "AGUARDANDO" || it.status === "PROGRAMANDO");
            const cortados = all.filter((it) => it.status === "CORTADO");

            return (
              <Card key={mid} colors={colors}>
                <div style={{ padding: 14, minHeight: 280 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <div>
                      <div style={{ fontWeight: 950, fontSize: 14 }}>{m.nome}</div>
                      <div style={{ fontSize: 12, color: colors.muted, marginTop: 2 }}>
                        {m.id} • desde: {fmtTempo(m.tempo_segundos)}
                      </div>

                      <div style={{ marginTop: 10, fontSize: 12 }}>
                        <b>Em execução:</b>{" "}
                        {exec ? (
                          <>
                            {exec.nome} <span style={{ color: colors.muted }}>(item {exec.fila_item_id})</span>
                          </>
                        ) : (
                          <span style={{ color: colors.muted }}>Nenhum</span>
                        )}
                      </div>

                      {exec?.download_url ? (
                        <div style={{ marginTop: 8 }}>
                          <a
                            href={`${API_URL}${exec.download_url}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{ fontSize: 12, fontWeight: 900 }}
                          >
                            ⬇️ Baixar arquivo em execução
                          </a>
                        </div>
                      ) : null}
                    </div>

                    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
                      <StatusBadge status={exec ? "EM_EXECUCAO" : m.status} colors={colors} />
                      <div style={{ fontSize: 12, color: colors.muted }}>
                        Fila viva: <b>{filaProg.length}</b>
                      </div>
                      <Button
                        variant="ghost"
                        colors={colors}
                        onClick={() => Promise.all([fetchFila(mid), fetchNext(mid), fetchOverview()])}
                        title="Recarregar"
                      >
                        Recarregar
                      </Button>
                    </div>
                  </div>

                  {/* Fila programador */}
                  <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
                    {filaProg.length === 0 ? (
                      <div style={{ padding: 10, color: colors.muted }}>Fila vazia</div>
                    ) : (
                      filaProg.map((it, idx) => {
                        const locked = (it.posicao ?? 999) <= 2;
                        const c = colorForPos(it.posicao);

                        return (
                          <div
                            key={it.id}
                            draggable={!locked}
                            onDragStart={() => onDragStartFilaItem(mid, it)}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                              e.preventDefault();
                              if (!dragging || dragging.type !== "fila_item") return;
                              if (dragging.maquina_id !== mid) return;

                              const fromPos = dragging.item.posicao ?? 999;
                              const toPos = it.posicao ?? 999;

                              // só mexe nos azuis (pos >= 3)
                              if (fromPos <= 2 || toPos <= 2) return;

                              const blue = filaProg.filter((x) => (x.posicao ?? 999) >= 3);
                              const fromBlueIndex = blue.findIndex((x) => x.id === dragging.item.id);
                              const toBlueIndex = blue.findIndex((x) => x.id === it.id);

                              reorderBlueWithinCnc(mid, fromBlueIndex, toBlueIndex);
                              setDragging(null);
                            }}
                            style={{
                              border: `1px solid ${colors.itemBd}`,
                              borderRadius: 14,
                              padding: 12,
                              background: colors.itemBg,
                              display: "flex",
                              alignItems: "center",
                              gap: 12,
                              cursor: locked ? "not-allowed" : "grab",
                              opacity: locked ? 0.85 : 1,
                            }}
                            title={locked ? "Travado (posição 1 ou 2)" : "Arraste para reordenar (somente azuis)"}
                          >
                            <div
                              style={{
                                width: 42,
                                height: 42,
                                borderRadius: 12,
                                background: c.bg,
                                border: `1px solid ${c.bd}`,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontWeight: 950,
                                fontSize: 13,
                                flexShrink: 0,
                              }}
                              title={c.tag}
                            >
                              {it.posicao}
                            </div>

                            <div style={{ flex: 1 }}>
                              <div style={{ fontWeight: 950, fontSize: 13 }}>{it.arquivo_nome}</div>
                              <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>
                                item: {it.id} • arquivo_id: {it.arquivo_id} • status: <b>{it.status}</b> • {locked ? "TRAVADO" : "EDITÁVEL"}
                              </div>
                            </div>

                            <Button
                              variant="ghost"
                              colors={colors}
                              disabled={locked || it.status !== "AGUARDANDO"}
                              onClick={() => removeFilaItem(it)}
                              title={locked ? "Travado" : "Remover (somente azul AGUARDANDO)"}
                            >
                              Remover
                            </Button>
                          </div>
                        );
                      })
                    )}
                  </div>

                  {/* Cortados */}
                  <div style={{ marginTop: 14 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <div style={{ fontWeight: 900, fontSize: 13 }}>CORTADOS</div>
                      <div style={{ fontSize: 12, opacity: 0.75 }}>{cortados.length}</div>
                    </div>

                    <div
                      style={{
                        marginTop: 8,
                        borderRadius: 14,
                        border: `1px solid ${colors.itemBd}`,
                        background: colors.dropBg,
                        padding: 10,
                        maxHeight: 160,
                        overflow: "auto",
                      }}
                    >
                      {cortados.length === 0 ? (
                        <div style={{ fontSize: 12, color: colors.muted }}>Nenhum cortado ainda.</div>
                      ) : (
                        cortados
                          .slice()
                          .reverse()
                          .map((it) => (
                            <div
                              key={it.id}
                              style={{
                                border: `1px solid ${colors.itemBd}`,
                                background: colors.itemBg,
                                borderRadius: 12,
                                padding: 10,
                                marginBottom: 8,
                                opacity: 0.75,
                              }}
                            >
                              <div style={{ fontWeight: 900, fontSize: 12 }}>{it.arquivo_nome}</div>
                              <div style={{ fontSize: 12, color: colors.muted }}>item: {it.id} • arquivo_id: {it.arquivo_id}</div>
                            </div>
                          ))
                      )}
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}