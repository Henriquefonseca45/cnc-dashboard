import axios from "axios";

export const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export const api = axios.create({
  baseURL: API_URL,
  timeout: 15000,
});

// Mensagem de erro amigável e útil pro operador/programador
export function getErrMsg(err) {
  // axios timeout
  if (err?.code === "ECONNABORTED") return "Timeout ao conectar no backend.";

  // sem resposta (backend offline / CORS / rede / DNS)
  if (!err?.response) {
    // erro típico de CORS em browser vira "Network Error"
    if (String(err?.message || "").toLowerCase().includes("network error")) {
      return "Falha de rede/CORS. Verifique VITE_API_URL, CORS do backend e se a API está acessível.";
    }
    return `Sem resposta do backend. Verifique se a API está online (${API_URL}).`;
  }

  const status = err.response.status;
  const data = err.response.data;

  // tenta extrair detalhe do FastAPI
  const detail =
    (typeof data === "string" && data) ||
    data?.detail ||
    data?.message ||
    JSON.stringify(data);

  if (status === 400) return `Requisição inválida (400): ${detail}`;
  if (status === 401) return `Não autorizado (401): ${detail}`;
  if (status === 403) return `Acesso negado (403): ${detail}`;
  if (status === 404) return `Endpoint não encontrado (404): ${detail}`;
  if (status >= 500) return `Erro no servidor (${status}): ${detail}`;

  return `Erro (${status}): ${detail}`;
}

// Log mínimo (sem "sujar" a UI) e mantém o throw para o dashboard tratar
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const url = error?.config?.url;
    console.error("API ERROR:", { status, url, message: error?.message, data: error?.response?.data });
    return Promise.reject(error);
  }
);