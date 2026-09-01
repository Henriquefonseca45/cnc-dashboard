import { useEffect, useState } from "react";
import { Clock3 } from "lucide-react";
import { http } from "./http";

const fieldClass = "h-11 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm font-bold text-slate-800";
const errorText = (error) => typeof error.response?.data?.detail === "string"
  ? error.response.data.detail : "Não foi possível salvar. Verifique a conexão e tente novamente.";

export default function MorningStatusDialog({ confirmation, operators, onConfirmed }) {
  const [status, setStatus] = useState("");
  const [operator, setOperator] = useState("");
  const [typeId, setTypeId] = useState("");
  const [types, setTypes] = useState([]);
  const [typesError, setTypesError] = useState("");
  const [retry, setRetry] = useState(0);
  const [workOrder, setWorkOrder] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [clock, setClock] = useState(Date.now);
  const openingMaintenance = status === "MANUTENÇÃO" && confirmation.status !== "MANUTENÇÃO";
  const resumingMaintenance = openingMaintenance && Boolean(confirmation.maintenanceResume);
  const selectedType = types.find((type) => String(type.id) === typeId);
  const lubrication = selectedType?.name?.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().startsWith("LUBRIFIC");
  const remaining = Math.max(0, Math.ceil((Date.parse(confirmation.deadlineAt)
    - (clock + Date.parse(confirmation.serverNow) - confirmation.receivedAt)) / 1000));

  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!openingMaintenance || resumingMaintenance) return;
    let active = true;
    http.get("/api/maintenance/types").then(({ data }) => {
      if (!active) return;
      const items = Array.isArray(data) ? data : [];
      setTypes(items);
      setTypesError(items.length ? "" : "Nenhum tipo de manutenção disponível.");
    }).catch(() => {
      if (active) setTypesError("Não foi possível carregar os tipos de manutenção.");
    });
    return () => { active = false; };
  }, [openingMaintenance, resumingMaintenance, retry]);

  async function confirm(event) {
    event.preventDefault();
    if (saving || !remaining) return;
    setSaving(true);
    setError("");
    try {
      await http.post(`/api/cncs/${confirmation.cncId}/morning-status-confirmation/confirm`, {
        confirmation_id: confirmation.id,
        status,
        ...(openingMaintenance && !resumingMaintenance ? {
          maintenance_type_id: Number(typeId),
          work_order: lubrication ? null : workOrder.trim(),
          opening_notes: notes.trim() || null,
        } : {}),
      }, { headers: { "X-User-Name": operator, "X-User-Role": "OPERADOR" } });
      await onConfirmed();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-[125] bg-black/70 backdrop-blur-sm" />
      <form
        onSubmit={confirm}
        role="dialog"
        aria-modal="true"
        aria-labelledby="morning-status-title"
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = [...event.currentTarget.querySelectorAll("select, input, textarea, button")]
            .filter((control) => !control.matches(":disabled"));
          const first = controls[0];
          const last = controls[controls.length - 1];
          if (!first) { event.preventDefault(); return; }
          if (event.shiftKey && event.target === first) { event.preventDefault(); last.focus(); }
          if (!event.shiftKey && event.target === last) { event.preventDefault(); first.focus(); }
        }}
        className="fixed z-[130] left-1/2 top-1/2 max-h-[92vh] w-[min(92vw,500px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl border-2 border-amber-400 bg-white p-6 shadow-2xl"
      >
        <div className="flex items-start gap-3">
          <Clock3 size={28} className="shrink-0 text-amber-800" />
          <div>
            <div className="text-xs font-black tracking-widest text-amber-800">INÍCIO DO TURNO · {confirmation.cncId}</div>
            <h2 id="morning-status-title" className="mt-2 text-xl font-black text-slate-800">Qual status deseja colocar?</h2>
            <p className="mt-2 text-sm text-slate-600">Selecione e confirme até 05:15. Sem resposta, a máquina ficará automaticamente como FALTA DE OPERADOR.</p>
          </div>
        </div>
        <div className="my-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-center text-amber-800">
          <div className="text-xs font-bold">Tempo para responder</div>
          <div className="text-3xl font-black tabular-nums">{String(Math.floor(remaining / 60)).padStart(2, "0")}:{String(remaining % 60).padStart(2, "0")}</div>
        </div>
        <fieldset disabled={saving || !remaining} className="grid gap-4">
          <label className="grid gap-2 text-xs font-black text-slate-600">
            Operador responsável
            <select autoFocus required value={operator} onChange={(e) => setOperator(e.target.value)} className={fieldClass}>
              <option value="">Selecione o operador</option>
              {operators.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <label className="grid gap-2 text-xs font-black text-slate-600">
            Status da máquina (atual: {confirmation.status})
            <select required value={status} onChange={(e) => { setStatus(e.target.value); setError(""); }} className={fieldClass}>
              <option value="">Selecione o status</option>
              {confirmation.statuses.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          {openingMaintenance ? (
            <>
              {resumingMaintenance ? (
                <div className="morningResumeCard rounded-xl border-2 border-violet-400 bg-violet-50 p-4 text-violet-900">
                  <div className="text-xs font-black tracking-wide">RETOMAR MANUTENÇÃO DO TURNO ANTERIOR</div>
                  <div className="mt-2 text-sm font-bold">{confirmation.maintenanceResume.type}</div>
                  <div className="mt-1 text-sm font-black">
                    {confirmation.maintenanceResume.workOrder
                      ? `Ordem de Serviço: ${confirmation.maintenanceResume.workOrder}`
                      : "Lubrificação — sem Ordem de Serviço"}
                  </div>
                  <p className="mt-2 text-xs font-semibold">O mesmo tipo e a mesma OS serão usados automaticamente.</p>
                </div>
              ) : <>
                <label className="grid gap-2 text-xs font-black text-slate-600">
                Tipo da manutenção
                <select required value={typeId} onChange={(e) => { setTypeId(e.target.value); setWorkOrder(""); }} className={fieldClass}>
                  <option value="">Selecione o tipo</option>
                  {types.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                </select>
              </label>
              {typesError ? <div role="alert" className="text-sm text-red-600">{typesError} <button type="button" className="underline" onClick={() => setRetry((value) => value + 1)}>Tentar novamente</button></div> : null}
              {!lubrication ? <label className="grid gap-2 text-xs font-black text-slate-600">
                Ordem de Serviço
                <input required value={workOrder} onChange={(e) => setWorkOrder(e.target.value)} className={fieldClass} />
              </label> : null}
              <label className="grid gap-2 text-xs font-black text-slate-600">
                Observação de abertura (opcional)
                <textarea value={notes} onChange={(e) => setNotes(e.target.value)} className={`${fieldClass} h-20 py-2`} />
              </label>
              </>}
            </>
          ) : null}
          <button type="submit" disabled={!status || !operator || (openingMaintenance && !resumingMaintenance && (!selectedType || (!lubrication && !workOrder.trim())))} className="h-12 rounded-xl bg-emerald-600 px-4 text-sm font-black text-white hover:bg-emerald-500 disabled:opacity-40">
            {saving ? "Confirmando..." : resumingMaintenance ? "Retomar manutenção" : "Confirmar status"}
          </button>
        </fieldset>
        {error ? <p role="alert" className="mt-3 text-sm text-red-600">{error}</p> : null}
        {!remaining ? <p role="status" className="mt-3 text-sm text-amber-800">Prazo encerrado. Aguardando atualização do servidor...</p> : null}
      </form>
    </>
  );
}
