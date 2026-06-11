import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, getErrMsg, API_URL } from "./api";
import "./ProgramadorDashboard.css";

// Remove acentos + upper => "REUNIÃO" vira "REUNIAO"
function normUpper(s) {
  return String(s || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase();
}
function U(s) {
  return normUpper(s);
}

function badgeTone(status = "") {
  const s = U(status);
  if (s.includes("USIN") || s.includes("CORT")) return "tone-green";
  if (s.includes("MANUT")) return "tone-purple";
  if (s.includes("PAR")) return "tone-red";
  if (s.includes("OCIOS")) return "tone-amber";
  return "tone-gray";
}

function fmtDate(iso) {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function ProgramadorDashboard() {
  // ✅ READONLY via querystring
  // Abra assim: /visual?readonly=1  (ou /programador?readonly=1)
  const readOnly = useMemo(() => {
    const qs = new URLSearchParams(window.location.search);
    return qs.get("readonly") === "1";
  }, []);

  const [maquinas, setMaquinas] = useState([]);
  const [selectedId, setSelectedId] = useState("CNC01");

  const [fila, setFila] = useState([]);
  const [filasById, setFilasById] = useState({});

  const [pool, setPool] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(null);

  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const [includeDone, setIncludeDone] = useState(false);

  const fileInputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const [draggingId, setDraggingId] = useState(null);

  // ✅ seleção
  const [selectedPoolIds, setSelectedPoolIds] = useState(() => new Set());
  const [selectedFilaItemIds, setSelectedFilaItemIds] = useState(() => new Set());

  // ✅ reorder fila (drag interno)
  const [reorderBusy, setReorderBusy] = useState(false);

  function togglePoolSelection(id) {
    if (readOnly) return;
    setSelectedPoolIds((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  function clearPoolSelection() {
    setSelectedPoolIds(new Set());
  }

  function toggleFilaSelection(itemId) {
    if (readOnly) return;
    setSelectedFilaItemIds((prev) => {
      const n = new Set(prev);
      if (n.has(itemId)) n.delete(itemId);
      else n.add(itemId);
      return n;
    });
  }

  function clearFilaSelection() {
    setSelectedFilaItemIds(new Set());
  }

  async function fetchMaquinas() {
    const r = await api.get("/maquinas");
    const data = r.data || [];
    setMaquinas(data);

    if (data.length > 0 && !data.find((m) => m.id === selectedId)) {
      setSelectedId(data[0].id);
    }
    return data;
  }

  async function fetchFila(mid, incDone = includeDone) {
    const r = await api.get(`/fila/${mid}?include_done=${incDone ? "true" : "false"}`);
    return r.data || [];
  }

  async function fetchAllFilas(ids, incDone = includeDone) {
    const entries = await Promise.all(
      ids.map(async (id) => {
        try {
          const data = await fetchFila(id, incDone);
          return [id, data];
        } catch {
          return [id, []];
        }
      })
    );
    const map = {};
    for (const [id, data] of entries) map[id] = data;
    setFilasById(map);
    return map;
  }

  async function fetchPool() {
    const r = await api.get("/arquivos/disponiveis");
    setPool(r.data || []);
  }

  async function reloadAll() {
    setErr("");
    setMsg("");
    setLoading(true);

    try {
      const list = await fetchMaquinas();
      const ids2 = (list || []).map((m) => m.id);

      if (ids2.length > 0) {
        await fetchAllFilas(ids2, includeDone);
      } else {
        setFilasById({});
      }

      const sid = (list || []).find((m) => m.id === selectedId) ? selectedId : ids2[0] || selectedId;
      const fsel = ids2.length ? await fetchFila(sid, includeDone) : [];
      setFila(fsel);

      await fetchPool();

      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setErr(getErrMsg(e));
      setMaquinas([]);
      setFilasById({});
      setFila([]);
      setPool([]);
      setLastUpdate(new Date().toISOString());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    reloadAll();
    // ✅ auto-refresh de 5 em 5 min
    const t = setInterval(() => reloadAll(), 5 * 60 * 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchFila(selectedId, includeDone)
      .then((f) => {
        setFila(f);
        clearFilaSelection();
      })
      .catch((e) => setErr(getErrMsg(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, includeDone]);

  // ===== KPIs =====
  const kpis = useMemo(() => {
    const list = Array.isArray(maquinas) ? maquinas : [];
    const total = list.length;

    let cortando = 0;
    let paradaProgramada = 0;
    let paradaNaoProgramada = 0;

    for (const m of list) {
      const s = U(m?.status);

      if (s.includes("USIN") || s.includes("CORT")) {
        cortando++;
        continue;
      }

      if (
        s.includes("SETUP") ||
        s.includes("REUNIA") ||
        s.includes("REUNIAO") ||
        s.includes("DESLIG") ||
        s.includes("REFEI") ||
        (s.includes("TROCA") && s.includes("SACRIFIC"))
      ) {
        paradaProgramada++;
        continue;
      }

      if (s.includes("MANUT") || (s.includes("AGUAR") && s.includes("EMPILH")) || s.includes("OCIOS")) {
        paradaNaoProgramada++;
        continue;
      }

      paradaNaoProgramada++;
    }

    const eficiencia = total > 0 ? Math.round((cortando / total) * 100) : 0;
    return { total, cortando, paradaProgramada, paradaNaoProgramada, eficiencia };
  }, [maquinas]);

  const paradaNaoProgramadaList = useMemo(() => {
    const list = Array.isArray(maquinas) ? maquinas : [];
    return list.filter((m) => {
      const s = U(m?.status);
      return s.includes("MANUT") || (s.includes("AGUAR") && s.includes("EMPILH")) || s.includes("OCIOS");
    });
  }, [maquinas]);

  const selectedMachine = useMemo(() => {
    return maquinas.find((m) => m.id === selectedId) || { id: selectedId, nome: selectedId, status: "" };
  }, [maquinas, selectedId]);

  const emExecucao = useMemo(() => {
    return (fila || []).find((it) => U(it.status) === "EM_EXECUCAO") || null;
  }, [fila]);

  const filaVisivel = useMemo(() => {
    return (fila || [])
      .filter((it) => U(it.status) !== "EM_EXECUCAO")
      .slice()
      .sort((a, b) => (a.posicao ?? 0) - (b.posicao ?? 0));
  }, [fila]);

  // ===== Upload: sobe pro POOL =====
  function onPickFiles() {
    if (readOnly) return;
    fileInputRef.current?.click();
  }

  function onFileInputChange(e) {
    if (readOnly) return;
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    uploadToPool(files);
  }

  function onPoolDropUpload(e) {
    if (readOnly) return;
    e.preventDefault();
    e.stopPropagation();
    const files = Array.from(e.dataTransfer.files || []);
    uploadToPool(files);
  }

  async function uploadToPool(files) {
    if (readOnly) return;
    if (!files || files.length === 0) return;

    setErr("");
    setMsg("");
    setUploading(true);

    try {
      for (const file of files) {
        const name = String(file?.name || "");
        if (!name.toLowerCase().endsWith(".dxf")) {
          throw new Error(`Arquivo inválido: "${name}". Envie apenas .DXF`);
        }

        const form = new FormData();
        form.append("file", file);

        const up = await api.post("/arquivos/upload", form, {
          headers: { "Content-Type": "multipart/form-data" },
        });

        const arquivo = up.data || {};
        const arquivo_id = arquivo?.id ?? arquivo?.arquivo_id;

        if (!arquivo_id) {
          throw new Error(`Upload OK, mas não veio id. Resposta: ${JSON.stringify(up.data)}`);
        }

        setMsg(`Upload OK: "${file.name}" entrou na fila geral.`);
      }

      await fetchPool();
      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setErr(getErrMsg(e));
    } finally {
      setUploading(false);
    }
  }

  // ===== Drag do POOL =====
  function getPoolDragIds(fallbackId) {
    const selected = Array.from(selectedPoolIds);
    if (selected.length > 0) {
      if (!selectedPoolIds.has(fallbackId)) return [fallbackId];
      return selected;
    }
    return [fallbackId];
  }

  function onDragStartPoolItem(e, file) {
    if (readOnly) return;
    const ids = getPoolDragIds(file.id);
    e.dataTransfer.setData("application/x-drag-type", "POOL");
    e.dataTransfer.setData("application/x-pool-ids", JSON.stringify(ids));
    e.dataTransfer.setData("text/plain", "POOL");
    e.dataTransfer.effectAllowed = "move";
    setDraggingId(file.id);
  }

  // ✅ Drag da FILA (itens da CNC -> outra CNC)
  function getFilaDragItemIds(fallbackItemId) {
    const selected = Array.from(selectedFilaItemIds);
    if (selected.length > 0) {
      if (!selectedFilaItemIds.has(fallbackItemId)) return [fallbackItemId];
      return selected;
    }
    return [fallbackItemId];
  }

  function onDragStartFilaMove(e, item) {
    if (readOnly) return;
    const ids = getFilaDragItemIds(item.id);
    e.dataTransfer.setData("application/x-drag-type", "FILA_ITEMS");
    e.dataTransfer.setData("application/x-fila-item-ids", JSON.stringify(ids));
    e.dataTransfer.setData("application/x-fila-from-machine", String(selectedId));
    e.dataTransfer.setData("text/plain", "FILA_ITEMS");
    e.dataTransfer.effectAllowed = "move";
    setDraggingId(item.id);
  }

  function onDragStartFilaReorderHandle(e, item) {
    if (readOnly) return;
    e.preventDefault();
    e.stopPropagation();

    e.dataTransfer.setData("application/x-drag-type", "FILA_REORDER");
    e.dataTransfer.setData("application/x-reorder-item-id", String(item.id));
    e.dataTransfer.setData("application/x-reorder-machine-id", String(selectedId));
    e.dataTransfer.setData("text/plain", "FILA_REORDER");
    e.dataTransfer.effectAllowed = "move";

    setDraggingId(item.id);
  }

  function onDragEndAny() {
    setDraggingId(null);
  }

  async function saveFilaOrderToBackend(machineId, orderedItemIds) {
    if (readOnly) return;
    await api.post(`/fila/${machineId}/reorder`, { ordered_item_ids: orderedItemIds });
  }

  async function reorderFilaLocalAndPersist(dragItemId, overItemId) {
    if (readOnly) return;
    if (!dragItemId || !overItemId) return;
    if (Number(dragItemId) === Number(overItemId)) return;

    const list = filaVisivel.slice();
    const fromIdx = list.findIndex((x) => Number(x.id) === Number(dragItemId));
    const toIdx = list.findIndex((x) => Number(x.id) === Number(overItemId));
    if (fromIdx < 0 || toIdx < 0) return;

    const [moved] = list.splice(fromIdx, 1);
    list.splice(toIdx, 0, moved);

    const exec = (fila || []).find((it) => U(it.status) === "EM_EXECUCAO") || null;
    const merged = exec ? [exec, ...list] : list;
    setFila(merged);
    setFilasById((prev) => ({ ...prev, [selectedId]: merged }));

    setReorderBusy(true);
    setErr("");
    setMsg("");

    try {
      const orderedIds = list.map((x) => Number(x.id)).filter(Boolean);
      await saveFilaOrderToBackend(selectedId, orderedIds);

      setMsg("Ordem da fila atualizada.");

      const fresh = await fetchFila(selectedId, includeDone);
      setFila(fresh);
      setFilasById((prev) => ({ ...prev, [selectedId]: fresh }));

      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setErr(
        `Falha ao salvar a reordenação. ` +
          `Se o endpoint /fila/${selectedId}/reorder não existir, precisa criar no backend. ` +
          `Detalhe: ${getErrMsg(e)}`
      );

      try {
        const fresh = await fetchFila(selectedId, includeDone);
        setFila(fresh);
        setFilasById((prev) => ({ ...prev, [selectedId]: fresh }));
      } catch {}
    } finally {
      setReorderBusy(false);
    }
  }

  // ===== DROP em cada CNC =====
  async function handleDropOnMachine(e, machineId) {
    if (readOnly) return;
    e.preventDefault();
    e.stopPropagation();

    const dragType = e.dataTransfer.getData("application/x-drag-type");

    setErr("");
    setMsg("");

    try {
      if (dragType === "POOL") {
        const raw = e.dataTransfer.getData("application/x-pool-ids");
        const ids = raw ? JSON.parse(raw) : [];
        const arquivoIds = (Array.isArray(ids) ? ids : []).map((x) => Number(x)).filter(Boolean);
        if (arquivoIds.length === 0) return;

        for (const arquivo_id of arquivoIds) {
          await api.post(`/fila/${machineId}/add`, { arquivo_id });
        }

        setMsg(`Enviado(s) ${arquivoIds.length} arquivo(s) para ${machineId}.`);

        const fM = await fetchFila(machineId, includeDone);
        setFilasById((prev) => ({ ...prev, [machineId]: fM }));
        if (machineId === selectedId) setFila(fM);

        await fetchPool();
        clearPoolSelection();
        setLastUpdate(new Date().toISOString());
        return;
      }

      if (dragType === "FILA_ITEMS") {
        const fromMachine = e.dataTransfer.getData("application/x-fila-from-machine") || "";
        if (!fromMachine) return;
        if (fromMachine === machineId) {
          setMsg("Destino igual à origem — nada foi movido.");
          return;
        }

        const raw = e.dataTransfer.getData("application/x-fila-item-ids");
        const ids = raw ? JSON.parse(raw) : [];
        const itemIds = (Array.isArray(ids) ? ids : []).map((x) => Number(x)).filter(Boolean);
        if (itemIds.length === 0) return;

        const sourceFila = filasById[fromMachine] || (fromMachine === selectedId ? fila : []);
        let sourceFilaFresh = sourceFila;

        if (!sourceFilaFresh || sourceFilaFresh.length === 0) {
          try {
            sourceFilaFresh = await fetchFila(fromMachine, includeDone);
          } catch {
            sourceFilaFresh = sourceFila || [];
          }
        }

        const byIdFresh = new Map((sourceFilaFresh || []).map((it) => [Number(it.id), it]));

        let moved = 0;

        for (const item_id of itemIds) {
          const it = byIdFresh.get(item_id);
          const arquivo_id = Number(it?.arquivo_id);
          if (!arquivo_id) continue;

          await api.post(`/fila/item/${item_id}/to_pool`);
          await api.post(`/fila/${machineId}/add`, { arquivo_id });

          moved++;
        }

        setMsg(`Movidos ${moved} item(ns) de ${fromMachine} → ${machineId}.`);

        const [fFrom, fTo] = await Promise.all([
          fetchFila(fromMachine, includeDone).catch(() => []),
          fetchFila(machineId, includeDone).catch(() => []),
        ]);

        setFilasById((prev) => ({
          ...prev,
          [fromMachine]: fFrom,
          [machineId]: fTo,
        }));

        if (selectedId === fromMachine) setFila(fFrom);
        if (selectedId === machineId) setFila(fTo);

        await fetchPool();

        if (selectedId === fromMachine) clearFilaSelection();

        setLastUpdate(new Date().toISOString());
        return;
      }
    } catch (e2) {
      setErr(getErrMsg(e2));
    } finally {
      setDraggingId(null);
    }
  }

  function cardData(maquinaId) {
    const filaM = filasById[maquinaId] || [];
    const exec = filaM.find((it) => U(it.status) === "EM_EXECUCAO") || null;
    const aguard = filaM.filter((it) => U(it.status) !== "EM_EXECUCAO");
    return {
      execNome: exec?.arquivo_nome || null,
      filaCount: aguard.length,
    };
  }

  // ✅ AÇÃO: voltar itens selecionados da fila para o POOL
  async function voltarSelecionadosParaPool() {
    if (readOnly) return;
    const ids = Array.from(selectedFilaItemIds);
    if (ids.length === 0) return;

    setErr("");
    setMsg("");

    try {
      for (const item_id of ids) {
        await api.post(`/fila/item/${item_id}/to_pool`);
      }

      setMsg(`Voltaram ${ids.length} item(ns) para a fila geral.`);

      const fsel = await fetchFila(selectedId, includeDone);
      setFila(fsel);
      setFilasById((prev) => ({ ...prev, [selectedId]: fsel }));

      await fetchPool();
      clearFilaSelection();
      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setErr(getErrMsg(e));
    }
  }

  // ✅ AÇÃO: excluir itens selecionados da fila
  async function excluirSelecionadosDaFila() {
    if (readOnly) return;
    const ids = Array.from(selectedFilaItemIds);
    if (ids.length === 0) return;

    if (!window.confirm(`Excluir ${ids.length} item(ns) da fila desta CNC?`)) return;

    setErr("");
    setMsg("");

    try {
      for (const item_id of ids) {
        await api.delete(`/fila/item/${item_id}/hard`);
      }

      setMsg(`Excluídos ${ids.length} item(ns) da fila.`);

      const fsel = await fetchFila(selectedId, includeDone);
      setFila(fsel);
      setFilasById((prev) => ({ ...prev, [selectedId]: fsel }));

      await fetchPool();
      clearFilaSelection();
      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setErr(getErrMsg(e));
    }
  }

  // ✅ AÇÃO: excluir arquivos do POOL
  async function excluirSelecionadosDoPool() {
    if (readOnly) return;
    const ids = Array.from(selectedPoolIds);
    if (ids.length === 0) return;

    if (!window.confirm(`Excluir ${ids.length} arquivo(s) do sistema? (vai sumir do pool)`)) return;

    setErr("");
    setMsg("");

    try {
      for (const arquivo_id of ids) {
        await api.delete(`/arquivos/${arquivo_id}`);
      }
      setMsg(`Excluídos ${ids.length} arquivo(s) do pool.`);
      await fetchPool();
      clearPoolSelection();
      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setErr(getErrMsg(e));
    }
  }

  const bigCheckStyle = { width: 22, height: 22, cursor: readOnly ? "not-allowed" : "pointer" };

  function getDragType(dt) {
    const t = dt?.getData?.("application/x-drag-type");
    if (t) return t;
    const types = Array.from(dt?.types || []);
    const plain = dt?.getData?.("text/plain");
    if (plain === "FILA_REORDER") return "FILA_REORDER";
    if (plain === "FILA_ITEMS") return "FILA_ITEMS";
    if (plain === "POOL") return "POOL";
    if (types.includes("application/x-reorder-item-id")) return "FILA_REORDER";
    if (types.includes("application/x-fila-item-ids")) return "FILA_ITEMS";
    if (types.includes("application/x-pool-ids")) return "POOL";
    return "";
  }

  return (
    <div className={`pgShell ${readOnly ? "pgReadOnly" : ""}`}>
      {/* Sidebar */}
      <aside className="pgSidebar">
        <div className="pgBrand">
          <div className="pgBrandIcon">🖥️</div>
          <div>
            <div className="pgBrandTitle">CNC Monitor</div>
            <div className="pgBrandSub">Painel de Produção {readOnly ? "(Visual)" : ""}</div>
          </div>
        </div>

        <nav className="pgNav">
          <button className="pgNavItem pgNavActive">
            <span className="pgNavDot" />
            Dashboard
          </button>
          <button className="pgNavItem">Máquinas</button>
        </nav>

        {/* UPLOAD + POOL */}
        <div className="pgSidebarUpload">
          <div className="pgSidebarUploadTitle">Upload / Fila Geral</div>

          {/* ✅ Some no visual */}
          {!readOnly && (
            <div
              className={`pgDrop ${uploading ? "busy" : ""}`}
              onDrop={onPoolDropUpload}
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              role="button"
              tabIndex={0}
              onClick={onPickFiles}
              title="Clique ou arraste arquivos DXF aqui"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".dxf,.DXF"
                multiple
                style={{ display: "none" }}
                onChange={onFileInputChange}
              />
              <div className="pgDropBig">{uploading ? "Enviando..." : "Arraste DXF aqui"}</div>
              <div className="pgDropSmall">ou clique para selecionar</div>
            </div>
          )}

          <div className="pgPoolHeader">
            <div className="pgPoolTitle">Arquivos na fila geral</div>
            <div className="pgPoolCount">{pool.length}</div>
          </div>

          {/* ✅ Ações do pool: some no visual */}
          {!readOnly && (
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <button className="pgBtn pgBtnGhost" onClick={clearPoolSelection} disabled={selectedPoolIds.size === 0}>
                Limpar seleção
              </button>
              <button className="pgBtn pgBtnPrimary" onClick={excluirSelecionadosDoPool} disabled={selectedPoolIds.size === 0}>
                Excluir do Pool
              </button>
            </div>
          )}

          <div className="pgPoolList">
            {pool.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 10 }}>
                Nenhum arquivo no pool.
              </div>
            ) : (
              pool.slice(0, 80).map((a) => {
                const checked = selectedPoolIds.has(a.id);
                return (
                  <div
                    key={a.id}
                    className={`pgPoolItem ${draggingId === a.id ? "dragging" : ""}`}
                    draggable={!readOnly}
                    onDragStart={(e) => onDragStartPoolItem(e, a)}
                    onDragEnd={onDragEndAny}
                    title={readOnly ? "Somente visual" : "Selecione e arraste para uma CNC"}
                    style={{
                      display: "flex",
                      gap: 12,
                      alignItems: "center",
                      padding: "10px 10px",
                      cursor: readOnly ? "default" : "grab",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={readOnly}
                      onChange={() => togglePoolSelection(a.id)}
                      onClick={(e) => e.stopPropagation()}
                      style={bigCheckStyle}
                      title="Selecionar"
                    />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="pgPoolName" style={{ fontSize: 14 }}>
                        {a.nome}
                      </div>
                      <div className="pgPoolMeta">
                        <span className="pgMono">id:{a.id}</span>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {!readOnly && (
            <>
              <div className="pgTiny" style={{ marginTop: 10, opacity: 0.9 }}>
                Dica: selecione vários e arraste um deles para a CNC.
              </div>
              <div className="pgTiny" style={{ marginTop: 6, opacity: 0.9 }}>
                Dica 2: na fila (centro), use o ícone ↕ para reordenar.
              </div>
            </>
          )}
        </div>

        <div className="pgSys">
          <div className={`pgSysDot ${err ? "bad" : "ok"}`} />
          <div>
            <div className="pgSysTitle">Status do Sistema</div>
            <div className="pgSysSub">{err ? "Backend Offline" : maquinas.length === 0 ? "Sem dados" : "Online"}</div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="pgMain">
        <div className="pgTopbar">
          <div>
            <div className="pgTitle">Painel de Produção {readOnly ? "(Visual)" : ""}</div>
            <div className="pgSubtitle">Monitoramento em tempo real das máquinas CNC</div>
          </div>

          <div className="pgTopRight">
            <div className="pgTiny">
              API: <span className="pgMono">{API_URL}</span>
            </div>
            <div className="pgTiny">
              Atualizado: <span className="pgMono">{lastUpdate ? fmtDate(lastUpdate) : "-"}</span>
            </div>

            {/* ✅ botões somem no visual */}
            {!readOnly && (
              <>
                <button className="pgBtn pgBtnGhost" onClick={() => setIncludeDone((v) => !v)} disabled={loading || reorderBusy}>
                  {includeDone ? "Ocultar baixados" : "Incluir baixados"}
                </button>

                <button className="pgBtn pgBtnPrimary" onClick={reloadAll} disabled={loading || reorderBusy}>
                  {loading ? "Atualizando..." : reorderBusy ? "Salvando ordem..." : "Atualizar"}
                </button>
              </>
            )}
          </div>
        </div>

        {(err || msg) && (
          <div className="pgAlerts">
            {err && <div className="pgAlert pgAlertErr">Erro: {err}</div>}
            {msg && <div className="pgAlert pgAlertOk">{msg}</div>}
          </div>
        )}

        <section className="pgKpis">
          <div className="pgKpiCard">
            <div className="pgKpiIcon i-blue">⚡</div>
            <div className="pgKpiNum">{kpis.total}</div>
            <div className="pgKpiLabel">Total de Máquinas</div>
          </div>

          <div className="pgKpiCard">
            <div className="pgKpiIcon i-green">▶</div>
            <div className="pgKpiNum">{kpis.cortando}</div>
            <div className="pgKpiLabel">USINANDO</div>
          </div>

          <div className="pgKpiCard">
            <div className="pgKpiIcon i-amber">⏸</div>
            <div className="pgKpiNum">{kpis.paradaProgramada}</div>
            <div className="pgKpiLabel">PARADA PROGRAMADA</div>
          </div>

          <div className="pgKpiCard">
            <div className="pgKpiIcon i-purple">⚠</div>
            <div className="pgKpiNum">{kpis.paradaNaoProgramada}</div>
            <div className="pgKpiLabel">PARADA NAO PROGRAMADA</div>
          </div>
        </section>

        <section className="pgEff">
          <div className="pgEffTop">
            <div className="pgEffLabel">Eficiência de Produção</div>
            <div className="pgEffPct">{kpis.eficiencia}%</div>
          </div>
          <div className="pgEffBar">
            <div className="pgEffFill" style={{ width: `${kpis.eficiencia}%` }} />
          </div>
        </section>

        <section className="pgMaint">
          <div className="pgMaintHeader">
            <div className="pgMaintTitle">
              <span className="pgMaintIcon">🧩</span>
              Maquinas em Parada Nao Programada
            </div>
            <div className="pgMaintSub">{paradaNaoProgramadaList.length} maquina(s) fora de operacao</div>
            <div className="pgMaintTag">Atencao</div>
          </div>

          <div className="pgMaintBody">
            {paradaNaoProgramadaList.length === 0 ? (
              <div className="pgEmpty">Nenhuma maquina em parada nao programada.</div>
            ) : (
              <div className="pgMaintGrid">
                {paradaNaoProgramadaList.map((m) => (
                  <div key={m.id} className="pgMaintCard">
                    <div className="pgMaintCardTop">
                      <div className="pgMaintCardId">{m.id}</div>
                      <div className={`pgTone ${badgeTone(m.status)}`}>{m.status}</div>
                    </div>
                    <div className="pgMaintCardName">{m.nome || "-"}</div>
                    <div className="pgTiny">
                      desde: <span className="pgMono">{fmtDate(m.status_desde)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <section className="pgGrid">
          {/* Fila da CNC */}
          <div className="pgPanel">
            <div className="pgPanelHeader">
              <div className="pgPanelTitle">Fila de Arquivos</div>

              <label className="pgSelectLabel">
                Máquina:
                <select className="pgSelect" value={selectedId} onChange={(e) => setSelectedId(e.target.value)} disabled={reorderBusy}>
                  {maquinas.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
                    </option>
                  ))}
                  {maquinas.length === 0 && <option value={selectedId}>{selectedId}</option>}
                </select>
              </label>
            </div>

            {/* ✅ Ações da fila CNC: somem no visual */}
            {!readOnly && (
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                <button className="pgBtn pgBtnGhost" onClick={clearFilaSelection} disabled={selectedFilaItemIds.size === 0 || reorderBusy}>
                  Limpar seleção
                </button>
                <button className="pgBtn pgBtnPrimary" onClick={voltarSelecionadosParaPool} disabled={selectedFilaItemIds.size === 0 || reorderBusy}>
                  Voltar p/ Fila Geral
                </button>
                <button className="pgBtn pgBtnGhost" onClick={excluirSelecionadosDaFila} disabled={selectedFilaItemIds.size === 0 || reorderBusy}>
                  Excluir da Fila
                </button>
              </div>
            )}

            <div className="pgFilaMeta">
              <div className="pgFilaMetaTop">
                <div className="pgFilaMetaId">{selectedMachine.id}</div>
                <div className={`pgTone ${badgeTone(selectedMachine.status)}`}>{selectedMachine.status || "—"}</div>
              </div>
              <div className="pgTiny">
                status desde: <span className="pgMono">{fmtDate(selectedMachine.status_desde)}</span>
              </div>

              <div className="pgNow">
                <div className="pgNowLabel">ARQUIVO ATUAL</div>
                <div className="pgNowValue">{emExecucao?.arquivo_nome || "Nenhum arquivo em execução"}</div>
              </div>
            </div>

            <div className="pgTableWrap">
              <table className="pgTable">
                <thead>
                  <tr>
                    <th style={{ width: 44 }}>Sel</th>
                    <th style={{ width: 44 }}>↕</th>
                    <th style={{ width: 70 }}>Pos</th>
                    <th>Arquivo</th>
                    <th style={{ width: 140 }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filaVisivel.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="pgEmptyCell">
                        Nenhum arquivo na fila
                      </td>
                    </tr>
                  ) : (
                    filaVisivel.map((it) => {
                      const checked = selectedFilaItemIds.has(it.id);
                      return (
                        <tr
                          key={it.id}
                          draggable={!readOnly && !reorderBusy}
                          onDragStart={(e) => {
                            if (readOnly) return;
                            const fromHandle = e.target?.closest?.(".pgReorderHandle");
                            if (fromHandle) {
                              e.preventDefault();
                              e.stopPropagation();
                              return;
                            }
                            onDragStartFilaMove(e, it);
                          }}
                          onDragEnd={onDragEndAny}
                          title={readOnly ? "" : "Arraste a LINHA para mover para outra CNC. Use ↕ para reordenar dentro desta fila."}
                          style={{ cursor: readOnly ? "default" : reorderBusy ? "not-allowed" : "grab" }}
                          onDragOver={(e) => {
                            if (readOnly) return;
                            const dt = e.dataTransfer;
                            const typ = getDragType(dt);
                            if (typ === "FILA_REORDER") {
                              e.preventDefault();
                              e.stopPropagation();
                              dt.dropEffect = "move";
                            }
                          }}
                          onDrop={(e) => {
                            if (readOnly) return;
                            const dt = e.dataTransfer;
                            const typ = getDragType(dt);
                            if (typ !== "FILA_REORDER") return;

                            e.preventDefault();
                            e.stopPropagation();

                            const mid = dt.getData("application/x-reorder-machine-id");
                            if (mid !== String(selectedId)) return;

                            const dragId = Number(dt.getData("application/x-reorder-item-id"));
                            reorderFilaLocalAndPersist(dragId, it.id);
                          }}
                        >
                          <td>
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={readOnly || reorderBusy}
                              onChange={() => toggleFilaSelection(it.id)}
                              title="Selecionar"
                              onClick={(e) => e.stopPropagation()}
                              style={bigCheckStyle}
                            />
                          </td>

                          {/* Handle para reordenar */}
                          <td>
                            <span
                              className="pgReorderHandle"
                              draggable={!readOnly && !reorderBusy}
                              onDragStart={(e) => onDragStartFilaReorderHandle(e, it)}
                              onDragEnd={onDragEndAny}
                              title={readOnly ? "" : "Arraste para reordenar"}
                              style={{
                                display: "inline-flex",
                                width: 34,
                                height: 34,
                                alignItems: "center",
                                justifyContent: "center",
                                cursor: readOnly ? "default" : reorderBusy ? "not-allowed" : "grab",
                                userSelect: "none",
                                borderRadius: 8,
                                border: "1px solid rgba(255,255,255,0.08)",
                                opacity: readOnly ? 0.35 : 1,
                              }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              ↕
                            </span>
                          </td>

                          <td className="pgMono">{it.posicao}</td>
                          <td title={it.arquivo_nome || ""}>
                            {it.arquivo_nome || `arquivo_id: ${it.arquivo_id}`}{" "}
                            <span className="pgTiny" style={{ opacity: 0.75 }}>
                              (item:{it.id})
                            </span>
                          </td>
                          <td>
                            <span className={`pgTone ${badgeTone(it.status)}`}>{it.status}</span>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>

              {reorderBusy && !readOnly && (
                <div className="pgTiny" style={{ marginTop: 10, opacity: 0.9 }}>
                  Salvando nova ordem...
                </div>
              )}
            </div>
          </div>

          {/* Cards CNC */}
          <div className="pgMachines">
            <div className="pgMachinesHeader">
              <div className="pgPanelTitle">Máquinas</div>
              <div className="pgTiny">{maquinas.length} máquinas cadastradas</div>
            </div>

            <div className="pgCards">
              {maquinas.map((m) => {
                const cd = cardData(m.id);
                return (
                  <button
                    key={m.id}
                    className={`pgCard ${m.id === selectedId ? "active" : ""}`}
                    onClick={() => setSelectedId(m.id)}
                    onDragOver={
                      readOnly
                        ? undefined
                        : (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                          }
                    }
                    onDrop={readOnly ? undefined : (e) => handleDropOnMachine(e, m.id)}
                    title={readOnly ? "" : "Solte o arquivo aqui para adicionar na fila (ou mova itens de outra CNC)"}
                    disabled={reorderBusy}
                  >
                    <div className="pgCardTop">
                      <div className="pgCardId">{m.id}</div>
                      <div className={`pgTone ${badgeTone(m.status)}`}>{m.status || "—"}</div>
                    </div>

                    <div className="pgCardName">{m.nome || "—"}</div>

                    <div className="pgCardBox">
                      <div className="pgCardBoxLabel">ARQUIVO ATUAL</div>
                      <div className="pgCardBoxValue">{cd.execNome || "Nenhum arquivo em execução"}</div>
                    </div>

                    <div className="pgCardMeta">
                      <div className="pgTiny">
                        desde: <span className="pgMono">{fmtDate(m.status_desde)}</span>
                      </div>
                      <div className="pgTiny">
                        FILA: <span className="pgMono">{cd.filaCount}</span>
                      </div>
                    </div>

                    {!readOnly && <div className="pgCardHint">Arraste do pool OU da linha da fila e solte aqui</div>}
                  </button>
                );
              })}

              {maquinas.length === 0 && (
                <div className="pgEmptyHint">
                  Nenhuma máquina carregada. Verifique se o backend está online e o VITE_API_URL está correto.
                </div>
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}