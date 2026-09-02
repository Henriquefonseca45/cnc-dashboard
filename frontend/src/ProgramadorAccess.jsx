import React, { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import ProgramadorDashboard from "./ProgramadorDashboard.jsx";
import ProgramadorAuditHistory from "./ProgramadorAuditHistory.jsx";
import { api, getErrMsg } from "./api";
import "./ProgramadorAccess.css";


function roleLabel(role) {
  return role === "lider" ? "Líder" : "Programador";
}


function ProgramadorLogin({ onAuthenticated, themeMode }) {
  const [login, setLogin] = useState("");
  const [senha, setSenha] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (!login.trim() || !senha) {
      setError("Informe usuário e senha.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await api.post("/programador/auth/login", { login: login.trim(), senha });
      onAuthenticated(response.data.user);
    } catch (err) {
      setError(err?.response?.status === 401 ? "Usuário ou senha inválidos." : getErrMsg(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={`programadorLoginPage theme-${themeMode}`}>
      <section className="programadorLoginCard" aria-labelledby="programador-login-title">
        <div className="programadorLoginMark">RVB</div>
        <div className="programadorLoginEyebrow">PROGRAMAÇÃO CNC</div>
        <h1 id="programador-login-title">Acesso ao módulo</h1>
        <p>Entre com seu usuário para acessar a operação de Programação.</p>
        <form onSubmit={submit}>
          <label>
            Usuário
            <input autoFocus autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} />
          </label>
          <label>
            Senha
            <input type="password" autoComplete="current-password" value={senha} onChange={(event) => setSenha(event.target.value)} />
          </label>
          {error ? <div className="programadorLoginError" role="alert">{error}</div> : null}
          <button type="submit" disabled={loading}>{loading ? "Entrando..." : "Entrar"}</button>
        </form>
      </section>
    </main>
  );
}


export default function ProgramadorAccess() {
  const location = useLocation();
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState(() => location.pathname.endsWith("/historico") ? "historico" : "operacao");
  const [themeMode, setThemeMode] = useState(() => {
    try { return localStorage.getItem("programador_dashboard_theme") || "dark"; } catch { return "dark"; }
  });

  useEffect(() => {
    let active = true;
    api.get("/programador/auth/me")
      .then((response) => { if (active) setUser(response.data.user); })
      .catch(() => { if (active) setUser(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const requestedView = location.pathname.endsWith("/historico") ? "historico" : "operacao";
    if (requestedView === "historico" && user && user.role !== "lider") {
      setView("operacao");
      navigate("/programador", { replace: true });
      return;
    }
    setView(requestedView);
  }, [location.pathname, navigate, user]);

  useEffect(() => {
    const syncTheme = (event) => setThemeMode(event.detail === "light" ? "light" : "dark");
    window.addEventListener("programador-theme-change", syncTheme);
    return () => window.removeEventListener("programador-theme-change", syncTheme);
  }, []);

  useEffect(() => {
    const interceptor = api.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error?.response?.status === 401) {
          setUser(null);
          setView("operacao");
        }
        return Promise.reject(error);
      },
    );
    return () => api.interceptors.response.eject(interceptor);
  }, []);

  async function logout() {
    try {
      await api.post("/programador/auth/logout");
    } finally {
      setUser(null);
      setView("operacao");
      navigate("/programador", { replace: true });
    }
  }

  if (loading) return <main className="programadorAuthLoading">Validando acesso...</main>;
  if (!user) return <ProgramadorLogin onAuthenticated={setUser} themeMode={themeMode} />;

  return (
    <div className={`programadorModule theme-${themeMode}`}>
      <header className="programadorModuleBar">
        <div className="programadorModuleIdentity">
          <strong>Programação CNC</strong>
          <span>Acesso identificado e auditado</span>
        </div>
        <nav aria-label="Módulo Programador">
          <button className={view === "operacao" ? "active" : ""} onClick={() => navigate("/programador")}>Operação</button>
          {user.role === "lider" ? (
            <button className={view === "historico" ? "active" : ""} onClick={() => navigate("/programador/historico")}>Histórico</button>
          ) : null}
        </nav>
        <div className="programadorCurrentUser">
          <span className="programadorAvatar" aria-hidden="true">{user.nome.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase()}</span>
          <span><strong>{user.nome}</strong><small>{roleLabel(user.role)}</small></span>
          <button onClick={logout}>Sair</button>
        </div>
      </header>
      <div className="programadorModuleContent">
        {view === "historico" && user.role === "lider" ? (
          <ProgramadorAuditHistory />
        ) : (
          <ProgramadorDashboard authUser={user} />
        )}
      </div>
    </div>
  );
}
