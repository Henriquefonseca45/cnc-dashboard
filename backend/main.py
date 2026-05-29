from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List
import shutil
import os
import sqlite3
import json
import re
import unicodedata

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from io import BytesIO
from urllib.parse import quote
from openpyxl import Workbook

from backend.db import get_conn
from backend.config_maquinas import MAQUINAS

# =========================
# APP
# =========================
app = FastAPI(title="CNC Dashboard API")
BASE_DIR = Path(__file__).resolve().parent  # .../cnc-dashboard/backend
FRONT_DIST = BASE_DIR.parent / "frontend" / "dist"
FRONT_ASSETS = FRONT_DIST / "assets"
TEST_MACHINE_ID = "CNC_TESTE"
TEST_MACHINE_IDS = {TEST_MACHINE_ID}

# =========================
# UI (Painel + Dashboard + Agente + Visual)
# =========================
@app.get("/ui/visual", include_in_schema=False)
def ui_visual():
    return FileResponse(BASE_DIR / "static" / "painel.html")


@app.get("/ui/painel", include_in_schema=False)
def ui_painel():
    return FileResponse(BASE_DIR / "static" / "painel.html")


@app.get("/ui/operador/{maquina_id}", include_in_schema=False)
def ui_operador(maquina_id: str):
    return FileResponse(BASE_DIR / "static" / "operador.html")


@app.get("/ui/agente/{maquina_id}", include_in_schema=False)
def ui_agente(maquina_id: str):
    return FileResponse(BASE_DIR / "static" / "agente.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

if FRONT_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=FRONT_ASSETS), name="frontend-assets")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page():
    if FRONT_DIST.exists() and (FRONT_DIST / "index.html").exists():
        return FileResponse(FRONT_DIST / "index.html")
    return FileResponse(BASE_DIR / "static" / "dashboard.html")


# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://192.168.17.152:5173",
        "http://192.168.17.152:5174",
        "http://192.168.17.227:5173",
        "http://192.168.17.227:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# STORAGE
# =========================
DXF_DIR = BASE_DIR.parent / "storage" / "dxf"
DXF_DIR.mkdir(parents=True, exist_ok=True)
CHAT_DIR = BASE_DIR.parent / "storage" / "chat"
CHAT_DIR.mkdir(parents=True, exist_ok=True)
CHAT_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_CHAT_IMAGE_BYTES = 8 * 1024 * 1024

# =========================
# MÉTRICAS
# =========================
HORAS_DIA_MAQUINA = 17
MINUTOS_DIA_MAQUINA = HORAS_DIA_MAQUINA * 60
SEGUNDOS_DIA_MAQUINA = MINUTOS_DIA_MAQUINA * 60

# =========================
# MODELS
# =========================
class StatusRequest(BaseModel):
    status: str
    motivo: str | None = None


class AddFilaRequest(BaseModel):
    arquivo_id: int


class ReorderFilaRequest(BaseModel):
    """
    Compatível com:
      { "ordem": [1,2,3] }  (antigo)
      { "ordered_item_ids": [1,2,3] } (novo)
    """
    ordem: List[int] | None = None
    ordered_item_ids: List[int] | None = None

    def ids(self) -> List[int]:
        base = self.ordered_item_ids if self.ordered_item_ids is not None else self.ordem
        base = base or []
        out: List[int] = []
        for x in base:
            try:
                xi = int(x)
                if xi > 0:
                    out.append(xi)
            except Exception:
                pass
        return out


class ChatMensagemIn(BaseModel):
    maquina_id: str
    autor: str
    mensagem: str


class ChatMensagemOut(BaseModel):
    id: int
    maquina_id: str
    autor: str
    mensagem: str
    criado_em: str
    imagem_url: str | None = None
    imagem_nome: str | None = None
    imagem_tipo: str | None = None


class MaterialSolicitacaoIn(BaseModel):
    maquina_id: str
    item_id: int | None = None
    arquivo_nome: str | None = None
    material: str | None = None


class MaterialEntregaIn(BaseModel):
    maquina_id: str
    item_id: int


class CortadoRequest(BaseModel):
    ok: bool = True


class FilaStatusRequest(BaseModel):
    id: int
    status: str  # PROGRAMADO | USINANDO | CONCLUIDO | CANCELADO
    motivo: str | None = None


class MoveFilaItemRequest(BaseModel):
    manter_status: bool = False


class TempoEstimadoIn(BaseModel):
    minutos: int


class OperadorPayload(BaseModel):
    nome: str


# =========================
# HELPERS (PROGRAMADOR / FILA)
# =========================
def _fila_programador_status_list():
    return ("AGUARDANDO", "PROGRAMANDO")


def _fila_ativa_status_list():
    return ("AGUARDANDO", "PROGRAMANDO", "EM_EXECUCAO", "BAIXADO")


def _fila_finalizada_status_list():
    return ("CORTADO", "CANCELADO")


def _normalizar_nome_arquivo(nome: str | None) -> str:
    return Path(str(nome or "")).name.strip().lower()


def _arquivo_ja_cortado_por_nome(conn, nome: str | None):
    nome_norm = _normalizar_nome_arquivo(nome)
    if not nome_norm:
        return None

    return conn.execute(
        """
        SELECT
            a.id AS arquivo_id,
            a.nome AS arquivo_nome,
            fi.id AS fila_item_id,
            fi.maquina_id
        FROM arquivos_dxf a
        LEFT JOIN fila_itens fi
               ON fi.arquivo_id = a.id
              AND UPPER(COALESCE(fi.status,'')) = 'CORTADO'
        WHERE LOWER(TRIM(a.nome)) = ?
          AND (
            UPPER(COALESCE(a.status,'')) = 'CORTADO'
            OR fi.id IS NOT NULL
          )
        ORDER BY
            CASE WHEN fi.id IS NOT NULL THEN 0 ELSE 1 END,
            COALESCE(fi.finalizado_em, fi.criado_em, a.criado_em) DESC,
            a.id DESC
        LIMIT 1
        """,
        (nome_norm,),
    ).fetchone()


def _arquivo_ja_em_fila_por_nome(conn, nome: str | None):
    nome_norm = _normalizar_nome_arquivo(nome)
    if not nome_norm:
        return None

    return conn.execute(
        """
        SELECT
            a.id AS arquivo_id,
            a.nome AS arquivo_nome,
            fi.id AS fila_item_id,
            fi.maquina_id,
            fi.status
        FROM arquivos_dxf a
        JOIN fila_itens fi ON fi.arquivo_id = a.id
        WHERE LOWER(TRIM(a.nome)) = ?
          AND UPPER(COALESCE(a.status,'')) <> 'EXCLUIDO'
          AND UPPER(COALESCE(fi.status,'')) IN ('AGUARDANDO','PROGRAMANDO','BAIXADO','EM_EXECUCAO')
        ORDER BY fi.criado_em DESC, fi.id DESC
        LIMIT 1
        """,
        (nome_norm,),
    ).fetchone()


def _detalhe_arquivo_ja_cortado(nome: str | None, row=None):
    arquivo_nome = Path(str(nome or "")).name
    maquina_id = None
    if row is not None:
        try:
            maquina_id = row["maquina_id"]
        except Exception:
            maquina_id = None

    if maquina_id:
        msg = f"Arquivo '{arquivo_nome}' ja foi CORTADO na maquina {maquina_id} e nao pode entrar novamente na fila."
    else:
        msg = f"Arquivo '{arquivo_nome}' ja foi CORTADO e nao pode entrar novamente na fila."

    return {
        "code": "ARQUIVO_JA_CORTADO",
        "message": msg,
        "arquivo_nome": arquivo_nome,
        "maquina_id": maquina_id,
    }


def _detalhe_arquivo_ja_em_fila(nome: str | None, row=None):
    arquivo_nome = Path(str(nome or "")).name
    maquina_id = None
    status = None
    if row is not None:
        try:
            maquina_id = row["maquina_id"]
        except Exception:
            maquina_id = None
        try:
            status = row["status"]
        except Exception:
            status = None

    if maquina_id:
        msg = f"Arquivo '{arquivo_nome}' ja esta na fila da maquina {maquina_id}."
    else:
        msg = f"Arquivo '{arquivo_nome}' ja esta em uma fila de maquina."

    return {
        "code": "ARQUIVO_JA_EM_FILA",
        "message": msg,
        "arquivo_nome": arquivo_nome,
        "maquina_id": maquina_id,
        "status": status,
    }


def _marcar_arquivos_mesmo_nome_como_cortado(conn, arquivo_id: int):
    conn.execute(
        """
        UPDATE arquivos_dxf
        SET status='CORTADO'
        WHERE LOWER(TRIM(nome)) = (
            SELECT LOWER(TRIM(nome))
            FROM arquivos_dxf
            WHERE id = ?
        )
        """,
        (arquivo_id,),
    )


def _ensure_arquivos_cols(conn):
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE arquivos_dxf ADD COLUMN status TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE arquivos_dxf ADD COLUMN deleted_em TEXT")
    except Exception:
        pass


def _ensure_maquinas_cols(conn):
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE maquinas ADD COLUMN operador_nome TEXT")
    except Exception:
        pass


def _ensure_test_maquina(conn):
    _ensure_maquinas_cols(conn)
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT OR IGNORE INTO maquinas (id, nome, status, status_desde)
        VALUES (?, ?, 'PARADA', ?)
        """,
        (TEST_MACHINE_ID, "CNC TESTE", now),
    )


def _ensure_chat_mensagens_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            maquina_id TEXT NOT NULL,
            autor TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            imagem_path TEXT,
            imagem_nome TEXT,
            imagem_tipo TEXT
        )
        """
    )
    for col, ddl in (
        ("imagem_path", "ALTER TABLE chat_mensagens ADD COLUMN imagem_path TEXT"),
        ("imagem_nome", "ALTER TABLE chat_mensagens ADD COLUMN imagem_nome TEXT"),
        ("imagem_tipo", "ALTER TABLE chat_mensagens ADD COLUMN imagem_tipo TEXT"),
    ):
        try:
            cur.execute(ddl)
        except Exception:
            pass
    conn.commit()


def _ensure_material_solicitacoes_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS material_solicitacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            maquina_id TEXT NOT NULL,
            item_id INTEGER,
            arquivo_nome TEXT,
            material TEXT,
            status TEXT NOT NULL DEFAULT 'ABERTA',
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            atendido_em TEXT
        )
        """
    )
    conn.commit()


def _infer_material_from_arquivo_nome(nome: str | None) -> str:
    clean = (nome or "").strip()
    if "." in clean:
        clean = clean.rsplit(".", 1)[0].strip()

    parts = [p.strip() for p in clean.split(" - ") if p.strip()]
    if len(parts) >= 5:
        return " - ".join(parts[4:]).strip()

    code_match = re.search(r"(\d+(?:[,.]\d+)?\s*(?:TX|KP|AD)\b.*)$", clean, flags=re.IGNORECASE)
    if code_match:
        return re.sub(r"\s+(?=(?:TX|KP|AD)\b)", "", code_match.group(1), count=1, flags=re.IGNORECASE).strip()

    up = clean.upper()
    idx = up.find("MM")
    if idx > 0:
        start = idx
        while start > 0 and (clean[start - 1].isdigit() or clean[start - 1] in ",. "):
            start -= 1
        return clean[start:].strip()

    return ""


def _marcar_material_solicitacoes_entregues(conn, maquina_id: str, item_id: int, entregue_em: str):
    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE material_solicitacoes
        SET status = 'ENTREGUE',
            atendido_em = COALESCE(atendido_em, ?)
        WHERE maquina_id = ?
          AND item_id = ?
          AND status = 'ABERTA'
        """,
        ((entregue_em or datetime.now().isoformat(timespec="seconds")), maquina_id.upper().strip(), item_id),
    )
    return cur.rowcount


def _get_material_solicitacao_aberta(conn, maquina_id: str, item_id: int):
    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()
    return cur.execute(
        """
        SELECT id, material, arquivo_nome
        FROM material_solicitacoes
        WHERE maquina_id = ?
          AND item_id = ?
          AND status = 'ABERTA'
        ORDER BY id DESC
        LIMIT 1
        """,
        ((maquina_id or "").upper().strip(), item_id),
    ).fetchone()


def _material_setup_bloqueio_detail(conn, maquina_id: str, item_id: int):
    req = _get_material_solicitacao_aberta(conn, maquina_id, item_id)
    if not req:
        return None

    material = req["material"] or "material solicitado"
    return (
        "Material solicitado ainda nao teve setup confirmado. "
        f"Confirme o Setup de material antes de colocar em USINANDO ({material})."
    )


