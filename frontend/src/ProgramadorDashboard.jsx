import React, { useEffect, useMemo, useRef, useState } from "react";
import { api, getErrMsg, API_URL } from "./api";
import "./ProgramadorDashboard.css";
import rvbLogo from "./assets/rvb-logo.png";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
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

function isFilaVivaStatus(status) {
  return ["AGUARDANDO", "PROGRAMANDO", "BAIXADO"].includes(U(status));
}

function isFilaExecutandoStatus(status) {
  return U(status) === "EM_EXECUCAO";
}

function isNearScrollBottom(el, gap = 80) {
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= gap;
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

function fmtHHMMSS(totalSec) {
  const s = Math.max(0, Math.floor(Number(totalSec) || 0));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
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
        if (code === "20" && current) current.y = -dxfNum(value);
        if (code === "42" && current) current.bulge = dxfNum(value);
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
      const t = { text: "", x: 0, y: 0, size: 120, rot: 0 };
      for (i += 1; i < pairs.length && pairs[i].code !== "0"; i += 1) {
        const { code, value } = pairs[i];
        if (code === "1" || code === "3") t.text += cleanDxfText(value);
        if (code === "10") t.x = dxfNum(value);
        if (code === "20") t.y = -dxfNum(value);
        if (code === "40") t.size = Math.max(40, Math.abs(dxfNum(value, 120)));
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

function getNowDateSafe(ms) {
  try {
    return new Date(ms || Date.now());
  } catch {
    return new Date();
  }
}

function getTurnoInfo(dateLike) {
  const d = dateLike instanceof Date ? dateLike : new Date(dateLike || Date.now());
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const cur = `${hh}:${mm}`;

  if (cur >= "05:00" && cur < "14:18") {
    return { nome: "1º Turno", inicio: "05:00", fim: "14:18" };
  }
  if (cur >= "14:18" && cur < "23:24") {
    return { nome: "2º Turno", inicio: "14:18", fim: "23:24" };
  }
  return { nome: "Fora de Turno", inicio: "-", fim: "-" };
}

function fmtMinHuman(min) {
  const m = Math.max(0, Math.floor(Number(min) || 0));
  if (m >= 60) {
    const h = Math.floor(m / 60);
    const r = m % 60;
    return r ? `${h}h ${r}min` : `${h}h`;
  }
  return `${m} min`;
}

function fmtHoursHuman(min) {
  const h = Number(min || 0) / 60;
  return `${h.toFixed(1)}h`;
}

function pct(n, d) {
  if (!d) return 0;
  return Number(((n / d) * 100).toFixed(1));
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

function buildEspessuraSummary(items = [], getText) {
  const map = new Map();

  for (const item of items || []) {
    const label = extractEspessuraLabel(getText(item));
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

function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180.0;
  return {
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  };
}

function describeArc(cx, cy, rOuter, rInner, startAngle, endAngle) {
  const outerStart = polarToCartesian(cx, cy, rOuter, endAngle);
  const outerEnd = polarToCartesian(cx, cy, rOuter, startAngle);
  const innerStart = polarToCartesian(cx, cy, rInner, startAngle);
  const innerEnd = polarToCartesian(cx, cy, rInner, endAngle);

  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";

  return [
    `M ${outerStart.x} ${outerStart.y}`,
    `A ${rOuter} ${rOuter} 0 ${largeArcFlag} 0 ${outerEnd.x} ${outerEnd.y}`,
    `L ${innerStart.x} ${innerStart.y}`,
    `A ${rInner} ${rInner} 0 ${largeArcFlag} 1 ${innerEnd.x} ${innerEnd.y}`,
    "Z",
  ].join(" ");
}

const MINUTOS_DIA_MAQUINA = 17 * 60;
const THEME_STORAGE_KEY = "programador_dashboard_theme";
const TEST_MACHINE_IDS = new Set(["CNC_TESTE"]);

function isTestMachineId(id) {
  return TEST_MACHINE_IDS.has(String(id || "").toUpperCase());
}

function isProductionMachine(machine) {
  return machine?.id && !isTestMachineId(machine.id);
}

function dashboardBucket(status = "") {
  const s = U(status);

  if (s.includes("USIN") || s.includes("CORT")) return "usinando";
  if (s.includes("SETUP") || (s.includes("TROCA") && s.includes("SACRIFIC"))) return "setup";
  if (s.includes("MANUT")) return "manutencao";
  if ((s.includes("AGUAR") || s.includes("AGUARD")) && (s.includes("EMPILH") || s.includes("EMPILHADEIRA")))
    return "falta_material";
  if (s.includes("PROG")) return "programacao";
  if (s.includes("REUNIA") || s.includes("REUNIAO")) return "reuniao";
  if (s.includes("REFEI")) return "refeicao";
  if (s.includes("DESLIG")) return "desligada";
  if (s.includes("OCIOS")) return "ociosa";
  if (s.includes("PAR")) return "parada";
  return "outros";
}

function bucketLabel(bucket) {
  switch (bucket) {
    case "usinando":
      return "Usinando";
    case "setup":
      return "Setup";
    case "manutencao":
      return "Manutenção";
    case "falta_material":
      return "Falta material";
    case "programacao":
      return "Programação";
    case "reuniao":
      return "Reunião";
    case "refeicao":
      return "Refeição";
    case "desligada":
      return "Desligada";
    case "ociosa":
      return "Ociosa";
    case "parada":
      return "Parada";
    case "rnc":
      return "RNC";
    case "abertura_material":
      return "Abertura material";
    default:
      return "Outros";
  }
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

function calcRestanteSeg(
  tempoSeg,
  inicioIso,
  pausadoSeg,
  pausaInicioIso,
  machineStatus,
  nowMs,
  freezeNowMs
) {
  const t = Number(tempoSeg);
  if (!t || t <= 0) return null;

  const startMs = Date.parse(inicioIso || "");
  if (!startMs) return null;

  const isUsi = isUsinandoMachineStatus(machineStatus);
  const pausaStartMs = Date.parse(pausaInicioIso || "");
  let effectiveNowMs = nowMs;

  if (!isUsi) {
    if (pausaInicioIso && pausaStartMs) effectiveNowMs = pausaStartMs;
    else if (freezeNowMs) effectiveNowMs = freezeNowMs;
    else effectiveNowMs = nowMs;
  }

  const elapsed = Math.floor((effectiveNowMs - startMs) / 1000);
  const pausedAccum = Math.max(0, Number(pausadoSeg) || 0);
  const effectiveElapsed = Math.max(0, elapsed - pausedAccum);
  return Math.max(0, t - effectiveElapsed);
}

function isAguardarEmpilhadeira(status = "") {
  const s = U(status);
  const agu = s.includes("AGUAR") || s.includes("AGUARD");
  const emp = s.includes("EMPILH") || s.includes("EMPILHADEIRA");
  return agu && emp;
}

function isManutencao(status = "") {
  const s = U(status);
  return s.includes("MANUT");
}

function isUsinando(status = "") {
  const s = U(status);
  return (
    s.includes("USIN") ||
    s.includes("CORT") ||
    s.includes("DETALHE CNC") ||
    s === "RNC" ||
    (s.includes("ABERTURA") && s.includes("MATERIAL"))
  );
}

function normOperStatus(st = "") {
  const s0 = String(st || "").trim();
  const s = s0.toUpperCase();

  if (!s) return "NA FILA";
  if (s === "NA_FILA" || s === "NA FILA" || s === "AGUARDANDO") return "NA FILA";
  if (s.includes("BAIX")) return "BAIXADO";
  if (s.includes("PROG")) return "PROGRAMADO";
  if (
    s.includes("USIN") ||
    s.includes("CORT") ||
    s.includes("DETALHE CNC") ||
    s === "RNC" ||
    (s.includes("ABERTURA") && s.includes("MATERIAL"))
  ) {
    return "USINANDO";
  }
  return s0;
}

function operPillClass(st = "") {
  const s = normOperStatus(st);
  if (s === "USINANDO") return "opPill opPillGreen";
  if (s === "BAIXADO") return "opPill opPillBlue";
  if (s === "PROGRAMADO") return "opPill opPillPurple";
  return "opPill opPillGray";
}

function dashboardReasonPillClass(motivo = "") {
  const s = U(motivo);
  if (s.includes("MANUT")) return "pgDashReasonPill purple";
  if (s.includes("FALTA") || s.includes("EMPILH")) return "pgDashReasonPill red";
  if (s.includes("PAR")) return "pgDashReasonPill red";
  if (s.includes("SETUP")) return "pgDashReasonPill amber";
  if (s.includes("PROG")) return "pgDashReasonPill blue";
  return "pgDashReasonPill gray";
}

function sumUnreadMap(map = {}) {
  return Object.values(map).reduce((acc, n) => acc + (Number(n) || 0), 0);
}

function getMachinesWithUnread(map = {}) {
  return Object.entries(map)
    .filter(([, n]) => (Number(n) || 0) > 0)
    .map(([machineId]) => machineId);
}

function buildUnreadTitle(unreadMap = {}) {
  const total = sumUnreadMap(unreadMap);
  if (total <= 0) return "Painel de Produção";

  const machines = getMachinesWithUnread(unreadMap);
  const machineText =
    machines.length <= 3 ? machines.join(", ") : `${machines.slice(0, 3).join(", ")} +${machines.length - 3}`;

  return `(${total}) ${machineText} - Painel de Produção`;
}

function countDaysInclusive(startMs, endMs) {
  if (!startMs || !endMs || endMs < startMs) return 0;

  const a = new Date(startMs);
  const b = new Date(endMs);
  a.setHours(0, 0, 0, 0);
  b.setHours(0, 0, 0, 0);

  const diff = Math.round((b.getTime() - a.getTime()) / 86400000);
  return diff + 1;
}

function isoDay(dateLike) {
  try {
    const d = new Date(dateLike);
    if (Number.isNaN(d.getTime())) return "";
    return d.toISOString().slice(0, 10);
  } catch {
    return "";
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function getArquivoBloqueadoDetail(err) {
  const detail = err?.response?.data?.detail;
  if (!detail || typeof detail !== "object") return null;
  return ["ARQUIVO_JA_CORTADO", "ARQUIVO_JA_EM_FILA"].includes(detail.code) ? detail : null;
}

function mostrarAvisoArquivoBloqueado(err) {
  const detail = getArquivoBloqueadoDetail(err);
  if (!detail) return false;

  const arquivo = detail.arquivo_nome || "Arquivo";
  const maquina = detail.maquina_id || "nao identificada";
  const titulo = detail.code === "ARQUIVO_JA_EM_FILA" ? "Arquivo ja esta na fila" : "Arquivo ja cortado";
  const linhaStatus = detail.status ? `\nStatus: ${detail.status}` : "";
  const msg =
    detail.message ||
    `Arquivo '${arquivo}' nao pode ser enviado novamente para a fila.`;

  window.alert(`${titulo}\n\nArquivo: ${arquivo}\nMaquina: ${maquina}${linhaStatus}\n\n${msg}`);
  return true;
}

function buildDashboardParams(filter, histFrom, histTo, nowTick) {
  const now = new Date(nowTick || Date.now());
  const today = isoDay(now);

  if (filter === "today") {
    return { data: today, label: "Hoje" };
  }

  if (filter === "week") {
    const start = new Date(now);
    start.setDate(now.getDate() - 6);
    return {
      data_inicio: isoDay(start),
      data_fim: today,
      label: "Últimos 7 dias",
    };
  }

  if (filter === "month") {
    const start = new Date(now);
    start.setDate(now.getDate() - 29);
    return {
      data_inicio: isoDay(start),
      data_fim: today,
      label: "Últimos 30 dias",
    };
  }

  if (filter === "custom") {
    if (histFrom && histTo) {
      return {
        data_inicio: histFrom,
        data_fim: histTo,
        label: "Personalizado",
      };
    }
    if (histFrom) {
      return {
        data_inicio: histFrom,
        data_fim: histFrom,
        label: "Personalizado",
      };
    }
    if (histTo) {
      return {
        data_inicio: histTo,
        data_fim: histTo,
        label: "Personalizado",
      };
    }
  }

  return { data: today, label: "Hoje" };
}

function extractMachineReasonRows(raw, machineId) {
  if (!raw || !machineId) return [];

  const labelize = (bucket) => ({
    bucket,
    motivo: bucketLabel(bucket),
  });

  const normalizeRows = (arr) =>
    (Array.isArray(arr) ? arr : [])
      .map((item) => {
        const bucket = item?.bucket || item?.motivo || item?.reason || item?.tipo || "outros";
        const min = Number(item?.tempo_min ?? item?.min ?? item?.valor ?? 0);
        return {
          ...labelize(bucket),
          min,
        };
      })
      .filter((x) => x.min > 0);

  if (raw?.parada_por_motivo_por_maquina?.[machineId]) {
    return normalizeRows(raw.parada_por_motivo_por_maquina[machineId]);
  }

  if (raw?.paradas_por_maquina?.[machineId]) {
    return normalizeRows(raw.paradas_por_maquina[machineId]);
  }

  const perMachine = Array.isArray(raw?.per_machine)
    ? raw.per_machine.find((x) => x?.maquina === machineId)
    : null;

  if (Array.isArray(perMachine?.paradas_por_motivo)) {
    return normalizeRows(perMachine.paradas_por_motivo);
  }

  if (perMachine) {
    const fallback = [
      { bucket: "setup", min: Number(perMachine.setup_min || 0) },
      { bucket: "manutencao", min: Number(perMachine.manutencao_min || 0) },
      { bucket: "falta_material", min: Number(perMachine.falta_material_min || 0) },
      { bucket: "programacao", min: Number(perMachine.programacao_min || 0) },
      { bucket: "reuniao", min: Number(perMachine.reuniao_min || 0) },
      { bucket: "refeicao", min: Number(perMachine.refeicao_min || 0) },
      { bucket: "ociosa", min: Number(perMachine.ociosa_min || 0) },
      { bucket: "outros", min: Number(perMachine.outros_min || 0) },
    ]
      .map((item) => ({
        ...labelize(item.bucket),
        min: item.min,
      }))
      .filter((item) => item.min > 0);

    return fallback;
  }

  return [];
}

function normalizeDashboardApiData(raw, maquinas, filasById, nowTick, fallbackLabel) {
  const productionMaquinas = (Array.isArray(maquinas) ? maquinas : []).filter(isProductionMachine);
  const periodo = raw?.periodo || {};
  const parametros = raw?.parametros || {};
  const iefObj = raw?.ief || {};
  const disponibilidadeObj = raw?.disponibilidade || {};
  const setupObj = raw?.setup_medio || {};
  const totalsObj = raw?.totals || {};
  const specialTotalsObj = raw?.special_totals || {};
  const paradas = Array.isArray(raw?.parada_por_motivo) ? raw.parada_por_motivo : [];
  const perMachineApi = Array.isArray(raw?.per_machine) ? raw.per_machine : [];

  const total = Number(parametros.quantidade_maquinas || productionMaquinas.length || 0);
  const periodoDias = Number(periodo.dias || 1);
  const periodoLabel =
    fallbackLabel ||
    (periodoDias === 1 ? (periodo.data_inicio ? `Dia ${periodo.data_inicio}` : "Hoje") : `${periodoDias} dias`);

  const rankingMaquinas = perMachineApi
    .map((item) => ({
      maquina: item.maquina,
      usinandoMin: Number(item.usinando_min || 0),
      setupMin: Number(item.setup_min || 0),
      perdidoMin: Number(item.tempo_parado_min || 0),
      usoPct: Number(item.uso_pct || 0),
      performancePct: Number(item.performance_pct || 0),
      statusAtual: item.status_atual || "",
      operadorNome: item.operador_nome || "",
    }))
    .sort((a, b) => b.usinandoMin - a.usinandoMin);

  const totals = {
    usinando: Number(totalsObj.usinando?.tempo_min || 0),
    setup: Number(totalsObj.setup?.tempo_min || 0),
    manutencao: Number(totalsObj.manutencao?.tempo_min || 0),
    falta_material: Number(totalsObj.falta_material?.tempo_min || 0),
    programacao: Number(totalsObj.programacao?.tempo_min || 0),
    reuniao: Number(totalsObj.reuniao?.tempo_min || 0),
    refeicao: Number(totalsObj.refeicao?.tempo_min || 0),
    desligada: Number(totalsObj.desligada?.tempo_min || 0),
    ociosa: Number(totalsObj.ociosa?.tempo_min || 0),
    parada: Number(totalsObj.parada?.tempo_min || 0),
    outros: Number(totalsObj.outros?.tempo_min || 0),
  };

  const specialTotals = {
    rnc: Number(specialTotalsObj.rnc?.tempo_min || 0),
    abertura_material: Number(specialTotalsObj.abertura_material?.tempo_min || 0),
  };

  const filaTotal = Object.entries(filasById || {}).reduce((acc, [machineId, arr]) => {
    if (isTestMachineId(machineId)) return acc;
    const list = Array.isArray(arr) ? arr : [];
    return acc + list.filter((it) => isFilaVivaStatus(it.status)).length;
  }, 0);

  const usinandoAgora = productionMaquinas.filter((m) => isUsinando(m.status)).length;

  const producaoPorHora = Array.from({ length: 24 }).map((_, idx) => ({
    hora: `${String(idx).padStart(2, "0")}h`,
    qtd: 0,
  }));

  const paradasFiltradas = paradas
    .map((item) => ({
      bucket: item.bucket,
      motivo: bucketLabel(item.bucket),
      min: Number(item.tempo_min || 0),
    }))
    .filter((item) => item.bucket !== "desligada" && item.bucket !== "parada" && item.min > 0)
    .sort((a, b) => b.min - a.min);

  return {
    turnoAtual: getTurnoInfo(getNowDateSafe(nowTick)),
    total,
    usinandoAgora,
    filaTotal,
    ief: Number(iefObj.percentual || 0),
    disponibilidade: Number(disponibilidadeObj.percentual || 0),
    totalSetups: Number(setupObj.quantidade_setups || 0),
    setupMedioAtualMin: Number(setupObj.tempo_medio_setup_min || 0),
    capacidadePlanejadaPorMaquinaMin: Number(parametros.capacidade_por_maquina_min || MINUTOS_DIA_MAQUINA),
    capacidadePlanejadaTotalMin: Number(parametros.capacidade_total_min || 0),
    tempoUsinandoMin: Number(iefObj.tempo_usinando_min || 0),
    tempoSetupMin: Number(setupObj.tempo_total_setup_min || 0),

    tempoParadoMin:
      Number(totals.manutencao || 0) +
      Number(totals.falta_material || 0) +
      Number(totals.ociosa || 0) +
      Number(totals.reuniao || 0) +
      Number(totals.refeicao || 0) +
      Number(totals.outros || 0),

    tempoDisponivelMin: Number(disponibilidadeObj.tempo_disponivel_min || 0),
    totals,
    specialTotals,
    paradasPorMotivo: paradasFiltradas,
    rankingMaquinas,
    producaoPorHora,
    maxHora: 1,
    producaoNoPeriodo: 0,
    periodoLabel,
    periodoDias,
    startMs: periodo.data_inicio ? Date.parse(`${periodo.data_inicio}T00:00:00`) : 0,
    endMs: periodo.data_fim ? Date.parse(`${periodo.data_fim}T23:59:59`) : 0,
    snapshotInfo: raw?._snapshot || null,
  };
}

export default function ProgramadorDashboard({ mode = "programador" }) {
  const isFacilitador = mode === "facilitador";
  const readOnly = useMemo(() => {
    const qs = new URLSearchParams(window.location.search);
    return isFacilitador || qs.get("readonly") === "1";
  }, [isFacilitador]);
  const isVisual = readOnly && !isFacilitador;
  const dashboardRef = useRef(null);
  const [exportandoPdf, setExportandoPdf] = useState(false);
  const [exportandoExcel, setExportandoExcel] = useState(false);

  const [themeMode, setThemeMode] = useState(() => {
    try {
      return localStorage.getItem(THEME_STORAGE_KEY) || "dark";
    } catch {
      return "dark";
    }
  });

  const [nowTick, setNowTick] = useState(Date.now());

  useEffect(() => {
    const t = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    } catch {}
  }, [themeMode]);

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

  const [view, setView] = useState("dashboard");
 const [visualTab, setVisualTab] = useState("almox");

  const [historicoAll, setHistoricoAll] = useState([]);
  const [histLoading, setHistLoading] = useState(false);
  const [materialHistory, setMaterialHistory] = useState([]);
  const [materialHistoryLoading, setMaterialHistoryLoading] = useState(false);
  const [rastreamentoFilas, setRastreamentoFilas] = useState([]);
  const [rastreamentoLoading, setRastreamentoLoading] = useState(false);
  const [rastreamentoSearch, setRastreamentoSearch] = useState("");
  const [histEspessuraFiltro, setHistEspessuraFiltro] = useState("");

  const [histFrom, setHistFrom] = useState("");
  const [histTo, setHistTo] = useState("");
  const [materialHistFrom, setMaterialHistFrom] = useState("");
  const [materialHistTo, setMaterialHistTo] = useState("");
  const [materialHistSearch, setMaterialHistSearch] = useState("");

  const [dashFilter, setDashFilter] = useState("today");
  const [dashboardApiRaw, setDashboardApiRaw] = useState(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardErr, setDashboardErr] = useState("");
  const [grafico3Maquina, setGrafico3Maquina] = useState("TODAS");

  const [selectedPoolIds, setSelectedPoolIds] = useState(() => new Set());
  const [selectedFilaItemIds, setSelectedFilaItemIds] = useState(() => new Set());

  const [reorderBusy, setReorderBusy] = useState(false);
  const [previewItem, setPreviewItem] = useState(null);
  const [previewMachineId, setPreviewMachineId] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [previewViewBox, setPreviewViewBox] = useState("0 0 100 100");
  const [previewShowText, setPreviewShowText] = useState(true);

  const [chatMsgs, setChatMsgs] = useState([]);
  const [chatText, setChatText] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);

  const [chatUnreadByMachine, setChatUnreadByMachine] = useState({});
  const [chatLastMessageByMachine, setChatLastMessageByMachine] = useState({});
  const [materialRequestsByMachine, setMaterialRequestsByMachine] = useState({});

  const freezeMsByMachineRef = useRef({});
  const chatListRef = useRef(null);
  const chatInputRef = useRef(null);
  const chatShouldScrollRef = useRef(true);
  const chatForceScrollRef = useRef(true);
  const audioCtxRef = useRef(null);
  const chatNotifyBootstrappedRef = useRef(false);
  const chatSeenByMachineRef = useRef({});
  const chatLastNotifiedByMachineRef = useRef({});
  const previewSvgRef = useRef(null);
  const previewDragRef = useRef(null);
  const viewRef = useRef("dashboard");
  const selectedIdRef = useRef(selectedId);
  const includeDoneRef = useRef(includeDone);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    includeDoneRef.current = includeDone;
  }, [includeDone]);

  const totalChatUnread = useMemo(() => sumUnreadMap(chatUnreadByMachine), [chatUnreadByMachine]);
  const unreadMachines = useMemo(() => getMachinesWithUnread(chatUnreadByMachine), [chatUnreadByMachine]);

  const chatMachineTabs = useMemo(() => {
    const fallback = ["CNC01", "CNC02", "CNC03", "CNC04", "CNC05", "CNC06", "CNC07"];
    const idsFromApi = (maquinas || []).map((m) => m.id).filter(Boolean);
    const ids = idsFromApi.length > 0 ? idsFromApi : fallback;

    return ids.map((id) => {
      const maq = (maquinas || []).find((m) => m.id === id);
      return {
        id,
        nome: maq?.nome || id,
        operador_nome: maq?.operador_nome || "-",
        status: maq?.status || "",
        unread: Number(chatUnreadByMachine[id] || 0),
        lastMsg: chatLastMessageByMachine[id] || null,
      };
    });
  }, [maquinas, chatUnreadByMachine, chatLastMessageByMachine]);

  function toggleThemeMode() {
    setThemeMode((prev) => (prev === "dark" ? "light" : "dark"));
  }

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

  function playChatNotification() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;

      if (!audioCtxRef.current) {
        audioCtxRef.current = new Ctx();
      }

      const ctx = audioCtxRef.current;
      if (ctx.state === "suspended") {
        ctx.resume().catch(() => {});
      }

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);

      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.05, ctx.currentTime + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.22);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start();
      osc.stop(ctx.currentTime + 0.24);
    } catch {}
  }

  function showBrowserChatNotification(machineId, mensagem) {
    try {
      if (typeof window === "undefined" || !("Notification" in window)) return;
      if (Notification.permission !== "granted") return;

      const titulo = `${machineId} enviou uma mensagem`;
      const body = mensagem ? String(mensagem).slice(0, 140) : "Nova mensagem do operador.";

      const n = new Notification(titulo, {
        body,
        tag: `chat-${machineId}`,
      });

      n.onclick = () => {
        try {
          window.focus();
          setSelectedId(machineId);
          setView("chat");
        } catch {}
        n.close();
      };

      setTimeout(() => {
        try {
          n.close();
        } catch {}
      }, 7000);
    } catch {}
  }

  async function ensureNotificationPermission() {
    try {
      if (typeof window === "undefined" || !("Notification" in window)) return;
      if (Notification.permission === "default") {
        await Notification.requestPermission();
      }
    } catch {}
  }

  function getNewestOperatorMsgId(messages) {
    const operMsgs = (messages || []).filter((m) => U(m.autor) === "OPERADOR");
    if (operMsgs.length === 0) return 0;
    return Math.max(...operMsgs.map((m) => Number(m.id) || 0));
  }

  function getNewestOperatorMsg(messages) {
    const operMsgs = (messages || []).filter((m) => U(m.autor) === "OPERADOR");
    if (operMsgs.length === 0) return null;
    return operMsgs.reduce((acc, cur) => ((Number(cur.id) || 0) > (Number(acc?.id) || 0) ? cur : acc), operMsgs[0]);
  }

  function markMachineChatAsRead(machineId, messages = null) {
    if (!machineId) return;

    const baseMessages = Array.isArray(messages) ? messages : machineId === selectedId ? chatMsgs : [];
    const newestOperId = getNewestOperatorMsgId(baseMessages);

    chatSeenByMachineRef.current[machineId] = newestOperId;
    chatLastNotifiedByMachineRef.current[machineId] = newestOperId;

    setChatUnreadByMachine((prev) => ({
      ...prev,
      [machineId]: 0,
    }));
  }

  async function fetchMaquinas() {
    const r = await api.get("/maquinas");
    const data = r.data || [];
    setMaquinas(data);

    const currentSelectedId = selectedIdRef.current;
    if (data.length > 0 && !data.find((m) => m.id === currentSelectedId)) {
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
async function exportarHistoricoExcel() {
  if (exportandoExcel) return;

  try {
    setExportandoExcel(true);
    setErr("");

    const search = new URLSearchParams();
    if (histFrom) search.set("data_inicio", histFrom);
    if (histTo) search.set("data_fim", histTo);
    search.set("somente_cortados", "true");

    const res = await api.get(`/historico/exportar/excel?${search.toString()}`, {
      responseType: "blob",
    });

    let filename = "historico_corte.xlsx";
    const cd =
      res.headers?.["content-disposition"] ||
      res.headers?.["Content-Disposition"];

    if (cd) {
      const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(cd);
      if (m?.[1]) filename = decodeURIComponent(m[1]);
    }

    const blob = new Blob([res.data], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    setErr(getErrMsg(e));
    alert(`Erro ao exportar Excel: ${getErrMsg(e)}`);
  } finally {
    setExportandoExcel(false);
  }
}

async function exportarPDF() {
  if (!dashboardRef.current || exportandoPdf) return;

  try {
    setExportandoPdf(true);
    setErr("");
    document.body.classList.add("pdf-mode");

    const element = dashboardRef.current;

    const canvas = await html2canvas(element, {
      scale: 2,
      useCORS: true,
      backgroundColor: "#ffffff",
      windowWidth: element.scrollWidth,
      windowHeight: element.scrollHeight,
      scrollX: 0,
      scrollY: 0,

      onclone: (clonedDoc) => {
        // aplica modo de exportação
        clonedDoc.body.classList.add("pdf-export-mode");

        // remove imagens decorativas / fundo / marca d'água
        clonedDoc.querySelectorAll(".pgWatermark, .pgBgLogo, .pgDashboardWatermark").forEach((el) => {
          el.remove();
        });

        // remove background-image inline que possa quebrar o html2canvas
        clonedDoc.querySelectorAll("*").forEach((el) => {
          const style = clonedDoc.defaultView?.getComputedStyle(el);
          if (!style) return;

          const bg = style.backgroundImage || "";
          if (bg && bg !== "none") {
            // mantém só se realmente precisar; decorativo vira none
            el.style.backgroundImage = "none";
          }
        });

        // evita SVG/canvas zerado quebrando a renderização
        clonedDoc.querySelectorAll("canvas").forEach((el) => {
          if (!el.width || !el.height) {
            el.style.display = "none";
          }
        });

        clonedDoc.querySelectorAll("svg").forEach((el) => {
          const w = el.getAttribute("width");
          const h = el.getAttribute("height");
          const rect = el.getBoundingClientRect();

          if ((!w || !h) && (rect.width <= 0 || rect.height <= 0)) {
            el.style.display = "none";
          }
        });
      },

      ignoreElements: (el) => {
        if (!el) return false;

        if (el.classList?.contains("pgWatermark")) return true;
        if (el.classList?.contains("pgBgLogo")) return true;
        if (el.classList?.contains("pgDashboardWatermark")) return true;

        return false;
      },
    });

    const imgData = canvas.toDataURL("image/png");
    const pdf = new jsPDF("l", "mm", "a4");

    const pageWidth = 297;
    const pageHeight = 210;

    const imgWidth = pageWidth;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;

    let heightLeft = imgHeight;
    let position = 0;

    pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
    heightLeft -= pageHeight;

    while (heightLeft > 0) {
      position = heightLeft - imgHeight;
      pdf.addPage();
      pdf.addImage(imgData, "PNG", 0, position, imgWidth, imgHeight);
      heightLeft -= pageHeight;
    }

    pdf.save("dashboard_producao.pdf");
  } catch (e) {
    console.error(e);
    setErr(getErrMsg(e));
    alert("Erro ao gerar PDF");
  } finally {
    document.body.classList.remove("pdf-mode");
    document.body.classList.remove("pdf-export-mode");
    setExportandoPdf(false);
  }
}

  async function baixarArquivoPool(arquivo) {
    try {
      const res = await api.get(`/arquivos/${arquivo.id}/download`, {
        responseType: "blob",
      });

      let filename = arquivo.arquivo_nome || arquivo.nome || `arquivo_${arquivo.id}.dxf`;
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
    } catch (e) {
      setErr(getErrMsg(e));
      alert(`Erro ao baixar arquivo da fila geral: ${getErrMsg(e)}`);
    }
  }

 async function baixarArquivoHistorico(item) {
  try {
    const res = await api.get(`/historico/item/${item.id}/download`, {
      responseType: "blob",
    });

    let filename = item.arquivo_nome || item.nome || `arquivo_${item.id}.dxf`;
    const cd =
      res.headers?.["content-disposition"] ||
      res.headers?.["Content-Disposition"];

    if (cd) {
      const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i.exec(cd);
      if (m?.[1]) filename = decodeURIComponent(m[1]);
    }

    const blob = new Blob([res.data], {
      type: "application/dxf",
    });

    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    setErr(getErrMsg(e));
    alert(`Erro ao baixar arquivo do histórico: ${getErrMsg(e)}`);
  }
}

  async function visualizarDxfFila(item, maquinaId = selectedId) {
    if (!item?.id || !maquinaId || previewLoading) return;

    try {
      setPreviewItem(item);
      setPreviewMachineId(maquinaId);
      setPreviewData(null);
      setPreviewLoading(true);

      const res = await api.get(`/agente/${maquinaId}/preview/fila/${item.id}`, {
        responseType: "text",
        transformResponse: [(data) => data],
      });

      const parsed = parseDxfPreview(res.data || "");
      setPreviewData(parsed);
      setPreviewViewBox(parsed.viewBox);
    } catch (e) {
      setErr(getErrMsg(e));
      alert(`Erro ao visualizar DXF: ${getErrMsg(e)}`);
      setPreviewItem(null);
      setPreviewMachineId("");
      setPreviewData(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  function fecharPreviewDxf() {
    if (previewLoading) return;
    setPreviewItem(null);
    setPreviewMachineId("");
    setPreviewData(null);
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

  async function fetchPool() {
    const r = await api.get("/arquivos/disponiveis");
    setPool(r.data || []);
  }

  async function fetchHistoricoAll() {
    setHistLoading(true);
    setErr("");
    try {
      const ids = (maquinas || []).filter(isProductionMachine).map((m) => m.id);
      if (ids.length === 0) {
        setHistoricoAll([]);
        return;
      }

      const parts = await Promise.all(
        ids.map(async (mid) => {
          try {
            const r = await api.get(`/historico/${mid}`);
            const arr = r.data || [];
           return arr.map((x) => ({ ...x, _maquina_id: mid }));
          } catch {
            return [];
          }
        })
      );

      const merged = parts.flat();
      merged.sort((a, b) => {
        const ta = Date.parse(a.finalizado_em || a.criado_em || "") || 0;
        const tb = Date.parse(b.finalizado_em || b.criado_em || "") || 0;
        return tb - ta;
      });

      setHistoricoAll(merged);
    } catch (e) {
      setErr(getErrMsg(e));
      setHistoricoAll([]);
    } finally {
      setHistLoading(false);
    }
  }

  async function fetchMaterialHistory() {
    setMaterialHistoryLoading(true);
    setErr("");

    try {
      const r = await api.get("/almoxarifado/solicitacoes?status=TODAS&limit=500");
      const data = Array.isArray(r.data) ? r.data : [];
      setMaterialHistory(data);
    } catch (e) {
      setErr(getErrMsg(e));
      setMaterialHistory([]);
    } finally {
      setMaterialHistoryLoading(false);
    }
  }

  async function fetchRastreamentoFilas() {
    setRastreamentoLoading(true);
    setErr("");

    try {
      const r = await api.get("/rastreamento/filas?limit=500");
      const data = Array.isArray(r.data) ? r.data : [];
      setRastreamentoFilas(data);
    } catch (e) {
      setErr(getErrMsg(e));
      setRastreamentoFilas([]);
    } finally {
      setRastreamentoLoading(false);
    }
  }

  async function fetchDashboardAnalytics({ silent = false } = {}) {
    if (!silent) setDashboardLoading(true);
    setDashboardErr("");

    try {
      const params = buildDashboardParams(dashFilter, histFrom, histTo, nowTick);
      const search = new URLSearchParams();

      if (params.data) search.set("data", params.data);
      if (params.data_inicio) search.set("data_inicio", params.data_inicio);
      if (params.data_fim) search.set("data_fim", params.data_fim);
      search.set("usar_snapshot", "false");

      const r = await api.get(`/dashboard/indicadores?${search.toString()}`);
      setDashboardApiRaw(r.data || null);
      return r.data || null;
    } catch (e) {
      setDashboardErr(getErrMsg(e));
      setDashboardApiRaw(null);
      return null;
    } finally {
      if (!silent) setDashboardLoading(false);
    }
  }

  async function fetchChat(maquinaId = selectedId, silent = false) {
    if (!maquinaId) return [];
    if (!silent) setChatLoading(true);

    try {
      const r = await api.get(`/chat/${maquinaId}`);
      const data = Array.isArray(r.data) ? [...r.data].reverse() : [];
      const el = chatListRef.current;
      chatShouldScrollRef.current = chatForceScrollRef.current || !el || isNearScrollBottom(el);
      chatForceScrollRef.current = false;
      setChatMsgs(data);
      return data;
    } catch (e) {
      if (!silent) setErr(getErrMsg(e));
      setChatMsgs([]);
      return [];
    } finally {
      if (!silent) setChatLoading(false);
    }
  }

  async function fetchChatNotifications({ bootstrap = false } = {}) {
    if (readOnly) return;

    const ids = (maquinas || []).map((m) => m.id).filter(Boolean);
    if (ids.length === 0) return;

    const unreadMapNext = {};
    const lastMsgMapNext = {};
    let shouldPlaySound = false;

    for (const machineId of ids) {
      try {
        const r = await api.get(`/chat/${machineId}`);
        const data = Array.isArray(r.data) ? [...r.data].reverse() : [];

        const operMsgs = data.filter((m) => U(m.autor) === "OPERADOR");
        const newestOperId = getNewestOperatorMsgId(data);
        const newestOperMsg = getNewestOperatorMsg(data);

        lastMsgMapNext[machineId] = newestOperMsg || null;

        const isCurrentOpenChat = viewRef.current === "chat" && selectedId === machineId;

        const hasSeen = chatSeenByMachineRef.current[machineId] != null;
        const hasNotified = chatLastNotifiedByMachineRef.current[machineId] != null;

        if (bootstrap || !hasSeen || !hasNotified) {
          chatSeenByMachineRef.current[machineId] = newestOperId;
          chatLastNotifiedByMachineRef.current[machineId] = newestOperId;
        }

        if (isCurrentOpenChat) {
          chatSeenByMachineRef.current[machineId] = newestOperId;
          chatLastNotifiedByMachineRef.current[machineId] = newestOperId;
          unreadMapNext[machineId] = 0;
        } else {
          const seenId = Number(chatSeenByMachineRef.current[machineId] || 0);
          const lastNotifiedId = Number(chatLastNotifiedByMachineRef.current[machineId] || 0);

          unreadMapNext[machineId] = operMsgs.filter((m) => (Number(m.id) || 0) > seenId).length;

          if (newestOperId > lastNotifiedId) {
            if (newestOperMsg) {
              showBrowserChatNotification(machineId, newestOperMsg.mensagem);
              shouldPlaySound = true;
            }
            chatLastNotifiedByMachineRef.current[machineId] = newestOperId;
          }
        }
      } catch {
        unreadMapNext[machineId] = Number(chatUnreadByMachine[machineId] || 0);
        lastMsgMapNext[machineId] = chatLastMessageByMachine[machineId] || null;
      }
    }

    setChatUnreadByMachine(unreadMapNext);
    setChatLastMessageByMachine(lastMsgMapNext);

    if (shouldPlaySound) {
      playChatNotification();
    }
  }

  async function fetchMaterialRequests(ids = []) {
    if (!readOnly || ids.length === 0) return;

    try {
      const r = await api.get("/almoxarifado/solicitacoes?status=TODAS&limit=300");
      const data = Array.isArray(r.data) ? r.data : [];
      const next = {};

      for (const machineId of ids) {
        next[machineId] = data
          .filter((req) => String(req.maquina_id || "").toUpperCase() === machineId)
          .slice(0, 3)
          .map((req) => ({
            id: req.id,
            material: req.material || "material nao informado",
            arquivo: req.arquivo_nome || "arquivo nao informado",
            status: req.status || "ABERTA",
            criado_em: req.criado_em,
            atendido_em: req.atendido_em,
          }));
      }

      setMaterialRequestsByMachine(next);
    } catch {
      const next = {};
      for (const machineId of ids) {
        next[machineId] = materialRequestsByMachine[machineId] || [];
      }
      setMaterialRequestsByMachine(next);
    }
  }

  async function sendChat() {
    const texto = String(chatText || "").trim();
    if (!texto || chatSending) {
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
      return;
    }

    setChatSending(true);
    setErr("");
    setMsg("");

    try {
      await api.post("/chat", {
        maquina_id: selectedId,
        autor: "PROGRAMADOR",
        mensagem: texto,
      });

      setChatText("");
      setMsg(`Mensagem enviada para ${selectedId}.`);
      chatForceScrollRef.current = true;
      const data = await fetchChat(selectedId, true);
      markMachineChatAsRead(selectedId, data);
    } catch (e) {
      setErr(getErrMsg(e));
    } finally {
      setChatSending(false);
      window.setTimeout(() => chatInputRef.current?.focus(), 0);
    }
  }

  async function openChatMachine(machineId) {
    if (!machineId) return;

    setSelectedId(machineId);
    setView("chat");

    const data = await fetchChat(machineId);
    markMachineChatAsRead(machineId, data);
  }

  async function reloadAll() {
    setErr("");
    setMsg("");
    setLoading(true);

    try {
      const list = await fetchMaquinas();
      const ids2 = (list || []).map((m) => m.id);

      if (ids2.length > 0) {
        const currentSelectedId = selectedIdRef.current;
        const currentIncludeDone = includeDoneRef.current;
        const all = await fetchAllFilas(ids2, currentIncludeDone);
        const sid = (list || []).find((m) => m.id === currentSelectedId) ? currentSelectedId : ids2[0] || currentSelectedId;
        setFila(all[sid] || []);

        if (isVisual) {
          await fetchMaterialRequests(ids2);
        }
      } else {
        setFilasById({});
        setFila([]);
        setMaterialRequestsByMachine({});
      }

      if (!readOnly) {
        await fetchPool();
      } else {
        setPool([]);
      }

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

    if (isVisual) {
      fetchHistoricoAll().catch(() => {});
    }

    const intervalMs = isFacilitador ? 60 * 1000 : readOnly ? 10 * 1000 : 5 * 60 * 1000;
    const t = setInterval(() => {
      reloadAll();
      if (isVisual) {
        fetchHistoricoAll().catch(() => {});
      }
    }, intervalMs);

    return () => clearInterval(t);
  }, [readOnly, isVisual, isFacilitador]);

  useEffect(() => {
    if (readOnly) return;
    ensureNotificationPermission();
  }, [readOnly]);

  useEffect(() => {
    const cached = filasById[selectedId];
    if (cached && Array.isArray(cached)) {
      setFila(cached);
      clearFilaSelection();
      return;
    }

    fetchFila(selectedId, includeDone)
      .then((f) => {
        setFila(f);
        setFilasById((prev) => ({ ...prev, [selectedId]: f }));
        clearFilaSelection();
      })
      .catch((e) => setErr(getErrMsg(e)));
  }, [selectedId, includeDone]);

  useEffect(() => {
    if (readOnly) return;
    if ((maquinas || []).length === 0) return;

    let cancelled = false;

    (async () => {
      const bootstrap = !chatNotifyBootstrappedRef.current;
      await fetchChatNotifications({ bootstrap });
      if (!cancelled) {
        chatNotifyBootstrappedRef.current = true;
      }
    })();

    const t = setInterval(() => {
      fetchChatNotifications({ bootstrap: false });
    }, 5000);

    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [readOnly, maquinas.length, selectedId, view]);

  useEffect(() => {
    if (readOnly) return;
    if (view !== "chat") return;
    if (!selectedId) return;

    chatForceScrollRef.current = true;
    const t = setInterval(() => {
      fetchChat(selectedId, true).then((data) => {
        markMachineChatAsRead(selectedId, data);
      });
    }, 3000);

    return () => clearInterval(t);
  }, [readOnly, view, selectedId]);

  useEffect(() => {
    if (readOnly) return;
    if (view !== "chat") return;

    chatForceScrollRef.current = true;
    fetchChat(selectedId, false).then((data) => {
      markMachineChatAsRead(selectedId, data);
    });
  }, [view, selectedId]);

  useEffect(() => {
    const el = chatListRef.current;
    if (!el) return;
    if (!chatShouldScrollRef.current) return;
    el.scrollTop = el.scrollHeight;
    chatShouldScrollRef.current = false;
  }, [chatMsgs]);

  useEffect(() => {
    document.title = buildUnreadTitle(chatUnreadByMachine);
    return () => {
      document.title = "Painel de Produção";
    };
  }, [chatUnreadByMachine]);

  useEffect(() => {
    if (!isVisual || visualTab !== "dashboard") return;
    fetchDashboardAnalytics();
  }, [isVisual, visualTab, dashFilter, histFrom, histTo]);

  useEffect(() => {
    if (!isVisual || visualTab !== "dashboard") return;
    const t = setInterval(() => {
      fetchDashboardAnalytics({ silent: true });
    }, 10000);
    return () => clearInterval(t);
  }, [isVisual, visualTab, dashFilter, histFrom, histTo]);

  const kpis = useMemo(() => {
    const list = Array.isArray(maquinas) ? maquinas.filter(isProductionMachine) : [];
    const total = list.length;

    let cortando = 0;
    let paradaProgramada = 0;
    let paradaNaoProgramada = 0;

    for (const m of list) {
      const s = U(m?.status);

      if (s.includes("DESLIG")) {
        continue;
      }

      if (s.includes("USIN") || s.includes("CORT")) {
        cortando++;
        continue;
      }

      if (
        s.includes("SETUP") ||
        s.includes("REUNIA") ||
        s.includes("REUNIAO") ||
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

    const maquinasConsideradas = Math.max(1, cortando + paradaProgramada + paradaNaoProgramada);
    const eficiencia = maquinasConsideradas > 0 ? Math.round((cortando / maquinasConsideradas) * 100) : 0;

    return { total, cortando, paradaProgramada, paradaNaoProgramada, eficiencia };
  }, [maquinas]);

  const paradaNaoProgramadaList = useMemo(() => {
    const list = Array.isArray(maquinas) ? maquinas.filter(isProductionMachine) : [];
    return list.filter((m) => {
      const s = U(m?.status);
      return s.includes("MANUT") || (s.includes("AGUAR") && s.includes("EMPILH")) || s.includes("OCIOS");
    });
  }, [maquinas]);

  const selectedMachine = useMemo(() => {
    return maquinas.find((m) => m.id === selectedId) || { id: selectedId, nome: selectedId, status: "", operador_nome: "" };
  }, [maquinas, selectedId]);

  const emExecucao = useMemo(() => {
    return (fila || []).find((it) => isFilaExecutandoStatus(it.status)) || null;
  }, [fila]);

  const filaVisivel = useMemo(() => {
    return (fila || [])
      .filter((it) => isFilaVivaStatus(it.status))
      .slice()
      .sort((a, b) => (a.posicao ?? 0) - (b.posicao ?? 0));
  }, [fila]);

  async function exportarListaFilaParaImpressao() {
    const machineList = Array.isArray(maquinas) ? maquinas.filter((m) => m?.id) : [];
    const machineIds = machineList.map((m) => m.id);

    if (machineIds.length === 0) {
      alert("Nao ha maquinas cadastradas para imprimir.");
      return;
    }

    let filasAtualizadas = filasById;
    try {
      filasAtualizadas = await fetchAllFilas(machineIds, false);
    } catch {
      filasAtualizadas = filasById || {};
    }

    const machineById = Object.fromEntries(machineList.map((m) => [m.id, m]));
    const itens = machineIds.flatMap((machineId) => {
      const machine = machineById[machineId] || { id: machineId, nome: machineId, status: "", operador_nome: "" };
      return (Array.isArray(filasAtualizadas?.[machineId]) ? filasAtualizadas[machineId] : [])
        .filter((it) => isFilaExecutandoStatus(it.status) || isFilaVivaStatus(it.status))
        .map((it) => ({
          ...it,
          machineId,
          machineNome: machine.nome || machineId,
          machineStatus: machine.status || "-",
          operadorNome: machine.operador_nome || "-",
        }));
    });

    itens.sort((a, b) => {
      const machineOrder = machineIds.indexOf(a.machineId) - machineIds.indexOf(b.machineId);
      if (machineOrder !== 0) return machineOrder;
      const aAtual = isFilaExecutandoStatus(a.status) ? -1 : 0;
      const bAtual = isFilaExecutandoStatus(b.status) ? -1 : 0;
      if (aAtual !== bAtual) return aAtual - bAtual;
      return (a.posicao ?? 999999) - (b.posicao ?? 999999);
    });

    if (itens.length === 0) {
      alert("Nao ha arquivos nas maquinas para imprimir.");
      return;
    }

    const emitidoEm = new Date().toLocaleString("pt-BR");
    const totalsByMachine = machineIds
      .map((id) => `${id}: ${itens.filter((it) => it.machineId === id).length}`)
      .join(" | ");
    const rows = itens
      .map((it, idx) => {
        const status = U(it.status) || "-";
        const ordem = isFilaExecutandoStatus(it.status) ? "Atual" : String(it.posicao ?? idx + 1);
        const nome = it.arquivo_nome || `arquivo_id: ${it.arquivo_id || "-"}`;
        const machineLabel = `${it.machineId}${it.machineNome && it.machineNome !== it.machineId ? ` - ${it.machineNome}` : ""}`;
        return `
          <tr data-row-id="${escapeHtml(it.id ?? idx)}" data-machine="${escapeHtml(it.machineId)}">
            <td>${escapeHtml(machineLabel)}</td>
            <td>${escapeHtml(ordem)}</td>
            <td>${escapeHtml(nome)}</td>
            <td>${escapeHtml(status)}</td>
            <td>${escapeHtml(it.operadorNome)}</td>
            <td>${escapeHtml(it.id ?? "-")}</td>
            <td>${escapeHtml(it.arquivo_id ?? "-")}</td>
            <td>${escapeHtml(fmtDate(it.criado_em))}</td>
          </tr>`;
      })
      .join("");

    const html = `<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <title>Lista geral de arquivos das maquinas</title>
  <style>
    * { box-sizing: border-box; }
    :root {
      --font-size: 14px;
      --row-padding: 11px;
      --col-machine: 80px;
      --col-order: 71px;
      --col-file: 185px;
      --col-status: 101px;
      --col-operator: 129px;
      --col-item: 74px;
      --col-file-id: 74px;
      --col-date: 150px;
    }
    body { margin: 32px; color: #111827; font-family: Arial, Helvetica, sans-serif; }
    header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #111827; padding-bottom: 16px; margin-bottom: 18px; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    .meta { color: #374151; font-size: 13px; line-height: 1.55; }
    .summary { text-align: right; font-size: 13px; color: #374151; line-height: 1.55; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: var(--font-size); }
    col.col-machine { width: var(--col-machine); }
    col.col-order { width: var(--col-order); }
    col.col-file { width: var(--col-file); }
    col.col-status { width: var(--col-status); }
    col.col-operator { width: var(--col-operator); }
    col.col-item { width: var(--col-item); }
    col.col-file-id { width: var(--col-file-id); }
    col.col-date { width: var(--col-date); }
    th, td {
      border: 1px solid #d1d5db;
      padding: var(--row-padding) 8px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    th { background: #f3f4f6; color: #111827; font-size: 11px; text-transform: uppercase; }
    td:nth-child(2), th:nth-child(2), td:nth-child(6), th:nth-child(6), td:nth-child(7), th:nth-child(7) { text-align: center; }
    .machine-hidden, .removed-row { display: none; }
    body.hide-col-1 .col-machine, body.hide-col-1 th:nth-child(1), body.hide-col-1 td:nth-child(1),
    body.hide-col-2 .col-order, body.hide-col-2 th:nth-child(2), body.hide-col-2 td:nth-child(2),
    body.hide-col-3 .col-file, body.hide-col-3 th:nth-child(3), body.hide-col-3 td:nth-child(3),
    body.hide-col-4 .col-status, body.hide-col-4 th:nth-child(4), body.hide-col-4 td:nth-child(4),
    body.hide-col-5 .col-operator, body.hide-col-5 th:nth-child(5), body.hide-col-5 td:nth-child(5),
    body.hide-col-6 .col-item, body.hide-col-6 th:nth-child(6), body.hide-col-6 td:nth-child(6),
    body.hide-col-7 .col-file-id, body.hide-col-7 th:nth-child(7), body.hide-col-7 td:nth-child(7),
    body.hide-col-8 .col-date, body.hide-col-8 th:nth-child(8), body.hide-col-8 td:nth-child(8) {
      display: none;
    }
    footer { margin-top: 18px; color: #6b7280; font-size: 11px; }
    @media print {
      body { margin: 12mm; }
      tr { break-inside: avoid; }
    }
  </style>
</head>
<body class="hide-col-2 hide-col-5 hide-col-6 hide-col-7 hide-col-8">
  <header>
    <div>
      <h1>Lista geral de arquivos das maquinas</h1>
      <div class="meta">
        Maquinas: <strong>${escapeHtml(machineIds.join(", "))}</strong><br />
        Arquivos por maquina: <strong>${escapeHtml(totalsByMachine)}</strong>
      </div>
    </div>
    <div class="summary">
      Emitido em: <strong>${escapeHtml(emitidoEm)}</strong><br />
      Total de arquivos: <strong>${itens.length}</strong><br />
      Inclui arquivos atuais e filas abertas.
    </div>
  </header>

  <table>
    <colgroup>
      <col class="col-machine" />
      <col class="col-order" />
      <col class="col-file" />
      <col class="col-status" />
      <col class="col-operator" />
      <col class="col-item" />
      <col class="col-file-id" />
      <col class="col-date" />
    </colgroup>
    <thead>
      <tr>
        <th>Maquina</th>
        <th>Ordem</th>
        <th>Arquivo</th>
        <th>Status</th>
        <th>Operador</th>
        <th>Item</th>
        <th>Arquivo ID</th>
        <th>Entrada</th>
      </tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>

  <footer>Gerado pelo painel CNC.</footer>
  <script>
    (function () {
      window.focus();
      setTimeout(function () { window.print(); }, 150);
    })();
  </script>
</body>
</html>`;

    const printWindow = window.open("", "_blank", "width=1100,height=800");
    if (!printWindow) {
      alert("O navegador bloqueou a janela de impressao. Libere pop-ups e tente novamente.");
      return;
    }
    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
  }

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

        setMsg(`Upload OK: "${arquivo.arquivo_nome || file.name}" entrou na fila geral.`);
      }

      await fetchPool();
      setLastUpdate(new Date().toISOString());
    } catch (e) {
      const msgErro = getErrMsg(e);
      setErr(msgErro);
      mostrarAvisoArquivoBloqueado(e);
    } finally {
      setUploading(false);
    }
  }

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
      setErr(`Falha ao salvar a reordenação. Detalhe: ${getErrMsg(e)}`);
      try {
        const fresh = await fetchFila(selectedId, includeDone);
        setFila(fresh);
        setFilasById((prev) => ({ ...prev, [selectedId]: fresh }));
      } catch {}
    } finally {
      setReorderBusy(false);
    }
  }

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
      const msgErro = getErrMsg(e2);
      setErr(msgErro);
      mostrarAvisoArquivoBloqueado(e2);
    } finally {
      setDraggingId(null);
    }
  }

  function cardData(maquinaId) {
    const filaM = filasById[maquinaId] || [];
    const exec = filaM.find((it) => isFilaExecutandoStatus(it.status)) || null;
    const aguard = filaM
      .filter((it) => isFilaVivaStatus(it.status))
      .slice()
      .sort((a, b) => (a.posicao ?? 0) - (b.posicao ?? 0));

    return {
      execNome: exec?.arquivo_nome || null,
      execTempoSeg: exec?.tempo_estimado_seg ?? null,
      execInicio: exec?.tempo_inicio_em ?? null,
      execPausadoSeg: exec?.tempo_pausado_seg ?? 0,
      execPausaInicio: exec?.tempo_pausa_inicio_em ?? null,
      filaCount: aguard.length,
      next3: aguard.slice(0, 3),
    };
  }

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

  function toStartOfDayIso(d) {
    if (!d) return null;
    return `${d}T00:00:00`;
  }

  function toEndOfDayIso(d) {
    if (!d) return null;
    return `${d}T23:59:59`;
  }

  const historicoFiltrado = useMemo(() => {
    const fromIso = toStartOfDayIso(histFrom);
    const toIso = toEndOfDayIso(histTo);

    const fromTs = fromIso ? Date.parse(fromIso) : null;
    const toTs = toIso ? Date.parse(toIso) : null;

    return (historicoAll || []).filter((h) => {
      const base = h.started_em || h.finalizado_em || h.criado_em;
      const t = Date.parse(base || "");
      if (!t) return false;

      if (fromTs != null && t < fromTs) return false;
      if (toTs != null && t > toTs) return false;
      return true;
    });
  }, [historicoAll, histFrom, histTo]);

  const materialHistoryFiltered = useMemo(() => {
    const fromIso = toStartOfDayIso(materialHistFrom);
    const toIso = toEndOfDayIso(materialHistTo);
    const fromTs = fromIso ? Date.parse(fromIso) : null;
    const toTs = toIso ? Date.parse(toIso) : null;
    const q = U(materialHistSearch).trim();

    return (materialHistory || []).filter((req) => {
      const base = req.criado_em || req.atendido_em;
      const t = Date.parse(base || "");
      if (fromTs != null && (!t || t < fromTs)) return false;
      if (toTs != null && (!t || t > toTs)) return false;

      if (!q) return true;

      const haystack = U(
        [
          req.maquina_id,
          req.material,
          req.arquivo_nome,
          req.status,
          req.item_id,
        ]
          .filter(Boolean)
          .join(" ")
      );

      return haystack.includes(q);
    });
  }, [materialHistory, materialHistFrom, materialHistTo, materialHistSearch]);

  const rastreamentoFiltrado = useMemo(() => {
    const q = U(rastreamentoSearch).trim();
    if (!q) return rastreamentoFilas || [];

    return (rastreamentoFilas || []).filter((mov) => {
      const haystack = U(
        [
          mov.criado_em,
          mov.acao,
          mov.arquivo_nome,
          mov.arquivo_id,
          mov.fila_item_id,
          mov.maquina_origem,
          mov.maquina_destino,
          mov.status_origem,
          mov.status_destino,
          mov.detalhe,
        ]
          .filter(Boolean)
          .join(" ")
      );
      return haystack.includes(q);
    });
  }, [rastreamentoFilas, rastreamentoSearch]);

  const corteEspessuraSummary = useMemo(() => {
    return buildEspessuraSummary(historicoFiltrado, (item) => item.arquivo_nome || "");
  }, [historicoFiltrado]);

  const historicoPorEspessura = useMemo(() => {
    if (!histEspessuraFiltro) return historicoFiltrado;
    return historicoFiltrado.filter((item) => extractEspessuraLabel(item.arquivo_nome || "") === histEspessuraFiltro);
  }, [historicoFiltrado, histEspessuraFiltro]);

  const materialEspessuraSummary = useMemo(() => {
    return buildEspessuraSummary(
      materialHistoryFiltered,
      (item) => `${item.material || ""} ${item.arquivo_nome || ""}`
    );
  }, [materialHistoryFiltered]);

  const dashboardRequestInfo = useMemo(() => {
    const params = buildDashboardParams(dashFilter, histFrom, histTo, nowTick);
    const startMs = params.data
      ? Date.parse(`${params.data}T00:00:00`)
      : params.data_inicio
      ? Date.parse(`${params.data_inicio}T00:00:00`)
      : 0;
    const endMs = params.data
      ? Date.parse(`${params.data}T23:59:59`)
      : params.data_fim
      ? Date.parse(`${params.data_fim}T23:59:59`)
      : startMs;

    return {
      ...params,
      startMs,
      endMs,
      days: Math.max(1, countDaysInclusive(startMs, endMs)),
    };
  }, [dashFilter, histFrom, histTo, nowTick]);

  const dashboardData = useMemo(() => {
    return normalizeDashboardApiData(
      dashboardApiRaw,
      maquinas,
      filasById,
      nowTick,
      dashboardRequestInfo.label
    );
  }, [dashboardApiRaw, maquinas, filasById, nowTick, dashboardRequestInfo]);

  const grafico3MachineOptions = useMemo(() => {
    const ids = (dashboardData?.rankingMaquinas || [])
      .map((x) => x.maquina)
      .filter(Boolean);
    return ["TODAS", ...ids];
  }, [dashboardData]);

  const grafico3Data = useMemo(() => {
    if (!dashboardData) return [];

const limparLista = (lista) =>
  (lista || [])
    .filter(
      (item) =>
        item.bucket !== "desligada" &&
        item.bucket !== "parada" &&
        item.bucket !== "outros" &&
        item.min > 0
    )
    .sort((a, b) => b.min - a.min);

    if (grafico3Maquina === "TODAS") {
      return limparLista(dashboardData.paradasPorMotivo || []);
    }

    const rows = extractMachineReasonRows(dashboardApiRaw, grafico3Maquina);
    return limparLista(rows);
  }, [dashboardData, dashboardApiRaw, grafico3Maquina]);

  const grafico4Data = useMemo(() => {
    const capacidadeMaquinaMin = Number(dashboardData?.capacidadePlanejadaPorMaquinaMin || 0);

    return (dashboardData?.rankingMaquinas || [])
      .map((item) => {
        const eficienciaPct =
          capacidadeMaquinaMin > 0
            ? Number(((Number(item.usinandoMin || 0) / capacidadeMaquinaMin) * 100).toFixed(1))
            : 0;

        return {
          ...item,
          eficienciaPct,
        };
      })
      .sort((a, b) => b.eficienciaPct - a.eficienciaPct);
  }, [dashboardData]);

  const grafico6Data = useMemo(() => {
    const order = [
      "usinando",
      "setup",
      "manutencao",
      "falta_material",
      "programacao",
      "reuniao",
      "refeicao",
      "ociosa",
      "rnc",
      "abertura_material",
    ];

    const colorByBucket = {
      usinando: "#22c55e",
      setup: "#f59e0b",
      manutencao: "#8b5cf6",
      falta_material: "#ef4444",
      programacao: "#3b82f6",
      reuniao: "#06b6d4",
      refeicao: "#eab308",
      ociosa: "#f97316",
      rnc: "#7c3aed",
      abertura_material: "#0f766e",
      parada: "#dc2626",
      outros: "#94a3b8",
    };

    const baseRows = order
      .map((bucket) => {
        const rncMin = Number(dashboardData?.specialTotals?.rnc || 0);
        const aberturaMin = Number(dashboardData?.specialTotals?.abertura_material || 0);
        let min = Number(dashboardData?.totals?.[bucket] || 0);

        if (bucket === "usinando") {
          min = Math.max(0, min - rncMin - aberturaMin);
        } else if (bucket === "rnc") {
          min = rncMin;
        } else if (bucket === "abertura_material") {
          min = aberturaMin;
        }

        return {
          bucket,
          label: bucketLabel(bucket),
          min,
          color: colorByBucket[bucket] || "#94a3b8",
        };
      })
      .filter((item) => item.min > 0);

    const totalMin = baseRows.reduce((acc, item) => acc + item.min, 0);

    const items =
      totalMin > 0
        ? baseRows
            .map((item) => ({
              ...item,
              pct: Number(((item.min / totalMin) * 100).toFixed(1)),
            }))
            .sort((a, b) => b.min - a.min)
        : [];

    return { totalMin, items };
  }, [dashboardData]);

  const grafico7Data = useMemo(() => {
    const items = [
      {
        bucket: "rnc",
        label: "RNC",
        min: Number(dashboardData?.specialTotals?.rnc || 0),
        color: "#7c3aed",
      },
      {
        bucket: "abertura_material",
        label: "Abertura material",
        min: Number(dashboardData?.specialTotals?.abertura_material || 0),
        color: "#0f766e",
      },
    ].filter((item) => item.min > 0);

    const totalMin = items.reduce((acc, item) => acc + item.min, 0);

    return { totalMin, items };
  }, [dashboardData]);

  return (
    <div
      className={`pgShell ${readOnly ? "pgReadOnly" : ""} ${isVisual ? "pgVisual" : ""} ${
        themeMode === "light" ? "pgThemeLight" : "pgThemeDark"
      }`}
    >
      {!readOnly && (
        <aside className="pgSidebar">
     <div className="pgBrand">
  <img
    src={rvbLogo}
    alt="RVB"
    className="pgBrandLogo"
  />
  <div>
    <div className="pgBrandTitle">CNC Monitor</div>
    <div className="pgBrandSub">Painel de Produção</div>
  </div>
</div>

          <nav className="pgNav">
            <button className={`pgNavItem ${view === "dashboard" ? "pgNavActive" : ""}`} onClick={() => setView("dashboard")}>
              <span className="pgNavDot" />
              Dashboard
            </button>

            <button
              className={`pgNavItem ${view === "historico" ? "pgNavActive" : ""}`}
              onClick={async () => {
                setView("historico");
                await fetchHistoricoAll();
              }}
            >
              <span className="pgNavDot" />
              Histórico de Corte
            </button>

            <button
              className={`pgNavItem ${view === "materialHistorico" ? "pgNavActive" : ""}`}
              onClick={async () => {
                setView("materialHistorico");
                await fetchMaterialHistory();
              }}
            >
              <span className="pgNavDot" />
              Histórico de Material
            </button>

            <button
              className={`pgNavItem ${view === "rastreamento" ? "pgNavActive" : ""}`}
              onClick={async () => {
                setView("rastreamento");
                await fetchRastreamentoFilas();
              }}
            >
              <span className="pgNavDot" />
              Rastreamento
            </button>

            <button
              className={`pgNavItem ${view === "chat" ? "pgNavActive" : ""}`}
              onClick={() => openChatMachine(selectedId)}
            >
              <span className="pgNavDot" />
              <span>Chat</span>
              {totalChatUnread > 0 && <span className="pgNavBadge">{totalChatUnread}</span>}
            </button>
          </nav>

          <div className="pgSidebarUpload">
            <div className="pgSidebarUploadTitle">Upload / Fila Geral</div>

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

            <div className="pgPoolHeader">
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div className="pgPoolTitle">Arquivos na fila geral</div>
                <div className="pgPoolCount">{pool.length}</div>
              </div>

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button
                  className="pgBtn pgBtnGhost"
                  onClick={clearPoolSelection}
                  disabled={selectedPoolIds.size === 0 || uploading || loading || reorderBusy}
                >
                  Limpar
                </button>

                <button
                  className="pgBtn pgBtnPrimary"
                  onClick={excluirSelecionadosDoPool}
                  disabled={selectedPoolIds.size === 0 || uploading || loading || reorderBusy}
                >
                  Excluir
                </button>
              </div>
            </div>

            <div className="pgPoolList poolRows">
              {pool.length === 0 ? (
                <div className="pgEmpty" style={{ padding: 10 }}>Nenhum arquivo disponível.</div>
              ) : (
                pool.slice(0, 80).map((a, idx) => {
                  const checked = selectedPoolIds.has(a.id);
                  const isDragging = draggingId === a.id;

                  return (
                    <div
                      key={a.id}
                      className={`poolRow ${checked ? "sel" : ""} ${isDragging ? "dragging" : ""}`}
                      draggable
                      onDragStart={(e) => onDragStartPoolItem(e, a)}
                      onDragEnd={onDragEndAny}
                      onClick={() => togglePoolSelection(a.id)}
                    >
                      <div className="rowPos">{idx + 1}</div>

                      <div className="rowMain">
                        <div className="rowTitle" title={a.arquivo_nome || a.nome || ""}>
                          {a.arquivo_nome || a.nome}
                        </div>
                        <div className="rowMeta" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                          <span className="pgMono">id:{a.id}</span>
                          <button
                            type="button"
                            className="pgBtn pgBtnGhost"
                            style={{ padding: "6px 10px" }}
                            onClick={(e) => {
                              e.stopPropagation();
                              baixarArquivoPool(a);
                            }}
                          >
                            Baixar
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="pgSys">
            <div className={`pgSysDot ${err ? "bad" : "ok"}`} />
            <div>
              <div className="pgSysTitle">Status do Sistema</div>
              <div className="pgSysSub">{err ? "Backend Offline" : maquinas.length === 0 ? "Sem dados" : "Online"}</div>
            </div>
          </div>
        </aside>
      )}

      <main className="pgMain">
 <div className="pgTopbar">
  <div>
    <div className="pgTitleWrap">
      {readOnly && (
        <img
          src={rvbLogo}
          alt="RVB"
          className="pgTopLogo"
        />
      )}

      <div className="pgTitle">
        Painel de Produção
        {isFacilitador && (
          <span className="pgTopChatBadge">Facilitador</span>
        )}
        {!readOnly && totalChatUnread > 0 && (
          <span className="pgTopChatBadge">
            {totalChatUnread} nova(s)
            {unreadMachines.length > 0
              ? ` • ${unreadMachines.slice(0, 3).join(", ")}${unreadMachines.length > 3 ? ` +${unreadMachines.length - 3}` : ""}`
              : ""}
          </span>
        )}
      </div>
    </div>

    {isVisual && (
      <div className="pgVisualTabs">
        <button
          className={`pgVisualTabBtn ${visualTab === "almox" ? "active" : ""}`}
          onClick={() => setVisualTab("almox")}
        >
          Almoxarifado
        </button>

        <button
          className={`pgVisualTabBtn ${visualTab === "producao" ? "active" : ""}`}
          onClick={() => setVisualTab("producao")}
        >
          Produção
        </button>

        <button
          className={`pgVisualTabBtn ${visualTab === "dashboard" ? "active" : ""}`}
          onClick={async () => {
            setVisualTab("dashboard");
            await fetchDashboardAnalytics();
          }}
        >
          Dashboard
        </button>
      </div>
    )}
  </div>

  <div className="pgTopRight">
    {!readOnly && (
      <>
        <button className="pgBtn pgBtnGhost pgThemeToggleBtn" onClick={toggleThemeMode}>
          {themeMode === "dark" ? "Tema Claro" : "Tema Escuro"}
        </button>

        {view === "historico" ? (
          <button
            className="pgBtn pgBtnPrimary"
            onClick={exportarHistoricoExcel}
            disabled={exportandoExcel || histLoading}
          >
            {exportandoExcel ? "Exportando..." : "Exportar Excel"}
          </button>
        ) : (
          <button
            className="pgBtn pgBtnPrimary"
            onClick={exportarPDF}
            disabled={exportandoPdf}
          >
            {exportandoPdf ? "Exportando..." : "Exportar PDF"}
          </button>
        )}

        <div className="pgTiny">
          API: <span className="pgMono">{API_URL}</span>
        </div>

        <div className="pgTiny">
          Atualizado:{" "}
          <span className="pgMono">
            {lastUpdate ? fmtDate(lastUpdate) : "-"}
          </span>
        </div>

        <button
          className="pgBtn pgBtnGhost"
          onClick={() => setIncludeDone((v) => !v)}
          disabled={loading || reorderBusy}
        >
          {includeDone ? "Ocultar baixados" : "Incluir baixados"}
        </button>

        <button
          className="pgBtn pgBtnPrimary"
          onClick={reloadAll}
          disabled={loading || reorderBusy}
        >
          {loading
            ? "Atualizando..."
            : reorderBusy
            ? "Salvando ordem..."
            : "Atualizar"}
        </button>
      </>
    )}
    {isFacilitador && (
      <>
        <button className="pgBtn pgBtnGhost" onClick={exportarListaFilaParaImpressao} disabled={loading}>
          Imprimir lista geral
        </button>

        <button className="pgBtn pgBtnPrimary" onClick={reloadAll} disabled={loading}>
          {loading ? "Atualizando..." : "Atualizar"}
        </button>

        <div className="pgTiny">
          Atualizado: <span className="pgMono">{lastUpdate ? fmtDate(lastUpdate) : "-"}</span>
        </div>
      </>
    )}
  </div>
</div>

        {(err || msg || dashboardErr) && (
          <div className="pgAlerts">
            {err && <div className="pgAlert pgAlertErr">Erro: {err}</div>}
            {dashboardErr && <div className="pgAlert pgAlertErr">Dashboard: {dashboardErr}</div>}
            {msg && <div className="pgAlert pgAlertOk">OK: {msg}</div>}
          </div>
        )}

        {((!readOnly && view === "dashboard") || isFacilitador) && (
          <>
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
                      <div
                        key={m.id}
                        className={`pgMaintCard ${
                          isAguardarEmpilhadeira(m.status)
                            ? "pgMaintCardEmp"
                            : isManutencao(m.status)
                            ? "pgMaintCardMan"
                            : isUsinando(m.status)
                            ? "pgMaintCardUsi"
                            : "pgMaintCardDefault"
                        }`}
                      >
                        <div className="pgMaintCardTop">
                          <div className="pgMaintCardId">{m.id}</div>
                          <div className={`pgTone ${badgeTone(m.status)}`}>{m.status}</div>
                        </div>
                        <div className="pgMaintCardName">{m.nome || "-"}</div>
                        <div className="pgTiny">
                          operador: <span className="pgMono">{m.operador_nome || "-"}</span>
                        </div>
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
              <div
                className="pgPanel pgQueuePanel"
                onDragOver={(e) => {
                  if (readOnly) return;
                  e.preventDefault();
                  e.stopPropagation();
                }}
                onDrop={readOnly ? undefined : (e) => handleDropOnMachine(e, selectedId)}
              >
                <div className="pgPanelHeader">
                  <div>
                    <div className="pgPanelTitle">Fila da CNC</div>
                    <div className="pgTiny">
                      Operador: <span className="pgMono">{selectedMachine?.operador_nome || "-"}</span>
                    </div>
                  </div>

                  <div className="pgPanelHeaderRight">
                    <div className="pgQueueHeadChip">
                      <div className="pgQueueHeadId">{selectedMachine?.id || selectedId}</div>
                      <div className={`pgTone ${badgeTone(selectedMachine?.status)}`}>{selectedMachine?.status || "—"}</div>
                    </div>
                  </div>
                </div>

                <div className="pgQueueBox">
                  <div className="pgQueueBoxLabel">ARQUIVO ATUAL</div>
                  <div className="pgQueueBoxValue">{emExecucao?.arquivo_nome || "Nenhum arquivo em execução"}</div>
                </div>

                <div className="pgQueueActions">
                  {!readOnly && (
                    <button className="pgBtn pgBtnGhost" onClick={clearFilaSelection} disabled={selectedFilaItemIds.size === 0 || reorderBusy}>
                      Limpar seleção
                    </button>
                  )}

                  <button className="pgBtn pgBtnGhost" onClick={exportarListaFilaParaImpressao} disabled={loading || reorderBusy}>
                    Imprimir lista geral
                  </button>

                  {!readOnly && (
                    <button className="pgBtn pgBtnPrimary" onClick={voltarSelecionadosParaPool} disabled={selectedFilaItemIds.size === 0 || reorderBusy}>
                      Voltar p/fila
                    </button>
                  )}
                </div>

                <div className="pgQueueListWrap">
                  <div className="pgQueueListTop">
                    <div className="pgQueueListTitle">PRÓXIMOS NA FILA</div>
                    <div className="pgQueueListCount">{filaVisivel.length}</div>
                  </div>

                  {filaVisivel.length === 0 ? (
                    <div className="pgEmpty" style={{ padding: 12 }}>
                      Fila vazia. Arraste DXF do pool para adicionar.
                    </div>
                  ) : (
                    <ul className="pgQueueList">
                      {filaVisivel.map((it) => {
                        const checked = selectedFilaItemIds.has(it.id);
                        const isDragging = draggingId === it.id;

                        return (
                          <li
                            key={it.id}
                            className={`pgQueueItem ${checked ? "sel" : ""} ${isDragging ? "dragging" : ""} ${readOnly ? "viewOnly" : ""}`}
                            draggable={!readOnly}
                            onDragStart={(e) => {
                              if (readOnly) return;
                              const startedOnGrip = e.target?.closest?.(".pgQueueGrip");
                              if (startedOnGrip) return;
                              onDragStartFilaMove(e, it);
                            }}
                            onDragEnd={onDragEndAny}
                            onDragOver={(e) => {
                              if (readOnly) return;
                              const dt = getDragType(e.dataTransfer);
                              if (dt !== "FILA_REORDER") return;
                              e.preventDefault();
                              e.stopPropagation();
                            }}
                            onDrop={(e) => {
                              if (readOnly) return;
                              const dt = getDragType(e.dataTransfer);
                              if (dt !== "FILA_REORDER") return;

                              e.preventDefault();
                              e.stopPropagation();

                              const dragItemId = e.dataTransfer.getData("application/x-reorder-item-id");
                              const machineId = e.dataTransfer.getData("application/x-reorder-machine-id");
                              if (String(machineId) !== String(selectedId)) return;

                              reorderFilaLocalAndPersist(dragItemId, it.id);
                            }}
                            onClick={readOnly ? undefined : () => toggleFilaSelection(it.id)}
                          >
                            {!readOnly && (
                              <>
                                <button
                                  className="pgQueueGrip"
                                  title="Arraste aqui para reordenar"
                                  draggable
                                  onDragStart={(e) => onDragStartFilaReorderHandle(e, it)}
                                  onDragEnd={onDragEndAny}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <span className="pgGripDots" />
                                </button>

                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleFilaSelection(it.id)}
                                  onClick={(e) => e.stopPropagation()}
                                  style={bigCheckStyle}
                                />
                              </>
                            )}

                            <div className="pgQueuePos">{it.posicao}</div>

                            <div className="pgQueueName">
                              <div className="pgQueueNameText">{it.arquivo_nome || `arquivo_id: ${it.arquivo_id}`}</div>
                              <div className="pgQueueMetaLine">
                                <span className="pgMono">item:{it.id}</span>
                                <span className="pgDotSep">•</span>
                                <span className="pgMono">arquivo:{it.arquivo_id}</span>
                              </div>
                            </div>

                            <div className="pgQueueRight">
                              {readOnly && (
                                <button
                                  type="button"
                                  className="pgBtn pgBtnGhost"
                                  style={{ height: 30, padding: "0 10px", fontSize: 11 }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    visualizarDxfFila(it, selectedId);
                                  }}
                                  disabled={previewLoading}
                                  title="Visualizar DXF"
                                >
                                  Visualizar
                                </button>
                              )}
                              <span className={operPillClass(it.status)}>{normOperStatus(it.status)}</span>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>

              <div className="pgMachines">
                <div className="pgMachinesHeader">
                  <div className="pgPanelTitle">Máquinas</div>
                  <div className="pgTiny">{maquinas.length} máquinas cadastradas</div>
                </div>

                <div className="pgCards">
                  {maquinas.map((m) => {
                    const cd = cardData(m.id);

                    const emp = isAguardarEmpilhadeira(m.status);
                    const man = !emp && isManutencao(m.status);
                    const usi = !emp && !man && isUsinando(m.status);

                    const statusClass = emp ? "pgCardEmp" : man ? "pgCardMan" : usi ? "pgCardUsi" : "";

                    const isU = isUsinandoMachineStatus(m.status);
                    const freezeMap = freezeMsByMachineRef.current;

                    if (!isU) {
                      if (!freezeMap[m.id]) freezeMap[m.id] = nowTick;
                    } else {
                      if (freezeMap[m.id]) delete freezeMap[m.id];
                    }

                    const freezeNowMs = freezeMap[m.id] || null;

                    return (
                      <button
                        key={m.id}
                        className={`pgCard ${m.id === selectedId ? "active" : ""} ${statusClass}`}
                        onClick={() => setSelectedId(m.id)}
                        onDragOver={(e) => {
                          if (readOnly) return;
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                        onDrop={readOnly ? undefined : (e) => handleDropOnMachine(e, m.id)}
                        disabled={!readOnly && reorderBusy}
                      >
                        <div className="pgCardTop">
                          <div className="pgCardId">{m.id}</div>

                          <div className="pgCardTimer">
                            {(() => {
                              const rest = calcRestanteSeg(
                                cd.execTempoSeg,
                                cd.execInicio,
                                cd.execPausadoSeg,
                                cd.execPausaInicio,
                                m.status,
                                nowTick,
                                freezeNowMs
                              );
                              return rest == null ? "--:--:--" : fmtHHMMSS(rest);
                            })()}
                          </div>

                          <div className={`pgTone ${badgeTone(m.status)}`}>{m.status || "—"}</div>
                        </div>

                        <div className="pgCardName">{m.nome || "—"}</div>

                        <div className="pgCardBox">
                          <div className="pgCardBoxLabel">ARQUIVO ATUAL</div>
                          <div className="pgCardBoxValue">{cd.execNome || "Nenhum arquivo em execução"}</div>
                        </div>

                        <div className="pgCardMeta">
                          <div className="pgTiny">
                            operador: <span className="pgMono">{m.operador_nome || "-"}</span>
                          </div>
                          <div className="pgTiny">
                            desde: <span className="pgMono">{fmtDate(m.status_desde)}</span>
                          </div>
                          <div className="pgTiny">
                            FILA: <span className="pgMono">{cd.filaCount}</span>
                          </div>
                        </div>

                        <div className="pgCardHint">
                          {readOnly ? "Clique para ver a fila completa" : "Arraste do pool OU da fila e solte aqui"}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>
          </>
        )}

        {isVisual && visualTab === "producao" && (
          <>
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
                      <div
                        key={m.id}
                        className={`pgMaintCard ${
                          isAguardarEmpilhadeira(m.status)
                            ? "pgMaintCardEmp"
                            : isManutencao(m.status)
                            ? "pgMaintCardMan"
                            : isUsinando(m.status)
                            ? "pgMaintCardUsi"
                            : "pgMaintCardDefault"
                        }`}
                      >
                        <div className="pgMaintCardTop">
                          <div className="pgMaintCardId">{m.id}</div>
                          <div className={`pgTone ${badgeTone(m.status)}`}>{m.status}</div>
                        </div>
                        <div className="pgMaintCardName">{m.nome || "-"}</div>
                        <div className="pgTiny">
                          operador: <span className="pgMono">{m.operador_nome || "-"}</span>
                        </div>
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
              <div className="pgMachines">
                <div className="pgMachinesHeader">
                  <div className="pgPanelTitle">Máquinas</div>
                  <div className="pgTiny">{maquinas.length} máquinas cadastradas</div>
                </div>

                <div className="pgCards">
                  {maquinas.map((m) => {
                    const cd = cardData(m.id);

                    const emp = isAguardarEmpilhadeira(m.status);
                    const man = !emp && isManutencao(m.status);
                    const usi = !emp && !man && isUsinando(m.status);
                    const statusClass = emp ? "pgCardEmp" : man ? "pgCardMan" : usi ? "pgCardUsi" : "";

                    const isU = isUsinandoMachineStatus(m.status);
                    const freezeMap = freezeMsByMachineRef.current;

                    if (!isU) {
                      if (!freezeMap[m.id]) freezeMap[m.id] = nowTick;
                    } else {
                      if (freezeMap[m.id]) delete freezeMap[m.id];
                    }

                    const freezeNowMs = freezeMap[m.id] || null;

                    return (
                      <button
                        key={m.id}
                        className={`pgCard ${m.id === selectedId ? "active" : ""} ${statusClass}`}
                        onClick={() => setSelectedId(m.id)}
                      >
                        <div className="pgCardTop">
                          <div className="pgCardId">{m.id}</div>

                          <div className="pgCardTimer">
                            {(() => {
                              const rest = calcRestanteSeg(
                                cd.execTempoSeg,
                                cd.execInicio,
                                cd.execPausadoSeg,
                                cd.execPausaInicio,
                                m.status,
                                nowTick,
                                freezeNowMs
                              );
                              return rest == null ? "--:--:--" : fmtHHMMSS(rest);
                            })()}
                          </div>

                          <div className={`pgTone ${badgeTone(m.status)}`}>{m.status || "—"}</div>
                        </div>

                        <div className="pgCardName">{m.nome || "—"}</div>

                        <div className="pgCardBox">
                          <div className="pgCardBoxLabel">ARQUIVO ATUAL</div>
                          <div className="pgCardBoxValue">{cd.execNome || "Nenhum arquivo em execução"}</div>
                        </div>

                        <div className="pgCardQueue">
                          <div className="pgCardQueueTop">
                            <div className="pgCardQueueTitle">PRÓXIMOS NA FILA</div>
                            <div className="pgCardQueueCount">{cd.filaCount}</div>
                          </div>

                          {cd.next3.length === 0 ? (
                            <div className="pgCardQueueEmpty">Fila vazia</div>
                          ) : (
                            <ul className="pgCardQueueList">
                              {cd.next3.map((it) => (
                                <li key={it.id} className="pgCardQueueItem" title={it.arquivo_nome || ""}>
                                  <span className="pgCardQueuePos">{it.posicao}</span>
                                  <span className="pgCardQueueName">{it.arquivo_nome || `arquivo_id: ${it.arquivo_id}`}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>

                        <div className="pgCardMeta">
                          <div className="pgTiny">
                            operador: <span className="pgMono">{m.operador_nome || "-"}</span>
                          </div>
                          <div className="pgTiny">
                            desde: <span className="pgMono">{fmtDate(m.status_desde)}</span>
                          </div>
                          <div className="pgTiny">
                            FILA: <span className="pgMono">{cd.filaCount}</span>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </section>
          </>
        )}

        {isVisual && visualTab === "almox" && (
          <section className="pgVisualAlmoxOnly">
            <div className="pgMachinesHeader">
              <div className="pgPanelTitle">Almoxarifado</div>
              <div className="pgTiny">Visão das máquinas para abastecimento</div>
            </div>

            <div className="pgCards pgCardsAlmox">
              {maquinas.map((m) => {
                const cd = cardData(m.id);

                const emp = isAguardarEmpilhadeira(m.status);
                const man = !emp && isManutencao(m.status);
                const usi = !emp && !man && isUsinando(m.status);
                const statusClass = emp ? "pgCardEmp" : man ? "pgCardMan" : usi ? "pgCardUsi" : "";
                const materialRequests = materialRequestsByMachine[m.id] || [];

                const isU = isUsinandoMachineStatus(m.status);
                const freezeMap = freezeMsByMachineRef.current;

                if (!isU) {
                  if (!freezeMap[m.id]) freezeMap[m.id] = nowTick;
                } else {
                  if (freezeMap[m.id]) delete freezeMap[m.id];
                }

                const freezeNowMs = freezeMap[m.id] || null;

                return (
                  <div key={m.id} className={`pgCard ${statusClass}`}>
                    <div className="pgCardTop">
                      <div className="pgCardId">{m.id}</div>

                      <div className="pgCardTimer">
                        {(() => {
                          const rest = calcRestanteSeg(
                            cd.execTempoSeg,
                            cd.execInicio,
                            cd.execPausadoSeg,
                            cd.execPausaInicio,
                            m.status,
                            nowTick,
                            freezeNowMs
                          );
                          return rest == null ? "--:--:--" : fmtHHMMSS(rest);
                        })()}
                      </div>

                      <div className={`pgTone ${badgeTone(m.status)}`}>{m.status || "—"}</div>
                    </div>

                    <div className="pgCardName">{m.nome || "—"}</div>

                    <div className="pgCardBox">
                      <div className="pgCardBoxLabel">ARQUIVO ATUAL</div>
                      <div className="pgCardBoxValue">{cd.execNome || "Nenhum arquivo em execução"}</div>
                    </div>

                    <div className="pgCardQueue">
                      <div className="pgCardQueueTop">
                        <div className="pgCardQueueTitle">PRÓXIMOS NA FILA</div>
                        <div className="pgCardQueueCount">{cd.filaCount}</div>
                      </div>

                      {cd.next3.length === 0 ? (
                        <div className="pgCardQueueEmpty">Fila vazia</div>
                      ) : (
                        <ul className="pgCardQueueList">
                          {cd.next3.map((it) => (
                            <li key={it.id} className="pgCardQueueItem" title={it.arquivo_nome || ""}>
                              <span className="pgCardQueuePos">{it.posicao}</span>
                              <span className="pgCardQueueName">
                                {it.arquivo_nome || `arquivo_id: ${it.arquivo_id}`}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div
                      className={`pgCardMaterialRequest ${
                        materialRequests.length > 0 ? "hasRequests" : ""
                      }`}
                    >
                      <div className="pgCardMaterialTop">
                        <div className="pgCardMaterialTitle">SOLICITACOES DE MATERIAL</div>
                        <div className="pgCardMaterialCount">{materialRequests.length}</div>
                      </div>

                      {materialRequests.length === 0 ? (
                        <div className="pgCardMaterialEmpty">Sem solicitacoes</div>
                      ) : (
                        <ul className="pgCardMaterialList">
                          {materialRequests.map((req) => (
                            <li
                              key={req.id}
                              className={`pgCardMaterialItem ${
                                U(req.status) === "ENTREGUE" ? "delivered" : ""
                              }`}
                              title={req.arquivo}
                            >
                              <div className="pgCardMaterialItemTop">
                                <div className="pgCardMaterialName">{req.material}</div>
                                <div className="pgCardMaterialStatus">
                                  {U(req.status) === "ENTREGUE" ? "ENTREGUE" : "ABERTA"}
                                </div>
                              </div>
                              <div className="pgCardMaterialFile">{req.arquivo}</div>
                              <div className="pgCardMaterialDate">
                                {U(req.status) === "ENTREGUE"
                                  ? `Entregue: ${fmtDate(req.atendido_em)}`
                                  : fmtDate(req.criado_em)}
                              </div>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="pgCardMeta">
                      <div className="pgTiny">
                        operador: <span className="pgMono">{m.operador_nome || "-"}</span>
                      </div>
                      <div className="pgTiny">
                        desde: <span className="pgMono">{fmtDate(m.status_desde)}</span>
                      </div>
                      <div className="pgTiny">
                        FILA: <span className="pgMono">{cd.filaCount}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

       {isVisual && visualTab === "dashboard" && (
  <div ref={dashboardRef}>
    <section className="pgDashBoardLike">
      <section className="pgDashTopBarLike">
        <div className="pgDashTopTitle" style={{ display: "none" }} />
<div className="pgDashTopFilters">
  <button
    className={`pgDashFilter ${dashFilter === "today" ? "active" : ""}`}
    onClick={() => setDashFilter("today")}
  >
    Hoje
  </button>

  <button
    className={`pgDashFilter ${dashFilter === "week" ? "active" : ""}`}
    onClick={() => setDashFilter("week")}
  >
    Semana
  </button>

  <button
    className={`pgDashFilter ${dashFilter === "month" ? "active" : ""}`}
    onClick={() => setDashFilter("month")}
  >
    Mês
  </button>

  <button
    className={`pgDashFilter ${dashFilter === "custom" ? "active" : ""}`}
    onClick={() => setDashFilter("custom")}
  >
    Personalizado
  </button>

  <button
    className="pgBtn pgBtnGhost"
    onClick={() => fetchDashboardAnalytics()}
    style={{ marginLeft: 8 }}
  >
    {dashboardLoading ? "Atualizando..." : "Atualizar"}
  </button>

  <button
    className="pgBtn pgBtnPrimary"
    onClick={exportarPDF}
    disabled={exportandoPdf}
    style={{ marginLeft: 8 }}
  >
    {exportandoPdf ? "Exportando..." : "Exportar PDF"}
  </button>
</div>
      </section>

      {dashFilter === "custom" && (
        <section className="pgPanel" style={{ marginTop: 0 }}>
          <div className="pgPanelHeader">
            <div>
              <div className="pgPanelTitle">Período personalizado</div>
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div className="pgTiny">De</div>
                <input
                  type="date"
                  value={histFrom}
                  onChange={(e) => setHistFrom(e.target.value)}
                  className="pgInput"
                />
              </div>

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div className="pgTiny">Até</div>
                <input
                  type="date"
                  value={histTo}
                  onChange={(e) => setHistTo(e.target.value)}
                  className="pgInput"
                />
              </div>

              <button
                className="pgBtn pgBtnGhost"
                onClick={async () => {
                  const today = isoDay(new Date());

                  setHistFrom("");
                  setHistTo("");
                  setDashFilter("today");

                  setDashboardLoading(true);
                  setDashboardErr("");

                  try {
                    const search = new URLSearchParams();
                    search.set("data", today);
                    search.set("usar_snapshot", "false");

                    const r = await api.get(`/dashboard/indicadores?${search.toString()}`);
                    setDashboardApiRaw(r.data || null);
                  } catch (e) {
                    setDashboardErr(getErrMsg(e));
                    setDashboardApiRaw(null);
                  } finally {
                    setDashboardLoading(false);
                  }
                }}
              >
                Limpar
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="pgDashChartsRow">
        <div className="pgDashChartCard pgDashChartMain pgDashIefCard">
          <div className="pgDashChartTitle">
            Gráfico 1 — IEF da Fábrica ({dashboardData.periodoLabel})
          </div>

          <div className="pgDashIefTop">
            <div className="pgDashIefBig">{dashboardData.ief}%</div>
          </div>

          <div className="pgDashIefStats">
            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Qtd. de CNCs</div>
              <div className="pgDashIefStatValue">{dashboardData.total}</div>
            </div>

            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Capacidade total</div>
              <div className="pgDashIefStatValue">{fmtHoursHuman(dashboardData.capacidadePlanejadaTotalMin)}</div>
            </div>

            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Tempo usinando</div>
              <div className="pgDashIefStatValue">{fmtHoursHuman(dashboardData.tempoUsinandoMin)}</div>
            </div>

            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Tempo não usado</div>
              <div className="pgDashIefStatValue">
                {fmtHoursHuman(Math.max(0, dashboardData.capacidadePlanejadaTotalMin - dashboardData.tempoUsinandoMin))}
              </div>
            </div>
          </div>

          <div className="pgDashIefBarWrap">
            <div className="pgDashIefBarTrack">
              <div
                className="pgDashIefBarFill"
                style={{ width: `${Math.max(0, Math.min(100, dashboardData.ief))}%` }}
              />
            </div>
            <div className="pgDashIefBarLegend">
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </div>
        </div>

        <div className="pgDashChartCard pgDashChartSide">
          <div className="pgDashChartTitle">
            Gráfico 2 — Ranking por Máquina ({dashboardData.periodoLabel})
          </div>

          <div className="pgDashBarList">
            {dashboardData.rankingMaquinas.length === 0 ? (
              <div className="pgEmpty">Sem dados.</div>
            ) : (() => {
              const maxUso = Math.max(1, ...dashboardData.rankingMaquinas.map((x) => x.usinandoMin));

              return dashboardData.rankingMaquinas.map((item) => (
                <div key={item.maquina} className="pgDashBarRow">
                  <div className="pgDashBarName">{item.maquina}</div>

                  <div className="pgDashBarTrack">
                    <div
                      className="pgDashBarFill"
                      style={{ width: `${(item.usinandoMin / maxUso) * 100}%` }}
                      title={`${fmtHoursHuman(item.usinandoMin)} usinando`}
                    />
                  </div>

                  <div className="pgDashBarValueRight">
                    {fmtHoursHuman(item.usinandoMin)}
                  </div>
                </div>
              ));
            })()}
          </div>
        </div>
      </section>

      <section className="pgDashChartsRow pgDashChartsRowBottom">
        <div className="pgDashChartCard">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
              marginBottom: 10,
            }}
          >
            <div className="pgDashChartTitle" style={{ marginBottom: 0 }}>
              Gráfico 3 — Tempo Parado por Motivo ({dashboardData.periodoLabel})
            </div>

            <select
              value={grafico3Maquina}
              onChange={(e) => setGrafico3Maquina(e.target.value)}
              className="pgInput pgDashSelect"
            >
              {grafico3MachineOptions.map((maq) => (
                <option key={maq} value={maq}>
                  {maq === "TODAS" ? "Todas as máquinas" : maq}
                </option>
              ))}
            </select>
          </div>

          <div className="pgDashReasonList">
            {grafico3Data.length === 0 ? (
              <div className="pgEmpty">
                Nenhuma parada registrada
                {grafico3Maquina !== "TODAS" ? ` para ${grafico3Maquina}` : ""}.
              </div>
            ) : (() => {
              const maxParada = Math.max(1, ...grafico3Data.map((x) => x.min));

              return grafico3Data.map((item) => (
                <div key={`${grafico3Maquina}-${item.bucket}`} className="pgDashReasonRow">
                  <div className="pgDashReasonName">{item.motivo}</div>
                  <div className="pgDashReasonTrack">
                    <div
                      className="pgDashReasonFill"
                      style={{ width: `${(item.min / maxParada) * 100}%` }}
                    />
                  </div>
                  <div className="pgDashReasonValue">{fmtMinHuman(item.min)}</div>
                </div>
              ));
            })()}
          </div>
        </div>

        <div className="pgDashChartCard">
          <div className="pgDashChartTitle">
            Gráfico 4 — Eficiência por Máquina ({dashboardData.periodoLabel})
          </div>

          <div className="pgDashReasonList">
            {grafico4Data.length === 0 ? (
              <div className="pgEmpty">Sem dados.</div>
            ) : (
              grafico4Data.map((item) => (
                <div key={item.maquina} className="pgDashReasonRow">
                  <div className="pgDashReasonName">{item.maquina}</div>

                  <div className="pgDashReasonTrack">
                    <div
                      className="pgDashPerfFill"
                      style={{
                        width: `${Math.max(2, Math.min(100, Number(item.eficienciaPct || 0)))}%`,
                        background: "linear-gradient(90deg, #22c55e, #16a34a)",
                      }}
                      title={`${item.maquina} • ${item.eficienciaPct}%`}
                    />
                  </div>

                  <div className="pgDashReasonValue">{item.eficienciaPct}%</div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="pgDashChartsRow pgDashChartsRowBottom pgDashChartsRow56">
        <div className="pgDashChartCard pgDashChartCard5">
          <div className="pgDashChartTitle">
            Gráfico 5 — Tempo Médio de Setup ({dashboardData.periodoLabel})
          </div>

          <div className="pgDashIefTop">
            <div className="pgDashIefBig">{Number(dashboardData.setupMedioAtualMin).toFixed(1)} min</div>
          </div>

          <div className="pgDashIefStats">
            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Tempo total setup</div>
              <div className="pgDashIefStatValue">{dashboardData.tempoSetupMin} min</div>
            </div>

            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Qtd. setups</div>
              <div className="pgDashIefStatValue">{dashboardData.totalSetups}</div>
            </div>

            <div className="pgDashIefStat">
              <div className="pgDashIefStatLabel">Média</div>
              <div className="pgDashIefStatValue">{Number(dashboardData.setupMedioAtualMin).toFixed(1)} min</div>
            </div>
          </div>
        </div>

        <div className="pgDashChartCard pgDashChartCard6">
          <div className="pgDashChartTitle">
            Gráfico 6 — Percentual de Cada Status ({dashboardData.periodoLabel})
          </div>

          {grafico6Data.items.length === 0 ? (
            <div className="pgEmpty">Sem dados para montar o dashboard.</div>
          ) : (
            <div className="pgDashPieLayout">
              <div className="pgDashPieWrap">
                <div className="pgDashPieChartSvgBox">
                  <svg
                    className="pgDashPieSvg"
                    viewBox="0 0 320 320"
                    role="img"
                    aria-label="Gráfico de pizza por status"
                  >
                    {(() => {
                      const cx = 160;
                      const cy = 160;
                      const outerR = 130;
                      const innerR = 0;

                      let acc = 0;

                      return grafico6Data.items.map((item) => {
                        const startAngle = (acc / 100) * 360;
                        const endAngle = ((acc + item.pct) / 100) * 360;
                        acc += item.pct;

                        if (item.pct <= 0) return null;

                        const d = describeArc(cx, cy, outerR, innerR, startAngle, endAngle);

                        return (
                          <path
                            key={item.bucket}
                            d={d}
                            fill={item.color}
                            className="pgDashPieSlice"
                          >
                            <title>{`${item.label}: ${item.pct}%`}</title>
                          </path>
                        );
                      });
                    })()}
                  </svg>
                </div>
              </div>

              <div className="pgDashPieLegend">
                {grafico6Data.items.map((item) => (
                  <div key={item.bucket} className="pgDashPieLegendRow">
                    <div className="pgDashPieLegendLeft">
                      <span
                        className="pgDashPieLegendDot"
                        style={{ background: item.color }}
                      />
                      <span className="pgDashPieLegendLabel">{item.label}</span>
                    </div>

                    <div className="pgDashPieLegendBar">
                      <div
                        className="pgDashPieLegendFill"
                        style={{
                          width: `${Math.max(3, Math.min(100, Number(item.pct || 0)))}%`,
                          background: item.color,
                        }}
                      />
                    </div>

                    <div className="pgDashPieLegendValue">{item.pct}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="pgDashChartCard pgDashChartCard7">
          <div className="pgDashChartTitle">
            Gráfico 7 — Tempo em RNC e Abertura Material ({dashboardData.periodoLabel})
          </div>

          {grafico7Data.items.length === 0 ? (
            <div className="pgEmpty">Sem registros de RNC ou Abertura material no período.</div>
          ) : (() => {
            const maxEspecial = Math.max(1, ...grafico7Data.items.map((x) => x.min));

            return grafico7Data.items.map((item) => (
              <div key={item.bucket} className="pgDashReasonRow">
                <div className="pgDashReasonName">{item.label}</div>
                <div className="pgDashReasonTrack">
                  <div
                    className="pgDashReasonFill"
                    style={{
                      width: `${(item.min / maxEspecial) * 100}%`,
                      background: item.color,
                    }}
                  />
                </div>
                <div className="pgDashReasonValue">{fmtMinHuman(item.min)}</div>
              </div>
            ));
          })()}
        </div>
      </section>

      <section className="pgDashBottomInfo">
        <div className="pgDashInfoCard">
          <div className="pgDashInfoTitle">Capacidade do período</div>
          <div className="pgDashInfoText">
            Cada máquina = <span className="pgMono">17h / 1020 min por dia</span>
          </div>
          <div className="pgDashInfoText">
            Período = <span className="pgMono">{dashboardData.periodoDias} dia(s)</span>
          </div>
          <div className="pgDashInfoText">
            Total planejado = <span className="pgMono">{fmtMinHuman(dashboardData.capacidadePlanejadaTotalMin)}</span>
          </div>
        </div>

        <div className="pgDashInfoCard">
          <div className="pgDashInfoTitle">Disponibilidade</div>
          <div className="pgDashInfoText">
            CNCs usinando agora: <span className="pgMono">{dashboardData.usinandoAgora}/{dashboardData.total}</span>
          </div>
          <div className="pgDashInfoText">
            Fila total: <span className="pgMono">{dashboardData.filaTotal}</span>
          </div>
          <div className="pgDashInfoText">
            Turno atual: <span className="pgMono">{dashboardData.turnoAtual.nome}</span>
          </div>
          <div className="pgDashInfoText">
            Disponibilidade: <span className="pgMono">{dashboardData.disponibilidade}%</span>
          </div>
        </div>

        <div className="pgDashInfoCard">
          <div className="pgDashInfoTitle">Paradas relevantes</div>
          {(grafico3Maquina === "TODAS" ? dashboardData.paradasPorMotivo : grafico3Data).length === 0 ? (
            <div className="pgDashInfoText">Sem paradas relevantes no período.</div>
          ) : (
            (grafico3Maquina === "TODAS" ? dashboardData.paradasPorMotivo : grafico3Data)
              .slice(0, 3)
              .map((item) => (
                <div key={`${grafico3Maquina}-info-${item.bucket}`} className="pgDashInfoReason">
                  <span className={dashboardReasonPillClass(item.motivo)}>
                    {fmtMinHuman(item.min)}
                  </span>
                  <span>{item.motivo}</span>
                </div>
              ))
          )}
        </div>
      </section>
    </section>
  </div>
)}

        {!readOnly && view === "historico" && (
          <section className="pgPanel" style={{ marginTop: 14 }}>
            <div className="pgPanelHeader">
              <div>
                <div className="pgPanelTitle">Histórico de Corte (todas as CNCs)</div>
                <div className="pgTiny">Centralizado com os últimos registros finalizados.</div>
              </div>

              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <div className="pgTiny">De</div>
                  <input type="date" value={histFrom} onChange={(e) => setHistFrom(e.target.value)} className="pgInput" />
                </div>

                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <div className="pgTiny">Até</div>
                  <input type="date" value={histTo} onChange={(e) => setHistTo(e.target.value)} className="pgInput" />
                </div>

                <button
                  className="pgBtn pgBtnGhost"
                  onClick={() => {
                    setHistFrom("");
                    setHistTo("");
                    setHistEspessuraFiltro("");
                  }}
                  disabled={histLoading || (!histFrom && !histTo && !histEspessuraFiltro)}
                >
                  Limpar
                </button>

                <button className="pgBtn pgBtnPrimary" onClick={fetchHistoricoAll} disabled={histLoading}>
                  {histLoading ? "Carregando..." : "Atualizar"}
                </button>

                <div className="pgTiny">
                  Mostrando: <span className="pgMono">{historicoPorEspessura.length}</span> / Total:{" "}
                  <span className="pgMono">{historicoAll.length}</span>
                </div>
              </div>
            </div>

            {histLoading ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Carregando histórico...</div>
            ) : historicoFiltrado.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Nenhum registro no período selecionado.</div>
            ) : (
              <div style={{ overflow: "auto" }}>
                <div className="pgEspessuraSummary">
                  <div className="pgEspessuraSummaryHeader">
                    <div className="pgEspessuraSummaryTitle">Cortes por espessura</div>
                    {histEspessuraFiltro && (
                      <button type="button" className="pgEspessuraClear" onClick={() => setHistEspessuraFiltro("")}>
                        Limpar filtro
                      </button>
                    )}
                  </div>
                  <div className="pgEspessuraSummaryGrid">
                    {corteEspessuraSummary.map((item) => (
                      <button
                        key={item.label}
                        type="button"
                        className={`pgEspessuraChip ${histEspessuraFiltro === item.label ? "active" : ""}`}
                        onClick={() => setHistEspessuraFiltro((prev) => (prev === item.label ? "" : item.label))}
                        title={`Mostrar arquivos de ${item.label}`}
                      >
                        <span>{item.label}</span>
                        <strong>{item.count}</strong>
                      </button>
                    ))}
                  </div>
                  {histEspessuraFiltro && (
                    <div className="pgTiny" style={{ marginTop: 10 }}>
                      Exibindo arquivos da espessura <span className="pgMono">{histEspessuraFiltro}</span>.
                    </div>
                  )}
                </div>

                {historicoPorEspessura.length === 0 ? (
                  <div className="pgEmpty" style={{ padding: 14 }}>Nenhum arquivo para a espessura selecionada.</div>
                ) : (
                  <>
                <table className="pgTable" style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 8px" }}>
                  <thead>
                    <tr className="pgTiny" style={{ opacity: 0.85 }}>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>CNC</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Arquivo</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Status</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Início</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Fim</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Ação</th>
                    </tr>
                  </thead>
                  <tbody>
                    {historicoPorEspessura.slice(0, 300).map((h) => (
                      <tr key={`${h._maquina_id}-${h.id}`} className="pgRow">
                        <td style={{ padding: "10px", fontWeight: 900 }}>{h._maquina_id}</td>
                        <td style={{ padding: "10px" }}>{h.arquivo_nome || "-"}</td>
                        <td style={{ padding: "10px" }}>
                          <span className={`pgTone ${badgeTone(h.status)}`}>{h.status || "-"}</span>
                        </td>
                        <td style={{ padding: "10px" }} className="pgMono">
                          {h.started_em ? fmtDate(h.started_em) : "-"}
                        </td>
                        <td style={{ padding: "10px" }} className="pgMono">
                          {h.finalizado_em ? fmtDate(h.finalizado_em) : fmtDate(h.criado_em)}
                        </td>
                        <td style={{ padding: "10px" }}>
                          <button
                            type="button"
                            className="pgBtn pgBtnGhost"
                            style={{ padding: "6px 10px" }}
                            onClick={() => baixarArquivoHistorico(h)}
                          >
                            Baixar
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div className="pgTiny" style={{ marginTop: 10, opacity: 0.9 }}>
                  Mostrando até 300 registros mais recentes.
                </div>
                  </>
                )}
              </div>
            )}
          </section>
        )}

        {!readOnly && view === "rastreamento" && (
          <section className="pgPanel" style={{ marginTop: 14 }}>
            <div className="pgPanelHeader">
              <div>
                <div className="pgPanelTitle">Rastreamento das Chapas nas Filas</div>
                <div className="pgTiny">Log das movimentacoes, downloads, status e trocas de CNC.</div>
              </div>

              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  type="text"
                  value={rastreamentoSearch}
                  onChange={(e) => setRastreamentoSearch(e.target.value)}
                  className="pgInput"
                  placeholder="Buscar arquivo, CNC, acao, status..."
                  style={{ minWidth: 260 }}
                />

                <button
                  className="pgBtn pgBtnGhost"
                  onClick={() => setRastreamentoSearch("")}
                  disabled={!rastreamentoSearch}
                >
                  Limpar
                </button>

                <button className="pgBtn pgBtnPrimary" onClick={fetchRastreamentoFilas} disabled={rastreamentoLoading}>
                  {rastreamentoLoading ? "Carregando..." : "Atualizar"}
                </button>

                <div className="pgTiny">
                  Mostrando: <span className="pgMono">{rastreamentoFiltrado.length}</span> / Total:{" "}
                  <span className="pgMono">{rastreamentoFilas.length}</span>
                </div>
              </div>
            </div>

            {rastreamentoLoading ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Carregando rastreamento...</div>
            ) : rastreamentoFilas.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Nenhuma movimentacao registrada ainda.</div>
            ) : rastreamentoFiltrado.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Nenhum movimento encontrado com esse filtro.</div>
            ) : (
              <div style={{ overflow: "auto" }}>
                <table className="pgTable" style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 8px" }}>
                  <thead>
                    <tr className="pgTiny" style={{ opacity: 0.85 }}>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Data</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Acao</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Arquivo</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Origem</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Destino</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Status</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Detalhe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rastreamentoFiltrado.slice(0, 500).map((mov) => (
                      <tr key={mov.id} className="pgRow">
                        <td style={{ padding: "10px" }} className="pgMono">{fmtDate(mov.criado_em)}</td>
                        <td style={{ padding: "10px", fontWeight: 900 }}>{mov.acao || "-"}</td>
                        <td style={{ padding: "10px" }}>
                          <div style={{ fontWeight: 800 }}>{mov.arquivo_nome || "-"}</div>
                          <div className="pgTiny">
                            item: <span className="pgMono">{mov.fila_item_id || "-"}</span> / arquivo:{" "}
                            <span className="pgMono">{mov.arquivo_id || "-"}</span>
                          </div>
                        </td>
                        <td style={{ padding: "10px" }}>
                          <span className="pgMono">{mov.maquina_origem || "-"}</span>
                          {mov.posicao_origem != null && <div className="pgTiny">pos. {mov.posicao_origem}</div>}
                        </td>
                        <td style={{ padding: "10px" }}>
                          <span className="pgMono">{mov.maquina_destino || "-"}</span>
                          {mov.posicao_destino != null && <div className="pgTiny">pos. {mov.posicao_destino}</div>}
                        </td>
                        <td style={{ padding: "10px" }}>
                          <span className="pgMono">{mov.status_origem || "-"}</span>
                          <span>{" -> "}</span>
                          <span className="pgMono">{mov.status_destino || "-"}</span>
                        </td>
                        <td style={{ padding: "10px" }}>{mov.detalhe || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {!readOnly && view === "materialHistorico" && (
          <section className="pgPanel" style={{ marginTop: 14 }}>
            <div className="pgPanelHeader">
              <div>
                <div className="pgPanelTitle">Histórico de Material Solicitado</div>
                <div className="pgTiny">Todos os materiais solicitados pelas CNCs ao almoxarifado.</div>
              </div>

              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  className="pgBtn pgBtnPrimary"
                  onClick={fetchMaterialHistory}
                  disabled={materialHistoryLoading}
                >
                  {materialHistoryLoading ? "Carregando..." : "Atualizar"}
                </button>

                <div className="pgTiny">
                  Mostrando: <span className="pgMono">{materialHistoryFiltered.length}</span> / Total:{" "}
                  <span className="pgMono">{materialHistory.length}</span>
                </div>
              </div>
            </div>

            <div className="pgMaterialHistoryFilters">
              <div className="pgMaterialFilterItem">
                <div className="pgTiny">De</div>
                <input
                  type="date"
                  value={materialHistFrom}
                  onChange={(e) => setMaterialHistFrom(e.target.value)}
                  className="pgInput"
                />
              </div>

              <div className="pgMaterialFilterItem">
                <div className="pgTiny">Até</div>
                <input
                  type="date"
                  value={materialHistTo}
                  onChange={(e) => setMaterialHistTo(e.target.value)}
                  className="pgInput"
                />
              </div>

              <div className="pgMaterialFilterSearch">
                <div className="pgTiny">Nome</div>
                <input
                  type="text"
                  value={materialHistSearch}
                  onChange={(e) => setMaterialHistSearch(e.target.value)}
                  className="pgInput"
                  placeholder="Material, arquivo ou CNC..."
                />
              </div>

              <button
                className="pgBtn pgBtnGhost"
                onClick={() => {
                  setMaterialHistFrom("");
                  setMaterialHistTo("");
                  setMaterialHistSearch("");
                }}
                disabled={!materialHistFrom && !materialHistTo && !materialHistSearch}
              >
                Limpar filtros
              </button>
            </div>

            {materialHistoryLoading ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Carregando histórico de material...</div>
            ) : materialHistory.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Nenhum material solicitado ainda.</div>
            ) : materialHistoryFiltered.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Nenhum registro encontrado com os filtros atuais.</div>
            ) : (
              <div style={{ overflow: "auto" }}>
                <div className="pgEspessuraSummary">
                  <div className="pgEspessuraSummaryTitle">Materiais solicitados por espessura</div>
                  <div className="pgEspessuraSummaryGrid">
                    {materialEspessuraSummary.map((item) => (
                      <div key={item.label} className="pgEspessuraChip">
                        <span>{item.label}</span>
                        <strong>{item.count}</strong>
                      </div>
                    ))}
                  </div>
                </div>

                <table className="pgTable" style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 8px" }}>
                  <thead>
                    <tr className="pgTiny" style={{ opacity: 0.85 }}>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>CNC</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Material</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Arquivo</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Status</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Solicitado em</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Entregue em</th>
                    </tr>
                  </thead>

                  <tbody>
                    {materialHistoryFiltered.map((req) => {
                      const entregue = U(req.status) === "ENTREGUE";

                      return (
                        <tr key={req.id} className="pgRow">
                          <td style={{ padding: "10px", fontWeight: 900 }}>{req.maquina_id || "-"}</td>
                          <td style={{ padding: "10px", fontWeight: 800 }}>{req.material || "-"}</td>
                          <td style={{ padding: "10px" }}>{req.arquivo_nome || "-"}</td>
                          <td style={{ padding: "10px" }}>
                            <span className={`pgMaterialStatusPill ${entregue ? "delivered" : "open"}`}>
                              {entregue ? "ENTREGUE" : "ABERTA"}
                            </span>
                          </td>
                          <td style={{ padding: "10px" }} className="pgMono">
                            {fmtDate(req.criado_em)}
                          </td>
                          <td style={{ padding: "10px" }} className="pgMono">
                            {req.atendido_em ? fmtDate(req.atendido_em) : "-"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <div className="pgTiny" style={{ marginTop: 10, opacity: 0.9 }}>
                  Mostrando até 500 solicitações mais recentes.
                </div>
              </div>
            )}
          </section>
        )}

        {false && !readOnly && view === "materialHistorico" && (
          <section className="pgPanel" style={{ marginTop: 14 }}>
            <div className="pgPanelHeader">
              <div>
                <div className="pgPanelTitle">Histórico de Material Solicitado</div>
                <div className="pgTiny">Todos os materiais solicitados pelas CNCs ao almoxarifado.</div>
              </div>

              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <button
                  className="pgBtn pgBtnPrimary"
                  onClick={fetchMaterialHistory}
                  disabled={materialHistoryLoading}
                >
                  {materialHistoryLoading ? "Carregando..." : "Atualizar"}
                </button>

                <div className="pgTiny">
                  Total: <span className="pgMono">{materialHistory.length}</span>
                </div>
              </div>
            </div>

            {materialHistoryLoading ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Carregando histÃ³rico de material...</div>
            ) : materialHistory.length === 0 ? (
              <div className="pgEmpty" style={{ padding: 14 }}>Nenhum material solicitado ainda.</div>
            ) : (
              <div style={{ overflow: "auto" }}>
                <table className="pgTable" style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 8px" }}>
                  <thead>
                    <tr className="pgTiny" style={{ opacity: 0.85 }}>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>CNC</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Material</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Arquivo</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Status</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Solicitado em</th>
                      <th style={{ textAlign: "left", padding: "6px 10px" }}>Entregue em</th>
                    </tr>
                  </thead>

                  <tbody>
                    {materialHistory.map((req) => {
                      const entregue = U(req.status) === "ENTREGUE";

                      return (
                        <tr key={req.id} className="pgRow">
                          <td style={{ padding: "10px", fontWeight: 900 }}>{req.maquina_id || "-"}</td>
                          <td style={{ padding: "10px", fontWeight: 800 }}>{req.material || "-"}</td>
                          <td style={{ padding: "10px" }}>{req.arquivo_nome || "-"}</td>
                          <td style={{ padding: "10px" }}>
                            <span className={`pgMaterialStatusPill ${entregue ? "delivered" : "open"}`}>
                              {entregue ? "ENTREGUE" : "ABERTA"}
                            </span>
                          </td>
                          <td style={{ padding: "10px" }} className="pgMono">
                            {fmtDate(req.criado_em)}
                          </td>
                          <td style={{ padding: "10px" }} className="pgMono">
                            {req.atendido_em ? fmtDate(req.atendido_em) : "-"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                <div className="pgTiny" style={{ marginTop: 10, opacity: 0.9 }}>
                  Mostrando atÃ© 500 solicitaÃ§Ãµes mais recentes.
                </div>
              </div>
            )}
          </section>
        )}

        {!readOnly && view === "chat" && (
          <section className="pgChatPage">
            <div className="pgChatHeaderCard">
              <div className="pgChatHeaderLeft">
                <div className="pgChatHeaderTitle">Chat Programador ↔ Operador</div>
                <div className="pgChatHeaderSub">
                  Escolha a CNC abaixo para abrir a conversa.
                </div>
              </div>

              <div className="pgChatHeaderRight">
                <button
                  className="pgBtn pgBtnPrimary"
                  onClick={async () => {
                    const data = await fetchChat(selectedId);
                    markMachineChatAsRead(selectedId, data);
                  }}
                  disabled={chatLoading || chatSending}
                >
                  {chatLoading ? "Atualizando..." : "Atualizar"}
                </button>
              </div>
            </div>

            <div className="pgChatMachinesBar">
              {chatMachineTabs.map((item) => {
                const active = item.id === selectedId;

                return (
                  <button
                    key={item.id}
                    className={`pgChatMachineTab ${active ? "active" : ""}`}
                    onClick={() => openChatMachine(item.id)}
                    title={`Abrir chat da ${item.id}`}
                  >
                    <span className="pgChatMachineTabLabel">{item.id}</span>

                    {item.unread > 0 && (
                      <span className="pgChatMachineBadge">
                        {item.unread > 99 ? "99+" : item.unread}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            <div className="pgChatHeaderCard pgChatHeaderCardInner">
              <div className="pgChatHeaderLeft">
                <div className="pgChatHeaderTitle">
                  Conversa da máquina <span className="pgMono">{selectedId}</span>
                </div>

                <div className="pgChatHeaderSub">
                  Operador: <span className="pgMono">{selectedMachine?.operador_nome || "-"}</span>
                </div>

                <div className="pgChatHeaderSub">
                  Não lidas desta CNC: <span className="pgMono">{Number(chatUnreadByMachine[selectedId] || 0)}</span>
                </div>
              </div>

              <div className="pgChatHeaderRight">
                <div className={`pgTone ${badgeTone(selectedMachine?.status)}`}>
                  {selectedMachine?.status || "—"}
                </div>
              </div>
            </div>

            <div className="pgChatPanel">
              <div ref={chatListRef} className="pgChatList">
                {chatLoading ? (
                  <div className="pgChatEmpty">
                    <div className="pgChatEmptyIcon">💬</div>
                    <div className="pgChatEmptyTitle">Carregando mensagens...</div>
                  </div>
                ) : chatMsgs.length === 0 ? (
                  <div className="pgChatEmpty">
                    <div className="pgChatEmptyIcon">💬</div>
                    <div className="pgChatEmptyTitle">Nenhuma mensagem nesta máquina</div>
                    <div className="pgChatEmptySub">
                      Envie a primeira mensagem para o operador da <span className="pgMono">{selectedId}</span>.
                    </div>
                  </div>
                ) : (
                  chatMsgs.map((m) => {
                    const mine = U(m.autor) === "PROGRAMADOR";

                    return (
                      <div key={m.id} className={`pgChatRow ${mine ? "mine" : "other"}`}>
                        <div className={`pgChatBubble ${mine ? "mine" : "other"}`}>
                          <div className="pgChatMeta">
                            <strong>{m.autor || "-"}</strong>
                            <span className="pgMono">{fmtDate(m.criado_em)}</span>
                          </div>
                          <div className="pgChatText">{m.mensagem || ""}</div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>

<div className="pgChatComposer">
  <input
    ref={chatInputRef}
    className="pgChatInput"
    type="text"
    placeholder={`Mensagem para o operador da ${selectedId}...`}
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
    className="pgChatSendBtn"
    onClick={sendChat}
    disabled={chatSending || !String(chatText || "").trim()}
  >
    {chatSending ? "Enviando..." : "Enviar"}
  </button>
            </div> {/* pgChatComposer */}
          </div>   {/* pgChatPanel */}
        </section>
      )}

      {previewItem && (
        <>
          <div className="fixed inset-0 z-[95] bg-black/70" onClick={fecharPreviewDxf} />
          <div
            className="fixed z-[100] left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[94vw] h-[88vh] rounded-2xl bg-white border border-[rgba(47,55,125,.12)] shadow-[0_25px_70px_-40px_rgba(32,37,61,.30)] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-14 px-4 border-b border-[rgba(47,55,125,.10)] flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[10px] tracking-[0.22em] text-slate-500">
                  VISUALIZADOR DXF - {previewMachineId || selectedId}
                </div>
                <div className="text-sm font-semibold text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis">
                  {previewItem?.arquivo_nome || previewItem?.nome || `Arquivo #${previewItem?.id}`}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button className="pgBtn pgBtnGhost" style={{ height: 34, padding: "0 12px" }} onClick={() => zoomPreview(0.75)} disabled={previewLoading}>+</button>
                <button className="pgBtn pgBtnGhost" style={{ height: 34, padding: "0 12px" }} onClick={() => zoomPreview(1.25)} disabled={previewLoading}>-</button>
                <button className="pgBtn pgBtnGhost" style={{ height: 34, padding: "0 12px" }} onClick={resetPreviewView} disabled={previewLoading}>Ajustar</button>
                <button
                  className={`pgBtn ${previewShowText ? "pgBtnPrimary" : "pgBtnGhost"}`}
                  style={{ height: 34, padding: "0 12px" }}
                  onClick={() => setPreviewShowText((x) => !x)}
                  disabled={previewLoading}
                >
                  Texto
                </button>
                <button className="pgBtn pgBtnGhost" style={{ height: 34, padding: "0 12px" }} onClick={fecharPreviewDxf} disabled={previewLoading}>Fechar</button>
              </div>
            </div>

            <div className="flex-1 bg-slate-950 relative">
              {previewLoading ? (
                <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70">Carregando visualizacao...</div>
              ) : !previewData?.items?.length ? (
                <div className="absolute inset-0 flex items-center justify-center text-sm text-white/70 px-6 text-center">Nao foi possivel montar a visualizacao deste DXF.</div>
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
                      if (item.type === "line") return <line key={idx} x1={item.x1} y1={item.y1} x2={item.x2} y2={item.y2} />;
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
                      if (item.type === "circle") return <circle key={idx} cx={item.cx} cy={item.cy} r={item.r} stroke="#bbf7d0" />;
                      if (item.type === "arc") return <path key={idx} d={arcPath(item)} stroke="#fde68a" />;
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
              <span>{previewData?.width ? `${Math.round(previewData.width)} x ${Math.round(previewData.height)}` : ""}</span>
            </div>
          </div>
        </>
      )}

      </main>
    </div>
  );
}
