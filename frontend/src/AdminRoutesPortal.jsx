import React, { useEffect, useMemo, useState } from "react";
import { Copy, ExternalLink, Search, Star, StarOff } from "lucide-react";
import { adminRoutes } from "./routes/adminRoutes.js";
import "./AdminRoutesPortal.css";

const FAVORITES_KEY = "cnc_admin_route_favorites";
const RECENTS_KEY = "cnc_admin_route_recents";

function readStorage(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // localStorage pode estar bloqueado em alguns navegadores.
  }
}

function currentUserRole() {
  try {
    return (window.localStorage.getItem("cnc_user_role") || "admin").toLowerCase();
  } catch {
    return "admin";
  }
}

function flattenRoutes(groups) {
  return groups.flatMap((group) =>
    group.itens.map((item) => ({
      ...item,
      grupo: group.grupo,
      key: `${group.grupo}:${item.nome}:${item.rota}`,
    }))
  );
}

function canSeeRoute(item, role) {
  if (role === "admin") return true;
  return (item.perfis || []).map((p) => String(p).toLowerCase()).includes(role);
}

function routeUrl(path) {
  return `${window.location.origin}${path}`;
}

export default function AdminRoutesPortal() {
  const role = currentUserRole();
  const isAdmin = role === "admin";
  const [query, setQuery] = useState("");
  const [favorites, setFavorites] = useState(() => readStorage(FAVORITES_KEY, []));
  const [recents, setRecents] = useState(() => readStorage(RECENTS_KEY, []));
  const [copied, setCopied] = useState("");

  useEffect(() => writeStorage(FAVORITES_KEY, favorites), [favorites]);
  useEffect(() => writeStorage(RECENTS_KEY, recents), [recents]);

  const allItems = useMemo(() => flattenRoutes(adminRoutes).filter((item) => canSeeRoute(item, role)), [role]);

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const groups = [];
    for (const group of adminRoutes) {
      const itens = group.itens
        .map((item) => ({ ...item, grupo: group.grupo, key: `${group.grupo}:${item.nome}:${item.rota}` }))
        .filter((item) => canSeeRoute(item, role))
        .filter((item) => {
          if (!q) return true;
          return [item.nome, item.rota, item.descricao, item.grupo].join(" ").toLowerCase().includes(q);
        });
      if (itens.length > 0) groups.push({ grupo: group.grupo, itens });
    }
    return groups;
  }, [query, role]);

  const favoriteItems = useMemo(
    () => favorites.map((key) => allItems.find((item) => item.key === key)).filter(Boolean),
    [favorites, allItems]
  );

  const recentItems = useMemo(
    () => recents.map((key) => allItems.find((item) => item.key === key)).filter(Boolean),
    [recents, allItems]
  );

  function toggleFavorite(item) {
    setFavorites((prev) =>
      prev.includes(item.key) ? prev.filter((key) => key !== item.key) : [item.key, ...prev]
    );
  }

  function registerRecent(item) {
    setRecents((prev) => [item.key, ...prev.filter((key) => key !== item.key)].slice(0, 8));
  }

  function openRoute(item, newTab = false) {
    if (!item.ativo) return;
    registerRecent(item);
    if (newTab) {
      window.open(item.rota, "_blank", "noopener,noreferrer");
      return;
    }
    window.location.href = item.rota;
  }

  async function copyRoute(item) {
    const text = routeUrl(item.rota);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(item.key);
      window.setTimeout(() => setCopied(""), 1600);
    } catch {
      const input = document.createElement("input");
      input.value = text;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(item.key);
      window.setTimeout(() => setCopied(""), 1600);
    }
  }

  function RouteCard({ item, compact = false }) {
    const isFav = favorites.includes(item.key);
    return (
      <article className={`adminRouteCard ${!item.ativo ? "disabled" : ""} ${compact ? "compact" : ""}`}>
        <div className="adminRouteTop">
          <div>
            <span className="adminRouteGroup">{item.grupo}</span>
            <h3>{item.nome}</h3>
          </div>
          <button className="adminRouteIconBtn" onClick={() => toggleFavorite(item)} title={isFav ? "Remover favorito" : "Favoritar"}>
            {isFav ? <Star size={18} /> : <StarOff size={18} />}
          </button>
        </div>
        <code>{item.rota}</code>
        <p>{item.descricao}</p>
        <div className="adminRouteMeta">
          <span className={item.ativo ? "active" : "dev"}>{item.ativo ? "Ativa" : "Em desenvolvimento"}</span>
          <span>{(item.perfis || []).join(", ")}</span>
        </div>
        <div className="adminRouteActions">
          <button onClick={() => openRoute(item)} disabled={!item.ativo}>Abrir</button>
          <button onClick={() => copyRoute(item)}>
            <Copy size={15} />
            {copied === item.key ? "Copiado" : "Copiar link"}
          </button>
          <button onClick={() => openRoute(item, true)} disabled={!item.ativo} title="Abrir em nova aba">
            <ExternalLink size={15} />
            Nova aba
          </button>
        </div>
      </article>
    );
  }

  if (!isAdmin) {
    return (
      <main className="adminRoutesPage">
        <section className="adminRoutesBlocked">
          <h1>Acesso restrito</h1>
          <p>A Central Admin é exclusiva para usuários Admin.</p>
          <button onClick={() => { window.location.href = "/"; }}>Voltar</button>
        </section>
      </main>
    );
  }

  return (
    <main className="adminRoutesPage">
      <section className="adminRoutesShell">
        <header className="adminRoutesHeader">
          <div>
            <p>Central Admin</p>
            <h1>Mapa do Sistema</h1>
            <span>Todos os atalhos importantes do CNC Dashboard em um só lugar.</span>
          </div>
          <label className="adminRoutesSearch">
            <Search size={17} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por nome, rota, descrição ou grupo..."
            />
          </label>
        </header>

        {favoriteItems.length > 0 && (
          <section className="adminRoutesSection">
            <div className="adminRoutesSectionTitle">
              <h2>Favoritos</h2>
              <span>{favoriteItems.length}</span>
            </div>
            <div className="adminRoutesGrid featured">
              {favoriteItems.map((item) => <RouteCard key={`fav-${item.key}`} item={item} compact />)}
            </div>
          </section>
        )}

        {recentItems.length > 0 && (
          <section className="adminRoutesSection">
            <div className="adminRoutesSectionTitle">
              <h2>Últimas acessadas</h2>
              <span>{recentItems.length}</span>
            </div>
            <div className="adminRoutesGrid recent">
              {recentItems.map((item) => <RouteCard key={`recent-${item.key}`} item={item} compact />)}
            </div>
          </section>
        )}

        {filteredGroups.map((group) => (
          <section key={group.grupo} className="adminRoutesSection">
            <div className="adminRoutesSectionTitle">
              <h2>{group.grupo}</h2>
              <span>{group.itens.length}</span>
            </div>
            <div className="adminRoutesGrid">
              {group.itens.map((item) => <RouteCard key={item.key} item={item} />)}
            </div>
          </section>
        ))}
      </section>
    </main>
  );
}