def _get_fila_programador(conn, maquina_id: str):
    cur = conn.cursor()
    status_list = _fila_programador_status_list()
    rows = cur.execute(
        f"""
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, fi.criado_em,
               a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ({",".join(["?"] * len(status_list))})
        ORDER BY fi.posicao ASC, fi.id ASC
        """,
        (maquina_id, *status_list),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_em_execucao_id(conn, maquina_id: str):
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id
        FROM fila_itens
        WHERE maquina_id = ? AND status = 'EM_EXECUCAO'
        ORDER BY posicao ASC, id ASC
        LIMIT 1
        """,
        (maquina_id,),
    ).fetchone()
    return row["id"] if row else None


def _reindex_fila(conn, maquina_id: str):
    cur = conn.cursor()

    em_exec_id = _get_em_execucao_id(conn, maquina_id)
    if em_exec_id:
        cur.execute("UPDATE fila_itens SET posicao = 0 WHERE id = ?", (em_exec_id,))

    fila_prog = _get_fila_programador(conn, maquina_id)
    for i, it in enumerate(fila_prog, start=1):
        cur.execute("UPDATE fila_itens SET posicao = ? WHERE id = ?", (i, it["id"]))


def _assert_no_other_em_execucao(conn, maquina_id: str, this_item_id: int):
    current = _get_em_execucao_id(conn, maquina_id)
    if current and current != this_item_id:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe item em execução nesta máquina (fila_item_id={current}). Finalize antes de iniciar outro.",
        )


def _ensure_fila_itens_cols(conn):
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE fila_itens ADD COLUMN started_em TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE fila_itens ADD COLUMN finalizado_em TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE fila_itens ADD COLUMN tempo_estimado_seg INTEGER")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE fila_itens ADD COLUMN tempo_inicio_em TEXT")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE fila_itens ADD COLUMN tempo_pausado_seg INTEGER")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE fila_itens ADD COLUMN tempo_pausa_inicio_em TEXT")
    except Exception:
        pass


def _ensure_chapa_movimentacao_log_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chapa_movimentacao_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fila_item_id INTEGER,
            arquivo_id INTEGER,
            arquivo_nome TEXT,
            acao TEXT NOT NULL,
            operador_nome TEXT,
            maquina_origem TEXT,
            maquina_destino TEXT,
            posicao_origem INTEGER,
            posicao_destino INTEGER,
            status_origem TEXT,
            status_destino TEXT,
            detalhe TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    try:
        cur.execute("ALTER TABLE chapa_movimentacao_log ADD COLUMN operador_nome TEXT")
    except Exception:
        pass


def _get_operador_nome_for_machine(conn, maquina_id: str | None) -> str | None:
    _ensure_maquinas_cols(conn)
    mid = (maquina_id or "").upper().strip()
    if not mid:
        return None
    row = conn.execute(
        "SELECT operador_nome FROM maquinas WHERE id = ?",
        (mid,),
    ).fetchone()
    nome = ((row["operador_nome"] if row else "") or "").strip()
    return nome or "Operador nao informado"


def _fila_item_log_snapshot(conn, item_id: int):
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()
    return cur.execute(
        """
        SELECT
            fi.id,
            fi.maquina_id,
            fi.arquivo_id,
            fi.posicao,
            fi.status,
            a.nome AS arquivo_nome
        FROM fila_itens fi
        LEFT JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ?
        """,
        (item_id,),
    ).fetchone()


def _log_chapa_movimentacao(
    conn,
    acao: str,
    *,
    fila_item_id=None,
    arquivo_id=None,
    arquivo_nome=None,
    maquina_origem=None,
    maquina_destino=None,
    posicao_origem=None,
    posicao_destino=None,
    status_origem=None,
    status_destino=None,
    operador_nome=None,
    detalhe=None,
):
    _ensure_chapa_movimentacao_log_table(conn)
    conn.execute(
        """
        INSERT INTO chapa_movimentacao_log (
            fila_item_id,
            arquivo_id,
            arquivo_nome,
            acao,
            operador_nome,
            maquina_origem,
            maquina_destino,
            posicao_origem,
            posicao_destino,
            status_origem,
            status_destino,
            detalhe,
            criado_em
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fila_item_id,
            arquivo_id,
            arquivo_nome,
            acao,
            operador_nome,
            maquina_origem,
            maquina_destino,
            posicao_origem,
            posicao_destino,
            status_origem,
            status_destino,
            detalhe,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


# =========================
# HELPERS: LOG DE STATUS / DASHBOARD
# =========================
def _ensure_maquina_status_log_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maquina_status_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            maquina_id TEXT NOT NULL,
            status TEXT NOT NULL,
            motivo TEXT,
            inicio_em TEXT NOT NULL,
            fim_em TEXT,
            criado_em TEXT NOT NULL
        )
        """
    )


def _infer_motivo_from_status(status: str) -> str | None:
    s = (status or "").strip().upper()

    if _is_machine_usinando(s):
        return "USINANDO"
    if "RNC" in s:
        return "RNC"
    if "ABERTURA" in s and "MATERIAL" in s:
        return "ABERTURA MATERIAL"
    if "SETUP" in s:
        return "SETUP"
    if "MANUT" in s:
        return "MANUTENCAO"
    if "EMPILH" in s:
        return "FALTA MATERIAL"
    if "PROG" in s:
        return "PROGRAMACAO"
    if "REUNIA" in s:
        return "REUNIAO"
    if "REFEI" in s:
        return "REFEICAO"
    if "DESLIG" in s:
        return "DESLIGADA"
    if "OCIOS" in s:
        return "OCIOSA"
    if "PAR" in s:
        return "PARADA"
    if "USIN" in s or "CORT" in s:
        return "USINANDO"
    return None


def _normalize_status_compare(status: str) -> str:
    return (status or "").strip().upper()


def _normalize_match_text(value: str) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.upper()


def _get_usinagem_tipo_permitido(arquivo_nome: str) -> str:
    nome = _normalize_match_text(arquivo_nome)
    if "ABERTURA DE MATERIAL" in nome or "ABERTURA MATERIAL" in nome:
        return "ABERTURA MATERIAL"
    if "DETALHE" in nome:
        return "DETALHE CNC"
    if "RNC" in nome:
        return "RNC"
    return "USINANDO"


def _canonical_usinagem_status(status: str) -> str:
    s = _normalize_status_compare(status)
    if s == "USINANDO DETALHE":
        return "DETALHE CNC"
    if s == "USINANDO RNC":
        return "RNC"
    if s in {"USINANDO ABERTURA DE MATERIAL", "ABERTURA DE MATERIAL"}:
        return "ABERTURA MATERIAL"
    return s


def _is_usinagem_status(status: str) -> bool:
    s = _canonical_usinagem_status(status)
    return s in {
        "USINANDO",
        "DETALHE CNC",
        "RNC",
        "ABERTURA MATERIAL",
    }


def _validate_usinagem_status_arquivo(conn, maquina_id: str, status: str):
    status_norm = _canonical_usinagem_status(status)
    if not _is_usinagem_status(status_norm):
        return

    row = conn.execute(
        """
        SELECT a.nome AS arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status = 'EM_EXECUCAO'
        ORDER BY fi.posicao ASC, fi.id ASC
        LIMIT 1
        """,
        (maquina_id,),
    ).fetchone()

    arquivo_nome = row["arquivo_nome"] if row else ""
    permitido = _get_usinagem_tipo_permitido(arquivo_nome)
    if status_norm != permitido:
        raise HTTPException(
            status_code=409,
            detail=f"Este arquivo so pode ser colocado como {permitido}.",
        )


def _close_open_status_log(conn, maquina_id: str, fim_iso: str):
    _ensure_maquina_status_log_table(conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE maquina_status_log
        SET fim_em = ?
        WHERE maquina_id = ?
          AND fim_em IS NULL
        """,
        (fim_iso, maquina_id),
    )


def _open_status_log(conn, maquina_id: str, status: str, motivo: str | None, inicio_iso: str):
    _ensure_maquina_status_log_table(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO maquina_status_log
        (maquina_id, status, motivo, inicio_em, fim_em, criado_em)
        VALUES (?, ?, ?, ?, NULL, ?)
        """,
        (maquina_id, status, motivo, inicio_iso, inicio_iso),
    )


def _status_is_usinando(status: str) -> bool:
    s = (status or "").strip().upper()
    return ("USIN" in s) or ("CORT" in s)


def _status_is_setup(status: str) -> bool:
    s = (status or "").strip().upper()
    return "SETUP" in s


def _status_is_indisponivel(status: str) -> bool:
    s = (status or "").strip().upper()
    termos = [
        "MANUT",
        "EMPILH",
        "PAR",
        "DESLIG",
        "REFEI",
        "REUNIA",
        "SETUP",
        "OCIOS",
    ]
    return any(t in s for t in termos)


def _dashboard_bucket_from_status(status: str, motivo: str | None = None) -> str:
    s = (status or "").strip().upper()
    m = (motivo or "").strip().upper()

    txt = f"{s} {m}".strip()

    if _is_machine_usinando(s):
        return "usinando"
    if "RNC" in txt:
        return "rnc"
    if "ABERTURA" in txt and "MATERIAL" in txt:
        return "abertura_material"
    if "USIN" in txt or "CORT" in txt:
        return "usinando"
    if "SETUP" in txt or ("TROCA" in txt and "SACRIFIC" in txt):
        return "setup"
    if "MANUT" in txt:
        return "manutencao"
    if ("AGUAR" in txt or "AGUARD" in txt) and ("EMPILH" in txt or "EMPILHADEIRA" in txt):
        return "falta_material"
    if "EMPILH" in txt:
        return "falta_material"
    if "PROG" in txt:
        return "programacao"
    if "REUNIA" in txt:
        return "reuniao"
    if "REFEI" in txt:
        return "refeicao"
    if "DESLIG" in txt:
        return "desligada"
    if "OCIOS" in txt:
        return "ociosa"
    if "PAR" in txt:
        return "parada"
    return "outros"


def _dashboard_special_bucket_from_status(status: str, motivo: str | None = None) -> str | None:
    s = _canonical_usinagem_status(status)
    m = _normalize_status_compare(motivo or "")
    txt = f"{s} {m}".strip()

    if s == "RNC" or "USINANDO RNC" in txt:
        return "rnc"
    if s == "ABERTURA MATERIAL" or "ABERTURA MATERIAL" in txt or "ABERTURA DE MATERIAL" in txt:
        return "abertura_material"
    return None


# =========================
# HELPERS: SNAPSHOT DIÁRIO DO DASHBOARD
# =========================
def _ensure_dashboard_snapshot_daily_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_snapshot_daily (
            data_ref TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            atualizado_em TEXT NOT NULL
        )
        """
    )


def _daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d = d + timedelta(days=1)


