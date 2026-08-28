const STATUS_LIMITS_MINUTES = {
  OCIOSA: 15,
  SETUP: 45,
  REFEICAO: 60,
  "AGUAR.EMPILHADEIRA": 15,
  "FALTA DE OPERADOR": 30,
  REUNIAO: 60,
  "TROCA CHAPA SACRIFICIO": 30,
  MANUTENCAO: 120,
};

function normalizeStatus(value = "") {
  return String(value)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toUpperCase();
}

function isMachiningStatus(status) {
  return (
    status.includes("USIN") ||
    status.includes("CORT") ||
    status.includes("DETALHE CNC") ||
    status === "RNC" ||
    (status.includes("ABERTURA") && status.includes("MATERIAL"))
  );
}

export function getStatusReminder({
  status,
  statusSince,
  nowMs = Date.now(),
  remainingSeconds = null,
  hasExecutingFile = false,
}) {
  const normalized = normalizeStatus(status);
  if (!normalized || normalized === "DESLIGADA") return null;

  if (isMachiningStatus(normalized)) {
    if (hasExecutingFile && remainingSeconds === 0) {
      return {
        kind: "estimated-finished",
        status: String(status || "USINANDO"),
        message: "O tempo estimado do arquivo terminou. Confirme se a CNC continua usinando ou atualize o status.",
      };
    }
    return null;
  }

  const sinceMs = Date.parse(statusSince || "");
  if (!Number.isFinite(sinceMs)) return null;
  const elapsedSeconds = Math.max(0, Math.floor((nowMs - sinceMs) / 1000));
  const limitMinutes = STATUS_LIMITS_MINUTES[normalized] ?? 30;
  if (elapsedSeconds < limitMinutes * 60) return null;

  return {
    kind: "status-stale",
    status: String(status || "").trim(),
    elapsedSeconds,
    limitMinutes,
    message: `A CNC está em ${String(status || "este status").trim()} há ${formatReminderDuration(elapsedSeconds)}. Confirme se o status ainda está correto.`,
  };
}

export function formatReminderDuration(totalSeconds) {
  const totalMinutes = Math.max(0, Math.floor(Number(totalSeconds || 0) / 60));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes} min`;
  if (minutes === 0) return `${hours}h`;
  return `${hours}h ${minutes}min`;
}

