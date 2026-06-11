import { useEffect, useState } from "react";
import api from "../services/api";

function minutesSince(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const min = Math.max(0, Math.floor(diffMs / 60000));
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h ${m}m`;
}

export default function Dashboard() {
  const [maquinas, setMaquinas] = useState([]);
  const [filas, setFilas] = useState({});
  const [error, setError] = useState("");

  async function carregar() {
    setError("");
    try {
      const res = await api.get("/maquinas");
      setMaquinas(res.data);

      // pré-carrega fila de cada máquina
      res.data.forEach((m) => carregarFila(m.id));
    } catch (e) {
      console.error(e);
      setError("Falha ao carregar /maquinas. Veja o console (F12).");
    }
  }

  async function carregarFila(id) {
    try {
      const res = await api.get(`/fila/${encodeURIComponent(id)}`);
      setFilas((prev) => ({ ...prev, [id]: res.data }));
    } catch (e) {
      console.warn("Falha ao carregar fila", id, e);
      setFilas((prev) => ({ ...prev, [id]: null }));
    }
  }

  useEffect(() => {
    carregar();
    // auto refresh a cada 5s (opcional)
    const t = setInterval(carregar, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <div style={{ padding: 20, fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h1 style={{ margin: 0 }}>CNC Dashboard</h1>
        <button onClick={carregar}>Atualizar</button>
      </div>

      {error && (
        <div style={{ marginTop: 12, padding: 12, border: "1px solid #f99", borderRadius: 8 }}>
          {error}
        </div>
      )}

      <div style={{ marginTop: 16, display: "flex", gap: 16, flexWrap: "wrap" }}>
        {maquinas.map((m) => {
          const fila = filas[m.id];

          return (
            <div
              key={m.id}
              style={{
                width: 320,
                border: "1px solid #ddd",
                borderRadius: 12,
                padding: 14,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800 }}>{m.nome}</div>
                  <div style={{ opacity: 0.75 }}>ID: {m.id}</div>
                </div>

                <div
                  style={{
                    padding: "6px 10px",
                    borderRadius: 999,
                    border: "1px solid #ccc",
                    height: "fit-content",
                    fontWeight: 800,
                  }}
                >
                  {m.status}
                </div>
              </div>

              <div style={{ marginTop: 10, opacity: 0.8 }}>
                Status desde: <b>{minutesSince(m.status_desde)}</b>
              </div>

              <div style={{ marginTop: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ fontWeight: 800 }}>Fila</div>
                  <button onClick={() => carregarFila(m.id)}>Recarregar</button>
                </div>

                {fila === undefined && <div style={{ marginTop: 8 }}>Carregando...</div>}
                {fila === null && <div style={{ marginTop: 8 }}>Erro ao buscar fila.</div>}
                {Array.isArray(fila) && fila.length === 0 && <div style={{ marginTop: 8 }}>Fila vazia ✅</div>}

                {Array.isArray(fila) && fila.length > 0 && (
                  <ol style={{ marginTop: 8, paddingLeft: 18 }}>
                    {fila.map((item, i) => (
                      <li key={item.id ?? i}>
                        {item.arquivo_nome || item.nome || item.file_name || JSON.stringify(item)}
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
