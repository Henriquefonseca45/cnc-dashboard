import React, { useEffect, useMemo, useRef, useState } from "react";
import { http } from "./http";
import { useNavigate, useParams } from "react-router-dom";
import rvbLogo from "./assets/rvb-logo.png";
import {
  RefreshCw,
  Eye,
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
const USINAGEM_TIPOS = [
  { value: "USINANDO", label: "USINANDO", requiredText: "" },
  { value: "DETALHE CNC", label: "DETALHE CNC", requiredText: "DETALHE" },
  { value: "RNC", label: "RNC", requiredText: "RNC" },
  {
    value: "ABERTURA MATERIAL",
    label: "ABERTURA MATERIAL",
    requiredText: "ABERTURA DE MATERIAL",
  },
];
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
  return (
    s.includes("USIN") ||
    s.includes("CORT") ||
    s.includes("DETALHE CNC") ||
    s === "RNC" ||
    (s.includes("ABERTURA") && s.includes("MATERIAL"))
  );
}

function normalizeUsinagemStatusValue(status = "") {
  const s = U(status);
  if (s === "USINANDO DETALHE") return "DETALHE CNC";
  if (s === "USINANDO RNC") return "RNC";
  if (s === "USINANDO ABERTURA DE MATERIAL" || s === "ABERTURA DE MATERIAL") {
    return "ABERTURA MATERIAL";
  }
  return String(status || "").trim();
}

function getArquivoNome(item) {
  return item?.arquivo_nome || item?.nome || `Item #${item?.id || "-"}`;
}

function getUsinagemTipoPermitido(item) {
  const nome = U(getArquivoNome(item));
  if (nome.includes("ABERTURA DE MATERIAL") || nome.includes("ABERTURA MATERIAL")) {
    return "ABERTURA MATERIAL";
  }
  if (nome.includes("DETALHE")) return "DETALHE CNC";
  if (nome.includes("RNC")) return "RNC";
  return "USINANDO";
}

function canUseUsinagemTipo(item, tipo) {
  return getUsinagemTipoPermitido(item) === normalizeUsinagemStatusValue(tipo);
}

function getUsinagemTipoBloqueio(item, tipo) {
  const rule = USINAGEM_TIPOS.find((x) => x.value === tipo);
  if (!rule || canUseUsinagemTipo(item, tipo)) return "";

  const permitido = getUsinagemTipoPermitido(item);
  const permitidoLabel = USINAGEM_TIPOS.find((x) => x.value === permitido)?.label || permitido;
  return `Este arquivo so pode ser colocado como ${permitidoLabel}.`;
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

function dxfNum(v, fallback = 0) {
  const n = Number(String(v || "").replace(",", "."));
  return Number.isFinite(n) ? n : fallback;
}

function cleanDxfText(value = "") {
  return String(value)
    .replace(/\\P/g, " ")
    .replace(/\\~|\\[A-Za-z][^;]*;/g, " ")
    .replace(/[{}]/g, "")
    .trim();
}

function bulgePathSegment(p1, p2) {
  const bulge = Number(p1?.bulge || 0);
  if (!bulge) return `L ${p2.x} ${p2.y}`;

  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  const chord = Math.hypot(dx, dy);
  if (!chord) return "";

  const radius = (chord * (1 + bulge * bulge)) / (4 * Math.abs(bulge));
  const largeArc = Math.abs(4 * Math.atan(bulge)) > Math.PI ? 1 : 0;
  const sweep = bulge > 0 ? 0 : 1;
  return `A ${radius} ${radius} 0 ${largeArc} ${sweep} ${p2.x} ${p2.y}`;
}

function polylinePath(points = [], closed = false) {
  if (!points.length) return "";
  const pts = closed ? [...points, points[0]] : points;
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length; i += 1) {
    d += ` ${bulgePathSegment(pts[i - 1], pts[i])}`;
  }
  return d;
}

