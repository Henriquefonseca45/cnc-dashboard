import React, { useState } from "react";
import { api, getErrMsg } from "./api";


export default function ProgramadorFirstAccess({ user, onCompleted, onLogout, themeMode }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    if (password !== confirmation) return setError("As senhas não coincidem.");
    if (password.length < 8 || !/[A-Za-zÀ-ÿ]/.test(password) || !/\d/.test(password)) {
      return setError("Use pelo menos 8 caracteres, com letras e números.");
    }
    setLoading(true);
    setError("");
    try {
      const response = await api.post("/programador/auth/primeiro-acesso", {
        nova_senha: password, confirmar_senha: confirmation,
      });
      onCompleted(response.data.user);
    } catch (err) {
      setError(getErrMsg(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={`programadorLoginPage theme-${themeMode}`}>
      <section className="programadorLoginCard" aria-labelledby="first-access-title">
        <div className="programadorLoginMark">RVB</div>
        <div className="programadorLoginEyebrow">BEM-VINDO À PROGRAMAÇÃO</div>
        <h1 id="first-access-title">Crie sua nova senha</h1>
        <p>Olá, {user.nome}. Por segurança, você precisa criar uma nova senha antes de continuar.</p>
        <form onSubmit={submit}>
          <label>Nova senha<input autoFocus type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <label>Confirme a nova senha<input type="password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
          <small className="programadorPasswordHint">Mínimo de 8 caracteres, incluindo letras e números.</small>
          {error ? <div className="programadorLoginError" role="alert">{error}</div> : null}
          <button type="submit" disabled={loading}>{loading ? "Salvando..." : "Salvar nova senha"}</button>
          <button className="programadorSecondaryButton" type="button" onClick={onLogout}>Sair</button>
        </form>
      </section>
    </main>
  );
}
