export function formatElapsed(totalSeconds) {
  const value = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const hours = String(Math.floor(value / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((value % 3600) / 60)).padStart(2, "0");
  const seconds = String(value % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function elapsedFromServer(startedAt, serverOffsetMs, clientNowMs) {
  const startedMs = Date.parse(startedAt || "");
  if (!Number.isFinite(startedMs)) return 0;
  return Math.max(0, Math.floor((clientNowMs + serverOffsetMs - startedMs) / 1000));
}

export function buildMaintenanceCards(machines, activeCalls) {
  const activeByCnc = new Map(activeCalls.map((call) => [String(call.cncId).toUpperCase(), call]));
  return machines
    .filter((machine) => /^CNC\d+$/i.test(String(machine.id || "")))
    .slice()
    .sort((a, b) => String(a.id).localeCompare(String(b.id), "pt-BR", { numeric: true }))
    .map((machine) => ({ ...machine, maintenance: activeByCnc.get(String(machine.id).toUpperCase()) || null }));
}
