import React, { useEffect, useMemo, useState } from "react";
import { Download, RefreshCw, Save } from "lucide-react";
import { api, getErrMsg } from "./api";
import "./ProgramadorCompetencyMatrix.css";


function keyOf(personId, operationId) {
  return `${personId}|${operationId}`;
}


function csvCell(value) {
  let text = String(value ?? "");
  if (/^[\s]*[=+@-]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}


export default function ProgramadorCompetencyMatrix() {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [criticalOnly, setCriticalOnly] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await api.get("/programador/competencias");
      setData(response.data);
      setDraft({});
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  const getSavedLevel = (personId, operationId) =>
    data?.avaliacoes?.[personId]?.[operationId]?.nivel;
  const getLevel = (personId, operationId) => {
    const key = keyOf(personId, operationId);
    return Object.prototype.hasOwnProperty.call(draft, key)
      ? draft[key]
      : getSavedLevel(personId, operationId);
  };

  const rows = useMemo(() => {
    if (!data) return [];
    const term = search.trim().toLocaleLowerCase("pt-BR");
    return data.operacoes.filter((operation) => {
      if (term && !operation.nome.toLocaleLowerCase("pt-BR").includes(term)) return false;
      if (!criticalOnly) return true;
      const coverage = data.colaboradores.filter((person) => {
        const key = keyOf(person.id, operation.id);
        const level = Object.prototype.hasOwnProperty.call(draft, key)
          ? draft[key]
          : data.avaliacoes?.[person.id]?.[operation.id]?.nivel;
        return level >= 3;
      }).length;
      return coverage < 2;
    });
  }, [criticalOnly, data, draft, search]);

  const summary = useMemo(() => {
    if (!data) return { completed: 0, total: 0, uncovered: 0, single: 0 };
    let completed = 0;
    let uncovered = 0;
    let single = 0;
    data.operacoes.forEach((operation) => {
      let coverage = 0;
      data.colaboradores.forEach((person) => {
        const key = keyOf(person.id, operation.id);
        const level = Object.prototype.hasOwnProperty.call(draft, key)
          ? draft[key]
          : data.avaliacoes?.[person.id]?.[operation.id]?.nivel;
        if (level !== undefined && level !== null) completed += 1;
        if (level >= 3) coverage += 1;
      });
      if (coverage === 0) uncovered += 1;
      if (coverage === 1) single += 1;
    });
    return {
      completed,
      total: data.operacoes.length * data.colaboradores.length,
      uncovered,
      single,
    };
  }, [data, draft]);

  const pending = Object.entries(draft).filter(([key, level]) => {
    const [personId, operationId] = key.split("|");
    return level !== getSavedLevel(personId, operationId);
  });

  function changeLevel(personId, operationId, rawValue) {
    const level = rawValue === "" ? undefined : Number(rawValue);
    setMessage("");
    setDraft((current) => ({ ...current, [keyOf(personId, operationId)]: level }));
  }

  async function save() {
    const changes = pending
      .filter(([, level]) => level !== undefined)
      .map(([key, nivel]) => {
        const [colaborador_id, operacao_id] = key.split("|");
        return { colaborador_id, operacao_id, nivel };
      });
    if (!changes.length) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await api.put("/programador/competencias", { alteracoes: changes });
      setData(response.data);
      setDraft({});
      setMessage(`${changes.length} ${changes.length === 1 ? "competência atualizada" : "competências atualizadas"}.`);
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      setSaving(false);
    }
  }

  function exportCsv() {
    if (!data) return;
    const lines = [["operação", "colaborador", "nível", "classificação"]];
    data.operacoes.forEach((operation) => data.colaboradores.forEach((person) => {
      const level = getLevel(person.id, operation.id);
      const levelInfo = data.niveis.find((item) => item.nivel === level);
      lines.push([operation.nome, person.nome, level ?? "", levelInfo?.nome || "Não avaliado"]);
    }));
    const csv = `\uFEFF${lines.map((line) => line.map(csvCell).join(";")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `matriz-competencias-cnc-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  if (loading && !data) return <main className="competencyPage"><div className="competencyLoading">Carregando matriz de competências...</div></main>;

  return (
    <main className="competencyPage">
      <header className="competencyHeading">
        <div>
          <span className="competencyEyebrow">DESENVOLVIMENTO DA EQUIPE CNC</span>
          <h1>Matriz de Competências</h1>
          <p>Conhecimento da equipe nas operações de programação e preparação.</p>
        </div>
        <div className="competencyHeaderActions">
          <button type="button" className="competencyBtn" onClick={exportCsv} disabled={!data}><Download size={17} />Exportar CSV</button>
          <button type="button" className="competencyBtn" onClick={load} disabled={loading || saving}><RefreshCw size={17} />Atualizar</button>
          <button type="button" className="competencyBtn primary" onClick={save} disabled={!pending.length || saving}>
            <Save size={17} />{saving ? "Salvando..." : `Salvar${pending.length ? ` (${pending.length})` : ""}`}
          </button>
        </div>
      </header>

      {error ? <div className="competencyAlert error" role="alert">{error}</div> : null}
      {message ? <div className="competencyAlert success" role="status">{message}</div> : null}

      {data ? <>
        <section className="competencyKpis">
          <article><span>Preenchimento</span><strong>{summary.completed}/{summary.total}</strong><small>{summary.total ? Math.round(summary.completed / summary.total * 100) : 0}% da matriz</small></article>
          <article><span>Operações</span><strong>{data.operacoes.length}</strong><small>mapeadas</small></article>
          <article className={summary.uncovered ? "attention" : "good"}><span>Sem cobertura</span><strong>{summary.uncovered}</strong><small>ninguém autônomo</small></article>
          <article className={summary.single ? "warning" : "good"}><span>Ponto único</span><strong>{summary.single}</strong><small>apenas uma referência</small></article>
        </section>

        <section className="competencyLegend" aria-label="Escala de competências">
          {data.niveis.map((level) => <div key={level.nivel} className={`competencyLegendItem level-${level.nivel}`} title={level.descricao}>
            <strong>{level.nivel}</strong><span>{level.nome}</span><small>{level.descricao}</small>
          </div>)}
        </section>

        <section className="competencyPanel">
          <div className="competencyToolbar">
            <label className="competencySearch"><span>Pesquisar operação</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Ex.: suporte, papelão..." /></label>
            <label className="competencyCritical"><input type="checkbox" checked={criticalOnly} onChange={(event) => setCriticalOnly(event.target.checked)} />Mostrar somente sem cobertura ou com uma pessoa autônoma</label>
          </div>
          <div className="competencyTableWrap">
            <table className="competencyTable">
              <thead><tr><th>Operação</th>{data.colaboradores.map((person) => <th key={person.id}>{person.nome}</th>)}<th>Cobertura</th></tr></thead>
              <tbody>
                {rows.map((operation) => {
                  const coverage = data.colaboradores.filter((person) => getLevel(person.id, operation.id) >= 3).length;
                  return <tr key={operation.id}>
                    <th scope="row">{operation.nome}</th>
                    {data.colaboradores.map((person) => {
                      const level = getLevel(person.id, operation.id);
                      const info = data.niveis.find((item) => item.nivel === level);
                      return <td key={person.id}>
                        <select
                          className={level === undefined ? "not-rated" : `level-${level}`}
                          aria-label={`${person.nome}: ${operation.nome}`}
                          title={info ? `${info.nome} — ${info.descricao}` : "Não avaliado"}
                          value={level ?? ""}
                          onChange={(event) => changeLevel(person.id, operation.id, event.target.value)}
                          disabled={saving}
                        >
                          <option value="" disabled={level !== undefined}>—</option>
                          {data.niveis.map((item) => <option key={item.nivel} value={item.nivel}>{item.nivel} — {item.nome}</option>)}
                        </select>
                      </td>;
                    })}
                    <td><span className={`coverageBadge ${coverage === 0 ? "none" : coverage === 1 ? "single" : "covered"}`}>{coverage === 0 ? "Sem cobertura" : coverage === 1 ? "Ponto único" : `${coverage} autônomos`}</span></td>
                  </tr>;
                })}
                {!rows.length ? <tr><td className="competencyEmpty" colSpan={data.colaboradores.length + 2}>Nenhuma operação encontrada.</td></tr> : null}
              </tbody>
            </table>
          </div>
        </section>
      </> : null}
    </main>
  );
}

