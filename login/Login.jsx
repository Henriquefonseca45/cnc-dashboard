import React, { useState } from "react";
import { http, setToken } from "./http";
import { useNavigate } from "react-router-dom";

export default function Login() {
  const navigate = useNavigate();
  const [login, setLogin] = useState("admin");
  const [senha, setSenha] = useState("admin123");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState("");

  async function entrar(e) {
    e.preventDefault();
    setErro("");
    setLoading(true);

    try {
      const r = await http.post("/auth/login", { login, senha });

      const token = r?.data?.token || "";
      const user = r?.data?.user || {};
      const nivel = String(user?.nivel || "").toUpperCase();
      const maquinaId = String(user?.maquina_id || "").toUpperCase();

      if (!token) throw new Error("Token não veio na resposta.");

      setToken(token);

      // ✅ PROGRAMADOR/ADMIN vai direto pro painel do programador
      if (nivel === "PROGRAMADOR" || nivel === "ADMIN") {
        navigate("/programador", { replace: true });
        return;
      }

      // ✅ OPERADOR vai direto pra CNC dele (se existir)
      if (nivel === "OPERADOR") {
        if (!maquinaId) {
          // fallback: se por algum motivo não veio máquina, manda pro select
          navigate("/select", { replace: true });
        } else {
          localStorage.setItem("cnc_current_cnc", maquinaId);
          navigate(`/operador/${maquinaId}`, { replace: true });
        }
        return;
      }

      // fallback geral
      navigate("/select", { replace: true });
    } catch (err) {
      console.error(err);
      const msg =
        err?.response?.data?.detail ||
        err?.response?.data?.msg ||
        err?.message ||
        "Falha no login";
      setErro(String(msg));
      setToken("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#050914] text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-2xl bg-[#0b1224]/70 border border-white/10 p-6">
        <div className="text-xl font-semibold">Login</div>
        <div className="text-xs text-slate-400 mt-1">
          Entre para usar o painel.
        </div>

        <form onSubmit={entrar} className="mt-6 space-y-3">
          <div>
            <label className="text-xs text-slate-300">Usuário</label>
            <input
              className="mt-1 w-full h-11 rounded-xl bg-white/5 border border-white/10 px-3 outline-none"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              autoComplete="username"
            />
          </div>

          <div>
            <label className="text-xs text-slate-300">Senha</label>
            <input
              className="mt-1 w-full h-11 rounded-xl bg-white/5 border border-white/10 px-3 outline-none"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              type="password"
              autoComplete="current-password"
            />
          </div>

          {erro && (
            <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/20 rounded-xl p-3">
              {erro}
            </div>
          )}

          <button
            disabled={loading}
            className="w-full h-12 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 font-semibold"
          >
            {loading ? "Entrando..." : "Entrar"}
          </button>
        </form>

        <div className="text-[11px] text-slate-400 mt-4">
          Dica: se o token expirar, você volta pra esta tela automaticamente.
        </div>
      </div>
    </div>
  );
}