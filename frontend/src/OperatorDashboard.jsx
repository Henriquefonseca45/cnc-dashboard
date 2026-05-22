import React, { useEffect, useMemo, useRef, useState } from "react";
import { http } from "./http";
import { useNavigate, useParams } from "react-router-dom";
import rvbLogo from "./assets/rvb-logo.png";
import {
  RefreshCw,
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
  MessageSquare,
  Send,
  PackagePlus,
} from "lucide-react";

console.log("API_URL", http?.defaults?.baseURL);

const CNC_IDS = ["CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07", "CNC_TESTE"];
const DEFAULT_CNC = (import.meta.env.VITE_CNC_ID || "CNC01").toUpperCase();
const OPERADORES = [
  "AGNALDO",
  "GILBERTO",
  "LUCAS",
  "ALEIXO",
  "EDSON",
  "CRISTIANO",
  "GIOVANI",
  "PIERRE",
  "IVANILDO",
  "MARCOS",
  "EDUARDO",
  "JONATHAN",
  "MATHEUS",
];

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

function isNearScrollBottom(el, gap = 80) {
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= gap;
}

function pad2(n) {
  return String(Math.max(0, Math.floor(n))).padStart(2, "0");
}

// ============================
// HELPERS
// ============================
function normUpper(s) {
  return String(s || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase();
}
function U(s) {
  return normUpper(s);
}
function isUsinandoMachineStatus(machineStatus = "") {
  const s = U(machineStatus);
  return s.includes("USIN") || s.includes("CORT");
}

function toInt(n, fallback = 0) {
  const x = Number(n);
  return Number.isFinite(x) ? Math.trunc(x) : fallback;
}

function fmtHHMMSS(sec) {
  if (sec == null) return "—";
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  return `${pad2(h)}:${pad2(m)}:${pad2(ss)}`;
}

function calcRemainingSecondsFrozen(item, machineStatus, nowMs, freezeNowMs) {
  const total = toInt(item?.tempo_estimado_seg, 0);
  const startIso = item?.tempo_inicio_em;
  if (!total || !startIso) return null;

  const start = Date.parse(startIso);
  if (!start || Number.isNaN(start)) return null;

  const isU = isUsinandoMachineStatus(machineStatus);

  const pausadoAcum = Math.max(0, toInt(item?.tempo_pausado_seg, 0));
  const pausaInicioIso = item?.tempo_pausa_inicio_em || null;
  const pausaStart = pausaInicioIso ? Date.parse(pausaInicioIso) : NaN;

  let effectiveNow = nowMs;

  if (!isU) {
    if (pausaInicioIso && !Number.isNaN(pausaStart) && pausaStart) {
      effectiveNow = pausaStart;
    } else if (freezeNowMs) {
      effectiveNow = freezeNowMs;
    } else {
      effectiveNow = nowMs;
    }
  }

  const elapsed = Math.floor((effectiveNow - start) / 1000);
  const effectiveElapsed = Math.max(0, elapsed - pausadoAcum);

  return Math.max(0, total - effectiveElapsed);
}

function getErrMsg(e) {
  try {
    const d = e?.response?.data;
    if (!d) return e?.message || "Erro";
    if (typeof d === "string") return d;
    if (d.detail) return String(d.detail);
    return JSON.stringify(d);
  } catch {
    return e?.message || "Erro";
  }
}

function inferMaterialFromFileName(name = "") {
  const clean = String(name || "")
    .replace(/\.[^.]+$/i, "")
    .trim();

  const parts = clean
    .split(/\s+-\s+/)
    .map((p) => p.trim())
    .filter(Boolean);

  if (parts.length >= 5) return parts.slice(4).join(" - ");

  const codeMatch = /(\d+(?:[,.]\d+)?\s*(?:TX|KP|AD)\b.*)$/i.exec(clean);
  if (codeMatch) return codeMatch[1].replace(/\s+(?=TX|KP|AD\b)/i, "").trim();

  const match = /(\d+(?:[,.]\d+)?\s*mm\b.*)$/i.exec(clean);
  return match?.[1]?.trim() || "";
}

function StatusPill({ label }) {
  const base =
    "px-2.5 py-1 rounded-full text-[10px] font-semibold border whitespace-nowrap";

  const cls =
    label === "Usinando"
      ? "bg-emerald-100 text-emerald-700 border-emerald-200"
      : label === "Programado"
      ? "bg-sky-100 text-sky-700 border-sky-200"
      : label === "Concluído"
      ? "bg-emerald-100 text-emerald-700 border-emerald-200"
      : label === "Cancelado"
      ? "bg-red-100 text-red-700 border-red-200"
      : label === "Baixado"
      ? "bg-sky-100 text-sky-700 border-sky-200"
      : "bg-slate-100 text-slate-600 border-slate-200";

  return <span className={cn(base, cls)}>{label}</span>;
}

function Shell({ children }) {
  return (
    <div className="min-h-screen text-slate-800 bg-[#f5f6f8]">
      <div className="pointer-events-none fixed inset-0">
        <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-[900px] h-[420px] bg-indigo-500/10 blur-[110px]" />
        <div className="absolute top-28 left-10 w-[520px] h-[320px] bg-sky-500/10 blur-[110px]" />
      </div>
      {children}
    </div>
  );
}

function Topbar({ onRefresh }) {
  return (
    <div className="sticky top-0 z-20 border-b border-[rgba(47,55,125,.10)] bg-white/75 backdrop-blur">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <img
            src={rvbLogo}
            alt="RVB"
            className="w-12 h-12 object-contain rounded-xl bg-white p-1 border border-[rgba(47,55,125,.12)] shadow-sm"
          />

          <div className="leading-tight">
            <div className="text-lg font-semibold text-[#2f377d]">Painel do Operador</div>
            <div className="text-xs text-slate-500">Controle CNC</div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={onRefresh}
            className="h-10 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] inline-flex items-center"
            title="Atualizar"
          >
            <RefreshCw size={16} className="opacity-80 text-[#2f377d]" />
          </button>
        </div>
      </div>
    </div>
  );
}

function Card({ title, right, children, className = "" }) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-white/80 border border-[rgba(47,55,125,.12)] shadow-[0_20px_45px_rgba(32,37,61,.10)] backdrop-blur",
        className
      )}
    >
      <div className="px-5 pt-4 pb-2 flex items-center justify-between">
        <div className="text-[14px] font-extrabold tracking-[0.14em] text-[#2f377d]">
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
    <div className="rounded-2xl bg-white/70 border border-[rgba(47,55,125,.10)] p-4">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-500">
        <span className="opacity-80">{icon}</span>
        {label}
      </div>
      <div
        className="mt-2 font-semibold text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis"
        title={value}
      >
        {value}
      </div>
    </div>
  );
}