def _compute_dashboard_indicadores(conn, dt_ini_base: datetime, dt_fim_base: datetime):
    """
    Cálculo central do dashboard.
    Usa somente os dados persistidos no banco.
    """

    _ensure_maquina_status_log_table(conn)
    _ensure_maquinas_cols(conn)
    cur = conn.cursor()

    now_dt = datetime.now()

    maquinas = cur.execute(
        """
        SELECT id, status, status_desde, operador_nome
        FROM maquinas
        WHERE id NOT IN ({})
        ORDER BY id
        """.format(",".join(["?"] * len(TEST_MACHINE_IDS))),
        tuple(TEST_MACHINE_IDS),
    ).fetchall()
    total_maquinas = len(maquinas)

    total_days = (dt_fim_base.date() - dt_ini_base.date()).days + 1
    if total_days <= 0:
        total_days = 1

    capacidade_por_maquina_seg = SEGUNDOS_DIA_MAQUINA * total_days
    tempo_total_seg = total_maquinas * capacidade_por_maquina_seg

    bucket_keys = [
        "usinando",
        "setup",
        "manutencao",
        "falta_material",
        "programacao",
        "reuniao",
        "refeicao",
        "desligada",
        "ociosa",
        "parada",
        "outros",
    ]

    special_bucket_keys = ["rnc", "abertura_material"]

    totals = {k: 0 for k in bucket_keys}
    special_totals = {k: 0 for k in special_bucket_keys}

    per_machine = {
        m["id"]: {
            "maquina": m["id"],
            "operador_nome": m["operador_nome"] or "",
            "status_atual": m["status"] or "",
            "qtd_setups": 0,
            "qtd_falta_material": 0,
            **{k: 0 for k in bucket_keys},
        }
        for m in maquinas
    }

    qtd_setups = 0
    qtd_falta_material = 0

    def overlap_seconds(seg_ini: datetime, seg_fim: datetime) -> int:
        ini = max(seg_ini, dt_ini_base)
        fim = min(seg_fim, dt_fim_base)
        if fim <= ini:
            return 0
        return int((fim - ini).total_seconds())

    logs = cur.execute(
        """
        SELECT maquina_id, status, motivo, inicio_em, fim_em
        FROM maquina_status_log
        WHERE NOT (
            COALESCE(fim_em, ?) < ?
            OR inicio_em > ?
        )
        ORDER BY maquina_id, inicio_em
        """,
        (
            now_dt.isoformat(timespec="seconds"),
            dt_ini_base.isoformat(timespec="seconds"),
            dt_fim_base.isoformat(timespec="seconds"),
        ),
    ).fetchall()

    for r in logs:
        maquina_id = r["maquina_id"]
        if maquina_id not in per_machine:
            continue

        try:
            seg_ini = datetime.fromisoformat(r["inicio_em"])
            seg_fim = datetime.fromisoformat(r["fim_em"] or now_dt.isoformat(timespec="seconds"))
        except Exception:
            continue

        secs = overlap_seconds(seg_ini, seg_fim)
        if secs <= 0:
            continue

        special_bucket = _dashboard_special_bucket_from_status(r["status"], r["motivo"])
        if special_bucket in special_totals:
            special_totals[special_bucket] += secs

        bucket = _dashboard_bucket_from_status(r["status"], r["motivo"])
        totals[bucket] += secs
        per_machine[maquina_id][bucket] += secs

        if bucket == "setup":
            qtd_setups += 1
            per_machine[maquina_id]["qtd_setups"] += 1
        elif bucket == "falta_material":
            qtd_falta_material += 1
            per_machine[maquina_id]["qtd_falta_material"] += 1

    tempo_usinando_seg = totals["usinando"]
    tempo_setup_seg = totals["setup"]
    tempo_falta_material_seg = totals["falta_material"]
    tempo_programacao_seg = totals["programacao"]

    tempo_disponivel_seg = tempo_usinando_seg + tempo_setup_seg + tempo_programacao_seg

    tempo_parado_seg = (
        totals["manutencao"]
        + totals["falta_material"]
        + totals["reuniao"]
        + totals["refeicao"]
        + totals["desligada"]
        + totals["ociosa"]
        + totals["parada"]
        + totals["outros"]
    )

    disponibilidade_pct = round((tempo_disponivel_seg / tempo_total_seg) * 100, 2) if tempo_total_seg > 0 else 0.0
    ief_pct = round((tempo_usinando_seg / tempo_total_seg) * 100, 2) if tempo_total_seg > 0 else 0.0
    setup_medio_min = round((tempo_setup_seg / qtd_setups) / 60, 2) if qtd_setups > 0 else 0.0
    falta_material_medio_min = (
        round((tempo_falta_material_seg / qtd_falta_material) / 60, 2) if qtd_falta_material > 0 else 0.0
    )

    parada_por_motivo_lista = [
        {
            "bucket": k,
            "motivo": k,
            "tempo_seg": v,
            "tempo_min": round(v / 60, 2),
            "tempo_horas": round(v / 3600, 2),
        }
        for k, v in sorted(
            {
                "setup": totals["setup"],
                "manutencao": totals["manutencao"],
                "falta_material": totals["falta_material"],
                "programacao": totals["programacao"],
                "reuniao": totals["reuniao"],
                "refeicao": totals["refeicao"],
                "desligada": totals["desligada"],
                "ociosa": totals["ociosa"],
                "parada": totals["parada"],
                "outros": totals["outros"],
            }.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        if v > 0
    ]

    per_machine_lista = []
    for machine_id, item in per_machine.items():
        usinando_min = round(item["usinando"] / 60, 2)
        setup_min = round(item["setup"] / 60, 2)
        setup_count = int(item.get("qtd_setups") or 0)
        setup_medio_machine_min = round((item["setup"] / setup_count) / 60, 2) if setup_count > 0 else 0.0
        falta_material_count = int(item.get("qtd_falta_material") or 0)
        falta_material_medio_machine_min = (
            round((item["falta_material"] / falta_material_count) / 60, 2)
            if falta_material_count > 0
            else 0.0
        )
        programacao_min = round(item["programacao"] / 60, 2)

        tempo_disponivel_machine_min = round((item["usinando"] + item["setup"] + item["programacao"]) / 60, 2)
        tempo_parado_machine_min = round(
            (
                item["manutencao"]
                + item["falta_material"]
                + item["reuniao"]
                + item["refeicao"]
                + item["desligada"]
                + item["ociosa"]
                + item["parada"]
                + item["outros"]
            ) / 60,
            2,
        )

        uso_pct = round((item["usinando"] / capacidade_por_maquina_seg) * 100, 2) if capacidade_por_maquina_seg > 0 else 0.0
        performance_pct = (
            round(((item["usinando"] + item["setup"] + item["programacao"]) / capacidade_por_maquina_seg) * 100, 2)
            if capacidade_por_maquina_seg > 0
            else 0.0
        )

        per_machine_lista.append(
            {
                "maquina": machine_id,
                "operador_nome": item["operador_nome"],
                "status_atual": item["status_atual"],
                "usinando_min": usinando_min,
                "setup_min": setup_min,
                "setup_medio_min": setup_medio_machine_min,
                "total_setups": setup_count,
                "programacao_min": programacao_min,
                "manutencao_min": round(item["manutencao"] / 60, 2),
                "falta_material_min": round(item["falta_material"] / 60, 2),
                "falta_material_medio_min": falta_material_medio_machine_min,
                "total_falta_material": falta_material_count,
                "reuniao_min": round(item["reuniao"] / 60, 2),
                "refeicao_min": round(item["refeicao"] / 60, 2),
                "desligada_min": round(item["desligada"] / 60, 2),
                "ociosa_min": round(item["ociosa"] / 60, 2),
                "parada_min": round(item["parada"] / 60, 2),
                "outros_min": round(item["outros"] / 60, 2),
                "tempo_disponivel_min": tempo_disponivel_machine_min,
                "tempo_parado_min": tempo_parado_machine_min,
                "uso_pct": uso_pct,
                "performance_pct": performance_pct,
            }
        )

    per_machine_lista.sort(key=lambda x: x["usinando_min"], reverse=True)

    return {
        "periodo": {
            "data_inicio": dt_ini_base.date().isoformat(),
            "data_fim": dt_fim_base.date().isoformat(),
            "dias": total_days,
        },
        "parametros": {
            "horas_dia_maquina": HORAS_DIA_MAQUINA,
            "minutos_dia_maquina": MINUTOS_DIA_MAQUINA,
            "segundos_dia_maquina": SEGUNDOS_DIA_MAQUINA,
            "quantidade_maquinas": total_maquinas,
            "capacidade_por_maquina_min": round(capacidade_por_maquina_seg / 60, 2),
            "capacidade_total_min": round(tempo_total_seg / 60, 2),
        },
        "totals": {
            k: {
                "tempo_seg": totals[k],
                "tempo_min": round(totals[k] / 60, 2),
                "tempo_horas": round(totals[k] / 3600, 2),
            }
            for k in bucket_keys
        },
        "special_totals": {
            k: {
                "tempo_seg": special_totals[k],
                "tempo_min": round(special_totals[k] / 60, 2),
                "tempo_horas": round(special_totals[k] / 3600, 2),
            }
            for k in special_bucket_keys
        },
        "ief": {
            "percentual": ief_pct,
            "tempo_usinando_seg": tempo_usinando_seg,
            "tempo_usinando_min": round(tempo_usinando_seg / 60, 2),
            "tempo_total_seg": tempo_total_seg,
            "tempo_total_min": round(tempo_total_seg / 60, 2),
        },
        "disponibilidade": {
            "percentual": disponibilidade_pct,
            "tempo_disponivel_seg": tempo_disponivel_seg,
            "tempo_disponivel_min": round(tempo_disponivel_seg / 60, 2),
            "tempo_total_seg": tempo_total_seg,
            "tempo_total_min": round(tempo_total_seg / 60, 2),
        },
        "setup_medio": {
            "quantidade_setups": qtd_setups,
            "tempo_total_setup_seg": tempo_setup_seg,
            "tempo_total_setup_min": round(tempo_setup_seg / 60, 2),
            "tempo_medio_setup_min": setup_medio_min,
        },
        "falta_material_medio": {
            "quantidade_ocorrencias": qtd_falta_material,
            "tempo_total_falta_material_seg": tempo_falta_material_seg,
            "tempo_total_falta_material_min": round(tempo_falta_material_seg / 60, 2),
            "tempo_medio_falta_material_min": falta_material_medio_min,
        },
        "parada_por_motivo": parada_por_motivo_lista,
        "per_machine": per_machine_lista,
        "resumo": {
            "tempo_parado_seg": tempo_parado_seg,
            "tempo_parado_min": round(tempo_parado_seg / 60, 2),
        },
    }

def _save_dashboard_snapshot_for_date(conn, data_ref: str):
    """
    Salva um snapshot diário fechado daquele dia.
    Mantém os dados persistidos no banco para não sumirem.
    """
    _ensure_dashboard_snapshot_daily_table(conn)

    dt_ini = datetime.fromisoformat(f"{data_ref}T00:00:00")
    dt_fim = datetime.fromisoformat(f"{data_ref}T23:59:59")

    payload = _compute_dashboard_indicadores(conn, dt_ini, dt_fim)

    cur = conn.cursor()
    agora = datetime.now().isoformat(timespec="seconds")

    cur.execute(
        """
        INSERT INTO dashboard_snapshot_daily (data_ref, payload_json, atualizado_em)
        VALUES (?, ?, ?)
        ON CONFLICT(data_ref) DO UPDATE SET
            payload_json = excluded.payload_json,
            atualizado_em = excluded.atualizado_em
        """,
        (data_ref, json.dumps(payload, ensure_ascii=False), agora),
    )


def _save_dashboard_snapshots_range(conn, start_date, end_date):
    _ensure_dashboard_snapshot_daily_table(conn)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    for d in _daterange(start_date, end_date):
        _save_dashboard_snapshot_for_date(conn, d.isoformat())


def _load_dashboard_snapshot_for_date(conn, data_ref: str):
    _ensure_dashboard_snapshot_daily_table(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT data_ref, payload_json, atualizado_em
        FROM dashboard_snapshot_daily
        WHERE data_ref = ?
        """,
        (data_ref,),
    ).fetchone()

    if not row:
        return None

    try:
        payload = json.loads(row["payload_json"])
    except Exception:
        return None

    payload["_snapshot"] = {
        "data_ref": row["data_ref"],
        "atualizado_em": row["atualizado_em"],
        "origem": "dashboard_snapshot_daily",
    }
    return payload


# =========================
# HELPERS: PAUSA/RETOMA TIMER PELO STATUS DA MÁQUINA
# =========================
def _is_machine_usinando(status: str) -> bool:
    s = (status or "").strip().upper()
    return (
        ("USIN" in s)
        or ("CORT" in s)
        or ("DETALHE CNC" in s)
        or (s == "RNC")
        or ("ABERTURA" in s and "MATERIAL" in s)
    )


def _pausar_timer_itens_em_execucao(conn, maquina_id: str, agora_iso: str):
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE fila_itens
        SET tempo_pausa_inicio_em = COALESCE(tempo_pausa_inicio_em, ?),
            tempo_pausado_seg = COALESCE(tempo_pausado_seg, 0)
        WHERE maquina_id = ?
          AND status = 'EM_EXECUCAO'
          AND tempo_pausa_inicio_em IS NULL
        """,
        (agora_iso, maquina_id),
    )


def _retomar_timer_itens_em_execucao(conn, maquina_id: str, agora_iso: str):
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    paused = cur.execute(
        """
        SELECT id, tempo_pausa_inicio_em, COALESCE(tempo_pausado_seg,0) as tempo_pausado_seg
        FROM fila_itens
        WHERE maquina_id = ?
          AND status = 'EM_EXECUCAO'
          AND tempo_pausa_inicio_em IS NOT NULL
        """,
        (maquina_id,),
    ).fetchall()

    for r in paused:
        start = r["tempo_pausa_inicio_em"]
        if not start:
            continue
        try:
            dt0 = datetime.fromisoformat(start)
            dt1 = datetime.fromisoformat(agora_iso)
            add = int((dt1 - dt0).total_seconds())
            if add < 0:
                add = 0
        except Exception:
            add = 0

        cur.execute(
            """
            UPDATE fila_itens
            SET tempo_pausado_seg = COALESCE(tempo_pausado_seg, 0) + ?,
                tempo_pausa_inicio_em = NULL
            WHERE id = ?
            """,
            (add, r["id"]),
        )


# =========================
# ROTAS BÁSICAS / TESTE
# =========================
@app.get("/cors-test")
def cors_test():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def home():
    if FRONT_DIST.exists() and (FRONT_DIST / "index.html").exists():
        return FileResponse(FRONT_DIST / "index.html")
    return {"ok": True, "msg": "Servidor CNC rodando", "frontend_build": False}

@app.get("/health")
def health():
    return {"ok": True, "msg": "Servidor CNC rodando"}


# =========================
# MÁQUINAS
# =========================
@app.get("/maquinas")
def listar_maquinas():
    conn = get_conn()
    _ensure_maquinas_cols(conn)
    _ensure_test_maquina(conn)
    conn.commit()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, nome, status, status_desde, operador_nome
        FROM maquinas
        ORDER BY id
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/maquinas/{maquina_id}/operador")
def set_operador_maquina(maquina_id: str, payload: OperadorPayload):
    conn = get_conn()
    _ensure_maquinas_cols(conn)
    _ensure_test_maquina(conn)
    cur = conn.cursor()

    nome = (payload.nome or "").strip()

    existe = cur.execute(
        "SELECT id FROM maquinas WHERE id = ?",
        (maquina_id,),
    ).fetchone()
    if not existe:
        conn.close()
        raise HTTPException(status_code=404, detail="Máquina não encontrada")

    cur.execute(
        """
        UPDATE maquinas
        SET operador_nome = ?
        WHERE id = ?
        """,
        (nome, maquina_id),
    )
    conn.commit()

    row = cur.execute(
        """
        SELECT id, nome, status, status_desde, operador_nome
        FROM maquinas
        WHERE id = ?
        """,
        (maquina_id,),
    ).fetchone()
    conn.close()

    return {"ok": True, "maquina": dict(row) if row else None}


@app.post("/maquinas/{maquina_id}/status")
def atualizar_status(maquina_id: str, req: StatusRequest):
    """
    Atualiza status da máquina:
    - grava histórico antigo (historico_status legado)
    - fecha log aberto em maquina_status_log
    - abre novo log com status/motivo
    - pausa/retoma timer do item EM_EXECUCAO
    - atualiza snapshots diários impactados

    IMPORTANTE:
    - se o status novo for igual ao atual, NÃO recria log
    - isso evita quebrar a lógica do setup e inflar quantidade de setups
    """
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_maquina_status_log_table(conn)
    _ensure_maquinas_cols(conn)
    _ensure_test_maquina(conn)
    _ensure_dashboard_snapshot_daily_table(conn)
    cur = conn.cursor()

    maquina = cur.execute(
        "SELECT status, status_desde FROM maquinas WHERE id = ?",
        (maquina_id,),
    ).fetchone()

    if not maquina:
        conn.close()
        raise HTTPException(status_code=404, detail="Máquina não encontrada")

    novo_status = (req.status or "").strip()
    if not novo_status:
        conn.close()
        raise HTTPException(status_code=400, detail="Status inválido")

    status_anterior = maquina["status"] or ""
    inicio_anterior = maquina["status_desde"]
    agora_iso = datetime.now().isoformat(timespec="seconds")

    anterior_norm = _normalize_status_compare(status_anterior)
    novo_norm = _normalize_status_compare(novo_status)
    if anterior_norm != novo_norm:
        try:
            _validate_usinagem_status_arquivo(conn, maquina_id, novo_status)
        except HTTPException:
            conn.close()
            raise

    # Se não mudou o status, não fecha/reabre log.
    if anterior_norm == novo_norm:
        motivo_atual = (req.motivo or "").strip() or _infer_motivo_from_status(novo_status)

        # Atualiza snapshot do dia atual mesmo sem recriar log,
        # garantindo persistência diária consistente.
        try:
            _save_dashboard_snapshot_for_date(conn, datetime.now().date().isoformat())
            conn.commit()
        except Exception:
            conn.rollback()

        conn.close()
        return {
            "ok": True,
            "maquina_id": maquina_id,
            "status": status_anterior,
            "motivo": motivo_atual,
            "desde": inicio_anterior,
            "status_inalterado": True,
        }

    if inicio_anterior:
        duracao = None
        try:
            inicio_dt = datetime.fromisoformat(inicio_anterior)
            agora_dt = datetime.fromisoformat(agora_iso)
            duracao = int((agora_dt - inicio_dt).total_seconds())
        except Exception:
            duracao = None

        cur.execute(
            """
            INSERT INTO historico_status
            (maquina_id, status, inicio, fim, duracao_segundos)
            VALUES (?, ?, ?, ?, ?)
            """,
            (maquina_id, status_anterior, inicio_anterior, agora_iso, duracao),
        )

    was_usinando = _is_machine_usinando(status_anterior)
    will_usinando = _is_machine_usinando(novo_status)

    if was_usinando and (not will_usinando):
        _pausar_timer_itens_em_execucao(conn, maquina_id, agora_iso)

    if (not was_usinando) and will_usinando:
        _retomar_timer_itens_em_execucao(conn, maquina_id, agora_iso)

    _close_open_status_log(conn, maquina_id, agora_iso)

    motivo = (req.motivo or "").strip() or _infer_motivo_from_status(novo_status)
    _open_status_log(conn, maquina_id, novo_status, motivo, agora_iso)

    cur.execute(
        """
        UPDATE maquinas
        SET status = ?, status_desde = ?
        WHERE id = ?
        """,
        (novo_status, agora_iso, maquina_id),
    )

    # Regera snapshots dos dias impactados
    try:
        if inicio_anterior:
            try:
                data_inicio_impacto = datetime.fromisoformat(inicio_anterior).date()
            except Exception:
                data_inicio_impacto = datetime.now().date()
        else:
            data_inicio_impacto = datetime.now().date()

        data_fim_impacto = datetime.now().date()
        _save_dashboard_snapshots_range(conn, data_inicio_impacto, data_fim_impacto)
    except Exception:
        # não derruba a troca de status por falha de snapshot
        pass

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "maquina_id": maquina_id,
        "status": novo_status,
        "motivo": motivo,
        "desde": agora_iso,
        "status_inalterado": False,
    }