function parseDxfPreview(text) {
  const raw = String(text || "").split(/\r?\n/);
  const pairs = [];
  for (let i = 0; i < raw.length - 1; i += 2) {
    pairs.push({ code: raw[i].trim(), value: raw[i + 1].trim() });
  }

  const items = [];
  const addLine = (x1, y1, x2, y2) => {
    if ([x1, y1, x2, y2].every(Number.isFinite)) {
      items.push({ type: "line", x1, y1: -y1, x2, y2: -y2 });
    }
  };

  for (let i = 0; i < pairs.length; i += 1) {
    const p = pairs[i];
    if (p.code !== "0") continue;
    const entity = p.value.toUpperCase();

    if (entity === "LINE") {
      const line = {};
      for (i += 1; i < pairs.length && pairs[i].code !== "0"; i += 1) {
        const { code, value } = pairs[i];
        if (code === "10") line.x1 = dxfNum(value);
        if (code === "20") line.y1 = dxfNum(value);
        if (code === "11") line.x2 = dxfNum(value);
        if (code === "21") line.y2 = dxfNum(value);
      }
      i -= 1;
      addLine(line.x1, line.y1, line.x2, line.y2);
      continue;
    }

    if (entity === "CIRCLE" || entity === "ARC") {
      const arc = { start: 0, end: 360 };
      for (i += 1; i < pairs.length && pairs[i].code !== "0"; i += 1) {
        const { code, value } = pairs[i];
        if (code === "10") arc.cx = dxfNum(value);
        if (code === "20") arc.cy = dxfNum(value);
        if (code === "40") arc.r = Math.abs(dxfNum(value));
        if (code === "50") arc.start = dxfNum(value);
        if (code === "51") arc.end = dxfNum(value);
      }
      i -= 1;
      if ([arc.cx, arc.cy, arc.r].every(Number.isFinite) && arc.r > 0) {
        items.push({ type: entity.toLowerCase(), cx: arc.cx, cy: -arc.cy, r: arc.r, start: arc.start, end: arc.end });
      }
      continue;
    }

    if (entity === "LWPOLYLINE") {
      const points = [];
      let current = null;
      let closed = false;
      for (i += 1; i < pairs.length && pairs[i].code !== "0"; i += 1) {
        const { code, value } = pairs[i];
        if (code === "70") closed = (Math.trunc(dxfNum(value)) & 1) === 1;
        if (code === "10") {
          current = { x: dxfNum(value), y: 0, bulge: 0 };
          points.push(current);
        }
        if (code === "20" && current) {
          current.y = -dxfNum(value);
        }
        if (code === "42" && current) {
          current.bulge = dxfNum(value);
        }
      }
      i -= 1;
      if (points.length > 1) items.push({ type: "polyline", points, closed });
      continue;
    }

    if (entity === "POLYLINE") {
      const points = [];
      let closed = false;
      for (i += 1; i < pairs.length; i += 1) {
        if (pairs[i].code === "70") closed = (Math.trunc(dxfNum(pairs[i].value)) & 1) === 1;
        if (pairs[i].code === "0" && pairs[i].value.toUpperCase() === "VERTEX") {
          const pt = { x: 0, y: 0, bulge: 0 };
          for (i += 1; i < pairs.length && pairs[i].code !== "0"; i += 1) {
            const { code, value } = pairs[i];
            if (code === "10") pt.x = dxfNum(value);
            if (code === "20") pt.y = -dxfNum(value);
            if (code === "42") pt.bulge = dxfNum(value);
          }
          points.push(pt);
          i -= 1;
        }
        if (pairs[i].code === "0" && pairs[i].value.toUpperCase() === "SEQEND") break;
      }
      if (points.length > 1) items.push({ type: "polyline", points, closed });
      continue;
    }

    if (entity === "TEXT" || entity === "MTEXT") {
      const t = { text: "", x: 0, y: 0, size: 70, rot: 0 };
      for (i += 1; i < pairs.length && pairs[i].code !== "0"; i += 1) {
        const { code, value } = pairs[i];
        if (code === "1" || code === "3") t.text += cleanDxfText(value);
        if (code === "10") t.x = dxfNum(value);
        if (code === "20") t.y = -dxfNum(value);
        if (code === "40") t.size = Math.max(24, Math.abs(dxfNum(value, 70)) * 0.55);
        if (code === "50") t.rot = -dxfNum(value);
      }
      i -= 1;
      if (t.text) items.push({ type: "text", ...t });
    }
  }

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const addPoint = (x, y) => {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  };

  for (const item of items) {
    if (item.type === "line") {
      addPoint(item.x1, item.y1);
      addPoint(item.x2, item.y2);
    } else if (item.type === "polyline") {
      item.points.forEach((pt) => addPoint(pt.x, pt.y));
    } else if (item.type === "circle" || item.type === "arc") {
      addPoint(item.cx - item.r, item.cy - item.r);
      addPoint(item.cx + item.r, item.cy + item.r);
    } else if (item.type === "text") {
      addPoint(item.x, item.y);
      addPoint(item.x + item.text.length * item.size * 0.65, item.y - item.size);
    }
  }

  if (!items.length || !Number.isFinite(minX)) {
    return { items: [], viewBox: "0 0 100 100", width: 100, height: 100 };
  }

  const width = Math.max(1, maxX - minX);
  const height = Math.max(1, maxY - minY);
  const pad = Math.max(width, height) * 0.05 || 10;
  return {
    items,
    viewBox: `${minX - pad} ${minY - pad} ${width + pad * 2} ${height + pad * 2}`,
    width,
    height,
  };
}