function Row({ title, subtitle, leftIcon, right }) {
  return (
    <div className="rounded-2xl bg-white/70 border border-[rgba(47,55,125,.10)] p-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-10 h-10 rounded-xl bg-[rgba(47,55,125,.05)] border border-[rgba(47,55,125,.10)] flex items-center justify-center">
          {leftIcon}
        </div>

        <div className="min-w-0 flex-1">
          <div
            className="font-semibold text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis"
            title={title}
          >
            {title}
          </div>

          <div
            className="text-xs text-slate-500 whitespace-nowrap overflow-hidden text-ellipsis"
            title={subtitle}
          >
            {subtitle}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">{right}</div>
    </div>
  );
}

export default function OperatorDashboard() {
  const { cncId } = useParams();
  const navigate = useNavigate();

  const cnc = (cncId || DEFAULT_CNC).toUpperCase();

  const [maquinas, setMaquinas] = useState([]);
  const [fila, setFila] = useState([]);
  const [historico, setHistorico] = useState([]);

  const [executando, setExecutando] = useState(null);
  const [loading, setLoading] = useState(false);
  const [baixandoId, setBaixandoId] = useState(null);

  const [menuOpenId, setMenuOpenId] = useState(null);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 224 });

  const [statusMaquina, setStatusMaquina] = useState("OCIOSA");
  const [salvandoStatus, setSalvandoStatus] = useState(false);

  const [operadorNome, setOperadorNome] = useState("");
  const [operadorEdit, setOperadorEdit] = useState(false);
  const [operadorDraft, setOperadorDraft] = useState("");
  const [salvandoOperador, setSalvandoOperador] = useState(false);

  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const freezeNowMsRef = useRef(null);
  const lastWasUsiRef = useRef(null);

  const [tempoModalOpen, setTempoModalOpen] = useState(false);
  const [tempoModalItem, setTempoModalItem] = useState(null);
  const [tempoModalMin, setTempoModalMin] = useState("45");
  const [tempoModalSaving, setTempoModalSaving] = useState(false);

  const [chatMsgs, setChatMsgs] = useState([]);
  const [chatText, setChatText] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);
  const chatListRef = useRef(null);
  const chatShouldScrollRef = useRef(true);
  const chatForceScrollRef = useRef(true);
  const [materialRequestingId, setMaterialRequestingId] = useState(null);
  const [materialSetupId, setMaterialSetupId] = useState(null);
  const [materialRequests, setMaterialRequests] = useState([]);

  useEffect(() => {
    if (cncId && !CNC_IDS.includes(cnc)) {
      navigate(`/operador/${DEFAULT_CNC}`, { replace: true });
    }
  }, [cncId, cnc, navigate]);

  useEffect(() => {
    setMenuOpenId(null);
  }, [cnc]);

  const maquinaAtual = useMemo(
    () => maquinas.find((m) => m.id === cnc),
    [maquinas, cnc]
  );

  const maquinaDesligada = U(maquinaAtual?.status || statusMaquina) === "DESLIGADA";

  useEffect(() => {
    const s = String(maquinaAtual?.status || "").trim();
    setStatusMaquina(s || "OCIOSA");
  }, [maquinaAtual?.status, cnc]);

  useEffect(() => {
    const statusAtual = String(maquinaAtual?.status || "").trim().toUpperCase();
    const nome = statusAtual === "DESLIGADA"
      ? ""
      : String(maquinaAtual?.operador_nome || "").trim();

    setOperadorNome(nome);
    setOperadorDraft(nome);
    setOperadorEdit(false);
  }, [maquinaAtual?.operador_nome, maquinaAtual?.status, cnc]);

  useEffect(() => {
    const st = String(maquinaAtual?.status || "");
    const isU = isUsinandoMachineStatus(st);

    if (lastWasUsiRef.current === null) {
      lastWasUsiRef.current = isU;
      freezeNowMsRef.current = null;
      return;
    }

    if (!isU && lastWasUsiRef.current === true) {
      freezeNowMsRef.current = Date.now();
    }

    if (isU && lastWasUsiRef.current === false) {
      freezeNowMsRef.current = null;
    }

    lastWasUsiRef.current = isU;
  }, [maquinaAtual?.status]);

  function openMenuFor(id, buttonEl) {
    if (!buttonEl) return;

    if (menuOpenId === id) {
      setMenuOpenId(null);
      return;
    }

    const r = buttonEl.getBoundingClientRect();
    const width = 224;
    const gap = 10;

    let left = r.right - width;
    left = Math.max(12, Math.min(left, window.innerWidth - width - 12));

    let top = r.bottom + gap;
    const approxHeight = 310;
    if (top + approxHeight > window.innerHeight - 12) {
      top = Math.max(12, r.top - approxHeight - gap);
    }

    setMenuPos({ top, left, width });
    setMenuOpenId(id);
  }

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") {
        setMenuOpenId(null);
        setTempoModalOpen(false);
      }
    }
    function onScroll() {
      setMenuOpenId(null);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
    };
  }, []);

  async function fetchChat(silent = false) {
    if (!cnc) return;

    if (!silent) setChatLoading(true);

    try {
      const r = await http.get(`/chat/${cnc}`);
      const data = Array.isArray(r.data) ? [...r.data].reverse() : [];
      const el = chatListRef.current;
      chatShouldScrollRef.current = chatForceScrollRef.current || !el || isNearScrollBottom(el);
      chatForceScrollRef.current = false;
      setChatMsgs(data);
    } catch (e) {
      console.error("fetchChat erro:", e);
      if (!silent) alert("Erro ao carregar chat: " + getErrMsg(e));
      setChatMsgs([]);
    } finally {
      if (!silent) setChatLoading(false);
    }
  }

  async function sendChat() {
    const texto = String(chatText || "").trim();
    if (!texto || chatSending) return;

    try {
      setChatSending(true);
      await http.post("/chat", {
        maquina_id: cnc,
        autor: "OPERADOR",
        mensagem: texto,
      });

      setChatText("");
      chatForceScrollRef.current = true;
      await fetchChat(true);
    } catch (e) {
      console.error("sendChat erro:", e);
      alert("Erro ao enviar mensagem: " + getErrMsg(e));
    } finally {
      setChatSending(false);
    }
  }

  async function carregarTudo() {
    setLoading(true);
    try {
      const [mRes, fRes, hRes, matRes] = await Promise.all([
        http.get("/maquinas"),
        http.get(`/fila/${cnc}`, { params: { include_done: true } }),
        http.get(`/historico/${cnc}`),
        http.get("/almoxarifado/solicitacoes", {
          params: { maquina_id: cnc, status: "TODAS", limit: 100 },
        }).catch(() => ({ data: [] })),
      ]);

      const maquinasData = mRes.data || [];
      const filaData = fRes.data || [];
      const histData = hRes.data || [];
      const materialData = Array.isArray(matRes.data) ? matRes.data : [];

      setMaquinas(maquinasData);
      setFila(filaData);
      setHistorico(histData);
      setMaterialRequests(materialData);

      const atual = filaData.find(
        (x) => String(x.status || "").toUpperCase() === "EM_EXECUCAO"
      );
      setExecutando(atual || null);
    } catch (e) {
      console.error("carregarTudo erro:", e);
      setMaterialRequests([]);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    chatForceScrollRef.current = true;
    carregarTudo();
    fetchChat();
  }, [cnc]);

  useEffect(() => {
    const t = setInterval(() => {
      fetchChat(true);
    }, 5000);

    return () => clearInterval(t);
  }, [cnc]);

  useEffect(() => {
    const el = chatListRef.current;
    if (!el) return;
    if (!chatShouldScrollRef.current) return;
    el.scrollTop = el.scrollHeight;
    chatShouldScrollRef.current = false;
  }, [chatMsgs]);

  async function atualizarStatusMaquina(novo) {
    setStatusMaquina(novo);

    try {
      setSalvandoStatus(true);

      await http.post(`/maquinas/${cnc}/status`, { status: novo });

      if (String(novo).toUpperCase() === "DESLIGADA") {
        await http.post(`/maquinas/${cnc}/operador`, { nome: "" });
        setOperadorNome("");
        setOperadorDraft("");
        setOperadorEdit(false);
      }

      await carregarTudo();
    } catch (e) {
      console.error(e);
      await carregarTudo();
    } finally {
      setSalvandoStatus(false);
    }
  }

  async function salvarOperador() {
    if (String(statusMaquina || "").toUpperCase() === "DESLIGADA") {
      alert("Máquina desligada não pode ter operador.");
      setOperadorNome("");
      setOperadorDraft("");
      setOperadorEdit(false);
      return;
    }

    const nome = String(operadorDraft || "").trim();

    try {
      setSalvandoOperador(true);
      await http.post(`/maquinas/${cnc}/operador`, { nome });
      await carregarTudo();
      setOperadorEdit(false);
    } catch (e) {
      console.error(e);
      alert("Erro ao salvar operador: " + getErrMsg(e));
    } finally {
      setSalvandoOperador(false);
    }
  }

  async function baixarArquivo(item) {
    if (!item?.id) return;
    if (baixandoId) return;

    const bloqueio = getDownloadBloqueio(item);
    if (bloqueio) {
      alert(bloqueio);
      return;
    }

    try {
      setBaixandoId(item.id);
      const res = await http.get(`/agente/${cnc}/download/fila/${item.id}`, {
        responseType: "blob",
      });

      let filename = item.arquivo_nome || `arquivo_${item.id}.dxf`;
      const cd =
        res.headers?.["content-disposition"] ||
        res.headers?.["Content-Disposition"];

      if (cd) {
        const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(cd);
        if (m?.[1]) filename = decodeURIComponent(m[1]);
      }

      const blob = new Blob([res.data], {
        type: res.data?.type || "application/octet-stream",
      });

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      await carregarTudo();
    } catch (e) {
      console.error(e);
      let msg = getErrMsg(e);
      try {
        const data = e?.response?.data;
        if (typeof Blob !== "undefined" && data instanceof Blob) {
          const text = await data.text();
          const parsed = JSON.parse(text);
          msg = parsed?.detail ? String(parsed.detail) : text || msg;
        }
      } catch {}
      alert("Erro ao baixar: " + msg);
    } finally {
      setBaixandoId(null);
    }
  }

  async function solicitarMaterial(item) {
    if (!item?.id || materialRequestingId) return;

    const arquivo = item.arquivo_nome || item.nome || `Arquivo #${item.id}`;
    const material =
      String(item.material || "").trim() ||
      inferMaterialFromFileName(arquivo) ||
      "material nao informado";

    try {
      setMaterialRequestingId(item.id);
      await http.post("/almoxarifado/solicitacoes", {
        maquina_id: cnc,
        item_id: item.id,
        arquivo_nome: arquivo,
        material,
      });

      await http.post(`/maquinas/${cnc}/status`, {
        status: "AGUAR.EMPILHADEIRA",
      });

      setStatusMaquina("AGUAR.EMPILHADEIRA");
      setMenuOpenId(null);
      await carregarTudo();
      alert("Solicitacao de material enviada ao almoxarifado.");
    } catch (e) {
      console.error("solicitarMaterial erro:", e);
      alert("Erro ao solicitar material: " + getErrMsg(e));
    } finally {
      setMaterialRequestingId(null);
    }
  }

  async function setupMaterial(item) {
    if (!item?.id || materialSetupId) return;

    try {
      setMaterialSetupId(item.id);

      await http.post(`/maquinas/${cnc}/status`, {
        status: "SETUP",
      });

      await http.post("/almoxarifado/solicitacoes/entregar", {
        maquina_id: cnc,
        item_id: item.id,
      });

      setStatusMaquina("SETUP");
      setMenuOpenId(null);
      await carregarTudo();
    } catch (e) {
      console.error("setupMaterial erro:", e);
      alert("Erro ao iniciar setup de material: " + getErrMsg(e));
    } finally {
      setMaterialSetupId(null);
    }
  }

  async function setItemStatus(item, novoStatus) {
    if (!item) return;
    try {
      await http.post(`/fila/${cnc}/status`, {
        id: item.id,
        status: novoStatus,
      });
      await carregarTudo();
    } catch (e) {
      console.error(e);
      alert("Erro: " + getErrMsg(e));
      await carregarTudo();
    } finally {
      setMenuOpenId(null);
    }
  }

  async function confirmarECortar(item) {
    if (!item?.id) return;
    const nome = item?.arquivo_nome || item?.nome || `#${item.id}`;
    const ok = window.confirm(`Confirmar CORTADO?\n\n${nome}`);
    if (!ok) return;
    await setItemStatus(item, "CONCLUIDO");
  }

  async function salvarTempoEstimado(item, minutos) {
    const m = toInt(minutos, 0);
    if (!item?.id) throw new Error("Item inválido");
    if (m <= 0) throw new Error("Informe minutos > 0");
    await http.post(`/fila/item/${item.id}/tempo_estimado`, { minutos: m });
  }

  function abrirPopupTempoParaUsinar(item) {
    setMenuOpenId(null);

    const bloqueio = getSetupMaterialBloqueio(item);
    if (bloqueio) {
      alert(bloqueio);
      return;
    }

    const seg = toInt(item?.tempo_estimado_seg, 0);
    if (seg > 0) setTempoModalMin(String(Math.max(1, Math.round(seg / 60))));
    else setTempoModalMin("45");

    setTempoModalItem(item);
    setTempoModalOpen(true);
  }

  async function confirmarTempoEUsinar() {
    if (!tempoModalItem?.id) return;

    try {
      setTempoModalSaving(true);

      const bloqueio = getSetupMaterialBloqueio(tempoModalItem);
      if (bloqueio) {
        alert(bloqueio);
        setTempoModalOpen(false);
        setTempoModalItem(null);
        await carregarTudo();
        return;
      }

      await salvarTempoEstimado(tempoModalItem, tempoModalMin);

      await http.post(`/fila/${cnc}/status`, {
        id: tempoModalItem.id,
        status: "USINANDO",
      });

      await http.post(`/maquinas/${cnc}/status`, {
        status: "USINANDO",
      });

      setStatusMaquina("USINANDO");
      setTempoModalOpen(false);
      setTempoModalItem(null);
      setMenuOpenId(null);

      await carregarTudo();
    } catch (e) {
      console.error(e);
      alert("Erro ao iniciar USINANDO: " + getErrMsg(e));
      await carregarTudo();
    } finally {
      setTempoModalSaving(false);
    }
  }

  const filaVisivel = useMemo(() => {
    return (fila || []).filter((it) => {
      const st = String(it.status || "").toUpperCase();
      return st !== "CORTADO" && st !== "CANCELADO";
    });
  }, [fila]);

  const baixadoPendente = useMemo(() => {
    return filaVisivel.find((it) => String(it.status || "").toUpperCase() === "BAIXADO") || null;
  }, [filaVisivel]);

  function getMaterialRequestAberta(item) {
    if (!item?.id) return null;
    return (
      (materialRequests || []).find(
        (req) =>
          Number(req?.item_id) === Number(item.id) &&
          String(req?.status || "").toUpperCase() === "ABERTA"
      ) || null
    );
  }

  function getSetupMaterialBloqueio(item) {
    const req = getMaterialRequestAberta(item);
    if (!req) return "";

    const material = req.material || "material solicitado";
    return `Existe solicitacao de material aberta para este arquivo:\n\n${material}\n\nConfirme o Setup de material antes de colocar em USINANDO.`;
  }

  function getDownloadBloqueio(item) {
    if (!item?.id) return "Item invalido.";
    const st = String(item.status || "").toUpperCase();
    if (!["AGUARDANDO", "PROGRAMANDO", "BAIXADO"].includes(st)) {
      return `Este arquivo nao pode ser baixado agora (status: ${item.status || "-"}).`;
    }

    if (baixadoPendente && Number(baixadoPendente.id) !== Number(item.id)) {
      const nome = baixadoPendente.arquivo_nome || baixadoPendente.nome || `Arquivo #${baixadoPendente.id}`;
      return `Ja existe um arquivo baixado aguardando USINANDO:\n\n${nome}\n\nColoque esse arquivo em USINANDO antes de baixar outro.`;
    }

    return "";
  }

  const menuItem = useMemo(() => {
    if (!menuOpenId) return null;
    return (fila || []).find((x) => x.id === menuOpenId) || null;
  }, [fila, menuOpenId]);

  function restanteItem(item) {
    const nowMs = Date.now();
    const machineStatus = maquinaAtual?.status || statusMaquina || "";
    return calcRemainingSecondsFrozen(
      item,
      machineStatus,
      nowMs,
      freezeNowMsRef.current
    );
  }

  function progressoItem(item) {
    const total = toInt(item?.tempo_estimado_seg, 0);
    const restante = restanteItem(item);

    if (!total || restante == null) {
      return { pct: 0, restanteSeg: restante, decorridoSeg: null };
    }

    const decorridoSeg = Math.max(0, total - restante);
    const pct = Math.max(0, Math.min(100, Math.round((decorridoSeg / total) * 100)));

    return { pct, restanteSeg: restante, decorridoSeg };
  }

  const execProg = useMemo(() => {
    if (!executando) return { pct: 0, restanteSeg: null, decorridoSeg: null };
    return progressoItem(executando);
  }, [executando, maquinaAtual?.status, statusMaquina, fila, tick]);

  return (
    <Shell>
      <Topbar
        onRefresh={async () => {
          await carregarTudo();
          await fetchChat();
        }}
      />

      <div className="relative max-w-6xl mx-auto px-6 py-6">
        {loading && (
          <div className="text-xs text-slate-400 mb-3">carregando…</div>
        )}

        <div className="grid grid-cols-12 gap-6 items-stretch auto-rows-min">
          <div className="col-span-12 md:col-span-4 flex flex-col gap-6">
            <Card
              title={cnc.replace("CNC", "CNC-")}
              right={
                <span className="px-3 py-1 rounded-xl bg-[rgba(47,55,125,.06)] border border-[rgba(47,55,125,.12)] text-xs text-[#2f377d]">
                  {maquinaAtual?.status || "—"}
                </span>
              }
            >
              <div className="grid grid-cols-2 gap-3">
                <StatBox
                  icon={<User2 size={14} className="text-slate-500" />}
                  label="Operador"
                  value={maquinaDesligada ? "Sem operador" : operadorNome || "Não informado"}
                />
                <StatBox
                  icon={<FileText size={14} className="text-slate-500" />}
                  label="Arquivo atual"
                  value={executando?.arquivo_nome || executando?.nome || "—"}
                />
              </div>

              <div className="mt-3">
                {!operadorEdit ? (
                  <button
                    className="w-full h-10 px-4 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] disabled:opacity-50 text-sm font-semibold text-[#2f377d] transition"
                    onClick={() => {
                      setOperadorDraft(operadorNome || "");
                      setOperadorEdit(true);
                    }}
                    title={
                      maquinaDesligada
                        ? "Máquina desligada não pode ter operador"
                        : "Definir operador"
                    }
                    disabled={maquinaDesligada}
                  >
                    {operadorNome ? "Trocar operador" : "Definir operador"}
                  </button>
                ) : (
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
                    <select
                      value={operadorDraft}
                      onChange={(e) => setOperadorDraft(e.target.value)}
                      className="flex-1 min-w-0 h-10 rounded-xl bg-white border border-[rgba(47,55,125,.12)] px-3 text-sm text-[#2f377d] font-semibold outline-none appearance-auto"
                      style={{ color: "#2f377d", WebkitTextFillColor: "#2f377d" }}
                      autoFocus
                      disabled={salvandoOperador || maquinaDesligada}
                    >
                      <option value="" style={{ color: "#2f377d", backgroundColor: "#ffffff" }}>
                        Selecione o operador
                      </option>
                      {OPERADORES.map((nome) => (
                        <option key={nome} value={nome} style={{ color: "#2f377d", backgroundColor: "#ffffff" }}>
                          {nome}
                        </option>
                      ))}
                    </select>

                    <div className="flex w-full gap-2 lg:w-auto lg:flex-shrink-0">
                      <button
                        className="flex-1 lg:flex-none h-10 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold text-white transition"
                        onClick={salvarOperador}
                        disabled={
                          !String(operadorDraft || "").trim() ||
                          salvandoOperador ||
                          maquinaDesligada
                        }
                        title="Salvar"
                      >
                        {salvandoOperador ? "..." : "Salvar"}
                      </button>
                      <button
                        className="flex-1 lg:flex-none h-10 px-4 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-sm text-[#2f377d]"
                        onClick={() => setOperadorEdit(false)}
                        title="Cancelar"
                        disabled={salvandoOperador}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                )}

                {maquinaDesligada && (
                  <div className="mt-2 text-[11px] text-slate-400">
                    Máquina desligada não pode ter operador atribuído.
                  </div>
                )}
              </div>

              <div className="mt-5">
                <div className="text-[15px] uppercase tracking-wider text-slate-600 mb-2">
                  Alterar status
                </div>

                <select
                  className="w-full h-11 rounded-xl bg-white border border-[rgba(47,55,125,.12)] px-3 text-sm text-slate-800 outline-none disabled:opacity-60 appearance-auto"
                  style={{ color: "#1e293b", WebkitTextFillColor: "#1e293b" }}
                  value={statusMaquina}
                  onChange={(e) => atualizarStatusMaquina(e.target.value)}
                  disabled={salvandoStatus}
                >
                  <option value="DESLIGADA">DESLIGADA</option>
                  <option value="USINANDO">USINANDO</option>
                  <option value="USINANDO DETALHE">DETALHE CNC</option>
                  <option value="SETUP">SETUP</option>
                  <option value="REFEIÇÃO">REFEIÇÃO</option>
                  <option value="MANUTENÇÃO">MANUTENÇÃO</option>
                  <option value="AGUAR.EMPILHADEIRA">AGUAR.EMPILHADEIRA</option>
                  <option value="REUNIÃO">REUNIÃO</option>
                  <option value="TROCA CHAPA SACRIFICIO">
                    TROCA CHAPA SACRIFICIO
                  </option>
                  <option value="OCIOSA">OCIOSA</option>
                  <option value="RNC">RNC</option>
                  <option value="ABERTURA MATERIAL">ABERTURA MATERIAL</option>
                </select>

                <div className="mt-4">
                  <button
                    className="w-full h-12 px-4 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold text-white transition"
                    disabled={!executando?.id}
                    onClick={() => executando?.id && confirmarECortar(executando)}
                  >
                    Cortado
                  </button>
                </div>
              </div>
            </Card>

            <Card
              title="CHAT COM PROGRAMADOR"
              right={
                <button
                  onClick={() => fetchChat()}
                  className="h-9 shrink-0 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] inline-flex items-center gap-2 text-xs text-[#2f377d]"
                  disabled={chatLoading || chatSending}
                >
                  <MessageSquare size={14} />
                  {chatLoading ? "Atualizando..." : "Atualizar"}
                </button>
              }
            >
              <div
                ref={chatListRef}
                className="rounded-2xl bg-[#f8fafc] border border-[rgba(47,55,125,.10)] p-3 h-[300px] overflow-auto space-y-3"
              >
                {chatLoading ? (
                  <div className="h-full flex items-center justify-center text-sm text-slate-400">
                    Carregando mensagens...
                  </div>
                ) : chatMsgs.length === 0 ? (
                  <div className="h-full flex items-center justify-center text-sm text-slate-400">
                    Nenhuma mensagem ainda.
                  </div>
                ) : (
                  chatMsgs.map((m) => {
                    const mine = String(m.autor || "").toUpperCase() === "OPERADOR";

                    return (
                      <div
                        key={m.id}
                        className={cn("flex w-full", mine ? "justify-end" : "justify-start")}
                      >
                        <div
                          className={cn(
                            "w-fit max-w-[82%] min-w-0 rounded-2xl border px-3 py-2",
                            mine
                              ? "bg-sky-100 border-sky-200"
                              : "bg-white border-[rgba(47,55,125,.10)]"
                          )}
                        >
                          <div className="flex items-start justify-between gap-3 text-[11px] text-slate-400 mb-1">
                            <strong className="text-[#2f377d] shrink-0">{m.autor || "-"}</strong>
                            <span className="text-right leading-tight">{fmtDate(m.criado_em)}</span>
                          </div>

                          <div className="text-sm text-slate-800 whitespace-pre-wrap break-words">
                            {m.mensagem || ""}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

              <div className="mt-3 w-full min-w-0 overflow-hidden">
                <div className="flex w-full min-w-0 items-center gap-2">
                  <input
                    className="flex-1 min-w-0 h-11 rounded-xl bg-white border border-[rgba(47,55,125,.12)] px-3 text-sm text-slate-800 outline-none"
                    type="text"
                    placeholder="Digite uma mensagem..."
                    value={chatText}
                    onChange={(e) => setChatText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        sendChat();
                      }
                    }}
                    disabled={chatSending}
                  />
                  <button
                    className="h-11 shrink-0 px-4 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-sm font-semibold text-white transition inline-flex items-center justify-center gap-2 whitespace-nowrap"
                    onClick={sendChat}
                    disabled={chatSending || !String(chatText || "").trim()}
                  >
                    <Send size={15} className="shrink-0" />
                    <span>{chatSending ? "Enviando..." : "Enviar"}</span>
                  </button>
                </div>
              </div>
            </Card>

            <Card title="HISTÓRICO DE CORTE" className="flex-1">
              {historico.length === 0 ? (
                <div className="min-h-[120px] flex items-center justify-center text-sm text-slate-400">
                  Sem histórico ainda.
                </div>
              ) : (
                <div className="space-y-3 max-h-[44vh] overflow-auto pr-1">
                  {historico.slice(0, 80).map((h) => {
                    const hs = String(h.status || "").toUpperCase();
                    const hLabel = hs === "CANCELADO" ? "Cancelado" : "Concluído";

                    return (
                      <Row
                        key={h.id}
                        leftIcon={
                          hs === "CANCELADO" ? (
                            <X size={18} className="text-red-500" />
                          ) : (
                            <CheckCircle2 size={18} className="text-emerald-500" />
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

          <div className="col-span-12 md:col-span-8 flex flex-col gap-6 min-h-[70vh]">
            <Card title="ARQUIVO EM EXECUÇÃO">
              <div className="rounded-2xl bg-white/70 border border-[rgba(47,55,125,.10)] p-4">
                {!executando ? (
                  <div className="text-sm text-slate-400 py-8 text-center">
                    Nenhum arquivo em execução.
                  </div>
                ) : (
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-2xl bg-emerald-100 border border-emerald-200 flex items-center justify-center">
                      <Activity size={18} className="text-emerald-600" />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div
                        className="font-bold text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis"
                        title={executando.arquivo_nome || executando.nome}
                      >
                        {executando.arquivo_nome || executando.nome}
                      </div>

                      <div className="text-xs text-slate-500 mt-1 inline-flex items-center gap-2">
                        <Clock3 size={14} className="opacity-80" />
                        <span>
                          Est.:{" "}
                          {executando?.tempo_estimado_seg
                            ? `${Math.round(executando.tempo_estimado_seg / 60)} min`
                            : "—"}
                          {" • "}
                          Decorrido:{" "}
                          {execProg.decorridoSeg != null ? fmtHHMMSS(execProg.decorridoSeg) : "—"}
                          {" • "}
                          Restante: {fmtHHMMSS(execProg.restanteSeg)}
                        </span>
                      </div>

                      <div className="mt-3 h-2 rounded-full bg-[rgba(47,55,125,.10)] overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-emerald-500/80 to-emerald-300/80 transition-all duration-500"
                          style={{ width: `${execProg.pct}%` }}
                        />
                      </div>

                      <div className="mt-1 text-[11px] text-slate-400 flex justify-between">
                        <span>Em execução…</span>
                        <span>{executando?.tempo_estimado_seg ? `${execProg.pct}%` : "—"}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-3 text-xs text-slate-500">
                Regra: o item só deve sair da fila quando marcar <b>Concluído</b> ou <b>Cancelado</b>.
              </div>

              {baixadoPendente && (
                <div className="mt-2 text-xs rounded-xl border border-amber-200 bg-amber-50 text-amber-800 px-3 py-2">
                  Para baixar outro arquivo, coloque em <b>USINANDO</b>: {baixadoPendente.arquivo_nome || baixadoPendente.nome || `Arquivo #${baixadoPendente.id}`}
                </div>
              )}
            </Card>

            <Card
              title="FILA DE ARQUIVOS"
              right={
                <span className="px-3 py-1 rounded-xl bg-white border border-[rgba(47,55,125,.12)] text-xs text-[#2f377d]">
                  {filaVisivel.length} itens
                </span>
              }
              className="flex-1 min-h-[280px]"
            >
              <div className="h-full overflow-auto pr-1 space-y-3">
                {filaVisivel.map((item) => {
                  const st = String(item.status || "").toUpperCase();

                  const label =
                    st === "EM_EXECUCAO"
                      ? "Usinando"
                      : st === "PROGRAMANDO"
                      ? "Programado"
                      : st === "BAIXADO"
                      ? "Baixado"
                      : "Na Fila";

                  const title =
                    item.arquivo_nome || item.nome || `Arquivo #${item.id}`;

                  const estMin = item?.tempo_estimado_seg
                    ? Math.round(toInt(item.tempo_estimado_seg, 0) / 60)
                    : null;

                  const restante = restanteItem(item);
                  const downloadBloqueio = getDownloadBloqueio(item);
                  const setupMaterialBloqueio = getSetupMaterialBloqueio(item);
                  const isBaixando = Number(baixandoId) === Number(item.id);

                  const subtitle = [
                    item.material || "—",
                    estMin != null ? `Est. ${estMin}min` : null,
                    restante != null ? `Rest. ${fmtHHMMSS(restante)}` : null,
                    setupMaterialBloqueio ? "Setup material pendente" : null,
                  ]
                    .filter(Boolean)
                    .join(" • ");

                  return (
                    <Row
                      key={item.id}
                      leftIcon={<FileText size={18} className="text-[#2f377d]/85" />}
                      title={title}
                      subtitle={subtitle}
                      right={
                        <>
                          <StatusPill label={label} />

                          <button
                            onClick={() => baixarArquivo(item)}
                            disabled={Boolean(baixandoId)}
                            aria-disabled={Boolean(downloadBloqueio) || Boolean(baixandoId)}
                            className={cn(
                              "h-10 w-10 rounded-xl bg-white border border-[rgba(47,55,125,.12)] flex items-center justify-center",
                              downloadBloqueio || baixandoId
                                ? "opacity-45 cursor-not-allowed"
                                : "hover:bg-[rgba(47,55,125,.05)]"
                            )}
                            title={downloadBloqueio || (isBaixando ? "Baixando..." : "Baixar")}
                          >
                            <Download size={16} className={isBaixando ? "text-[#2f377d]/45 animate-pulse" : "text-[#2f377d]/85"} />
                          </button>

                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              openMenuFor(item.id, e.currentTarget);
                            }}
                            className="h-10 w-10 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] flex items-center justify-center"
                            title="Opções"
                          >
                            <MoreVertical size={16} className="text-[#2f377d]/75" />
                          </button>
                        </>
                      }
                    />
                  );
                })}

                {filaVisivel.length === 0 && (
                  <div className="text-sm text-slate-400 py-10 text-center">
                    Sem itens na fila.
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      </div>

      {menuOpenId && (
        <>
          <div
            className="fixed inset-0 z-[80]"
            onClick={() => setMenuOpenId(null)}
          />
          <div
            className="fixed z-[90] rounded-2xl bg-white/95 border border-[rgba(47,55,125,.12)] shadow-[0_25px_60px_-40px_rgba(32,37,61,.30)] backdrop-blur p-2"
            style={{
              top: menuPos.top,
              left: menuPos.left,
              width: menuPos.width,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setItemStatus(menuItem, "PROGRAMADO")}
              className="w-full px-3 py-2 rounded-xl hover:bg-[rgba(47,55,125,.05)] flex items-center gap-3 text-sm text-slate-800"
            >
              <Wrench size={16} className="text-[#2f377d]/70" />
              Programado
            </button>

            <button
              onClick={() => abrirPopupTempoParaUsinar(menuItem)}
              aria-disabled={Boolean(getSetupMaterialBloqueio(menuItem))}
              title={getSetupMaterialBloqueio(menuItem) || "Usinando"}
              className={cn(
                "w-full px-3 py-2 rounded-xl flex items-center gap-3 text-sm text-slate-800",
                getSetupMaterialBloqueio(menuItem)
                  ? "opacity-60 cursor-not-allowed"
                  : "hover:bg-[rgba(47,55,125,.05)]"
              )}
            >
              <Play size={16} className="text-emerald-600" />
              Usinando
            </button>

            <button
              onClick={() => confirmarECortar(menuItem)}
              className="w-full px-3 py-2 rounded-xl hover:bg-[rgba(47,55,125,.05)] flex items-center gap-3 text-sm text-slate-800"
            >
              <CheckCircle2 size={16} className="text-emerald-600" />
              Concluído
            </button>

            <button
              onClick={() => solicitarMaterial(menuItem)}
              disabled={materialRequestingId === menuItem?.id}
              className="w-full px-3 py-2 rounded-xl hover:bg-[rgba(47,55,125,.05)] disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-3 text-sm text-slate-800"
            >
              <PackagePlus size={16} className="text-[#2f377d]/70" />
              Solicitar material
            </button>

            <button
              onClick={() => setupMaterial(menuItem)}
              disabled={materialSetupId === menuItem?.id}
              className="w-full px-3 py-2 rounded-xl hover:bg-[rgba(47,55,125,.05)] disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-3 text-sm text-slate-800"
            >
              <Wrench size={16} className="text-amber-600" />
              Setup de material
            </button>

            <div className="h-px bg-[rgba(47,55,125,.10)] my-2" />

            <button
              onClick={() => setItemStatus(menuItem, "CANCELADO")}
              className="w-full px-3 py-2 rounded-xl hover:bg-red-50 flex items-center gap-3 text-sm text-red-600"
            >
              <X size={16} className="text-red-500" />
              Cancelar
            </button>
          </div>
        </>
      )}

      {tempoModalOpen && (
        <>
          <div
            className="fixed inset-0 z-[95] bg-black/60"
            onClick={() => !tempoModalSaving && setTempoModalOpen(false)}
          />
          <div
            className="fixed z-[100] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[92vw] max-w-md rounded-2xl bg-white/95 border border-[rgba(47,55,125,.12)] shadow-[0_25px_70px_-40px_rgba(32,37,61,.30)] backdrop-blur p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs tracking-[0.25em] text-slate-500">
                  DEFINIR TEMPO ESTIMADO
                </div>
                <div className="mt-2 font-semibold text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis">
                  {tempoModalItem?.arquivo_nome ||
                    tempoModalItem?.nome ||
                    `Item #${tempoModalItem?.id}`}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  Ao confirmar, o tempo começa e o item vai para <b>USINANDO</b>.
                </div>
              </div>

              <button
                className="h-9 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-sm text-[#2f377d]"
                onClick={() => !tempoModalSaving && setTempoModalOpen(false)}
                disabled={tempoModalSaving}
                title="Fechar"
              >
                <X size={16} />
              </button>
            </div>

            <div className="mt-4">
              <label className="text-[10px] tracking-[0.20em] text-slate-500">
                TEMPO (MINUTOS)
              </label>
              <input
                value={tempoModalMin}
                onChange={(e) => setTempoModalMin(e.target.value)}
                type="number"
                min="1"
                className="mt-2 w-full h-11 rounded-xl bg-white border border-[rgba(47,55,125,.12)] px-3 text-sm text-slate-800 outline-none"
                placeholder="ex: 45"
                disabled={tempoModalSaving}
              />

              <div className="mt-2 text-[11px] text-slate-400">
                Ex.: 45 min = <b>{fmtHHMMSS(toInt(tempoModalMin, 0) * 60)}</b>
              </div>
            </div>

            <div className="mt-4 flex gap-2">
              <button
                className="flex-1 h-11 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-sm text-[#2f377d]"
                onClick={() => !tempoModalSaving && setTempoModalOpen(false)}
                disabled={tempoModalSaving}
              >
                Cancelar
              </button>
              <button
                className="flex-1 h-11 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm font-semibold text-white transition"
                onClick={confirmarTempoEUsinar}
                disabled={tempoModalSaving}
              >
                {tempoModalSaving ? "Salvando..." : "Confirmar e Usinar"}
              </button>
            </div>

            <div className="mt-3 text-[11px] text-slate-400">
              Se aparecer erro “Já existe item em execução”, finalize o atual antes.
            </div>
          </div>
        </>
      )}
    </Shell>
  );
}
