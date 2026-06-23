import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { MessageSquare, PackageCheck, RefreshCw, Search, Send, Truck, XCircle } from "lucide-react";
import { http } from "./http";
import { getErrMsg } from "./api";
import "./AlmoxarifadoChatPage.css";

const FILTERS = [
  { key: "pendentes", label: "Pendentes" },
  { key: "entregues", label: "Entregues" },
  { key: "sem_material", label: "Sem Material" },
  { key: "TODAS", label: "Todas" },
];

function fmtDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return value;
  }
}

function statusClass(status) {
  const st = String(status || "").toUpperCase();
  if (st === "ENTREGUE") return "ok";
  if (st === "CANCELADA_SEM_MATERIAL") return "danger";
  if (st === "EM_SEPARACAO") return "warn";
  if (st === "CANCELADA") return "muted";
  return "info";
}

export default function AlmoxarifadoChatPage({ embedded = false, basePath = "/almoxarifado-chat" }) {
  const { solicitacaoId } = useParams();
  const navigate = useNavigate();
  const listRef = useRef([]);
  const msgBoxRef = useRef(null);

  const [filter, setFilter] = useState("pendentes");
  const [query, setQuery] = useState("");
  const [requests, setRequests] = useState([]);
  const [selectedId, setSelectedId] = useState(solicitacaoId ? Number(solicitacaoId) : null);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [loadingList, setLoadingList] = useState(false);
  const [loadingChat, setLoadingChat] = useState(false);
  const [sending, setSending] = useState(false);
  const [acting, setActing] = useState("");
  const [error, setError] = useState("");

  const filteredRequests = useMemo(() => {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return requests;
    return requests.filter((item) => {
      const textSearch = [
        item.maquina_id,
        item.material,
        item.arquivo_nome,
        item.op,
        item.operador_nome,
        item.status_label,
        item.ultima_mensagem,
      ].join(" ").toLowerCase();
      return textSearch.includes(q);
    });
  }, [query, requests]);

  async function loadRequests(silent = false) {
    if (!silent) setLoadingList(true);
    try {
      const res = await http.get("/api/material/solicitacoes", {
        params: { status: filter, limit: 300 },
      });
      const data = Array.isArray(res.data) ? res.data : [];
      listRef.current = data;
      setRequests(data);
      if (!selectedId && data[0]?.id) {
        setSelectedId(Number(data[0].id));
      }
      if (selectedId && !data.some((item) => Number(item.id) === Number(selectedId))) {
        setSelected(null);
      }
      setError("");
    } catch (err) {
      console.error("loadRequests erro:", err);
      setError(getErrMsg(err));
    } finally {
      if (!silent) setLoadingList(false);
    }
  }

  async function loadChat(id, silent = false) {
    if (!id) return;
    if (!silent) setLoadingChat(true);
    try {
      const [detailRes, msgRes] = await Promise.all([
        http.get(`/api/material/solicitacoes/${id}`),
        http.get(`/api/material/solicitacoes/${id}/mensagens`),
      ]);
      setSelected(detailRes.data || null);
      setMessages(Array.isArray(msgRes.data) ? msgRes.data : []);
      await http.patch(`/api/material/solicitacoes/${id}/visualizar-almoxarifado`);
      setError("");
    } catch (err) {
      console.error("loadChat erro:", err);
      setError(getErrMsg(err));
    } finally {
      if (!silent) setLoadingChat(false);
    }
  }

  useEffect(() => {
    loadRequests();
  }, [filter]);

  useEffect(() => {
    const t = setInterval(() => loadRequests(true), 5000);
    return () => clearInterval(t);
  }, [filter, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    loadChat(selectedId);
    if (!embedded) navigate(`${basePath}/${selectedId}`, { replace: true });
  }, [selectedId, embedded, basePath]);

  useEffect(() => {
    if (!selectedId) return;
    const t = setInterval(() => loadChat(selectedId, true), 4000);
    return () => clearInterval(t);
  }, [selectedId]);

  useEffect(() => {
    const el = msgBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function sendMessage() {
    const mensagem = String(text || "").trim();
    if (!selectedId || !mensagem || sending) return;
    try {
      setSending(true);
      await http.post(`/api/material/solicitacoes/${selectedId}/mensagens`, {
        usuario_nome: "Almoxarifado",
        perfil: "ALMOXARIFADO",
        mensagem,
      });
      setText("");
      await Promise.all([loadChat(selectedId, true), loadRequests(true)]);
    } catch (err) {
      alert("Erro ao enviar mensagem: " + getErrMsg(err));
    } finally {
      setSending(false);
    }
  }

  async function finishRequest(type, requestId = selectedId) {
    if (!requestId || acting) return;
    const isDelivered = type === "entregar";
    const isSeparating = type === "em-separacao";
    if (!isSeparating) {
      const question = isDelivered
        ? "Confirmar entrega deste material?"
        : "Tem certeza que deseja marcar esta solicitacao como SEM MATERIAL?";
      if (!window.confirm(question)) return;
    }

    try {
      setActing(`${type}-${requestId}`);
      await http.patch(`/api/material/solicitacoes/${requestId}/${type}`, {
        usuario_nome: "Almoxarifado",
        perfil: "ALMOXARIFADO",
        mensagem: "",
      });
      if (Number(requestId) === Number(selectedId)) {
        await Promise.all([loadChat(requestId, true), loadRequests(true)]);
      } else {
        await loadRequests(true);
      }
    } catch (err) {
      alert("Erro ao atualizar solicitacao: " + getErrMsg(err));
    } finally {
      setActing("");
    }
  }

  function isPendingRequest(item) {
    return ["AGUARDANDO_ALMOXARIFADO", "ABERTA", "EM_SEPARACAO"].includes(String(item?.status || "").toUpperCase());
  }

  return (
    <main className={embedded ? "almPage almPageEmbedded" : "almPage"}>
      <section className="almShell">
        <header className="almHeader">
          <div>
            <p className="almEyebrow">Almoxarifado</p>
            <h1>Chat de solicitações de material</h1>
            <span>Atendimentos enviados pelos operadores CNC.</span>
          </div>
          <button className="almRefresh" onClick={() => loadRequests()} disabled={loadingList}>
            <RefreshCw size={16} />
            {loadingList ? "Atualizando..." : "Atualizar"}
          </button>
        </header>

        <div className="almFilters">
          <div className="almTabs">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                className={filter === item.key ? "active" : ""}
                onClick={() => setFilter(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <label className="almSearch">
            <Search size={15} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar CNC, material, OP..." />
          </label>
        </div>

        {error ? <div className="almError">{error}</div> : null}

        <div className="almGrid">
          <aside className="almList" aria-label="Solicitações de material">
            {filteredRequests.length === 0 ? (
              <div className="almEmpty">Nenhuma solicitação encontrada.</div>
            ) : (
              filteredRequests.map((item) => {
                const unread = Number(item.nao_lidas_almoxarifado || 0);
                const active = Number(item.id) === Number(selectedId);
                return (
                  <div
                    key={item.id}
                    role="button"
                    tabIndex={0}
                    className={`almRequest ${active ? "active" : ""}`}
                    onClick={() => setSelectedId(Number(item.id))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId(Number(item.id));
                      }
                    }}
                  >
                    <div className="almRequestTop">
                      <strong>{item.maquina_id || "CNC"}</strong>
                      <span className={`almStatus ${statusClass(item.status)}`}>{item.status_label || item.status}</span>
                    </div>
                    <div className="almMaterial">{item.material || "Material não informado"}</div>
                    <div className="almMeta">{item.arquivo_nome || item.op || "Sem arquivo/OP"} · {item.operador_nome || "Operador"}</div>
                    <div className="almLast">
                      <span>{item.ultima_mensagem || "Sem mensagens"}</span>
                      {unread > 0 ? <b>{unread}</b> : null}
                    </div>
                    <small>{fmtDate(item.ultima_mensagem_em || item.criado_em)}</small>

                    {isPendingRequest(item) ? (
                      <div className="almCardActions" onClick={(e) => e.stopPropagation()}>
                        <button
                          className="separating"
                          onClick={() => finishRequest("em-separacao", item.id)}
                          disabled={Boolean(acting) || String(item.status || "").toUpperCase() === "EM_SEPARACAO"}
                        >
                          <Truck size={15} />
                          Estou separando
                        </button>
                        <button
                          className="deliver"
                          onClick={() => finishRequest("entregar", item.id)}
                          disabled={Boolean(acting)}
                        >
                          <PackageCheck size={15} />
                          Material entregue
                        </button>
                        <button
                          className="noMaterial"
                          onClick={() => finishRequest("sem-material", item.id)}
                          disabled={Boolean(acting)}
                        >
                          <XCircle size={15} />
                          Sem material
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })
            )}
          </aside>

          <section className="almChat">
            {!selected ? (
              <div className="almEmpty almEmptyChat">
                <MessageSquare size={32} />
                Selecione uma solicitação para abrir o chat.
              </div>
            ) : (
              <>
                <div className="almChatHead">
                  <div>
                    <div className="almChatTitle">
                      <strong>{selected.maquina_id}</strong>
                      <span className={`almStatus ${statusClass(selected.status)}`}>{selected.status_label || selected.status}</span>
                    </div>
                    <p>{selected.material || "Material não informado"}</p>
                    <small>{selected.arquivo_nome || selected.op || "Sem arquivo/OP"} · {selected.operador_nome || "Operador"}</small>
                  </div>
                </div>

                <div ref={msgBoxRef} className="almMessages">
                  {loadingChat ? (
                    <div className="almEmpty">Carregando chat...</div>
                  ) : messages.length === 0 ? (
                    <div className="almEmpty">Nenhuma mensagem ainda.</div>
                  ) : (
                    messages.map((msg) => {
                      const mine = String(msg.perfil || "").toUpperCase() === "ALMOXARIFADO";
                      const system = String(msg.tipo || "").toUpperCase() !== "USUARIO";
                      return (
                        <div key={msg.id} className={`almMsg ${mine ? "mine" : ""} ${system ? "system" : ""}`}>
                          <div className="almMsgBubble">
                            <div className="almMsgMeta">
                              <strong>{msg.usuario_nome || msg.perfil || "Sistema"}</strong>
                              <span>{msg.perfil}</span>
                              <time>{fmtDate(msg.criado_em)}</time>
                            </div>
                            <p>{msg.mensagem}</p>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>

                <div className="almInput">
                  <input
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                    placeholder="Digite a resposta para o operador..."
                    disabled={sending}
                  />
                  <button onClick={sendMessage} disabled={sending || !String(text || "").trim()}>
                    <Send size={16} />
                    {sending ? "Enviando..." : "Enviar"}
                  </button>
                </div>
              </>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}
