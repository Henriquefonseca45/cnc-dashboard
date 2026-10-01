import React, { useEffect, useMemo, useState } from "react";
import { Download, RefreshCw, Save } from "lucide-react";
import { api, getErrMsg } from "./api";
import "./ProgramadorCompetencyMatrix.css";

const keyOf = (personId, operationId) => `${personId}|${operationId}`;

function csvCell(value) {
  let text = String(value ?? "");
  if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

function LevelSelect({ levels, value, onChange, label, disabled }) {
  const info = levels.find((item) => item.nivel === value);
  return <select className={value == null ? "not-rated" : `level-${value}`} value={value ?? ""}
    aria-label={label} title={info ? `${info.nome} — ${info.descricao}` : "Não avaliado"}
    onChange={(event) => onChange(Number(event.target.value))} disabled={disabled}>
    <option value="" disabled>—</option>
    {levels.map((item) => <option key={item.nivel} value={item.nivel}>{item.nivel} — {item.nome}</option>)}
  </select>;
}

export default function ProgramadorCompetencyMatrix() {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({});
  const [reviewDraft, setReviewDraft] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [criticalOnly, setCriticalOnly] = useState(false);

  async function load() {
    setLoading(true); setError("");
    try {
      const response = await api.get("/programador/competencias");
      setData(response.data); setDraft({}); setReviewDraft({});
    } catch (err) { setError(getErrMsg(err)); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  const isLeader = data?.podeRevisar === true;
  const currentPerson = data?.colaboradorAtual;
  const assessment = (personId, operationId) => data?.avaliacoes?.[personId]?.[operationId];
  const selfLevel = (operationId) => {
    if (Object.prototype.hasOwnProperty.call(draft, operationId)) return draft[operationId];
    return assessment(currentPerson?.id, operationId)?.autoavaliacaoNivel;
  };
  const reviewLevel = (personId, operationId) => {
    const key = keyOf(personId, operationId);
    if (Object.prototype.hasOwnProperty.call(reviewDraft, key)) return reviewDraft[key];
    const item = assessment(personId, operationId);
    return item?.status === "PENDENTE" ? item.autoavaliacaoNivel : item?.nivelValidado ?? item?.autoavaliacaoNivel;
  };

  const selfChanges = Object.entries(draft).filter(([operationId, level]) =>
    level !== assessment(currentPerson?.id, operationId)?.autoavaliacaoNivel);
  const reviewChanges = Object.entries(reviewDraft);

  const visibleOperations = useMemo(() => {
    if (!data) return [];
    const term = search.trim().toLocaleLowerCase("pt-BR");
    return data.operacoes.filter((operation) => {
      if (term && !operation.nome.toLocaleLowerCase("pt-BR").includes(term)) return false;
      if (!criticalOnly || !isLeader) return true;
      return data.colaboradores.filter((person) => assessment(person.id, operation.id)?.nivelValidado >= 3).length < 2;
    });
  }, [criticalOnly, data, isLeader, search]);

  const summary = useMemo(() => {
    if (!data) return { completed: 0, total: 0, pending: 0, uncovered: 0, single: 0 };
    let completed = 0, pending = 0, uncovered = 0, single = 0;
    data.operacoes.forEach((operation) => {
      let coverage = 0;
      data.colaboradores.forEach((person) => {
        const item = data.avaliacoes?.[person.id]?.[operation.id];
        if (item?.autoavaliacaoNivel != null) completed += 1;
        if (item?.status === "PENDENTE") pending += 1;
        if (item?.nivelValidado >= 3) coverage += 1;
      });
      if (isLeader && coverage === 0) uncovered += 1;
      if (isLeader && coverage === 1) single += 1;
    });
    return { completed, total: data.operacoes.length * data.colaboradores.length, pending, uncovered, single };
  }, [data, isLeader]);

  async function saveSelf() {
    if (!selfChanges.length) return;
    await saveRequest("/programador/competencias", selfChanges.map(([operacao_id, nivel]) => ({ operacao_id, nivel })), "Autoavaliação enviada ao líder.");
  }

  async function saveReviews() {
    if (!reviewChanges.length) return;
    await saveRequest("/programador/competencias/validacoes", reviewChanges.map(([key, nivel]) => {
      const [colaborador_id, operacao_id] = key.split("|");
      return { colaborador_id, operacao_id, nivel };
    }), `${reviewChanges.length} ${reviewChanges.length === 1 ? "competência validada" : "competências validadas"}.`);
  }

  async function saveRequest(url, changes, success) {
    setSaving(true); setError(""); setMessage("");
    try {
      const response = await api.put(url, { alteracoes: changes });
      setData(response.data); setDraft({}); setReviewDraft({}); setMessage(success);
    } catch (err) { setError(getErrMsg(err)); }
    finally { setSaving(false); }
  }

  function exportCsv() {
    if (!data) return;
    const lines = [["operação", "colaborador", "autoavaliação", "nível validado", "status"]];
    data.operacoes.forEach((operation) => data.colaboradores.forEach((person) => {
      const item = assessment(person.id, operation.id) || {};
      lines.push([operation.nome, person.nome, item.autoavaliacaoNivel ?? "", item.nivelValidado ?? "", item.status || "Não avaliado"]);
    }));
    const csv = `\uFEFF${lines.map((line) => line.map(csvCell).join(";")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url;
    link.download = `matriz-competencias-cnc-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (loading && !data) return <main className="competencyPage"><div className="competencyLoading">Carregando matriz de competências...</div></main>;
  const actionCount = isLeader ? reviewChanges.length : selfChanges.length;

  return <main className="competencyPage">
    <header className="competencyHeading"><div>
      <span className="competencyEyebrow">DESENVOLVIMENTO DA EQUIPE CNC</span>
      <h1>{isLeader ? "Validação da Matriz de Competências" : "Minha Matriz de Competências"}</h1>
      <p>{isLeader ? "Confira a autoavaliação de cada pessoa, ajuste quando necessário e valide o conhecimento." : "Informe seu nível atual. O líder conferirá cada resposta antes de ela entrar na matriz oficial."}</p>
    </div><div className="competencyHeaderActions">
      {isLeader ? <button type="button" className="competencyBtn" onClick={exportCsv}><Download size={17} />Exportar CSV</button> : null}
      <button type="button" className="competencyBtn" onClick={load} disabled={loading || saving}><RefreshCw size={17} />Atualizar</button>
      <button type="button" className="competencyBtn primary" onClick={isLeader ? saveReviews : saveSelf} disabled={!actionCount || saving}>
        <Save size={17} />{saving ? "Salvando..." : isLeader ? `Salvar validações${actionCount ? ` (${actionCount})` : ""}` : `Enviar ao líder${actionCount ? ` (${actionCount})` : ""}`}
      </button>
    </div></header>

    {error ? <div className="competencyAlert error" role="alert">{error}</div> : null}
    {message ? <div className="competencyAlert success" role="status">{message}</div> : null}

    {data && !isLeader && !currentPerson ? <div className="competencyAlert error">Seu login ainda não está vinculado à matriz. O nome ou login precisa começar com Matheus, Paulo, Dirley, Lucas, Bruno ou Aleixo.</div> : null}

    {data ? <>
      <section className="competencyKpis">
        <article><span>{isLeader ? "Autoavaliações" : "Preenchimento"}</span><strong>{summary.completed}/{summary.total}</strong><small>{summary.total ? Math.round(summary.completed / summary.total * 100) : 0}% preenchido</small></article>
        <article><span>Operações</span><strong>{data.operacoes.length}</strong><small>mapeadas</small></article>
        <article className={summary.pending ? "warning" : "good"}><span>Pendentes do líder</span><strong>{summary.pending}</strong><small>aguardando validação</small></article>
        <article className={isLeader && summary.uncovered ? "attention" : "good"}><span>Sem cobertura validada</span><strong>{isLeader ? summary.uncovered : "—"}</strong><small>ninguém validado como autônomo</small></article>
      </section>

      <section className="competencyLegend" aria-label="Escala de competências">{data.niveis.map((level) =>
        <div key={level.nivel} className={`competencyLegendItem level-${level.nivel}`} title={level.descricao}><strong>{level.nivel}</strong><span>{level.nome}</span><small>{level.descricao}</small></div>)}</section>

      <section className="competencyPanel">
        <div className="competencyToolbar">
          <label className="competencySearch"><span>Pesquisar operação</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Ex.: suporte, papelão..." /></label>
          {isLeader ? <label className="competencyCritical"><input type="checkbox" checked={criticalOnly} onChange={(event) => setCriticalOnly(event.target.checked)} />Mostrar somente operações críticas</label> : <span className="competencyFlowHint">Autoavaliação → validação do líder → matriz oficial</span>}
        </div>
        {isLeader ? <LeaderMatrix data={data} operations={visibleOperations} assessment={assessment} reviewLevel={reviewLevel}
          saving={saving} reviewDraft={reviewDraft} setReviewDraft={setReviewDraft} /> : currentPerson ?
          <SelfAssessment data={data} operations={visibleOperations} person={currentPerson} assessment={assessment}
            selfLevel={selfLevel} setDraft={setDraft} saving={saving} /> : null}
      </section>
    </> : null}
  </main>;
}

function SelfAssessment({ data, operations, person, assessment, selfLevel, setDraft, saving }) {
  return <div className="competencySelfList">
    <div className="competencySelfTitle"><strong>{person.nome}</strong><span>Preencha com sinceridade; o nível ficará pendente até a conferência do líder.</span></div>
    {operations.map((operation) => {
      const item = assessment(person.id, operation.id);
      return <div className="competencySelfRow" key={operation.id}>
        <div><strong>{operation.nome}</strong><small>{item?.status === "VALIDADO" ? `Validado no nível ${item.nivelValidado}${item.revisadoPor ? ` por ${item.revisadoPor}` : ""}` : item?.status === "PENDENTE" ? "Aguardando validação do líder" : "Ainda não preenchido"}</small></div>
        <LevelSelect levels={data.niveis} value={selfLevel(operation.id)} onChange={(level) => setDraft((old) => ({ ...old, [operation.id]: level }))} label={`${person.nome}: ${operation.nome}`} disabled={saving} />
        <span className={`competencyStatus ${item?.status === "VALIDADO" ? "validated" : item?.status === "PENDENTE" ? "pending" : "empty"}`}>{item?.status === "VALIDADO" ? "Validado" : item?.status === "PENDENTE" ? "Pendente" : "Não enviado"}</span>
      </div>;
    })}
  </div>;
}

function LeaderMatrix({ data, operations, assessment, reviewLevel, saving, reviewDraft, setReviewDraft }) {
  return <div className="competencyTableWrap"><table className="competencyTable leader"><thead><tr><th>Operação</th>{data.colaboradores.map((person) => <th key={person.id}>{person.nome}</th>)}<th>Cobertura</th></tr></thead><tbody>
    {operations.map((operation) => {
      const coverage = data.colaboradores.filter((person) => assessment(person.id, operation.id)?.nivelValidado >= 3).length;
      return <tr key={operation.id}><th scope="row">{operation.nome}</th>{data.colaboradores.map((person) => {
        const item = assessment(person.id, operation.id); const key = keyOf(person.id, operation.id);
        return <td key={person.id}><div className={`competencyReviewCell ${item?.status === "PENDENTE" ? "pending" : ""}`}>
          <small>{item?.autoavaliacaoNivel == null ? "Não avaliado" : `Auto: ${item.autoavaliacaoNivel}`}</small>
          {item?.autoavaliacaoNivel != null ? <><LevelSelect levels={data.niveis} value={reviewLevel(person.id, operation.id)}
            onChange={(level) => setReviewDraft((old) => ({ ...old, [key]: level }))} label={`Validar ${person.nome}: ${operation.nome}`} disabled={saving} />
            {item.status === "PENDENTE" && !Object.prototype.hasOwnProperty.call(reviewDraft, key) ? <button type="button" onClick={() => setReviewDraft((old) => ({ ...old, [key]: item.autoavaliacaoNivel }))}>Confirmar</button> : <span className="competencyReviewedMark">{Object.prototype.hasOwnProperty.call(reviewDraft, key) ? "Pronto para salvar" : "Validado"}</span>}</> : null}
        </div></td>;
      })}<td><span className={`coverageBadge ${coverage === 0 ? "none" : coverage === 1 ? "single" : "covered"}`}>{coverage === 0 ? "Sem cobertura" : coverage === 1 ? "Ponto único" : `${coverage} autônomos`}</span></td></tr>;
    })}
    {!operations.length ? <tr><td className="competencyEmpty" colSpan={data.colaboradores.length + 2}>Nenhuma operação encontrada.</td></tr> : null}
  </tbody></table></div>;
}
