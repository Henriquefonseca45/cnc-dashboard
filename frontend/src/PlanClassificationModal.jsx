import { useMemo, useState } from "react";
import "./PlanClassificationModal.css";
import { PLAN_PRIORITIES } from "./planClassification";

function initialItem(item, index) {
  return {
    key: item.key || `${item.name}-${index}`,
    name: item.name,
    file: item.file || null,
    priority: item.priority || "normal",
    compatible_cnc_ids: [...(item.compatible_cnc_ids || [])],
  };
}

export default function PlanClassificationModal({ files, machines, mode = "import", saving, error, onCancel, onConfirm }) {
  const [items, setItems] = useState(() => files.map(initialItem));
  const [bulkPriority, setBulkPriority] = useState("normal");
  const [bulkCncs, setBulkCncs] = useState([]);
  const [validation, setValidation] = useState({});
  const title = mode === "edit" ? "Editar classificação" : "Classificar planos";
  const productionMachines = useMemo(() => machines.filter((machine) => machine?.id && machine.id !== "CNC_TESTE"), [machines]);

  function updateItem(key, patch) {
    setItems((current) => current.map((item) => item.key === key ? { ...item, ...patch } : item));
    setValidation((current) => ({ ...current, [key]: "" }));
  }

  function toggleCnc(item, cncId) {
    const selected = item.compatible_cnc_ids.includes(cncId);
    updateItem(item.key, {
      compatible_cnc_ids: selected
        ? item.compatible_cnc_ids.filter((id) => id !== cncId)
        : [...item.compatible_cnc_ids, cncId],
    });
  }

  function applyAll() {
    setItems((current) => current.map((item) => ({ ...item, priority: bulkPriority, compatible_cnc_ids: [...bulkCncs] })));
    setValidation({});
  }

  function submit(event) {
    event.preventDefault();
    const invalid = {};
    for (const item of items) {
      if (!item.compatible_cnc_ids.length) invalid[item.key] = "Selecione pelo menos um CNC compatível para este plano.";
    }
    setValidation(invalid);
    if (Object.keys(invalid).length) return;
    onConfirm(items);
  }

  return (
    <div className="planClassOverlay" role="presentation">
      <form className="planClassModal" role="dialog" aria-modal="true" aria-labelledby="plan-class-title" onSubmit={submit}>
        <header className="planClassHeader">
          <div>
            <div className="planClassEyebrow">IMPORTAÇÃO CNC</div>
            <h2 id="plan-class-title">{title}</h2>
            <p>Defina a prioridade e as máquinas compatíveis antes de adicionar os planos à fila.</p>
          </div>
          <button type="button" className="planClassClose" onClick={onCancel} disabled={saving} aria-label="Fechar">×</button>
        </header>

        {mode === "import" && items.length > 1 ? (
          <section className="planClassBulk">
            <strong>Aplicar a todos</strong>
            <div className="planClassBulkControls">
              <label>Prioridade
                <select value={bulkPriority} onChange={(event) => setBulkPriority(event.target.value)}>
                  {PLAN_PRIORITIES.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
                </select>
              </label>
              <div className="planClassBulkMachines">
                <span>CNCs compatíveis</span>
                <div>{productionMachines.map((machine) => (
                  <label key={machine.id}><input type="checkbox" checked={bulkCncs.includes(machine.id)} onChange={() => setBulkCncs((current) => current.includes(machine.id) ? current.filter((id) => id !== machine.id) : [...current, machine.id])} /> {machine.id}</label>
                ))}</div>
              </div>
              <button type="button" className="pgBtn pgBtnGhost" onClick={applyAll}>Aplicar aos planos</button>
            </div>
          </section>
        ) : null}

        <div className="planClassList">
          {items.map((item) => (
            <section className={`planClassItem ${validation[item.key] ? "hasError" : ""}`} key={item.key}>
              <div className="planClassFileName" title={item.name}>{item.name}</div>
              <div className="planClassLabel">Prioridade</div>
              <div className="planClassPriorities">
                {PLAN_PRIORITIES.map((entry) => (
                  <button type="button" key={entry.value} className={`planPriority ${entry.value} ${item.priority === entry.value ? "active" : ""}`} onClick={() => updateItem(item.key, { priority: entry.value })}>{entry.label}</button>
                ))}
              </div>
              <div className="planClassLabel">Pode ser usinado em</div>
              <div className="planClassMachines">
                {productionMachines.map((machine) => (
                  <label key={machine.id} className={item.compatible_cnc_ids.includes(machine.id) ? "checked" : ""}>
                    <input type="checkbox" checked={item.compatible_cnc_ids.includes(machine.id)} onChange={() => toggleCnc(item, machine.id)} />
                    <span>{machine.nome || machine.id}</span><small>{machine.id}</small>
                  </label>
                ))}
              </div>
              {validation[item.key] ? <p className="planClassError">{validation[item.key]}</p> : null}
            </section>
          ))}
        </div>

        {error ? <div className="planClassServerError" role="alert">{error}</div> : null}
        <footer className="planClassActions">
          <button type="button" className="pgBtn pgBtnGhost" onClick={onCancel} disabled={saving}>Cancelar</button>
          <button type="submit" className="pgBtn pgBtnPrimary" disabled={saving || !productionMachines.length}>{saving ? "Salvando..." : mode === "edit" ? "Salvar classificação" : "Importar planos"}</button>
        </footer>
      </form>
    </div>
  );
}
