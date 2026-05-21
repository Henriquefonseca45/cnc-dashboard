import React, { useEffect, useMemo, useRef, useState } from "react";
import { Send, MessageSquare } from "lucide-react";
import { api, getErrMsg } from "../api";

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function isNearScrollBottom(el, gap = 80) {
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= gap;
}

export default function MachineChat({
  maquinaId,
  autor = "PROGRAMADOR",
  title = "Chat",
  compact = false,
  height = 320,
}) {
  const [mensagens, setMensagens] = useState([]);
  const [texto, setTexto] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [erro, setErro] = useState("");
  const listRef = useRef(null);
  const shouldScrollRef = useRef(true);
  const forceScrollRef = useRef(true);

  async function loadChat(silent = false) {
    if (!maquinaId) return;
    if (!silent) setLoading(true);
    setErro("");

    try {
      const res = await api.get(`/chat/${maquinaId}?limit=100`);
      const arr = Array.isArray(res.data) ? [...res.data].reverse() : [];
      const el = listRef.current;
      shouldScrollRef.current = forceScrollRef.current || !el || isNearScrollBottom(el);
      forceScrollRef.current = false;
      setMensagens(arr);
    } catch (e) {
      setErro(getErrMsg?.(e) || "Falha ao carregar chat");
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function sendChat() {
    const msg = texto.trim();
    if (!msg || !maquinaId || sending) return;

    setSending(true);
    setErro("");

    try {
      await api.post("/chat", {
        maquina_id: maquinaId,
        autor,
        mensagem: msg,
      });

      setTexto("");
      forceScrollRef.current = true;
      await loadChat(true);
    } catch (e) {
      setErro(getErrMsg?.(e) || "Falha ao enviar mensagem");
    } finally {
      setSending(false);
    }
  }

  useEffect(() => {
    forceScrollRef.current = true;
    loadChat();
    const t = setInterval(() => loadChat(true), 5000);
    return () => clearInterval(t);
  }, [maquinaId]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    if (!shouldScrollRef.current) return;
    el.scrollTop = el.scrollHeight;
    shouldScrollRef.current = false;
  }, [mensagens]);

  const total = useMemo(() => mensagens.length, [mensagens]);

  return (
    <div className={`mcWrap ${compact ? "mcWrapCompact" : ""}`}>
      <div className="mcHead">
        <div className="mcTitle">
          <MessageSquare size={16} />
          <span>{title}</span>
        </div>
        <div className="mcMeta">
          {maquinaId || "-"} • {total} msg
        </div>
      </div>

      <div
        ref={listRef}
        className="mcList"
        style={{ height }}
      >
        {loading ? (
          <div className="mcEmpty">Carregando chat...</div>
        ) : mensagens.length === 0 ? (
          <div className="mcEmpty">Nenhuma mensagem ainda.</div>
        ) : (
          mensagens.map((m) => {
            const mine = String(m.autor || "").toUpperCase() === String(autor).toUpperCase();
            return (
              <div key={m.id} className={`mcMsgRow ${mine ? "mine" : "other"}`}>
                <div className={`mcMsg ${mine ? "mine" : "other"}`}>
                  <div className="mcMsgTop">
                    <strong>{m.autor}</strong>
                    <span>{fmtDate(m.criado_em)}</span>
                  </div>
                  <div className="mcMsgText">{m.mensagem}</div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {erro ? <div className="mcError">{erro}</div> : null}

      <div className="mcSend">
        <input
          className="mcInput"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Digite uma mensagem..."
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendChat();
            }
          }}
        />
        <button className="mcBtn" onClick={sendChat} disabled={sending || !texto.trim()}>
          <Send size={16} />
          <span>{sending ? "Enviando..." : "Enviar"}</span>
        </button>
      </div>
    </div>
  );
}
