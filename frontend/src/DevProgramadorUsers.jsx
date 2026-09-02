import React, { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, getErrMsg } from "./api";
import { ProgramadorLogin } from "./ProgramadorAccess.jsx";
import "./DevProgramadorUsers.css";


const EMPTY_SUMMARY = { total: 0, programadores: 0, lideres: 0, primeiro_acesso: 0 };

function dateTime(value) {
  if (!value) return "Nunca";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("pt-BR");
}

function UserDialog({ mode, user, onClose, onSaved }) {
  const [form, setForm] = useState({
    nome: user?.nome || "", login: user?.login || "", role: user?.role || "programador", senha_temporaria: "", confirmar_senha_temporaria: "",
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const create = mode === "create";

  function change(event) { setForm((current) => ({ ...current, [event.target.name]: event.target.value })); }
  async function submit(event) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const payload = { nome: form.nome, login: form.login, role: form.role };
      if (create) { payload.senha_temporaria = form.senha_temporaria; payload.confirmar_senha_temporaria = form.confirmar_senha_temporaria; }
      await (create ? api.post("/dev/programador/api/usuarios", payload) : api.put(`/dev/programador/api/usuarios/${user.id}`, payload));
      onSaved();
    } catch (err) { setError(getErrMsg(err)); } finally { setSaving(false); }
  }
  return (
    <div className="devUsersOverlay" role="presentation" onMouseDown={onClose}>
      <section className="devUsersDialog" role="dialog" aria-modal="true" aria-labelledby="user-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="devUsersClose" type="button" onClick={onClose} aria-label="Fechar">×</button>
        <span>GESTÃO DE ACESSO</span><h2 id="user-dialog-title">{create ? "Novo usuário" : "Editar usuário"}</h2>
        <form onSubmit={submit}>
          <label>Nome completo<input name="nome" autoFocus required value={form.nome} onChange={change} /></label>
          <label>Login<input name="login" required value={form.login} onChange={change} /></label>
          <label>Perfil<select name="role" value={form.role} onChange={change}><option value="programador">Programador</option><option value="lider">Líder</option></select></label>
          {create ? <label>Senha temporária<input name="senha_temporaria" type="password" required autoComplete="new-password" value={form.senha_temporaria} onChange={change} /><small>Mínimo de 8 caracteres, com letras e números.</small></label> : null}
          {create ? <label>Confirmar senha temporária<input name="confirmar_senha_temporaria" type="password" required autoComplete="new-password" value={form.confirmar_senha_temporaria} onChange={change} /></label> : null}
          {error ? <div className="devUsersError" role="alert">{error}</div> : null}
          <footer><button type="button" onClick={onClose}>Cancelar</button><button className="primary" disabled={saving}>{saving ? "Salvando..." : "Salvar"}</button></footer>
        </form>
      </section>
    </div>
  );
}

function ActionDialog({ action, onClose, onSaved }) {
  const reset = action.kind === "reset";
  const [password, setPassword] = useState(""); const [confirmation, setConfirmation] = useState(""); const [error, setError] = useState(""); const [saving, setSaving] = useState(false);
  async function submit(event) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      if (reset) await api.post(`/dev/programador/api/usuarios/${action.user.id}/redefinir-senha`, { senha_temporaria: password, confirmar_senha_temporaria: confirmation });
      else await api.patch(`/dev/programador/api/usuarios/${action.user.id}/status`, { ativo: !action.user.ativo });
      onSaved();
    } catch (err) { setError(getErrMsg(err)); } finally { setSaving(false); }
  }
  const verb = action.user.ativo ? "Desativar" : "Ativar";
  return (
    <div className="devUsersOverlay" onMouseDown={onClose}>
      <section className="devUsersDialog compact" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <button className="devUsersClose" onClick={onClose}>×</button>
        <span>CONFIRMAÇÃO</span><h2>{reset ? "Redefinir senha" : `${verb} usuário`}</h2>
        <p>{reset ? `Defina uma nova senha temporária para ${action.user.nome}. As sessões abertas serão encerradas.` : `${verb} o acesso de ${action.user.nome}?${action.user.ativo ? " As sessões abertas serão encerradas." : ""}`}</p>
        <form onSubmit={submit}>
          {reset ? <label>Nova senha temporária<input autoFocus type="password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label> : null}
          {reset ? <label>Confirmar senha temporária<input type="password" required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label> : null}
          {reset ? <label className="devUsersCheck"><input type="checkbox" checked readOnly /> Exigir criação de nova senha no próximo login</label> : null}
          {error ? <div className="devUsersError">{error}</div> : null}
          <footer><button type="button" onClick={onClose}>Cancelar</button><button className="primary" disabled={saving}>{saving ? "Confirmando..." : "Confirmar"}</button></footer>
        </form>
      </section>
    </div>
  );
}

