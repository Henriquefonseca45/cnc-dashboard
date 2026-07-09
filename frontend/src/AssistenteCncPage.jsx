import React, { useMemo, useRef, useState } from "react";
import { AlertTriangle, Bot, Clock, Factory, Loader2, Send, Wrench } from "lucide-react";
import { http, API_URL } from "./http";
import rvbLogo from "./assets/rvb-logo.png";
import "./AssistenteCncPage.css";

const quickQuestions = [
  { label: "Status geral", message: "Como estao as CNCs?", icon: Factory },
  { label: "Maquinas usinando", message: "Quais maquinas estao usinando?", icon: Factory },
  { label: "Maquinas paradas", message: "Quais maquinas estao paradas?", icon: AlertTriangle },
  { label: "Em manutencao", message: "Tem alguma CNC em manutencao?", icon: Wrench },
  { label: "Em setup", message: "Tem alguma CNC em setup?", icon: Wrench, tone: "setup" },
  { label: "Dados desatualizados", message: "Alguma maquina deixou de enviar dados?", icon: Clock },
];

function assistantHeaders() {
  const storedUser = localStorage.getItem("rvb_user_name") || localStorage.getItem("user_name");
  const storedRole = localStorage.getItem("rvb_user_role") || localStorage.getItem("user_role");
  const token = localStorage.getItem("cnc_assistant_token");
  return {
    ...(storedUser ? { "x-user-name": storedUser } : { "x-user-name": "Operador RVB" }),
    ...(storedRole ? { "x-user-role": storedRole } : { "x-user-role": "OPERADOR" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function formatDate(value) {
  if (!value) return "nao informado";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-BR");
}

function getErrorMessage(error) {
  const status = error?.response?.status;
  if (status === 401) return "Acesso nao autenticado para consultar as CNCs.";
  if (status === 429) return "Muitas consultas em pouco tempo. Aguarde um instante.";
  return "Nao foi possivel consultar as maquinas.";
}

function renderAssistantText(message) {
  const text = String(message.text || "");
  if (message.role !== "assistant") return text;
  return text.split(/\n{2,}/).map((block, index) => {
    const isMachineBlock = /^CNC\d+/i.test(block.trim());
    return (
      <div key={`${message.id}-block-${index}`} className={isMachineBlock ? "assistantMachineBlock" : "assistantTextBlock"}>
        {block}
      </div>
    );
  });
}

export default function AssistenteCncPage() {
  const [messages, setMessages] = useState([
    {
      id: "welcome",
      role: "assistant",
      text: "Ola. Posso consultar o status atual das CNCs, arquivos em execucao, paradas, manutencoes e dados desatualizados.",
      at: new Date().toISOString(),
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastUpdate, setLastUpdate] = useState("");
  const [hasStaleData, setHasStaleData] = useState(false);
  const chatRef = useRef(null);

  const canSend = useMemo(() => input.trim().length > 0 && !loading, [input, loading]);

  async function sendMessage(text) {
    const pergunta = String(text || "").trim();
    if (!pergunta || loading) return;

    const userMsg = { id: `u-${Date.now()}`, role: "user", text: pergunta, at: new Date().toISOString() };
    setMessages((current) => [...current, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await http.post(
        "/api/assistant/chat",
        { mensagem: pergunta },
        { headers: assistantHeaders() },
      );
      const data = res.data || {};
      setLastUpdate(data.ultima_atualizacao || "");
      setHasStaleData(Boolean(data.dados_desatualizados));
      setMessages((current) => [
        ...current,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          text: data.resposta || "Nao encontrei uma resposta com os dados disponiveis.",
          at: new Date().toISOString(),
          tools: data.ferramentas || [],
        },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        { id: `e-${Date.now()}`, role: "assistant", text: getErrorMessage(error), at: new Date().toISOString(), error: true },
      ]);
    } finally {
      setLoading(false);
      window.requestAnimationFrame(() => {
        if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
      });
    }
  }

  function onSubmit(event) {
    event.preventDefault();
    sendMessage(input);
  }

  return (
    <main className="assistantPage">
      <section className="assistantShell">
        <header className="assistantHeader">
          <div className="assistantBrand">
            <img src={rvbLogo} alt="RVB" />
            <div>
              <p>Assistente Virtual CNC RVB</p>
              <h1>Assistente CNC</h1>
            </div>
          </div>
          <div className={`assistantStatus ${hasStaleData ? "stale" : "ok"}`}>
            <span />
            {hasStaleData ? "Ha dados desatualizados" : "Consulta somente leitura"}
          </div>
        </header>

        <div className="assistantMeta">
          <div>
            <Clock size={16} />
            <span>Ultima comunicacao: {formatDate(lastUpdate)}</span>
          </div>
          <div>
            <Bot size={16} />
            <span>Sem comandos de operacao das CNCs</span>
          </div>
        </div>

        <div className="assistantQuickGrid">
          {quickQuestions.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.label}
                type="button"
                className={item.tone || ""}
                onClick={() => sendMessage(item.message)}
                disabled={loading}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>

        <section className="assistantChat" ref={chatRef} aria-live="polite">
          {messages.map((message) => (
            <article key={message.id} className={`assistantBubble ${message.role} ${message.error ? "error" : ""}`}>
              <div className="assistantBubbleText">{renderAssistantText(message)}</div>
              <time>{formatDate(message.at)}</time>
            </article>
          ))}
          {loading && (
            <article className="assistantBubble assistant loading">
              <Loader2 size={18} className="assistantSpin" />
              <span>Consultando CNCs...</span>
            </article>
          )}
        </section>

        <form className="assistantComposer" onSubmit={onSubmit}>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            maxLength={500}
            placeholder="Digite sua pergunta sobre as CNCs"
          />
          <button type="submit" disabled={!canSend} title="Enviar pergunta">
            <Send size={20} />
          </button>
        </form>

        {API_URL ? null : <div className="assistantApiHint">Usando o mesmo endereco do dashboard para consultar a API.</div>}
      </section>
    </main>
  );
}