function arcPath(item) {
  const start = (item.start * Math.PI) / 180;
  const end = (item.end * Math.PI) / 180;
  const x1 = item.cx + item.r * Math.cos(start);
  const y1 = item.cy - item.r * Math.sin(start);
  const x2 = item.cx + item.r * Math.cos(end);
  const y2 = item.cy - item.r * Math.sin(end);
  const delta = ((item.end - item.start) % 360 + 360) % 360;
  const largeArc = delta > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${item.r} ${item.r} 0 ${largeArc} 0 ${x2} ${y2}`;
}

function scaleViewBox(viewBox, factor) {
  const [x, y, w, h] = String(viewBox || "0 0 100 100").split(/\s+/).map(Number);
  const nextW = Math.max(1, w * factor);
  const nextH = Math.max(1, h * factor);
  return `${x + (w - nextW) / 2} ${y + (h - nextH) / 2} ${nextW} ${nextH}`;
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
  const [previewItem, setPreviewItem] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewViewBox, setPreviewViewBox] = useState("0 0 100 100");
  const [previewShowText, setPreviewShowText] = useState(true);
  const previewSvgRef = useRef(null);
  const previewDragRef = useRef(null);

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
  const [tempoModalTipo, setTempoModalTipo] = useState("USINANDO");
  const [tempoModalSaving, setTempoModalSaving] = useState(false);

  const [chatMsgs, setChatMsgs] = useState([]);
  const [chatText, setChatText] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);
  const chatListRef = useRef(null);
  const chatInputRef = useRef(null);
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
    setStatusMaquina(normalizeUsinagemStatusValue(s || "OCIOSA"));
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
    if (!texto || chatSending) {
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
      return;
    }

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
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
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
    if (USINAGEM_TIPOS.some((tipo) => tipo.value === novo)) {
      const bloqueio = getUsinagemTipoBloqueio(executando, novo);
      if (bloqueio) {
        alert(bloqueio);
        return;
      }
    }

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

  async function visualizarDxf(item) {
    if (!item?.id || previewLoading) return;

    try {
      setPreviewItem(item);
      setPreviewData(null);
      setPreviewLoading(true);

      const res = await http.get(`/agente/${cnc}/preview/fila/${item.id}`, {
        responseType: "text",
        transformResponse: [(data) => data],
      });

      const parsed = parseDxfPreview(res.data || "");
      setPreviewData(parsed);
      setPreviewViewBox(parsed.viewBox);
    } catch (e) {
      console.error(e);
      alert("Erro ao visualizar DXF: " + getErrMsg(e));
      setPreviewItem(null);
      setPreviewData(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  function resetPreviewView() {
    if (previewData?.viewBox) setPreviewViewBox(previewData.viewBox);
  }

  function zoomPreview(factor) {
    setPreviewViewBox((vb) => scaleViewBox(vb, factor));
  }

  function previewPointFromEvent(e) {
    const svg = previewSvgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const [x, y, w, h] = String(previewViewBox || "0 0 100 100").split(/\s+/).map(Number);
    return {
      x: x + ((e.clientX - rect.left) / Math.max(1, rect.width)) * w,
      y: y + ((e.clientY - rect.top) / Math.max(1, rect.height)) * h,
    };
  }

  function startPreviewPan(e) {
    if (!previewData?.items?.length) return;
    previewDragRef.current = {
      start: previewPointFromEvent(e),
      viewBox: previewViewBox,
    };
  }

  function movePreviewPan(e) {
    const drag = previewDragRef.current;
    if (!drag?.start) return;
    const p = previewPointFromEvent(e);
    if (!p) return;
    const [x, y, w, h] = String(drag.viewBox).split(/\s+/).map(Number);
    setPreviewViewBox(`${x + drag.start.x - p.x} ${y + drag.start.y - p.y} ${w} ${h}`);
  }

  function stopPreviewPan() {
    previewDragRef.current = null;
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

    setTempoModalTipo(getUsinagemTipoPermitido(item));
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

      const tipoBloqueio = getUsinagemTipoBloqueio(tempoModalItem, tempoModalTipo);
      if (tipoBloqueio) {
        alert(tipoBloqueio);
        return;
      }

      await salvarTempoEstimado(tempoModalItem, tempoModalMin);

      await http.post(`/fila/${cnc}/status`, {
        id: tempoModalItem.id,
        status: "USINANDO",
      });

      await http.post(`/maquinas/${cnc}/status`, {
        status: tempoModalTipo,
      });

      setStatusMaquina(tempoModalTipo);
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
    return (
      filaVisivel.find((it) =>
        ["PROGRAMANDO", "BAIXADO"].includes(String(it.status || "").toUpperCase())
      ) || null
    );
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
      return `Ja existe um arquivo programado/baixado aguardando USINANDO:\n\n${nome}\n\nColoque esse arquivo em USINANDO antes de baixar outro.`;
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
                  <option value="DETALHE CNC">DETALHE CNC</option>
                  <option value="RNC">RNC</option>
                  <option value="ABERTURA MATERIAL">ABERTURA MATERIAL</option>
                  <option value="SETUP">SETUP</option>
                  <option value="REFEIÇÃO">REFEIÇÃO</option>
                  <option value="MANUTENÇÃO">MANUTENÇÃO</option>
                  <option value="AGUAR.EMPILHADEIRA">AGUAR.EMPILHADEIRA</option>
                  <option value="REUNIÃO">REUNIÃO</option>
                  <option value="TROCA CHAPA SACRIFICIO">
                    TROCA CHAPA SACRIFICIO
                  </option>
                  <option value="OCIOSA">OCIOSA</option>
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
                    ref={chatInputRef}
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
                            onClick={() => visualizarDxf(item)}
                            disabled={previewLoading}
                            className={cn(
                              "h-10 w-10 rounded-xl bg-white border border-[rgba(47,55,125,.12)] flex items-center justify-center",
                              previewLoading
                                ? "opacity-45 cursor-wait"
                                : "hover:bg-[rgba(47,55,125,.05)]"
                            )}
                            title="Visualizar DXF"
                          >
                            <Eye size={16} className="text-[#2f377d]/85" />
                          </button>

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

      {previewItem && (
        <>
          <div
            className="fixed inset-0 z-[95] bg-black/70"
            onClick={() => {
              if (!previewLoading) {
                setPreviewItem(null);
                setPreviewData(null);
              }
            }}
          />
          <div
            className="fixed z-[100] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[94vw] h-[88vh] rounded-2xl bg-white border border-[rgba(47,55,125,.12)] shadow-[0_25px_70px_-40px_rgba(32,37,61,.30)] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-14 px-4 border-b border-[rgba(47,55,125,.10)] flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[10px] tracking-[0.22em] text-slate-500">
                  VISUALIZADOR DXF
                </div>
                <div className="text-sm font-semibold text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis">
                  {previewItem?.arquivo_nome || previewItem?.nome || `Arquivo #${previewItem?.id}`}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  className="h-9 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-xs font-semibold text-[#2f377d]"
                  onClick={() => zoomPreview(0.75)}
                  disabled={previewLoading}
                  title="Aproximar"
                >
                  +
                </button>
                <button
                  className="h-9 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-xs font-semibold text-[#2f377d]"
                  onClick={() => zoomPreview(1.25)}
                  disabled={previewLoading}
                  title="Afastar"
                >
                  -
                </button>
                <button
                  className="h-9 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-xs font-semibold text-[#2f377d]"
                  onClick={resetPreviewView}
                  disabled={previewLoading}
                  title="Enquadrar"
                >
                  Ajustar
                </button>
                <button
                  className={cn(
                    "h-9 px-3 rounded-xl border text-xs font-semibold",
                    previewShowText
                      ? "bg-[#2f377d] border-[#2f377d] text-white"
                      : "bg-white border-[rgba(47,55,125,.12)] text-[#2f377d] hover:bg-[rgba(47,55,125,.05)]"
                  )}
                  onClick={() => setPreviewShowText((x) => !x)}
                  disabled={previewLoading}
                  title="Mostrar/ocultar textos"
                >
                  Texto
                </button>
                <button
                  className="h-9 px-3 rounded-xl bg-white border border-[rgba(47,55,125,.12)] hover:bg-[rgba(47,55,125,.05)] text-sm text-[#2f377d]"
                  onClick={() => {
                    if (!previewLoading) {
                      setPreviewItem(null);
                      setPreviewData(null);
                    }
                  }}
                  disabled={previewLoading}
                  title="Fechar"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="flex-1 bg-slate-950 relative">
              {previewLoading ? (
                <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70">
                  Carregando visualizacao...
                </div>
              ) : !previewData?.items?.length ? (
                <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70 px-6 text-center">
                  Nao foi possivel montar a visualizacao deste DXF.
                </div>
              ) : (
                <svg
                  ref={previewSvgRef}
                  viewBox={previewViewBox}
                  className="w-full h-full cursor-grab active:cursor-grabbing select-none"
                  preserveAspectRatio="xMidYMid meet"
                  onMouseDown={startPreviewPan}
                  onMouseMove={movePreviewPan}
                  onMouseUp={stopPreviewPan}
                  onMouseLeave={stopPreviewPan}
                  onWheel={(e) => {
                    e.preventDefault();
                    zoomPreview(e.deltaY < 0 ? 0.85 : 1.15);
                  }}
                >
                  <rect x="-100000000" y="-100000000" width="200000000" height="200000000" fill="#020617" />
                  <g stroke="#e5e7eb" strokeWidth="1.5" fill="none" vectorEffect="non-scaling-stroke">
                    {previewData.items.map((item, idx) => {
                      if (item.type === "line") {
                        return (
                          <line
                            key={idx}
                            x1={item.x1}
                            y1={item.y1}
                            x2={item.x2}
                            y2={item.y2}
                          />
                        );
                      }
                      if (item.type === "polyline") {
                        return (
                          <path
                            key={idx}
                            d={polylinePath(item.points, item.closed)}
                            fill={item.closed ? "rgba(34,197,94,.08)" : "none"}
                            stroke="#dbeafe"
                          />
                        );
                      }
                      if (item.type === "circle") {
                        return <circle key={idx} cx={item.cx} cy={item.cy} r={item.r} stroke="#bbf7d0" />;
                      }
                      if (item.type === "arc") {
                        return <path key={idx} d={arcPath(item)} stroke="#fde68a" />;
                      }
                      if (item.type === "text" && previewShowText) {
                        return (
                          <text
                            key={idx}
                            x={item.x}
                            y={item.y}
                            fontSize={item.size}
                            fill="#f8fafc"
                            stroke="none"
                            transform={`rotate(${item.rot || 0} ${item.x} ${item.y})`}
                            style={{ userSelect: "none" }}
                          >
                            {item.text}
                          </text>
                        );
                      }
                      return null;
                    })}
                  </g>
                </svg>
              )}
            </div>

            <div className="h-10 px-4 border-t border-[rgba(47,55,125,.10)] bg-white flex items-center justify-between text-xs text-slate-500">
              <span>{previewData?.items?.length || 0} entidades renderizadas</span>
              <span>
                {previewData?.width ? `${Math.round(previewData.width)} x ${Math.round(previewData.height)}` : ""}
              </span>
            </div>
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
            className="fixed z-[100] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[92vw] max-w-md max-h-[92vh] overflow-y-auto rounded-2xl bg-white/95 border border-[rgba(47,55,125,.12)] shadow-[0_25px_70px_-40px_rgba(32,37,61,.30)] backdrop-blur p-4"
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
                  Ao confirmar, o tempo começa e o item vai para o tipo escolhido.
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
                TIPO DE USINAGEM
              </label>

              <div className="mt-2 grid grid-cols-1 gap-2">
                {USINAGEM_TIPOS.map((tipo) => {
                  const bloqueio = getUsinagemTipoBloqueio(tempoModalItem, tipo.value);
                  const active = tempoModalTipo === tipo.value;

                  return (
                    <button
                      key={tipo.value}
                      type="button"
                      onClick={() => {
                        if (bloqueio) {
                          alert(bloqueio);
                          return;
                        }
                        setTempoModalTipo(tipo.value);
                      }}
                      disabled={tempoModalSaving}
                      title={bloqueio || tipo.label}
                      className={cn(
                        "h-10 rounded-xl border px-3 text-sm font-semibold text-left transition",
                        active
                          ? "bg-emerald-600 border-emerald-600 text-white"
                          : "bg-white border-[rgba(47,55,125,.12)] text-slate-800 hover:bg-[rgba(47,55,125,.05)]",
                        bloqueio ? "opacity-45" : ""
                      )}
                    >
                      {tipo.label}
                    </button>
                  );
                })}
              </div>
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
