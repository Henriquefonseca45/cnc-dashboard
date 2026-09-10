import { useCallback, useEffect, useState } from "react";
import { api, getErrMsg } from "./api";
import { priorityLabel } from "./planClassification";
import "./FacilitadorNextPlans.css";

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR");
}

export default function FacilitadorNextPlans() {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = useCallback(async () => {
    try {
      const response = await api.get("/api/facilitador/proximos-planos");
      setPlans(Array.isArray(response.data?.items) ? response.data.items : []);
      setUpdatedAt(new Date());
      setError("");
    } catch (requestError) {
      setError(getErrMsg(requestError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => {
      if (!document.hidden) load();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <section className="facNextPlans" aria-labelledby="fac-next-plans-title">
      <header>
        <div>
          <h2 id="fac-next-plans-title">Próximos planos</h2>
          <p>Mesma ordem dos Planos aguardando da Alimentação CNC</p>
        </div>
        <div className="facNextPlansStatus">
          {updatedAt && <small>Atualizado {updatedAt.toLocaleTimeString("pt-BR")}</small>}
          <button type="button" className="pgBtn pgBtnGhost" onClick={load} disabled={loading}>
            {loading ? "Atualizando..." : "Atualizar"}
          </button>
        </div>
      </header>

      {error && <div className="feedingError" role="alert">Erro: {error}</div>}

      <div className="facNextPlansList">
        {!loading && plans.length === 0 ? (
          <div className="pgEmpty">Nenhum plano aguardando distribuição.</div>
        ) : (
          plans.map((plan, index) => (
            <article key={plan.id} className="facNextPlanRow">
              <strong className="facNextPlanPosition">{index + 1}</strong>
              <div className="facNextPlanName" title={plan.nome}>{plan.nome}</div>
              <div className="facNextPlanFlags">
                <span className={`feedingPriority feedingPriority-${plan.priority || "normal"}`}>
                  {priorityLabel(plan.priority)}
                </span>
                <span>{plan.programado ? "🔒 Programado" : "Programado: NÃO"}</span>
              </div>
              <small title={`CNCs permitidas: ${(plan.compatible_cnc_ids || []).join(", ")}`}>
                CNCs: {(plan.compatible_cnc_ids || []).join(", ") || "Legado — classificação pendente"}
              </small>
              <time>Entrada: {formatDate(plan.criado_em)}{plan.alimentacao_pausada ? " · Pausado" : ""}</time>
            </article>
          ))
        )}
        {loading && plans.length === 0 && <div className="pgEmpty">Carregando próximos planos...</div>}
      </div>
    </section>
  );
}