export default function DevProgramadorUsers() {
  const [auth, setAuth] = useState({ loading: true, user: null });
  const [data, setData] = useState({ items: [], summary: EMPTY_SUMMARY });
  const [filters, setFilters] = useState({ busca: "", role: "", status: "" });
  const [dialog, setDialog] = useState(null); const [error, setError] = useState(""); const [loading, setLoading] = useState(false);

  useEffect(() => { api.get("/programador/auth/me").then((response) => setAuth({ loading: false, user: response.data.user })).catch(() => setAuth({ loading: false, user: null })); }, []);
  const load = useCallback(async () => {
    if (auth.user?.role !== "dev") return;
    setLoading(true); setError("");
    try { const response = await api.get("/dev/programador/api/usuarios", { params: filters }); setData(response.data); }
    catch (err) { setError(getErrMsg(err)); } finally { setLoading(false); }
  }, [auth.user, filters]);
  useEffect(() => { const timer = setTimeout(load, 180); return () => clearTimeout(timer); }, [load]);

  async function logout() { await api.post("/programador/auth/logout").catch(() => {}); setAuth({ loading: false, user: null }); }
  function saved() { setDialog(null); load(); }
  if (auth.loading) return <main className="programadorAuthLoading">Validando acesso DEV...</main>;
  if (!auth.user) return <ProgramadorLogin themeMode="light" eyebrow="ADMINISTRAÇÃO TÉCNICA" description="Entre com suas credenciais para continuar." onAuthenticated={(user) => setAuth({ loading: false, user })} />;
  if (auth.user.must_change_password) return <Navigate to="/programador/primeiro-acesso" replace />;
  if (auth.user.role !== "dev") return <main className="devUsersDenied"><section><h1>Acesso não autorizado</h1><p>Esta área é exclusiva do perfil DEV.</p><button onClick={logout}>Sair</button></section></main>;

  return (
    <main className="devUsersPage">
      <header><div><span>ADMINISTRAÇÃO TÉCNICA</span><h1>Usuários da Programação</h1><p>Gerencie acessos de Programadores e Líderes sem expor credenciais.</p></div><div className="devUsersIdentity"><strong>{auth.user.nome}</strong><small>DEV</small><button onClick={logout}>Sair</button></div></header>
      <section className="devUsersSummary">
        <article><span>Total</span><strong>{data.summary.total}</strong></article><article><span>Programadores</span><strong>{data.summary.programadores}</strong></article><article><span>Líderes</span><strong>{data.summary.lideres}</strong></article><article><span>Primeiro acesso pendente</span><strong>{data.summary.primeiro_acesso}</strong></article>
      </section>
      <section className="devUsersPanel">
        <div className="devUsersToolbar">
          <input aria-label="Buscar usuário" placeholder="Buscar por nome ou login" value={filters.busca} onChange={(event) => setFilters({ ...filters, busca: event.target.value })} />
          <select aria-label="Filtrar perfil" value={filters.role} onChange={(event) => setFilters({ ...filters, role: event.target.value })}><option value="">Todos os perfis</option><option value="programador">Programador</option><option value="lider">Líder</option></select>
          <select aria-label="Filtrar situação" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">Todas as situações</option><option value="ativo">Ativos</option><option value="inativo">Inativos</option><option value="primeiro_acesso">Primeiro acesso pendente</option></select>
          <button className="primary" onClick={() => setDialog({ kind: "create" })}>+ Novo usuário</button>
        </div>
        {error ? <div className="devUsersError">{error}</div> : null}
        <div className="devUsersTableWrap"><table><thead><tr><th>Nome</th><th>Login</th><th>Perfil</th><th>Status</th><th>Primeiro acesso</th><th>Último acesso</th><th>Ações</th></tr></thead><tbody>
          {!loading && data.items.length === 0 ? <tr><td colSpan="7" className="empty">Nenhum usuário encontrado.</td></tr> : null}
          {data.items.map((user) => <tr key={user.id}><td><strong>{user.nome}</strong></td><td>@{user.login}</td><td><span className="devUsersBadge role">{user.role === "lider" ? "Líder" : "Programador"}</span></td><td><span className={`devUsersBadge ${user.ativo ? "active" : "inactive"}`}>{user.ativo ? "Ativo" : "Inativo"}</span></td><td>{user.must_change_password ? <span className="devUsersBadge pending">Pendente</span> : "Concluído"}</td><td>{dateTime(user.last_login_at)}</td><td><div className="devUsersActions"><button onClick={() => setDialog({ kind: "edit", user })}>Editar</button><button onClick={() => setDialog({ kind: "reset", user })}>Redefinir senha</button><button onClick={() => setDialog({ kind: "status", user })}>{user.ativo ? "Desativar" : "Ativar"}</button></div></td></tr>)}
          {loading ? <tr><td colSpan="7" className="empty">Atualizando...</td></tr> : null}
        </tbody></table></div>
      </section>
      {dialog?.kind === "create" || dialog?.kind === "edit" ? <UserDialog mode={dialog.kind} user={dialog.user} onClose={() => setDialog(null)} onSaved={saved} /> : null}
      {dialog?.kind === "reset" || dialog?.kind === "status" ? <ActionDialog action={dialog} onClose={() => setDialog(null)} onSaved={saved} /> : null}
    </main>
  );
}