# =========================
# DASHBOARD / INDICADORES
# =========================
@app.get("/dashboard/indicadores")
def dashboard_indicadores(
    data: str | None = Query(None),
    data_inicio: str | None = Query(None),
    data_fim: str | None = Query(None),
    usar_snapshot: bool = Query(True),
):
    """
    Retorna indicadores do dashboard usando maquina_status_log + snapshots diários.

    Aceita:
    - /dashboard/indicadores?data=2026-03-10
    - /dashboard/indicadores?data_inicio=2026-03-01&data_fim=2026-03-10

    Regras:
    - para 1 dia, pode devolver snapshot persistido
    - para período, garante snapshots diários do intervalo e calcula o consolidado
    """
    conn = get_conn()
    _ensure_maquina_status_log_table(conn)
    _ensure_maquinas_cols(conn)
    _ensure_dashboard_snapshot_daily_table(conn)

    try:
        if data_inicio or data_fim:
            if data_inicio:
                dt_ini_base = datetime.fromisoformat(f"{data_inicio}T00:00:00")
            elif data_fim:
                dt_ini_base = datetime.fromisoformat(f"{data_fim}T00:00:00")
            else:
                dt_ini_base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            if data_fim:
                dt_fim_base = datetime.fromisoformat(f"{data_fim}T23:59:59")
            elif data_inicio:
                dt_fim_base = datetime.fromisoformat(f"{data_inicio}T23:59:59")
            else:
                dt_fim_base = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
        elif data:
            dt_ini_base = datetime.fromisoformat(f"{data}T00:00:00")
            dt_fim_base = datetime.fromisoformat(f"{data}T23:59:59")
        else:
            now = datetime.now()
            dt_ini_base = now.replace(hour=0, minute=0, second=0, microsecond=0)
            dt_fim_base = now.replace(hour=23, minute=59, second=59, microsecond=0)

        if dt_fim_base < dt_ini_base:
            conn.close()
            raise HTTPException(status_code=400, detail="Período inválido: data_fim menor que data_inicio.")

    except Exception:
        conn.close()
        raise HTTPException(status_code=400, detail="Data inválida. Use YYYY-MM-DD.")

    # Se for apenas 1 dia e o usuário quiser snapshot, tenta carregar o persistido
    is_single_day = dt_ini_base.date() == dt_fim_base.date()

    if is_single_day and usar_snapshot:
        data_ref = dt_ini_base.date().isoformat()
        snap = _load_dashboard_snapshot_for_date(conn, data_ref)
        if snap:
            conn.close()
            return snap

        # Se não existir ainda, gera e devolve
        _save_dashboard_snapshot_for_date(conn, data_ref)
        conn.commit()

        snap = _load_dashboard_snapshot_for_date(conn, data_ref)
        if snap:
            conn.close()
            return snap

    # Garante snapshots do período para manter histórico persistido
    try:
        _save_dashboard_snapshots_range(conn, dt_ini_base.date(), dt_fim_base.date())
        conn.commit()
    except Exception:
        conn.rollback()

    payload = _compute_dashboard_indicadores(conn, dt_ini_base, dt_fim_base)
    conn.close()
    return payload


@app.get("/dashboard/snapshots")
def listar_dashboard_snapshots(
    data_inicio: str | None = Query(None),
    data_fim: str | None = Query(None),
):
    conn = get_conn()
    _ensure_dashboard_snapshot_daily_table(conn)
    cur = conn.cursor()

    sql = """
        SELECT data_ref, payload_json, atualizado_em
        FROM dashboard_snapshot_daily
    """
    params = []

    filtros = []
    if data_inicio:
        filtros.append("data_ref >= ?")
        params.append(data_inicio)
    if data_fim:
        filtros.append("data_ref <= ?")
        params.append(data_fim)

    if filtros:
        sql += " WHERE " + " AND ".join(filtros)

    sql += " ORDER BY data_ref DESC"

    rows = cur.execute(sql, tuple(params)).fetchall()
    conn.close()

    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except Exception:
            payload = None

        out.append(
            {
                "data_ref": r["data_ref"],
                "atualizado_em": r["atualizado_em"],
                "payload": payload,
            }
        )

    return out


@app.post("/dashboard/snapshots/rebuild")
def rebuild_dashboard_snapshots(
    data_inicio: str = Query(...),
    data_fim: str = Query(...),
):
    conn = get_conn()
    _ensure_dashboard_snapshot_daily_table(conn)

    try:
        dt_ini = datetime.fromisoformat(data_inicio).date()
        dt_fim = datetime.fromisoformat(data_fim).date()
    except Exception:
        conn.close()
        raise HTTPException(status_code=400, detail="Datas inválidas. Use YYYY-MM-DD.")

    try:
        _save_dashboard_snapshots_range(conn, dt_ini, dt_fim)
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "data_inicio": dt_ini.isoformat(),
        "data_fim": dt_fim.isoformat(),
    }


# =========================
# ARQUIVOS DXF
# =========================
@app.post("/arquivos/upload")
async def upload_dxf(file: UploadFile = File(...)):
    nome = file.filename or ""
    if not nome.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos .dxf são permitidos")

    safe_name = Path(nome).name

    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_arquivos_cols(conn)
    ja_cortado = _arquivo_ja_cortado_por_nome(conn, safe_name)
    ja_em_fila = _arquivo_ja_em_fila_por_nome(conn, safe_name) if not ja_cortado else None
    conn.close()
    if ja_cortado:
        raise HTTPException(
            status_code=409,
            detail=_detalhe_arquivo_ja_cortado(safe_name, ja_cortado),
        )
    if ja_em_fila:
        raise HTTPException(
            status_code=409,
            detail=_detalhe_arquivo_ja_em_fila(safe_name, ja_em_fila),
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored_name = f"{stamp}__{safe_name}"
    dest = DXF_DIR / stored_name

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (limite 50MB)")

    dest.write_bytes(content)

    conn = get_conn()
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO arquivos_dxf (nome, path, criado_em, status) VALUES (?, ?, ?, ?)",
        (safe_name, str(dest), datetime.now().isoformat(timespec="seconds"), "DISPONIVEL"),
    )
    conn.commit()
    arquivo_id = cur.lastrowid
    conn.close()

    return {"ok": True, "id": arquivo_id, "nome": safe_name, "stored": stored_name}


