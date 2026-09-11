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
  const [downloadingId, setDownloadingId] = useState(null);
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

  async function download(plan) {
    setDownloadingId(plan.id);
    setError("");
    try {
      const response = await api.get(`/api/facilitador/proximos-planos/${plan.id}/download`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = url;
      link.download = plan.nome;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (requestError) {
      setError(getErrMsg(requestError));
    } finally {
      setDownloadingId(null);
    }
  }

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
              <button
                type="button"
                className="pgBtn pgBtnGhost facNextPlanDownload"
                onClick={() => download(plan)}
                disabled={downloadingId !== null}
                aria-label={`Baixar arquivo ${plan.nome}`}
              >
                {downloadingId === plan.id ? "Baixando..." : "Baixar arquivo"}
              </button>
            </article>
          ))
        )}
        {loading && plans.length === 0 && <div className="pgEmpty">Carregando próximos planos...</div>}
      </div>
    </section>
  );
}