@app.get("/arquivos")
def listar_arquivos():
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, nome, status, criado_em, deleted_em
        FROM arquivos_dxf
        ORDER BY id DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/arquivos/disponiveis")
def listar_arquivos_disponiveis():
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT a.id, a.nome, a.status, a.criado_em
        FROM arquivos_dxf a
        WHERE UPPER(COALESCE(a.status,'')) NOT IN ('EXCLUIDO','CORTADO')
          AND a.id NOT IN (
            SELECT DISTINCT arquivo_id
            FROM fila_itens
            WHERE status IN ('AGUARDANDO','PROGRAMANDO','EM_EXECUCAO','BAIXADO','CORTADO')
        )
          AND NOT EXISTS (
            SELECT 1
            FROM arquivos_dxf ac
            LEFT JOIN fila_itens fic
                   ON fic.arquivo_id = ac.id
                  AND UPPER(COALESCE(fic.status,'')) = 'CORTADO'
            WHERE LOWER(TRIM(ac.nome)) = LOWER(TRIM(a.nome))
              AND (
                UPPER(COALESCE(ac.status,'')) = 'CORTADO'
                OR fic.id IS NOT NULL
              )
        )
        ORDER BY a.id DESC
        """
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@app.get("/arquivos/{arquivo_id}/download")
def download_arquivo_pool(arquivo_id: int):
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    row = cur.execute(
        """
        SELECT id, nome, path, status
        FROM arquivos_dxf
        WHERE id = ?
        """,
        (arquivo_id,),
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    status = (row["status"] or "").upper().strip()
    if status == "EXCLUIDO":
        raise HTTPException(status_code=404, detail="Arquivo excluído")

    arquivo_path = row["path"]
    arquivo_nome = row["nome"]

    if not arquivo_path or not os.path.exists(arquivo_path):
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado no servidor")

    return FileResponse(
        path=arquivo_path,
        filename=arquivo_nome,
        media_type="application/dxf",
    )


@app.delete("/arquivos/{arquivo_id}")
def excluir_arquivo(arquivo_id: int):
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    arq = cur.execute(
        "SELECT id, nome, path, status FROM arquivos_dxf WHERE id = ?",
        (arquivo_id,),
    ).fetchone()
    if not arq:
        conn.close()
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")

    if (arq["status"] or "").upper() == "EXCLUIDO":
        conn.close()
        return {"ok": True, "id": arquivo_id, "status": "EXCLUIDO"}

    ativo = cur.execute(
        """
        SELECT 1
        FROM fila_itens
        WHERE arquivo_id = ?
          AND status IN ('AGUARDANDO','PROGRAMANDO','EM_EXECUCAO','BAIXADO')
        LIMIT 1
        """,
        (arquivo_id,),
    ).fetchone()

    if ativo:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail="Não é possível excluir: arquivo está em uma fila ativa. Remova da fila primeiro.",
        )

    agora = datetime.now().isoformat(timespec="seconds")
    cur.execute(
        "UPDATE arquivos_dxf SET status='EXCLUIDO', deleted_em=? WHERE id=?",
        (agora, arquivo_id),
    )

    conn.commit()
    conn.close()

    try:
        p = arq["path"]
        if p and os.path.exists(p):
            os.remove(p)
    except Exception:
        pass

    return {"ok": True, "id": arquivo_id, "status": "EXCLUIDO", "deleted_em": agora}


# =========================
# FILA (DB)
# =========================
@app.get("/fila/{maquina_id}")
def get_fila_db(maquina_id: str, include_done: bool = Query(False)):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    if include_done:
        status_list = ("AGUARDANDO", "PROGRAMANDO", "EM_EXECUCAO", "BAIXADO", "CORTADO", "CANCELADO")
    else:
        status_list = ("AGUARDANDO", "PROGRAMANDO", "EM_EXECUCAO", "BAIXADO")

    itens = cur.execute(
        f"""
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, fi.criado_em,
               fi.started_em, fi.finalizado_em,
               fi.tempo_estimado_seg, fi.tempo_inicio_em,
               fi.tempo_pausado_seg, fi.tempo_pausa_inicio_em,
               a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ({",".join(["?"] * len(status_list))})
        ORDER BY fi.posicao ASC
        """,
        (maquina_id, *status_list),
    ).fetchall()

    conn.close()
    return [dict(x) for x in itens]


@app.post("/fila/{maquina_id}/add")
def add_fila(maquina_id: str, req: AddFilaRequest):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    arq = cur.execute("SELECT id, nome, status FROM arquivos_dxf WHERE id = ?", (req.arquivo_id,)).fetchone()
    if not arq:
        conn.close()
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if (arq["status"] or "").upper() == "EXCLUIDO":
        conn.close()
        raise HTTPException(status_code=409, detail="Arquivo está EXCLUIDO e não pode entrar na fila.")

    ja_cortado_nome = _arquivo_ja_cortado_por_nome(conn, arq["nome"])
    if ja_cortado_nome:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=_detalhe_arquivo_ja_cortado(arq["nome"], ja_cortado_nome),
        )

    ja_em_fila_nome = _arquivo_ja_em_fila_por_nome(conn, arq["nome"])
    if ja_em_fila_nome:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=_detalhe_arquivo_ja_em_fila(arq["nome"], ja_em_fila_nome),
        )

    arq_status = (arq["status"] or "").upper()
    if arq_status == "CORTADO":
        conn.close()
        raise HTTPException(status_code=409, detail=_detalhe_arquivo_ja_cortado(arq["nome"]))

    ja_cortado = cur.execute(
        """
        SELECT 1
        FROM fila_itens
        WHERE arquivo_id = ?
          AND status = 'CORTADO'
        LIMIT 1
        """,
        (req.arquivo_id,),
    ).fetchone()
    if ja_cortado:
        conn.close()
        raise HTTPException(status_code=409, detail=_detalhe_arquivo_ja_cortado(arq["nome"]))

    last = cur.execute(
        """
        SELECT COALESCE(MAX(posicao), 0) as maxpos
        FROM fila_itens
        WHERE maquina_id = ? AND status IN ('AGUARDANDO','PROGRAMANDO','EM_EXECUCAO')
        """,
        (maquina_id,),
    ).fetchone()

    pos = int(last["maxpos"]) + 1

    cur.execute(
        """
        INSERT INTO fila_itens (maquina_id, arquivo_id, posicao, status, criado_em)
        VALUES (?, ?, ?, 'AGUARDANDO', ?)
        """,
        (maquina_id, req.arquivo_id, pos, datetime.now().isoformat(timespec="seconds")),
    )

    item_id = cur.lastrowid
    _reindex_fila(conn, maquina_id)
    _log_chapa_movimentacao(
        conn,
        "ADICIONADO_NA_FILA",
        fila_item_id=item_id,
        arquivo_id=req.arquivo_id,
        arquivo_nome=arq["nome"],
        maquina_destino=maquina_id,
        posicao_destino=pos,
        status_destino="AGUARDANDO",
        detalhe="Arquivo enviado da fila geral para a CNC.",
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "maquina_id": maquina_id,
        "posicao": pos,
        "item_id": item_id,
        "arquivo_id": req.arquivo_id,
        "arquivo_nome": arq["nome"],
    }


@app.post("/fila/{maquina_id}/reorder")
def reorder_fila(maquina_id: str, req: ReorderFilaRequest):
    mid = (maquina_id or "").upper().strip()
    ids = req.ids()
    if not ids:
        raise HTTPException(status_code=400, detail="Lista de itens vazia (ordem/ordered_item_ids).")

    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE;")

    allowed_status = _fila_programador_status_list()

    rows = cur.execute(
        f"""
        SELECT fi.id, fi.arquivo_id, fi.posicao, fi.status, a.nome AS arquivo_nome
        FROM fila_itens fi
        LEFT JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ({",".join(["?"] * len(allowed_status))})
        ORDER BY fi.posicao ASC, fi.id ASC
        """,
        (mid, *allowed_status),
    ).fetchall()

    existing_ids = [int(r["id"]) for r in rows]
    before_by_id = {int(r["id"]): dict(r) for r in rows}
    existing_set = set(existing_ids)

    wanted = []
    for x in ids:
        try:
            xi = int(x)
            if xi in existing_set:
                wanted.append(xi)
        except Exception:
            pass

    if not wanted and existing_ids:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=400, detail="Nenhum item da lista pertence à fila desta máquina.")

    wanted_set = set(wanted)
    tail = [x for x in existing_ids if x not in wanted_set]
    final_order = wanted + tail

    for i, item_id in enumerate(final_order, start=1):
        cur.execute(
            "UPDATE fila_itens SET posicao = ? WHERE id = ? AND maquina_id = ?",
            (i, item_id, mid),
        )
        before = before_by_id.get(item_id) or {}
        old_pos = before.get("posicao")
        if old_pos != i:
            _log_chapa_movimentacao(
                conn,
                "REORDENADO_NA_FILA",
                fila_item_id=item_id,
                arquivo_id=before.get("arquivo_id"),
                arquivo_nome=before.get("arquivo_nome"),
                maquina_origem=mid,
                maquina_destino=mid,
                posicao_origem=old_pos,
                posicao_destino=i,
                status_origem=before.get("status"),
                status_destino=before.get("status"),
                detalhe="Ordem da fila alterada.",
            )

    _reindex_fila(conn, mid)

    conn.commit()
    conn.close()

    return {"ok": True, "maquina_id": mid, "count": len(final_order), "ordem_aplicada": final_order}


@app.post("/fila/item/{item_id}/to_pool")
def fila_item_to_pool(item_id: int):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    row = _fila_item_log_snapshot(conn, item_id)

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item não encontrado")

    st = (row["status"] or "").upper()
    if st == "EM_EXECUCAO":
        conn.close()
        raise HTTPException(status_code=409, detail="Não pode voltar para o pool: item está EM_EXECUCAO.")

    if st in _fila_finalizada_status_list():
        conn.close()
        raise HTTPException(status_code=409, detail=f"Nao pode voltar para o pool: item ja foi finalizado ({st}).")

    cur.execute("DELETE FROM fila_itens WHERE id=?", (item_id,))
    _reindex_fila(conn, row["maquina_id"])
    _log_chapa_movimentacao(
        conn,
        "VOLTOU_PARA_FILA_GERAL",
        fila_item_id=item_id,
        arquivo_id=row["arquivo_id"],
        arquivo_nome=row["arquivo_nome"],
        maquina_origem=row["maquina_id"],
        posicao_origem=row["posicao"],
        status_origem=row["status"],
        detalhe="Item removido da fila da CNC e voltou para a fila geral.",
    )

    conn.commit()
    conn.close()

    return {"ok": True, "item_id": item_id, "maquina_id": row["maquina_id"], "arquivo_id": row["arquivo_id"]}


@app.delete("/fila/item/{item_id}/hard")
def fila_item_hard_delete(item_id: int):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    row = _fila_item_log_snapshot(conn, item_id)

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item não encontrado")

    st = (row["status"] or "").upper()
    if st == "EM_EXECUCAO":
        conn.close()
        raise HTTPException(status_code=409, detail="Não pode excluir: item está EM_EXECUCAO.")

    if st in _fila_finalizada_status_list():
        conn.close()
        raise HTTPException(status_code=409, detail=f"Nao pode excluir: item ja foi finalizado ({st}).")

    cur.execute("DELETE FROM fila_itens WHERE id=?", (item_id,))
    _reindex_fila(conn, row["maquina_id"])
    _log_chapa_movimentacao(
        conn,
        "EXCLUIDO_DA_FILA",
        fila_item_id=item_id,
        arquivo_id=row["arquivo_id"],
        arquivo_nome=row["arquivo_nome"],
        maquina_origem=row["maquina_id"],
        posicao_origem=row["posicao"],
        status_origem=row["status"],
        detalhe="Item excluido da fila da CNC.",
    )

    conn.commit()
    conn.close()
    return {"ok": True, "item_id": item_id, "maquina_id": row["maquina_id"], "arquivo_id": row["arquivo_id"]}


@app.post("/fila/item/{item_id}/move/{dest_maquina_id}")
def mover_item_para_outra_cnc(item_id: int, dest_maquina_id: str, req: MoveFilaItemRequest = MoveFilaItemRequest()):
    dest = dest_maquina_id.upper().strip()

    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    item = cur.execute(
        """
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, a.nome AS arquivo_nome
        FROM fila_itens fi
        LEFT JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ?
        """,
        (item_id,),
    ).fetchone()

    if not item:
        conn.close()
        raise HTTPException(status_code=404, detail="Item não encontrado")

    origem = (item["maquina_id"] or "").upper().strip()
    st = (item["status"] or "").upper().strip()
    arquivo_id = int(item["arquivo_id"])

    if origem == dest:
        conn.close()
        return {"ok": True, "msg": "Origem e destino são iguais", "item_id": item_id, "maquina_id": origem}

    if st == "EM_EXECUCAO":
        conn.close()
        raise HTTPException(status_code=409, detail="Não pode mover: item está EM_EXECUCAO.")

    if st in _fila_finalizada_status_list():
        conn.close()
        raise HTTPException(status_code=409, detail=f"Nao pode mover: item ja foi finalizado ({st}).")

    m = cur.execute("SELECT id FROM maquinas WHERE id = ?", (dest,)).fetchone()
    if not m:
        conn.close()
        raise HTTPException(status_code=404, detail="Máquina destino não encontrada")

    arq = cur.execute("SELECT id, status FROM arquivos_dxf WHERE id=?", (arquivo_id,)).fetchone()
    if not arq:
        conn.close()
        raise HTTPException(status_code=404, detail="Arquivo (arquivos_dxf) não encontrado")
    if (arq["status"] or "").upper() == "EXCLUIDO":
        conn.close()
        raise HTTPException(status_code=409, detail="Arquivo está EXCLUIDO e não pode ser movido.")

    last = cur.execute(
        """
        SELECT COALESCE(MAX(posicao), 0) as maxpos
        FROM fila_itens
        WHERE maquina_id = ? AND status IN ('AGUARDANDO','PROGRAMANDO','EM_EXECUCAO')
        """,
        (dest,),
    ).fetchone()
    new_pos = int(last["maxpos"]) + 1

    agora = datetime.now().isoformat(timespec="seconds")
    new_status = st if req.manter_status else "AGUARDANDO"

    cur.execute("DELETE FROM fila_itens WHERE id=?", (item_id,))

    cur.execute(
        """
        INSERT INTO fila_itens (maquina_id, arquivo_id, posicao, status, criado_em, started_em, finalizado_em)
        VALUES (?, ?, ?, ?, ?, NULL, NULL)
        """,
        (dest, arquivo_id, new_pos, new_status, agora),
    )
    new_item_id = cur.lastrowid

    _reindex_fila(conn, origem)
    _reindex_fila(conn, dest)
    _log_chapa_movimentacao(
        conn,
        "MOVIDO_ENTRE_CNCS",
        fila_item_id=new_item_id,
        arquivo_id=arquivo_id,
        arquivo_nome=item["arquivo_nome"],
        maquina_origem=origem,
        maquina_destino=dest,
        posicao_origem=item["posicao"],
        posicao_destino=new_pos,
        status_origem=st,
        status_destino=new_status,
        detalhe=f"Movido da {origem} para {dest}. Item anterior: {item_id}.",
    )

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "origem": origem,
        "destino": dest,
        "item_id_antigo": item_id,
        "item_id_novo": new_item_id,
        "arquivo_id": arquivo_id,
        "status_destino": new_status,
    }


# =========================
# HISTÓRICO
# =========================
# =========================
# RASTREAMENTO DAS CHAPAS
# =========================
@app.get("/rastreamento/filas")
def listar_rastreamento_filas(
    maquina_id: str | None = Query(None),
    arquivo_id: int | None = Query(None),
    item_id: int | None = Query(None),
    acao: str | None = Query(None),
    somente_operadores: bool = Query(False),
    limit: int = Query(300),
):
    conn = get_conn()
    _ensure_chapa_movimentacao_log_table(conn)
    cur = conn.cursor()

    filtros = []
    params = []

    mid = (maquina_id or "").upper().strip()
    if mid:
        filtros.append("(maquina_origem = ? OR maquina_destino = ?)")
        params.extend([mid, mid])

    if arquivo_id:
        filtros.append("arquivo_id = ?")
        params.append(arquivo_id)

    if item_id:
        filtros.append("fila_item_id = ?")
        params.append(item_id)

    act = (acao or "").upper().strip()
    if act:
        filtros.append("acao = ?")
        params.append(act)

    if somente_operadores:
        filtros.append("COALESCE(TRIM(operador_nome), '') <> ''")

    where_sql = "WHERE " + " AND ".join(filtros) if filtros else ""
    lim = max(1, min(int(limit or 300), 1000))

    rows = cur.execute(
        f"""
        SELECT
            id,
            fila_item_id,
            arquivo_id,
            arquivo_nome,
            acao,
            operador_nome,
            maquina_origem,
            maquina_destino,
            posicao_origem,
            posicao_destino,
            status_origem,
            status_destino,
            detalhe,
            criado_em
        FROM chapa_movimentacao_log
        {where_sql}
        ORDER BY datetime(criado_em) DESC, id DESC
        LIMIT ?
        """,
        tuple(params + [lim]),
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@app.get("/historico/{maquina_id}")
def get_historico(maquina_id: str):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT
            fi.id,
            fi.maquina_id,
            fi.arquivo_id,
            fi.posicao,
            fi.status,
            fi.criado_em,
            fi.started_em,
            fi.finalizado_em,
            fi.tempo_estimado_seg,
            fi.tempo_inicio_em,
            fi.tempo_pausado_seg,
            fi.tempo_pausa_inicio_em,
            a.nome AS arquivo_nome,
            a.path AS arquivo_path,
            a.status AS arquivo_status
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ('CORTADO','CANCELADO')
        ORDER BY COALESCE(fi.finalizado_em, fi.criado_em) DESC, fi.id DESC
        LIMIT 200
        """,
        (maquina_id,),
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


@app.get("/historico/item/{item_id}/download")
def baixar_arquivo_historico(item_id: int):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    row = cur.execute(
        """
        SELECT
            fi.id AS fila_item_id,
            fi.maquina_id,
            fi.arquivo_id,
            fi.status,
            fi.finalizado_em,
            a.nome AS arquivo_nome,
            a.path AS arquivo_path,
            a.status AS arquivo_status
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ?
          AND fi.status IN ('CORTADO', 'CANCELADO')
        """,
        (item_id,),
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Item de histórico não encontrado")

    if (row["arquivo_status"] or "").upper().strip() == "EXCLUIDO":
        raise HTTPException(status_code=404, detail="Arquivo do histórico foi excluído")

    arquivo_path = row["arquivo_path"]
    arquivo_nome = row["arquivo_nome"]

    if not arquivo_path or not os.path.exists(arquivo_path):
        raise HTTPException(status_code=404, detail="Arquivo físico não encontrado no servidor")

    return FileResponse(
        path=arquivo_path,
        filename=arquivo_nome,
        media_type="application/dxf",
    )


@app.get("/historico/exportar/excel")
def exportar_historico_excel(
    maquina_id: str | None = Query(None),
    somente_cortados: bool = Query(False),
):
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()

    filtros = []
    params = []

    if maquina_id:
        filtros.append("fi.maquina_id = ?")
        params.append(maquina_id)
    else:
        filtros.append("fi.maquina_id NOT IN ({})".format(",".join(["?"] * len(TEST_MACHINE_IDS))))
        params.extend(TEST_MACHINE_IDS)

    if somente_cortados:
        filtros.append("fi.status = 'CORTADO'")
    else:
        filtros.append("fi.status IN ('CORTADO','CANCELADO')")

    where_sql = " AND ".join(filtros) if filtros else "1=1"

    rows = cur.execute(
        f"""
        SELECT
            fi.maquina_id,
            fi.status,
            a.nome AS arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE {where_sql}
        ORDER BY COALESCE(fi.finalizado_em, fi.criado_em) DESC, fi.id DESC
        """,
        tuple(params),
    ).fetchall()

    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Historico CNC"

    ws.append([
        "ARQUIVO",
        "STATUS",
        "MAQUINA",
    ])

    for r in rows:
        ws.append([
            r["arquivo_nome"],
            r["status"],
            r["maquina_id"],
        ])

    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            v = "" if cell.value is None else str(cell.value)
            if len(v) > max_len:
                max_len = len(v)
        ws.column_dimensions[col_letter].width = min(max_len + 2, 45)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    nome_arquivo = "historico_cnc.xlsx"
    if maquina_id:
        nome_arquivo = f"historico_{maquina_id}.xlsx"
    if somente_cortados:
        nome_arquivo = nome_arquivo.replace(".xlsx", "_cortados.xlsx")

    tmp_dir = BASE_DIR / "temp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    tmp_file = tmp_dir / nome_arquivo
    with open(tmp_file, "wb") as f:
        f.write(output.getvalue())

    return FileResponse(
        path=tmp_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=nome_arquivo,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome_arquivo)}"
        },
    )


# =========================
# TEMPO ESTIMADO
# =========================
@app.post("/fila/item/{item_id}/tempo_estimado")
def set_tempo_estimado(item_id: int, body: TempoEstimadoIn):
    conn = None
    try:
        minutos = int(body.minutos or 0)
        if minutos <= 0:
            raise HTTPException(status_code=400, detail="minutos deve ser > 0")

        tempo_seg = minutos * 60

        conn = get_conn()
        _ensure_fila_itens_cols(conn)
        cur = conn.cursor()

        row = _fila_item_log_snapshot(conn, item_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Item {item_id} nao encontrado")

        cur.execute(
            """
            UPDATE fila_itens
            SET tempo_estimado_seg = ?,
                tempo_inicio_em = NULL
            WHERE id = ?
            """,
            (tempo_seg, item_id),
        )
        _log_chapa_movimentacao(
            conn,
            "TEMPO_ESTIMADO_DEFINIDO",
            fila_item_id=item_id,
            arquivo_id=row["arquivo_id"],
            arquivo_nome=row["arquivo_nome"],
            maquina_origem=row["maquina_id"],
            maquina_destino=row["maquina_id"],
            posicao_origem=row["posicao"],
            posicao_destino=row["posicao"],
            status_origem=row["status"],
            status_destino=row["status"],
            operador_nome=_get_operador_nome_for_machine(conn, row["maquina_id"]),
            detalhe=f"Tempo estimado definido para {minutos} min.",
        )
        conn.commit()

        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Item {item_id} não encontrado")

        return {"ok": True, "item_id": item_id, "tempo_estimado_seg": tempo_seg, "tempo_inicio_em": None}

    except HTTPException:
        raise
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"SQLite error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno: {e}")
    finally:
        if conn:
            conn.close()


# =========================
# STATUS DO ITEM NA FILA
# =========================
@app.post("/fila/{maquina_id}/status")
def set_status_fila_item(maquina_id: str, req: FilaStatusRequest):
    action = (req.status or "").strip().upper()
    mapa = {
        "PROGRAMADO": "PROGRAMANDO",
        "USINANDO": "EM_EXECUCAO",
        "CONCLUIDO": "CORTADO",
        "CANCELADO": "CANCELADO",
    }
    if action not in mapa:
        raise HTTPException(status_code=400, detail="Status inválido. Use PROGRAMADO/USINANDO/CONCLUIDO/CANCELADO")

    target = mapa[action]
    motivo_cancelamento = (req.motivo or "").strip()
    if target == "CANCELADO" and not motivo_cancelamento:
        raise HTTPException(status_code=400, detail="Informe o motivo do cancelamento.")

    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    row = _fila_item_log_snapshot(conn, req.id)

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item não encontrado")

    atual = (row["status"] or "").upper()
    if atual in ("CORTADO", "CANCELADO"):
        conn.close()
        raise HTTPException(status_code=409, detail="Item já finalizado")

    agora = datetime.now().isoformat(timespec="seconds")

    if target == "EM_EXECUCAO":
        _assert_no_other_em_execucao(conn, maquina_id, req.id)
        material_bloqueio = _material_setup_bloqueio_detail(conn, maquina_id, req.id)
        if material_bloqueio:
            conn.close()
            raise HTTPException(status_code=409, detail=material_bloqueio)

        chk = cur.execute(
            "SELECT tempo_estimado_seg, tempo_inicio_em FROM fila_itens WHERE id=? AND maquina_id=?",
            (req.id, maquina_id),
        ).fetchone()

        if not chk or not chk["tempo_estimado_seg"]:
            conn.close()
            raise HTTPException(status_code=409, detail="Defina o tempo estimado antes de colocar em USINANDO.")

        cur.execute(
            """
            UPDATE fila_itens
            SET status='EM_EXECUCAO',
                started_em=COALESCE(started_em, ?),
                finalizado_em=NULL,
                tempo_inicio_em=COALESCE(tempo_inicio_em, ?),
                tempo_pausado_seg=COALESCE(tempo_pausado_seg, 0),
                tempo_pausa_inicio_em=NULL
            WHERE id=? AND maquina_id=?
            """,
            (agora, agora, req.id, maquina_id),
        )

    elif target in ("CORTADO", "CANCELADO"):
        cur.execute(
            """
            UPDATE fila_itens
            SET status=?,
                finalizado_em=COALESCE(finalizado_em, ?)
            WHERE id=? AND maquina_id=?
            """,
            (target, agora, req.id, maquina_id),
        )
        if target == "CORTADO":
            _marcar_arquivos_mesmo_nome_como_cortado(conn, row["arquivo_id"])

    else:
        cur.execute(
            "UPDATE fila_itens SET status=? WHERE id=? AND maquina_id=?",
            (target, req.id, maquina_id),
        )

    _log_chapa_movimentacao(
        conn,
        {
            "PROGRAMANDO": "STATUS_PROGRAMADO",
            "EM_EXECUCAO": "INICIOU_USINAGEM",
            "CORTADO": "MARCADO_CORTADO",
            "CANCELADO": "CANCELADO",
        }.get(target, "STATUS_ALTERADO"),
        fila_item_id=req.id,
        arquivo_id=row["arquivo_id"],
        arquivo_nome=row["arquivo_nome"],
        maquina_origem=row["maquina_id"],
        maquina_destino=row["maquina_id"],
        posicao_origem=row["posicao"],
        posicao_destino=row["posicao"],
        status_origem=atual,
        status_destino=target,
        operador_nome=_get_operador_nome_for_machine(conn, maquina_id),
        detalhe=(
            f"Status alterado via tela: {action}. Motivo: {motivo_cancelamento}"
            if target == "CANCELADO"
            else f"Status alterado via tela: {action}."
        ),
    )

    _reindex_fila(conn, maquina_id)
    conn.commit()

    out = cur.execute(
        """
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, fi.criado_em,
               fi.started_em, fi.finalizado_em,
               fi.tempo_estimado_seg, fi.tempo_inicio_em,
               fi.tempo_pausado_seg, fi.tempo_pausa_inicio_em,
               a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id=? AND fi.maquina_id=?
        """,
        (req.id, maquina_id),
    ).fetchone()

    conn.close()
    return {"ok": True, "item": dict(out) if out else None}


# =========================
# AGENTE (FILA via BANCO)
# =========================
@app.get("/agente/{maquina_id}/next")
def agente_next(maquina_id: str):
    conn = get_conn()
    cur = conn.cursor()

    pendente = cur.execute(
        """
        SELECT fi.id as fila_item_id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status,
               a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ('PROGRAMANDO','BAIXADO')
        ORDER BY fi.posicao ASC, fi.id ASC
        LIMIT 1
        """,
        (maquina_id,),
    ).fetchone()

    if pendente:
        conn.close()
        return {
            "maquina_id": maquina_id,
            "pendente": True,
            "modo": "FILA",
            "fila_item_id": pendente["fila_item_id"],
            "arquivo_id": pendente["arquivo_id"],
            "arquivo_nome": pendente["arquivo_nome"],
            "posicao": pendente["posicao"],
            "status": pendente["status"],
            "download_url": f"/agente/{maquina_id}/download/fila/{pendente['fila_item_id']}",
            "bloqueou_novo": True,
            "detail": "Ja existe arquivo programado/baixado aguardando USINANDO.",
        }

    m = cur.execute("SELECT id FROM maquinas WHERE id = ?", (maquina_id,)).fetchone()
    if not m:
        conn.close()
        raise HTTPException(status_code=404, detail="Máquina não encontrada")

    row = cur.execute(
        """
        SELECT fi.id as fila_item_id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status,
               a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status = 'AGUARDANDO'
        ORDER BY fi.posicao ASC, fi.id ASC
        LIMIT 1
        """,
        (maquina_id,),
    ).fetchone()

    if not row:
        conn.close()
        return {"maquina_id": maquina_id, "pendente": False, "modo": "FILA"}

    fila_item_id = row["fila_item_id"]

    cur.execute("UPDATE fila_itens SET status='PROGRAMANDO' WHERE id = ?", (fila_item_id,))
    _reindex_fila(conn, maquina_id)
    _log_chapa_movimentacao(
        conn,
        "AGENTE_RESERVOU_PROXIMO",
        fila_item_id=fila_item_id,
        arquivo_id=row["arquivo_id"],
        arquivo_nome=row["arquivo_nome"],
        maquina_origem=maquina_id,
        maquina_destino=maquina_id,
        posicao_origem=row["posicao"],
        posicao_destino=row["posicao"],
        status_origem=row["status"],
        status_destino="PROGRAMANDO",
        operador_nome=_get_operador_nome_for_machine(conn, maquina_id),
        detalhe="Agente reservou o proximo arquivo da fila.",
    )

    conn.commit()
    conn.close()

    return {
        "maquina_id": maquina_id,
        "pendente": True,
        "modo": "FILA",
        "fila_item_id": row["fila_item_id"],
        "arquivo_id": row["arquivo_id"],
        "arquivo_nome": row["arquivo_nome"],
        "posicao": row["posicao"],
        "status": "PROGRAMANDO",
        "download_url": f"/agente/{maquina_id}/download/fila/{row['fila_item_id']}",
    }


@app.get("/agente/{maquina_id}/download/fila/{fila_item_id}")
def agente_download_fila(maquina_id: str, fila_item_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE;")

    row = cur.execute(
        """
        SELECT fi.id as fila_item_id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status,
               a.nome as arquivo_nome, a.path as arquivo_path
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ? AND fi.maquina_id = ?
        """,
        (fila_item_id, maquina_id),
    ).fetchone()

    if not row:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=404, detail="Item de fila não encontrado")

    if (row["status"] or "").upper() not in ("AGUARDANDO", "PROGRAMANDO", "BAIXADO"):
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Item não pode ser baixado (status={row['status']})")

    item_pendente = cur.execute(
        """
        SELECT fi.id as fila_item_id, fi.status, a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ('PROGRAMANDO','BAIXADO')
          AND fi.id <> ?
        ORDER BY fi.posicao ASC, fi.id ASC
        LIMIT 1
        """,
        (maquina_id, fila_item_id),
    ).fetchone()

    if item_pendente:
        conn.rollback()
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=(
                "Ja existe um arquivo programado/baixado aguardando USINANDO nesta maquina: "
                f"{item_pendente['arquivo_nome']}. Coloque esse arquivo em USINANDO antes de baixar outro."
            ),
        )

    cur.execute(
        """
        UPDATE fila_itens
        SET status = 'BAIXADO'
        WHERE id = ? AND maquina_id = ? AND status IN ('AGUARDANDO','PROGRAMANDO')
        """,
        (fila_item_id, maquina_id),
    )

    _reindex_fila(conn, maquina_id)
    _log_chapa_movimentacao(
        conn,
        "ARQUIVO_BAIXADO" if (row["status"] or "").upper() != "BAIXADO" else "DOWNLOAD_REFEITO",
        fila_item_id=fila_item_id,
        arquivo_id=row["arquivo_id"],
        arquivo_nome=row["arquivo_nome"],
        maquina_origem=maquina_id,
        maquina_destino=maquina_id,
        posicao_origem=row["posicao"],
        posicao_destino=row["posicao"],
        status_origem=row["status"],
        status_destino="BAIXADO",
        operador_nome=_get_operador_nome_for_machine(conn, maquina_id),
        detalhe="Operador baixou o arquivo da fila.",
    )

    conn.commit()
    conn.close()

    return FileResponse(
        path=row["arquivo_path"],
        filename=row["arquivo_nome"],
        media_type="application/dxf",
    )


@app.get("/agente/{maquina_id}/preview/fila/{fila_item_id}")
def agente_preview_fila(maquina_id: str, fila_item_id: int):
    conn = get_conn()
    cur = conn.cursor()

    row = cur.execute(
        """
        SELECT fi.id as fila_item_id, fi.maquina_id, fi.arquivo_id, fi.status,
               a.nome as arquivo_nome, a.path as arquivo_path
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ? AND fi.maquina_id = ?
        """,
        (fila_item_id, maquina_id),
    ).fetchone()

    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Item de fila nÃ£o encontrado")

    arquivo_path = row["arquivo_path"]
    if not arquivo_path or not os.path.exists(arquivo_path):
        raise HTTPException(status_code=404, detail="Arquivo fÃ­sico nÃ£o encontrado no servidor")

    return FileResponse(
        path=arquivo_path,
        filename=row["arquivo_nome"],
        media_type="text/plain; charset=utf-8",
    )


@app.post("/agente/{maquina_id}/fila/{fila_item_id}/executar")
def agente_executar(maquina_id: str, fila_item_id: int):
    conn = get_conn()
    cur = conn.cursor()

    row = cur.execute(
        """
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, a.nome AS arquivo_nome
        FROM fila_itens fi
        LEFT JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ? AND fi.maquina_id = ?
        """,
        (fila_item_id, maquina_id),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item de fila não encontrado")

    st = row["status"]
    if st not in ("AGUARDANDO", "PROGRAMANDO", "BAIXADO", "EM_EXECUCAO"):
        conn.close()
        raise HTTPException(status_code=400, detail=f"Item não pode entrar em execução (status={st})")

    _assert_no_other_em_execucao(conn, maquina_id, fila_item_id)
    material_bloqueio = _material_setup_bloqueio_detail(conn, maquina_id, fila_item_id)
    if material_bloqueio:
        conn.close()
        raise HTTPException(status_code=409, detail=material_bloqueio)

    if st != "EM_EXECUCAO":
        cur.execute("UPDATE fila_itens SET status='EM_EXECUCAO' WHERE id = ?", (fila_item_id,))
        _reindex_fila(conn, maquina_id)
        _log_chapa_movimentacao(
            conn,
            "INICIOU_USINAGEM",
            fila_item_id=fila_item_id,
            arquivo_id=row["arquivo_id"],
            arquivo_nome=row["arquivo_nome"],
            maquina_origem=maquina_id,
            maquina_destino=maquina_id,
            posicao_origem=row["posicao"],
            posicao_destino=row["posicao"],
            status_origem=st,
            status_destino="EM_EXECUCAO",
            operador_nome=_get_operador_nome_for_machine(conn, maquina_id),
            detalhe="Operador/agente colocou o arquivo em usinagem.",
        )
        conn.commit()

    conn.close()
    return {"ok": True, "maquina_id": maquina_id, "fila_item_id": fila_item_id, "status": "EM_EXECUCAO"}


@app.post("/agente/{maquina_id}/fila/{fila_item_id}/cortado")
def agente_cortado(maquina_id: str, fila_item_id: int, req: CortadoRequest):
    conn = get_conn()
    cur = conn.cursor()

    row = cur.execute(
        """
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, a.nome AS arquivo_nome
        FROM fila_itens fi
        LEFT JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ? AND fi.maquina_id = ?
        """,
        (fila_item_id, maquina_id),
    ).fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Item de fila não encontrado")

    if row["status"] != "EM_EXECUCAO":
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Só pode marcar CORTADO quando estiver EM_EXECUCAO (status={row['status']}).",
        )

    cur.execute(
        "UPDATE fila_itens SET status='CORTADO', finalizado_em=? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), fila_item_id),
    )
    _marcar_arquivos_mesmo_nome_como_cortado(conn, row["arquivo_id"])
    _reindex_fila(conn, maquina_id)
    _log_chapa_movimentacao(
        conn,
        "MARCADO_CORTADO",
        fila_item_id=fila_item_id,
        arquivo_id=row["arquivo_id"],
        arquivo_nome=row["arquivo_nome"],
        maquina_origem=maquina_id,
        maquina_destino=maquina_id,
        posicao_origem=row["posicao"],
        posicao_destino=row["posicao"],
        status_origem=row["status"],
        status_destino="CORTADO",
        operador_nome=_get_operador_nome_for_machine(conn, maquina_id),
        detalhe="Operador marcou o arquivo como cortado.",
    )

    conn.commit()
    conn.close()

    return {"ok": True, "maquina_id": maquina_id, "fila_item_id": fila_item_id, "status": "CORTADO"}


# =========================
# FILA (FILE SYSTEM) - SEM CONFLITO
# =========================
EXTENSOES_VALIDAS = {".dxf"}


def garantir_estrutura_fs(raiz: Path):
    entrada = raiz / "ENTRADA"
    em_uso = raiz / "EM_USO"
    finalizados = raiz / "FINALIZADOS"
    entrada.mkdir(parents=True, exist_ok=True)
    em_uso.mkdir(parents=True, exist_ok=True)
    finalizados.mkdir(parents=True, exist_ok=True)
    return entrada, em_uso, finalizados


def listar_arquivos_fs(pasta: Path):
    itens = []
    if not pasta.exists():
        return itens

    for p in pasta.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in EXTENSOES_VALIDAS:
            continue

        st = p.stat()
        itens.append(
            {
                "arquivo": p.name,
                "tamanho_bytes": st.st_size,
                "modificado_em": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "ts": st.st_mtime,
            }
        )

    itens.sort(key=lambda x: x["ts"])
    for i, it in enumerate(itens, start=1):
        it["posicao"] = i
        it.pop("ts", None)
    return itens


def get_raiz_fs(maquina_id: str) -> Path:
    mid = maquina_id.upper().strip()
    if mid not in MAQUINAS:
        raise HTTPException(status_code=404, detail="Máquina não cadastrada (FS)")
    raiz = Path(MAQUINAS[mid])
    if not raiz.exists():
        raise HTTPException(status_code=404, detail=f"Pasta não encontrada: {raiz}")
    if not raiz.is_dir():
        raise HTTPException(status_code=400, detail=f"Caminho não é pasta: {raiz}")
    return raiz


@app.get("/fila_fs/{maquina_id}")
def get_fila_fs(maquina_id: str, include_done: bool = False):
    raiz = get_raiz_fs(maquina_id)
    entrada, em_uso, finalizados = garantir_estrutura_fs(raiz)

    fila = listar_arquivos_fs(entrada)
    executando = listar_arquivos_fs(em_uso)

    resp = {
        "maquina_id": maquina_id.upper().strip(),
        "base_path": str(raiz),
        "arquivo_em_execucao": executando[0]["arquivo"] if executando else None,
        "fila": fila,
        "total_na_fila": len(fila),
    }

    if include_done:
        done = listar_arquivos_fs(finalizados)
        resp["finalizados_ultimos"] = done[-50:]

    return resp


@app.post("/fila_fs/{maquina_id}/iniciar_proximo")
def iniciar_proximo_fs(maquina_id: str):
    raiz = get_raiz_fs(maquina_id)
    entrada, em_uso, _ = garantir_estrutura_fs(raiz)

    em_uso_itens = listar_arquivos_fs(em_uso)
    if em_uso_itens:
        raise HTTPException(status_code=409, detail=f"Já existe arquivo em uso: {em_uso_itens[0]['arquivo']}")

    fila = listar_arquivos_fs(entrada)
    if not fila:
        raise HTTPException(status_code=404, detail="Fila vazia (ENTRADA sem DXF)")

    proximo = fila[0]["arquivo"]
    shutil.move(str(entrada / proximo), str(em_uso / proximo))

    return {"ok": True, "maquina_id": maquina_id.upper().strip(), "iniciado": proximo}


@app.post("/fila_fs/{maquina_id}/finalizar")
def finalizar_fs(maquina_id: str):
    raiz = get_raiz_fs(maquina_id)
    _, em_uso, finalizados = garantir_estrutura_fs(raiz)

    executando = listar_arquivos_fs(em_uso)
    if not executando:
        raise HTTPException(status_code=404, detail="Nenhum arquivo em uso para finalizar")

    atual = executando[0]["arquivo"]
    origem = em_uso / atual

    destino = finalizados / atual
    if destino.exists():
        base = destino.stem
        ext = destino.suffix
        destino = finalizados / f"{base}__{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"

    shutil.move(str(origem), str(destino))

    return {"ok": True, "maquina_id": maquina_id.upper().strip(), "finalizado": atual, "salvo_como": destino.name}


# =========================
# CHAT CNC
# =========================
def _safe_chat_image_name(filename: str | None, content_type: str | None) -> str:
    raw = Path(filename or "imagem").name.strip() or "imagem"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._") or "imagem"
    ext = Path(safe).suffix.lower()
    if ext not in CHAT_IMAGE_EXTS:
        guessed = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }.get((content_type or "").lower(), ".jpg")
        safe = f"{Path(safe).stem or 'imagem'}{guessed}"
    return safe


def _chat_row_to_dict(row):
    return {
        "id": row[0],
        "maquina_id": row[1],
        "autor": row[2],
        "mensagem": row[3] or "",
        "criado_em": row[4],
        "imagem_url": f"/chat/imagem/{row[0]}" if row[5] else None,
        "imagem_nome": row[6],
        "imagem_tipo": row[7],
    }


@app.get("/chat/{maquina_id}")
def listar_chat(maquina_id: str, limit: int = 100):
    conn = get_conn()
    _ensure_chat_mensagens_table(conn)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, maquina_id, autor, mensagem, criado_em, imagem_path, imagem_nome, imagem_tipo
        FROM chat_mensagens
        WHERE maquina_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (maquina_id.upper(), limit),
    )

    rows = cur.fetchall()
    conn.close()

    return [_chat_row_to_dict(r) for r in rows]


@app.post("/chat")
def enviar_chat(msg: ChatMensagemIn):
    conn = get_conn()
    _ensure_chat_mensagens_table(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO chat_mensagens (maquina_id, autor, mensagem, criado_em)
        VALUES (?, ?, ?, datetime('now','localtime'))
        """,
        (
            msg.maquina_id.upper(),
            msg.autor,
            msg.mensagem,
        ),
    )

    conn.commit()
    conn.close()

    return {"ok": True}


@app.post("/chat/imagem")
async def enviar_chat_imagem(
    maquina_id: str = Form(...),
    autor: str = Form(...),
    mensagem: str = Form(""),
    file: UploadFile = File(...),
):
    safe_name = _safe_chat_image_name(file.filename, file.content_type)
    ext = Path(safe_name).suffix.lower()
    content_type = (file.content_type or "").lower()

    if ext not in CHAT_IMAGE_EXTS or (
        content_type and not content_type.startswith("image/") and content_type != "application/octet-stream"
    ):
        raise HTTPException(status_code=400, detail="Envie apenas imagens JPG, PNG, GIF, WEBP ou BMP.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Imagem vazia.")
    if len(content) > MAX_CHAT_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Imagem muito grande. Limite de 8 MB.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    stored_name = f"{stamp}_{maquina_id.upper().strip()}_{safe_name}"
    image_path = CHAT_DIR / stored_name
    image_path.write_bytes(content)

    conn = get_conn()
    _ensure_chat_mensagens_table(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO chat_mensagens (maquina_id, autor, mensagem, criado_em, imagem_path, imagem_nome, imagem_tipo)
        VALUES (?, ?, ?, datetime('now','localtime'), ?, ?, ?)
        """,
        (
            maquina_id.upper().strip(),
            autor,
            (mensagem or "").strip(),
            str(image_path),
            safe_name,
            file.content_type or "image/jpeg",
        ),
    )
    msg_id = cur.lastrowid
    conn.commit()

    row = cur.execute(
        """
        SELECT id, maquina_id, autor, mensagem, criado_em, imagem_path, imagem_nome, imagem_tipo
        FROM chat_mensagens
        WHERE id = ?
        """,
        (msg_id,),
    ).fetchone()
    conn.close()

    return _chat_row_to_dict(row)


@app.get("/chat/imagem/{mensagem_id}")
def baixar_chat_imagem(mensagem_id: int):
    conn = get_conn()
    _ensure_chat_mensagens_table(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT imagem_path, imagem_nome, imagem_tipo
        FROM chat_mensagens
        WHERE id = ?
        """,
        (mensagem_id,),
    ).fetchone()
    conn.close()

    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="Imagem nao encontrada.")

    path = Path(row[0])
    try:
        path.relative_to(CHAT_DIR)
    except Exception:
        raise HTTPException(status_code=404, detail="Imagem invalida.")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo da imagem nao encontrado.")

    return FileResponse(
        path,
        media_type=row[2] or "application/octet-stream",
        filename=row[1] or path.name,
    )


# =========================
# ALMOXARIFADO
# =========================
@app.get("/almoxarifado/solicitacoes")
def listar_material_solicitacoes(
    maquina_id: str | None = None,
    status: str = "ABERTA",
    limit: int = 100,
):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()

    lim = max(1, min(int(limit or 100), 500))
    st = (status or "ABERTA").upper().strip()
    mid = (maquina_id or "").upper().strip()
    filtrar_status = st not in ("TODAS", "TODOS", "ALL", "*")

    if mid and filtrar_status:
        rows = cur.execute(
            """
            SELECT id, maquina_id, item_id, arquivo_nome, material, status, criado_em, atendido_em
            FROM material_solicitacoes
            WHERE maquina_id = ? AND status = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (mid, st, lim),
        ).fetchall()
    elif mid:
        rows = cur.execute(
            """
            SELECT id, maquina_id, item_id, arquivo_nome, material, status, criado_em, atendido_em
            FROM material_solicitacoes
            WHERE maquina_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (mid, lim),
        ).fetchall()
    elif filtrar_status:
        rows = cur.execute(
            """
            SELECT id, maquina_id, item_id, arquivo_nome, material, status, criado_em, atendido_em
            FROM material_solicitacoes
            WHERE status = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (st, lim),
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT id, maquina_id, item_id, arquivo_nome, material, status, criado_em, atendido_em
            FROM material_solicitacoes
            ORDER BY id DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()

    conn.close()

    return [
        {
            "id": r[0],
            "maquina_id": r[1],
            "item_id": r[2],
            "arquivo_nome": r[3],
            "material": r[4],
            "status": r[5],
            "criado_em": r[6],
            "atendido_em": r[7],
        }
        for r in rows
    ]


@app.post("/almoxarifado/solicitacoes")
def criar_material_solicitacao(req: MaterialSolicitacaoIn):
    mid = (req.maquina_id or "").upper().strip()
    if not mid:
        raise HTTPException(status_code=400, detail="maquina_id obrigatorio")

    arquivo_nome = (req.arquivo_nome or "").strip() or None
    material = (req.material or "").strip() or _infer_material_from_arquivo_nome(arquivo_nome) or "material nao informado"

    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO material_solicitacoes
        (maquina_id, item_id, arquivo_nome, material, status, criado_em)
        VALUES (?, ?, ?, ?, 'ABERTA', datetime('now','localtime'))
        """,
        (mid, req.item_id, arquivo_nome, material),
    )

    conn.commit()
    item_id = cur.lastrowid
    conn.close()

    return {"ok": True, "id": item_id}


@app.post("/almoxarifado/solicitacoes/entregar")
def entregar_material_solicitacao(req: MaterialEntregaIn):
    mid = (req.maquina_id or "").upper().strip()
    if not mid:
        raise HTTPException(status_code=400, detail="maquina_id obrigatorio")
    if not req.item_id:
        raise HTTPException(status_code=400, detail="item_id obrigatorio")

    agora = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    updated = _marcar_material_solicitacoes_entregues(conn, mid, req.item_id, agora)
    conn.commit()
    conn.close()

    return {"ok": True, "updated": updated}


@app.get("/{full_path:path}", include_in_schema=False)
def react_fallback(full_path: str, request: Request):
    # não intercepta API nem arquivos estáticos antigos
    prefixes_bloqueados = (
        "maquinas",
        "arquivos",
        "fila",
        "fila_fs",
        "historico",
        "chat",
        "almoxarifado",
        "agente",
        "dashboard/indicadores",
        "dashboard/snapshots",
        "cors-test",
        "health",
        "static",
        "assets",
        "ui",
        "docs",
        "redoc",
        "openapi.json",
    )

    if any(full_path == p or full_path.startswith(p + "/") for p in prefixes_bloqueados):
        raise HTTPException(status_code=404, detail="Rota não encontrada")

    target = FRONT_DIST / full_path
    if target.exists() and target.is_file():
        return FileResponse(target)

    index_file = FRONT_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    raise HTTPException(status_code=404, detail="Frontend não gerado. Rode npm run build.")
