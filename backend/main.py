from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List
import logging
import shutil
import os
import platform
import subprocess
import sqlite3
import json
import re
import unicodedata
import time
import threading

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from io import BytesIO
from urllib.parse import quote
from openpyxl import Workbook

from backend.db import get_conn
from backend.config_maquinas import MAQUINAS
from backend.audit import log_action
from backend.maintenance import (
    MaintenanceError,
    change_machine_status,
    close_orphaned_maintenance_calls,
    ensure_maintenance_schema,
    iso_now as maintenance_iso_now,
    maintenance_row_to_dict,
)
from backend.cnc_assistant import (
    TEST_MACHINE_IDS,
    build_response,
    detect_intent,
    find_cnc_id,
    normalize_machine,
)
from backend.status_confirmation import (
    StatusConfirmationError,
    confirm_current_status,
    get_pending_status_confirmation,
    process_status_confirmations,
)
from backend.morning_status_confirmation import (
    confirm_morning_status,
    get_pending_morning_status,
    process_morning_status_confirmations,
)
from backend.plan_classification import (
    PlanClassificationError,
    classifications_by_plan,
    ensure_plan_classification_schema,
    normalize_priority,
    plan_is_compatible_with,
    set_plan_classification,
    validate_compatible_cnc_ids,
)

# =========================
# APP
# =========================
app = FastAPI(title="CNC Dashboard API")
BASE_DIR = Path(__file__).resolve().parent  # .../cnc-dashboard/backend
FRONT_DIST = BASE_DIR.parent / "frontend" / "dist"
FRONT_ASSETS = FRONT_DIST / "assets"
TEST_MACHINE_ID = "CNC_TESTE"
ASSISTANT_RATE_BUCKET: dict[str, list[float]] = {}
logger = logging.getLogger("cnc_dashboard")
STATUS_CONFIRMATION_STOP = threading.Event()
STATUS_CONFIRMATION_THREAD: threading.Thread | None = None

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
MINUTOS_DIA_MAQUINA = 18 * 60 + 24
HORAS_DIA_MAQUINA = MINUTOS_DIA_MAQUINA / 60
SEGUNDOS_DIA_MAQUINA = MINUTOS_DIA_MAQUINA * 60

# =========================
# MODELS
# =========================
class StatusRequest(BaseModel):
    status: str
    motivo: str | None = None
    maintenance_type_id: int | None = None
    work_order: str | None = None
    opening_notes: str | None = None
    closing_notes: str | None = None


class MaintenanceStartRequest(BaseModel):
    maintenance_type_id: int | None = None
    work_order: str | None = None
    opening_notes: str | None = None


class MaintenanceFinishRequest(BaseModel):
    new_status: str
    closing_notes: str | None = None


class AddFilaRequest(BaseModel):
    arquivo_id: int


class PlanClassificationRequest(BaseModel):
    priority: str = "normal"
    compatible_cnc_ids: List[str]


class AbrirVCarveRequest(BaseModel):
    arquivo_id: int | None = None
    item_id: int | None = None
    maquina_id: str | None = None


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
    arquivo_id: int | None = None
    arquivo_nome: str | None = None
    op: str | None = None
    material: str | None = None
    quantidade: str | None = None
    operador_id: str | None = None
    operador_nome: str | None = None


class MaterialEntregaIn(BaseModel):
    maquina_id: str
    item_id: int


class MaterialChatMensagemIn(BaseModel):
    usuario_id: str | None = None
    usuario_nome: str | None = None
    perfil: str = "OPERADOR"
    mensagem: str


class InvalidarApontamentoIn(BaseModel):
    motivo: str


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


class AssistantChatRequest(BaseModel):
    mensagem: str


class AssistantChatResponse(BaseModel):
    resposta: str
    ferramentas: list[str]
    ultima_atualizacao: str | None = None
    dados_desatualizados: bool = False


# =========================
# HELPERS (PROGRAMADOR / FILA)
# =========================
def _fila_programador_status_list():
    return ("AGUARDANDO", "PROGRAMANDO")


def _fila_ativa_status_list():
    return ("AGUARDANDO", "PROGRAMANDO", "EM_EXECUCAO", "BAIXADO")


def _fila_finalizada_status_list():
    return ("CORTADO", "CANCELADO")


def obter_ip_cliente(request: Request) -> str:
    # Use X-Forwarded-For/X-Real-IP somente quando o sistema estiver atras de um proxy controlado pela empresa.
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "desconhecido"


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
    ensure_plan_classification_schema(conn)
    try:
        cur.execute("ALTER TABLE arquivos_dxf ADD COLUMN deleted_em TEXT")
    except Exception:
        pass


VCARVE_EXTENSOES_PERMITIDAS = {".dxf", ".dwg", ".crv", ".crv3d"}


def _is_path_inside(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _is_wsl_environment() -> bool:
    if platform.system().lower() != "linux":
        return False
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
        return "microsoft" in version or "wsl" in version
    except Exception:
        return False


def _wsl_to_windows_path(path: Path) -> str:
    try:
        out = subprocess.check_output(["wslpath", "-w", str(path)], text=True, stderr=subprocess.DEVNULL)
        converted = out.strip()
        if converted:
            return converted
    except Exception:
        pass
    return str(path)


def _resolve_arquivo_cnc_path(row) -> Path:
    arquivo_path = (row["path"] or "").strip()
    arquivo_nome = (row["nome"] or "").strip()
    base_config = os.getenv("ARQUIVOS_CNC_BASE", "").strip()

    if arquivo_path:
        raw_path = Path(arquivo_path)
    elif arquivo_nome:
        raw_path = Path(arquivo_nome)
    else:
        raise FileNotFoundError("Arquivo sem caminho cadastrado.")

    if base_config:
        base = Path(base_config).resolve(strict=False)
        caminho = raw_path if raw_path.is_absolute() else base / raw_path
        caminho = caminho.resolve(strict=False)
        if not _is_path_inside(caminho, base):
            raise PermissionError("Arquivo fora da pasta base permitida para CNC.")
    else:
        caminho = raw_path if raw_path.is_absolute() else DXF_DIR / raw_path
        caminho = caminho.resolve(strict=False)

    if caminho.suffix.lower() not in VCARVE_EXTENSOES_PERMITIDAS:
        raise ValueError("Tipo de arquivo não permitido para abrir no VCarve.")

    if not caminho.exists():
        raise FileNotFoundError("Arquivo físico não encontrado no servidor.")

    return caminho


def _abrir_arquivo_no_vcarve(caminho_arquivo: Path):
    sistema = platform.system().lower()

    if sistema == "windows":
        vcarve_exe = os.getenv("VCARVE_EXE", "").strip()
        if vcarve_exe and Path(vcarve_exe).exists():
            subprocess.Popen([vcarve_exe, str(caminho_arquivo)], shell=False)
            return

        startfile = getattr(os, "startfile", None)
        if not startfile:
            raise RuntimeError(
                "Não foi possível abrir o VCarve neste ambiente. "
                "O backend não está rodando em Windows com interface gráfica."
            )
        startfile(str(caminho_arquivo))
        return

    if _is_wsl_environment() and shutil.which("cmd.exe"):
        caminho_windows = _wsl_to_windows_path(caminho_arquivo)
        vcarve_exe = os.getenv("VCARVE_EXE", "").strip()
        if vcarve_exe:
            subprocess.Popen(["cmd.exe", "/c", "start", "", vcarve_exe, caminho_windows], shell=False)
        else:
            subprocess.Popen(["cmd.exe", "/c", "start", "", caminho_windows], shell=False)
        return

    if sistema != "windows":
        raise RuntimeError(
            "Não foi possível abrir o VCarve neste ambiente. "
            f"O backend está rodando em {platform.system()}, então ele não consegue abrir o VCarve instalado no PC do navegador. "
            "Execute o backend no Windows onde o VCarve está instalado ou use um agente local nesse computador."
        )


def _ensure_maquinas_cols(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maquinas (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PARADA',
            status_desde TEXT,
            arquivo_pendente_id INTEGER,
            operador_nome TEXT,
            ultima_comunicacao TEXT
        )
        """
    )
    columns = {row[1] for row in cur.execute("PRAGMA table_info(maquinas)").fetchall()}
    if "operador_nome" not in columns:
        cur.execute("ALTER TABLE maquinas ADD COLUMN operador_nome TEXT")
    if "ultima_comunicacao" not in columns:
        cur.execute("ALTER TABLE maquinas ADD COLUMN ultima_comunicacao TEXT")


def _touch_maquina_comunicacao(conn, maquina_id: str, quando_iso: str | None = None):
    _ensure_maquinas_cols(conn)
    mid = str(maquina_id or "").upper().strip()
    if not mid:
        return
    conn.execute(
        "UPDATE maquinas SET ultima_comunicacao = ? WHERE id = ?",
        (quando_iso or datetime.now().isoformat(timespec="seconds"), mid),
    )


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
    for _col, ddl in (
        ("maquina_nome", "ALTER TABLE material_solicitacoes ADD COLUMN maquina_nome TEXT"),
        ("arquivo_id", "ALTER TABLE material_solicitacoes ADD COLUMN arquivo_id INTEGER"),
        ("op", "ALTER TABLE material_solicitacoes ADD COLUMN op TEXT"),
        ("quantidade", "ALTER TABLE material_solicitacoes ADD COLUMN quantidade TEXT"),
        ("operador_id", "ALTER TABLE material_solicitacoes ADD COLUMN operador_id TEXT"),
        ("operador_nome", "ALTER TABLE material_solicitacoes ADD COLUMN operador_nome TEXT"),
        ("atualizado_em", "ALTER TABLE material_solicitacoes ADD COLUMN atualizado_em TEXT"),
        ("em_separacao_por", "ALTER TABLE material_solicitacoes ADD COLUMN em_separacao_por TEXT"),
        ("em_separacao_por_nome", "ALTER TABLE material_solicitacoes ADD COLUMN em_separacao_por_nome TEXT"),
        ("em_separacao_em", "ALTER TABLE material_solicitacoes ADD COLUMN em_separacao_em TEXT"),
        ("entregue_por", "ALTER TABLE material_solicitacoes ADD COLUMN entregue_por TEXT"),
        ("entregue_por_nome", "ALTER TABLE material_solicitacoes ADD COLUMN entregue_por_nome TEXT"),
        ("entregue_em", "ALTER TABLE material_solicitacoes ADD COLUMN entregue_em TEXT"),
        ("cancelado_por", "ALTER TABLE material_solicitacoes ADD COLUMN cancelado_por TEXT"),
        ("cancelado_por_nome", "ALTER TABLE material_solicitacoes ADD COLUMN cancelado_por_nome TEXT"),
        ("cancelado_em", "ALTER TABLE material_solicitacoes ADD COLUMN cancelado_em TEXT"),
        ("motivo_cancelamento", "ALTER TABLE material_solicitacoes ADD COLUMN motivo_cancelamento TEXT"),
        ("visualizado_almoxarifado", "ALTER TABLE material_solicitacoes ADD COLUMN visualizado_almoxarifado INTEGER DEFAULT 0"),
        ("visualizado_operador", "ALTER TABLE material_solicitacoes ADD COLUMN visualizado_operador INTEGER DEFAULT 1"),
        ("ultima_mensagem", "ALTER TABLE material_solicitacoes ADD COLUMN ultima_mensagem TEXT"),
        ("ultima_mensagem_em", "ALTER TABLE material_solicitacoes ADD COLUMN ultima_mensagem_em TEXT"),
    ):
        try:
            cur.execute(ddl)
        except Exception:
            pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS material_chat_mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            solicitacao_id INTEGER NOT NULL,
            usuario_id TEXT,
            usuario_nome TEXT,
            perfil TEXT NOT NULL,
            mensagem TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'USUARIO',
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            lida_operador INTEGER DEFAULT 0,
            lida_almoxarifado INTEGER DEFAULT 0
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

    code_match = re.search(r"(\d+(?:[,.]\d+)?\s*(?:TX|KP|AD|EX|MDF)\b.*)$", clean, flags=re.IGNORECASE)
    if code_match:
        return re.sub(r"\s+(?=(?:TX|KP|AD|EX|MDF)\b)", "", code_match.group(1), count=1, flags=re.IGNORECASE).strip()

    up = clean.upper()
    idx = up.find("MM")
    if idx > 0:
        start = idx
        while start > 0 and (clean[start - 1].isdigit() or clean[start - 1] in ",. "):
            start -= 1
        return clean[start:].strip()

    return ""


MATERIAL_STATUS_LABELS = {
    "ABERTA": "Aguardando Almoxarifado",
    "AGUARDANDO_ALMOXARIFADO": "Aguardando Almoxarifado",
    "EM_SEPARACAO": "Em separacao",
    "ENTREGUE": "Material Entregue",
    "CANCELADA_SEM_MATERIAL": "Sem Material",
    "CANCELADA": "Cancelada",
}
MATERIAL_PENDENTES = ("ABERTA", "AGUARDANDO_ALMOXARIFADO", "EM_SEPARACAO")


def _material_status_norm(status: str | None) -> str:
    st = (status or "AGUARDANDO_ALMOXARIFADO").upper().strip()
    if st == "ABERTA":
        return "AGUARDANDO_ALMOXARIFADO"
    return st


def _material_msg_to_dict(row):
    return {
        "id": row["id"],
        "solicitacao_id": row["solicitacao_id"],
        "usuario_id": row["usuario_id"],
        "usuario_nome": row["usuario_nome"],
        "perfil": row["perfil"],
        "mensagem": row["mensagem"],
        "tipo": row["tipo"],
        "criado_em": row["criado_em"],
        "lida_operador": bool(row["lida_operador"]),
        "lida_almoxarifado": bool(row["lida_almoxarifado"]),
    }


def _material_row_to_dict(row):
    status = _material_status_norm(row["status"])
    return {
        "id": row["id"],
        "maquina_id": row["maquina_id"],
        "maquina_nome": row["maquina_nome"] or row["maquina_id"],
        "item_id": row["item_id"],
        "arquivo_id": row["arquivo_id"],
        "arquivo_nome": row["arquivo_nome"],
        "op": row["op"],
        "material": row["material"],
        "quantidade": row["quantidade"],
        "operador_id": row["operador_id"],
        "operador_nome": row["operador_nome"],
        "status": status,
        "status_label": MATERIAL_STATUS_LABELS.get(status, status),
        "criado_em": row["criado_em"],
        "atualizado_em": row["atualizado_em"],
        "atendido_em": row["atendido_em"],
        "em_separacao_por": row["em_separacao_por"],
        "em_separacao_por_nome": row["em_separacao_por_nome"],
        "em_separacao_em": row["em_separacao_em"],
        "entregue_por": row["entregue_por"],
        "entregue_por_nome": row["entregue_por_nome"],
        "entregue_em": row["entregue_em"],
        "cancelado_por": row["cancelado_por"],
        "cancelado_por_nome": row["cancelado_por_nome"],
        "cancelado_em": row["cancelado_em"],
        "motivo_cancelamento": row["motivo_cancelamento"],
        "visualizado_almoxarifado": bool(row["visualizado_almoxarifado"]),
        "visualizado_operador": bool(row["visualizado_operador"]),
        "ultima_mensagem": row["ultima_mensagem"],
        "ultima_mensagem_em": row["ultima_mensagem_em"],
    }


def _material_add_message(
    conn,
    solicitacao_id: int,
    usuario_id: str | None,
    usuario_nome: str | None,
    perfil: str,
    mensagem: str,
    tipo: str = "USUARIO",
):
    _ensure_material_solicitacoes_table(conn)
    perfil_clean = (perfil or "OPERADOR").upper().strip()
    tipo_clean = (tipo or "USUARIO").upper().strip()
    texto = (mensagem or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="mensagem obrigatoria")

    lida_operador = 1 if perfil_clean == "OPERADOR" else 0
    lida_almoxarifado = 1 if perfil_clean == "ALMOXARIFADO" else 0
    if tipo_clean in ("SISTEMA", "STATUS"):
        lida_operador = 0
        lida_almoxarifado = 0

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO material_chat_mensagens
        (solicitacao_id, usuario_id, usuario_nome, perfil, mensagem, tipo, criado_em, lida_operador, lida_almoxarifado)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'), ?, ?)
        """,
        (solicitacao_id, usuario_id, usuario_nome, perfil_clean, texto, tipo_clean, lida_operador, lida_almoxarifado),
    )
    cur.execute(
        """
        UPDATE material_solicitacoes
        SET ultima_mensagem = ?,
            ultima_mensagem_em = datetime('now','localtime'),
            atualizado_em = datetime('now','localtime'),
            visualizado_operador = ?,
            visualizado_almoxarifado = ?
        WHERE id = ?
        """,
        (texto, lida_operador, lida_almoxarifado, solicitacao_id),
    )
    return cur.lastrowid


def _criar_material_solicitacao_core(conn, req: MaterialSolicitacaoIn):
    mid = (req.maquina_id or "").upper().strip()
    if not mid:
        raise HTTPException(status_code=400, detail="maquina_id obrigatorio")

    arquivo_nome = (req.arquivo_nome or "").strip() or None
    material = (req.material or "").strip() or _infer_material_from_arquivo_nome(arquivo_nome) or "material nao informado"
    op = (req.op or "").strip() or None
    operador_nome = (req.operador_nome or "").strip() or None

    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()
    dup = cur.execute(
        """
        SELECT id
        FROM material_solicitacoes
        WHERE maquina_id = ?
          AND COALESCE(item_id, 0) = COALESCE(?, 0)
          AND COALESCE(arquivo_nome, '') = COALESCE(?, '')
          AND COALESCE(material, '') = COALESCE(?, '')
          AND status IN ('ABERTA', 'AGUARDANDO_ALMOXARIFADO', 'EM_SEPARACAO')
        ORDER BY id DESC
        LIMIT 1
        """,
        (mid, req.item_id, arquivo_nome, material),
    ).fetchone()
    if dup:
        raise HTTPException(status_code=409, detail="Ja existe uma solicitacao pendente para este material.")

    cur.execute(
        """
        INSERT INTO material_solicitacoes
        (
            maquina_id, maquina_nome, item_id, arquivo_id, arquivo_nome, op, material, quantidade,
            operador_id, operador_nome, status, criado_em, atualizado_em,
            visualizado_almoxarifado, visualizado_operador
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AGUARDANDO_ALMOXARIFADO', datetime('now','localtime'), datetime('now','localtime'), 0, 1)
        """,
        (
            mid,
            mid,
            req.item_id,
            req.arquivo_id,
            arquivo_nome,
            op,
            material,
            (req.quantidade or "").strip() or None,
            (req.operador_id or "").strip() or None,
            operador_nome,
        ),
    )
    solicitacao_id = cur.lastrowid
    _material_add_message(
        conn,
        solicitacao_id,
        req.operador_id,
        operador_nome or "Operador",
        "OPERADOR",
        "Solicitacao de material enviada ao Almoxarifado.",
        "SISTEMA",
    )
    cur.execute(
        """
        UPDATE material_chat_mensagens
        SET lida_operador = 1
        WHERE solicitacao_id = ?
        """,
        (solicitacao_id,),
    )
    cur.execute(
        """
        UPDATE material_solicitacoes
        SET visualizado_operador = 1
        WHERE id = ?
        """,
        (solicitacao_id,),
    )
    return solicitacao_id


def _marcar_material_solicitacoes_entregues(conn, maquina_id: str, item_id: int, entregue_em: str):
    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id
        FROM material_solicitacoes
        WHERE maquina_id = ?
          AND item_id = ?
          AND status IN ('ABERTA', 'AGUARDANDO_ALMOXARIFADO', 'EM_SEPARACAO')
        """,
        ((maquina_id or "").upper().strip(), item_id),
    ).fetchall()
    cur.execute(
        """
        UPDATE material_solicitacoes
        SET status = 'ENTREGUE',
            atendido_em = COALESCE(atendido_em, ?),
            entregue_em = COALESCE(entregue_em, ?),
            entregue_por_nome = COALESCE(entregue_por_nome, 'Almoxarifado'),
            atualizado_em = ?,
            visualizado_operador = 0
        WHERE maquina_id = ?
          AND item_id = ?
          AND status IN ('ABERTA', 'AGUARDANDO_ALMOXARIFADO', 'EM_SEPARACAO')
        """,
        (
            (entregue_em or datetime.now().isoformat(timespec="seconds")),
            (entregue_em or datetime.now().isoformat(timespec="seconds")),
            (entregue_em or datetime.now().isoformat(timespec="seconds")),
            maquina_id.upper().strip(),
            item_id,
        ),
    )
    for r in rows:
        _material_add_message(
            conn,
            int(r["id"]),
            None,
            "Almoxarifado",
            "ALMOXARIFADO",
            "Material entregue pelo Almoxarifado.",
            "STATUS",
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
          AND status IN ('ABERTA', 'AGUARDANDO_ALMOXARIFADO', 'EM_SEPARACAO')
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
        "Material solicitado ainda nao foi marcado como entregue pelo Almoxarifado. "
        f"Aguarde a entrega antes de colocar em USINANDO ({material})."
    )


def _get_fila_reindexavel(conn, maquina_id: str):
    cur = conn.cursor()
    status_list = ("AGUARDANDO", "PROGRAMANDO", "BAIXADO")
    rows = cur.execute(
        f"""
        SELECT fi.id, fi.maquina_id, fi.arquivo_id, fi.posicao, fi.status, fi.criado_em,
               a.nome as arquivo_nome
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ({",".join(["?"] * len(status_list))})
        ORDER BY
          CASE WHEN fi.status = 'BAIXADO' THEN 0 ELSE 1 END,
          fi.posicao ASC,
          fi.id ASC
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

    # BAIXADO deve continuar como o primeiro item aguardando execucao.
    fila_prog = _get_fila_reindexavel(conn, maquina_id)
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


def _ensure_cnc_queue_audit_table(conn):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cnc_queue_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnc_id TEXT NOT NULL,
            arquivo_id INTEGER,
            arquivo_nome TEXT,
            acao TEXT NOT NULL DEFAULT 'REORDENAR_FILA',
            posicao_anterior INTEGER,
            posicao_nova INTEGER,
            ip_origem TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )


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


def _log_cnc_queue_audit(
    conn,
    *,
    cnc_id: str,
    arquivo_id=None,
    arquivo_nome=None,
    posicao_anterior=None,
    posicao_nova=None,
    ip_origem=None,
):
    _ensure_cnc_queue_audit_table(conn)
    conn.execute(
        """
        INSERT INTO cnc_queue_audit (
            cnc_id,
            arquivo_id,
            arquivo_nome,
            acao,
            posicao_anterior,
            posicao_nova,
            ip_origem,
            criado_em
        )
        VALUES (?, ?, ?, 'REORDENAR_FILA', ?, ?, ?, ?)
        """,
        (
            cnc_id,
            arquivo_id,
            arquivo_nome,
            posicao_anterior,
            posicao_nova,
            str(ip_origem or "desconhecido")[:45],
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
    for _col, ddl in (
        ("operador_nome", "ALTER TABLE maquina_status_log ADD COLUMN operador_nome TEXT"),
        ("invalidado", "ALTER TABLE maquina_status_log ADD COLUMN invalidado INTEGER DEFAULT 0"),
        ("invalidado_por", "ALTER TABLE maquina_status_log ADD COLUMN invalidado_por TEXT"),
        ("invalidado_em", "ALTER TABLE maquina_status_log ADD COLUMN invalidado_em TEXT"),
        ("motivo_invalidacao", "ALTER TABLE maquina_status_log ADD COLUMN motivo_invalidacao TEXT"),
    ):
        try:
            cur.execute(ddl)
        except Exception:
            pass


def _require_admin_or_supervisor(x_user_role: str | None = Header(default=None), x_user_name: str | None = Header(default=None)):
    role = (x_user_role or "ADMIN").strip().upper()
    if role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Acesso permitido somente para Admin ou Supervisor.")
    return (x_user_name or role).strip() or role


def _require_queue_audit_viewer(x_user_role: str | None = Header(default=None), x_user_name: str | None = Header(default=None)):
    role = (x_user_role or "").strip().upper()
    if role not in {"ADMIN", "SUPERVISOR", "PROGRAMADOR"}:
        raise HTTPException(status_code=403, detail="Acesso permitido somente para Admin, Supervisor ou Programador.")
    return {"nome": (x_user_name or role).strip() or role, "role": role}


def _maintenance_actor(
    x_user_id: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
):
    return {"id": x_user_id, "name": x_user_name, "role": x_user_role}


def _normalize_cnc_audit_id(cnc_id: str) -> str:
    raw = str(cnc_id or "").strip().upper()
    if raw.isdigit():
        return f"CNC{int(raw):02d}"
    match = re.fullmatch(r"CNC\s*0?(\d{1,2})", raw)
    if match:
        return f"CNC{int(match.group(1)):02d}"
    return raw


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
    if "OPERADOR" in s:
        return "FALTA OPERADOR"
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


def _local_naive_datetime(value: str | datetime) -> datetime:
    """Compatibiliza registros antigos sem fuso e registros ISO com fuso do servidor."""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


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
    operador_nome = _get_operador_nome_for_machine(conn, maquina_id)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO maquina_status_log
        (maquina_id, status, motivo, operador_nome, inicio_em, fim_em, criado_em, invalidado)
        VALUES (?, ?, ?, ?, ?, NULL, ?, 0)
        """,
        (maquina_id, status, motivo, operador_nome, inicio_iso, inicio_iso),
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
        "OPERADOR",
    ]
    return any(t in s for t in termos)


def _dashboard_bucket_from_status(status: str, motivo: str | None = None) -> str:
    s = (status or "").strip().upper()
    m = (motivo or "").strip().upper()

    txt = f"{s} {m}".strip()

    if _is_machine_usinando(s):
        return "usinando"
    if "USIN" in txt or "CORT" in txt:
        return "usinando"
    if "TROCA" in txt and "SACRIFIC" in txt:
        return "troca_sacrificio"
    if "SETUP" in txt:
        return "setup"
    if "MANUT" in txt:
        return "manutencao"
    if ("AGUAR" in txt or "AGUARD" in txt) and ("EMPILH" in txt or "EMPILHADEIRA" in txt):
        return "falta_material"
    if "EMPILH" in txt:
        return "falta_material"
    if "OPERADOR" in txt:
        return "falta_operador"
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


def _normalize_manutencao_motivo(motivo: str | None) -> str:
    text = _normalize_match_text(motivo or "")

    if "ELETR" in text:
        return "ELETRICO"
    if "LUB" in text:
        return "LUBRIFICACAO"
    if "MEC" in text:
        return "MECANICO"

    # Registros antigos de manutencao nao tinham motivo detalhado.
    return "MECANICO"


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
        "falta_operador",
        "programacao",
        "troca_sacrificio",
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
            "status_timeline": [],
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
          AND COALESCE(invalidado, 0) = 0
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
            seg_ini = _local_naive_datetime(r["inicio_em"])
            seg_fim = _local_naive_datetime(r["fim_em"] or now_dt.isoformat(timespec="seconds"))
        except Exception:
            continue

        secs = overlap_seconds(seg_ini, seg_fim)
        if secs <= 0:
            continue

        timeline_ini = max(seg_ini, dt_ini_base)
        timeline_fim = min(seg_fim, dt_fim_base)
        per_machine[maquina_id]["status_timeline"].append(
            {
                "status": r["status"] or "",
                "motivo": r["motivo"] or "",
                "inicio_em": timeline_ini.isoformat(timespec="seconds"),
                "fim_em": timeline_fim.isoformat(timespec="seconds"),
            }
        )

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
        + totals["falta_operador"]
        + totals["troca_sacrificio"]
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
                "falta_operador": totals["falta_operador"],
                "programacao": totals["programacao"],
                "troca_sacrificio": totals["troca_sacrificio"],
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
                + item["falta_operador"]
                + item["troca_sacrificio"]
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
                "status_timeline": item["status_timeline"],
                "usinando_min": usinando_min,
                "setup_min": setup_min,
                "setup_medio_min": setup_medio_machine_min,
                "total_setups": setup_count,
                "programacao_min": programacao_min,
                "troca_sacrificio_min": round(item["troca_sacrificio"] / 60, 2),
                "manutencao_min": round(item["manutencao"] / 60, 2),
                "falta_material_min": round(item["falta_material"] / 60, 2),
                "falta_operador_min": round(item["falta_operador"] / 60, 2),
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
# =========================
# ADMIN
# =========================
@app.get("/api/admin/status-apontamentos")
def admin_listar_status_apontamentos(
    request: Request,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    cnc: str | None = None,
    operador: str | None = None,
    status: str | None = None,
    situacao: str = "todos",
    limit: int = 500,
):
    _require_admin_or_supervisor(
        request.headers.get("x-user-role"),
        request.headers.get("x-user-name"),
    )

    conn = get_conn()
    _ensure_maquina_status_log_table(conn)
    _ensure_maquinas_cols(conn)
    cur = conn.cursor()

    where = []
    params: list = []
    if data_inicio:
        where.append("date(l.inicio_em) >= date(?)")
        params.append(data_inicio)
    if data_fim:
        where.append("date(l.inicio_em) <= date(?)")
        params.append(data_fim)
    if cnc:
        where.append("UPPER(l.maquina_id) = ?")
        params.append(cnc.upper().strip())
    if operador:
        where.append("LOWER(COALESCE(l.operador_nome, m.operador_nome, '')) LIKE ?")
        params.append(f"%{operador.lower().strip()}%")
    if status:
        where.append("LOWER(COALESCE(l.status, '')) LIKE ?")
        params.append(f"%{status.lower().strip()}%")

    sit = (situacao or "todos").lower().strip()
    if sit == "validos":
        where.append("COALESCE(l.invalidado, 0) = 0")
    elif sit == "invalidados":
        where.append("COALESCE(l.invalidado, 0) = 1")

    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    lim = max(1, min(int(limit or 500), 1000))
    rows = cur.execute(
        f"""
        SELECT
          l.id,
          l.maquina_id,
          COALESCE(l.operador_nome, m.operador_nome, '') AS operador_nome,
          l.status,
          l.motivo,
          l.inicio_em,
          l.fim_em,
          l.criado_em,
          COALESCE(l.invalidado, 0) AS invalidado,
          l.invalidado_por,
          l.invalidado_em,
          l.motivo_invalidacao
        FROM maquina_status_log l
        LEFT JOIN maquinas m ON m.id = l.maquina_id
        {sql_where}
        ORDER BY l.inicio_em DESC, l.id DESC
        LIMIT ?
        """,
        (*params, lim),
    ).fetchall()
    conn.close()

    out = []
    now_iso = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        inicio = r["inicio_em"]
        fim = r["fim_em"] or now_iso
        duracao_seg = 0
        try:
            duracao_seg = max(0, int((datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)).total_seconds()))
        except Exception:
            pass
        out.append({
            "id": r["id"],
            "cnc": r["maquina_id"],
            "operador": r["operador_nome"],
            "status": r["status"],
            "observacao": r["motivo"] or "",
            "inicio_em": r["inicio_em"],
            "fim_em": r["fim_em"],
            "duracao_seg": duracao_seg,
            "invalidado": bool(r["invalidado"]),
            "situacao": "Invalidado" if r["invalidado"] else "Valido",
            "invalidado_por": r["invalidado_por"],
            "invalidado_em": r["invalidado_em"],
            "motivo_invalidacao": r["motivo_invalidacao"],
        })
    return out


@app.post("/api/admin/status-apontamentos/{apontamento_id}/invalidar")
def admin_invalidar_status_apontamento(apontamento_id: int, body: InvalidarApontamentoIn, request: Request):
    admin_user = _require_admin_or_supervisor(
        request.headers.get("x-user-role"),
        request.headers.get("x-user-name"),
    )
    motivo = (body.motivo or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="Motivo da invalidacao obrigatorio.")

    conn = get_conn()
    _ensure_maquina_status_log_table(conn)
    row = conn.execute(
        "SELECT id, invalidado FROM maquina_status_log WHERE id = ?",
        (apontamento_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Apontamento nao encontrado.")
    if int(row["invalidado"] or 0) == 1:
        conn.close()
        raise HTTPException(status_code=409, detail="Apontamento ja esta invalidado.")

    conn.execute(
        """
        UPDATE maquina_status_log
        SET invalidado = 1,
            invalidado_por = ?,
            invalidado_em = datetime('now','localtime'),
            motivo_invalidacao = ?
        WHERE id = ?
        """,
        (admin_user, motivo, apontamento_id),
    )
    _ensure_dashboard_snapshot_daily_table(conn)
    conn.execute("DELETE FROM dashboard_snapshot_daily")
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Apontamento invalidado com sucesso."}


def _assistant_require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
):
    expected_token = (os.getenv("CNC_ASSISTANT_TOKEN") or os.getenv("ASSISTANT_API_TOKEN") or "").strip()
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if expected_token and bearer == expected_token:
        return {"id": x_user_id, "nome": x_user_name or "token", "role": x_user_role or "API"}
    if x_user_id or x_user_name or x_user_role:
        return {"id": x_user_id, "nome": x_user_name or x_user_id or x_user_role, "role": x_user_role or "OPERADOR"}
    raise HTTPException(status_code=401, detail="Autenticacao obrigatoria para consultar o assistente CNC.")


def _assistant_rate_limit(request: Request, user: dict):
    limit = max(1, int(os.getenv("CNC_ASSISTANT_RATE_LIMIT_PER_MINUTE", "20") or "20"))
    client_host = request.client.host if request.client else "anon"
    key = str(user.get("id") or user.get("nome") or client_host)
    now = time.time()
    bucket = [stamp for stamp in ASSISTANT_RATE_BUCKET.get(key, []) if now - stamp < 60]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Muitas perguntas em pouco tempo. Aguarde um instante e tente novamente.")
    bucket.append(now)
    ASSISTANT_RATE_BUCKET[key] = bucket


def _cnc_current_file(conn, maquina_id: str) -> str | None:
    try:
        row = conn.execute(
            """
            SELECT a.nome AS arquivo_nome
            FROM fila_itens fi
            JOIN arquivos_dxf a ON a.id = fi.arquivo_id
            WHERE fi.maquina_id = ?
              AND UPPER(COALESCE(fi.status, '')) = 'EM_EXECUCAO'
            ORDER BY fi.started_em DESC, fi.id DESC
            LIMIT 1
            """,
            (maquina_id,),
        ).fetchone()
        return row["arquivo_nome"] if row else None
    except Exception:
        return None


def _cnc_last_communication(conn, maquina_id: str) -> str | None:
    try:
        row = conn.execute(
            """
            SELECT ultima_comunicacao
            FROM maquinas
            WHERE id = ?
            """,
            (maquina_id,),
        ).fetchone()
        return row["ultima_comunicacao"] if row else None
    except Exception:
        return None


def _assistant_list_cncs() -> list[dict]:
    conn = get_conn()
    _ensure_maquinas_cols(conn)
    rows = conn.execute(
        """
        SELECT id, nome, status, status_desde, operador_nome, ultima_comunicacao
        FROM maquinas
        ORDER BY id
        """
    ).fetchall()
    machines = []
    for row in rows:
        raw = dict(row)
        machine_id = str(raw.get("id") or "").upper().strip()
        if machine_id in TEST_MACHINE_IDS:
            continue
        machine = normalize_machine(
            raw,
            arquivo_atual=_cnc_current_file(conn, machine_id),
            ultima_comunicacao=_cnc_last_communication(conn, machine_id),
        )
        machines.append(machine.as_dict())
    conn.close()
    return machines


def consultar_status_geral() -> list[dict]:
    return _assistant_list_cncs()


def consultar_status_cnc(cnc_id: str) -> dict | None:
    cnc = str(cnc_id or "").upper().strip()
    return next((m for m in _assistant_list_cncs() if m["id"] == cnc), None)


def consultar_cncs_usinando() -> list[dict]:
    return [m for m in _assistant_list_cncs() if m["status"] == "usinando"]


def consultar_cncs_paradas() -> list[dict]:
    stopped = {"parada_nao_programada", "parada_programada", "desligada", "sem_comunicacao"}
    return [m for m in _assistant_list_cncs() if m["status"] in stopped]


def consultar_cncs_em_manutencao() -> list[dict]:
    return [m for m in _assistant_list_cncs() if m["status"] == "manutencao"]


def consultar_cncs_em_setup() -> list[dict]:
    return [m for m in _assistant_list_cncs() if m["status"] == "setup"]


def consultar_dados_desatualizados() -> list[dict]:
    return [m for m in _assistant_list_cncs() if m.get("dados_desatualizados") is True]


def consultar_arquivo_atual(cnc_id: str) -> str | None:
    machine = consultar_status_cnc(cnc_id)
    return machine.get("arquivo_atual") if machine else None


def _assistant_latest_update(machines: list[dict]) -> str | None:
    updates = [m.get("ultima_comunicacao") for m in machines if m.get("ultima_comunicacao")]
    return max(updates) if updates else None


@app.get("/api/cncs/status")
def api_cncs_status(_user: dict = Depends(_assistant_require_auth)):
    return {"maquinas": consultar_status_geral(), "somente_leitura": True}


@app.get("/api/cncs/paradas")
def api_cncs_paradas(_user: dict = Depends(_assistant_require_auth)):
    return {"maquinas": consultar_cncs_paradas(), "somente_leitura": True}


@app.get("/api/cncs/manutencoes")
def api_cncs_manutencoes(_user: dict = Depends(_assistant_require_auth)):
    return {"maquinas": consultar_cncs_em_manutencao(), "somente_leitura": True}


@app.get("/api/cncs/desatualizadas")
def api_cncs_desatualizadas(_user: dict = Depends(_assistant_require_auth)):
    return {"maquinas": consultar_dados_desatualizados(), "somente_leitura": True}


@app.get("/api/cncs/{cnc_id}/queue-audit")
def api_cnc_queue_audit(
    cnc_id: str,
    limit: int = Query(100, ge=1, le=500),
    data_inicio: str | None = Query(default=None),
    data_fim: str | None = Query(default=None),
    ip: str | None = Query(default=None),
    _user: dict = Depends(_require_queue_audit_viewer),
):
    mid = _normalize_cnc_audit_id(cnc_id)
    conn = get_conn()
    _ensure_cnc_queue_audit_table(conn)

    where = ["cnc_id = ?"]
    params: list = [mid]
    if data_inicio:
        where.append("criado_em >= ?")
        params.append(data_inicio)
    if data_fim:
        where.append("criado_em <= ?")
        params.append(data_fim)
    if ip:
        where.append("ip_origem = ?")
        params.append(ip.strip())
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, cnc_id, arquivo_id, arquivo_nome, acao, posicao_anterior, posicao_nova, ip_origem, criado_em
        FROM cnc_queue_audit
        WHERE {" AND ".join(where)}
        ORDER BY criado_em DESC, id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get("/api/cncs/{cnc_id}")
def api_cnc_status(cnc_id: str, _user: dict = Depends(_assistant_require_auth)):
    machine = consultar_status_cnc(cnc_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Maquina nao encontrada.")
    return {"maquina": machine, "somente_leitura": True}


@app.post("/api/assistant/chat", response_model=AssistantChatResponse)
def api_assistant_chat(req: AssistantChatRequest, request: Request, user: dict = Depends(_assistant_require_auth)):
    _assistant_rate_limit(request, user)
    mensagem = (req.mensagem or "").strip()
    if not mensagem:
        raise HTTPException(status_code=400, detail="Mensagem obrigatoria.")
    if len(mensagem) > 500:
        raise HTTPException(status_code=413, detail="Mensagem muito longa. Limite de 500 caracteres.")

    blocked = ("ligue", "desligue", "pare a maquina", "interrompa", "altere", "mova", "execute", "revele", "token", "senha")
    if any(term in mensagem.lower() for term in blocked):
        resposta = "Posso apenas consultar dados das CNCs. Nao executo comandos, nao altero status e nao revelo configuracoes internas."
        log_action(None, "ASSISTANT_CHAT_BLOCKED", extra=json.dumps({"usuario": user, "pergunta": mensagem}, ensure_ascii=False))
        return AssistantChatResponse(resposta=resposta, ferramentas=[], ultima_atualizacao=None, dados_desatualizados=False)

    try:
        intent, cnc_id = detect_intent(mensagem)
        tools = []
        if intent == "cnc":
            tools.append("consultar_status_cnc")
        elif intent == "arquivo":
            tools.append("consultar_arquivo_atual")
        elif intent == "usinando":
            tools.append("consultar_cncs_usinando")
        elif intent == "paradas":
            tools.append("consultar_cncs_paradas")
        elif intent == "manutencao":
            tools.append("consultar_cncs_em_manutencao")
        elif intent == "setup":
            tools.append("consultar_cncs_em_setup")
        elif intent == "desatualizadas":
            tools.append("consultar_dados_desatualizados")
        else:
            tools.append("consultar_status_geral")

        machines = consultar_status_geral()
        if intent in {"cnc", "arquivo"} and not cnc_id:
            cnc_id = find_cnc_id(mensagem)
        resposta = build_response(intent, machines, cnc_id)
        latest = _assistant_latest_update(machines)
        stale = any(m.get("dados_desatualizados") is True for m in machines)
        log_action(
            None,
            "ASSISTANT_CHAT",
            extra=json.dumps(
                {"usuario": user, "pergunta": mensagem, "ferramentas": tools},
                ensure_ascii=False,
            ),
        )
        return AssistantChatResponse(resposta=resposta, ferramentas=tools, ultima_atualizacao=latest, dados_desatualizados=stale)
    except HTTPException:
        raise
    except Exception:
        return AssistantChatResponse(
            resposta="Nao foi possivel consultar as maquinas neste momento.",
            ferramentas=[],
            ultima_atualizacao=None,
            dados_desatualizados=False,
        )


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


def _legacy_atualizar_status_desativado(maquina_id: str, req: StatusRequest):
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


def _legacy_machine_status_hook(conn, machine: dict, novo_status: str, agora_iso: str):
    """Preserva históricos, timers e snapshots na transação do use case central."""
    maquina_id = machine["id"]
    status_anterior = machine.get("status") or ""
    inicio_anterior = machine.get("status_desde")
    _ensure_fila_itens_cols(conn)
    _ensure_maquina_status_log_table(conn)
    _ensure_dashboard_snapshot_daily_table(conn)
    _validate_usinagem_status_arquivo(conn, maquina_id, novo_status)
    if inicio_anterior:
        duracao = None
        try:
            duracao = int((datetime.fromisoformat(agora_iso) - datetime.fromisoformat(inicio_anterior)).total_seconds())
        except Exception:
            pass
        conn.execute(
            "INSERT INTO historico_status (maquina_id, status, inicio, fim, duracao_segundos) VALUES (?, ?, ?, ?, ?)",
            (maquina_id, status_anterior, inicio_anterior, agora_iso, duracao),
        )
    was_usinando = _is_machine_usinando(status_anterior)
    will_usinando = _is_machine_usinando(novo_status)
    if was_usinando and not will_usinando:
        _pausar_timer_itens_em_execucao(conn, maquina_id, agora_iso)
    if not was_usinando and will_usinando:
        _retomar_timer_itens_em_execucao(conn, maquina_id, agora_iso)
    _close_open_status_log(conn, maquina_id, agora_iso)
    _open_status_log(conn, maquina_id, novo_status, _infer_motivo_from_status(novo_status), agora_iso)
    try:
        start_date = datetime.fromisoformat(inicio_anterior).date() if inicio_anterior else datetime.now().date()
        _save_dashboard_snapshots_range(conn, start_date, datetime.now().date())
    except Exception:
        pass


def _run_status_change(maquina_id: str, status: str, actor: dict, **maintenance_data):
    try:
        return change_machine_status(
            get_conn,
            maquina_id,
            status,
            actor,
            legacy_hook=_legacy_machine_status_hook,
            **maintenance_data,
        )
    except MaintenanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/maquinas/{maquina_id}/status")
def atualizar_status(maquina_id: str, req: StatusRequest, actor: dict = Depends(_maintenance_actor)):
    result = _run_status_change(
        maquina_id,
        req.status,
        actor,
        maintenance_type_id=req.maintenance_type_id,
        work_order=req.work_order,
        opening_notes=req.opening_notes,
        closing_notes=req.closing_notes,
    )
    return {
        **result,
        "maquina_id": maquina_id,
        "status": result["machine"]["status"],
        "desde": result["machine"].get("status_desde"),
        "status_inalterado": result["status_unchanged"],
    }


def _automatic_shutdown_machine(maquina_id: str) -> None:
    _run_status_change(
        maquina_id,
        "DESLIGADA",
        {"id": None, "name": "Sistema", "role": "ADMIN"},
    )
    conn = get_conn()
    try:
        conn.execute("UPDATE maquinas SET operador_nome = '' WHERE id = ?", (maquina_id,))
        conn.commit()
    finally:
        conn.close()


def _process_nightly_status_confirmations() -> dict:
    return process_status_confirmations(get_conn, _automatic_shutdown_machine)


def _status_confirmation_worker() -> None:
    while not STATUS_CONFIRMATION_STOP.is_set():
        try:
            _process_nightly_status_confirmations()
        except Exception:
            logger.exception("Falha ao processar confirmações noturnas de status")
        try:
            process_morning_status_confirmations(get_conn, legacy_hook=_legacy_machine_status_hook)
        except Exception:
            logger.exception("Falha ao processar confirmações da manhã")
        now = datetime.now().astimezone()
        current_minute = now.hour * 60 + now.minute
        in_confirmation_window = (
            (23 * 60 + 18) <= current_minute <= (23 * 60 + 25)
            or (now.weekday() < 5 and (5 * 60 + 4) <= current_minute <= (5 * 60 + 16))
        )
        STATUS_CONFIRMATION_STOP.wait(1 if in_confirmation_window else 30)


@app.on_event("startup")
def start_status_confirmation_worker():
    global STATUS_CONFIRMATION_THREAD
    if STATUS_CONFIRMATION_THREAD and STATUS_CONFIRMATION_THREAD.is_alive():
        return
    STATUS_CONFIRMATION_STOP.clear()
    STATUS_CONFIRMATION_THREAD = threading.Thread(
        target=_status_confirmation_worker,
        name="status-confirmation-worker",
        daemon=True,
    )
    STATUS_CONFIRMATION_THREAD.start()


@app.on_event("shutdown")
def stop_status_confirmation_worker():
    STATUS_CONFIRMATION_STOP.set()
    if STATUS_CONFIRMATION_THREAD and STATUS_CONFIRMATION_THREAD.is_alive():
        STATUS_CONFIRMATION_THREAD.join(timeout=2)


@app.get("/api/cncs/{cnc_id}/status-confirmation")
def api_pending_status_confirmation(cnc_id: str):
    _process_nightly_status_confirmations()
    return {"item": get_pending_status_confirmation(get_conn, cnc_id)}


@app.post("/api/cncs/{cnc_id}/status-confirmation/confirm")
def api_confirm_status_confirmation(cnc_id: str, actor: dict = Depends(_maintenance_actor)):
    actor_name = str(actor.get("name") or "").strip()
    if not actor_name:
        raise HTTPException(status_code=422, detail="Selecione o operador antes de confirmar o status.")
    _process_nightly_status_confirmations()
    try:
        return confirm_current_status(get_conn, cnc_id, actor_name)
    except StatusConfirmationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


class MorningStatusRequest(StatusRequest):
    confirmation_id: int


@app.get("/api/cncs/{cnc_id}/morning-status-confirmation")
def api_pending_morning_status(cnc_id: str):
    process_morning_status_confirmations(get_conn, legacy_hook=_legacy_machine_status_hook)
    return {"item": get_pending_morning_status(get_conn, cnc_id)}


@app.post("/api/cncs/{cnc_id}/morning-status-confirmation/confirm")
def api_confirm_morning_status(cnc_id: str, req: MorningStatusRequest, actor: dict = Depends(_maintenance_actor)):
    try:
        return confirm_morning_status(
            get_conn, cnc_id, req.confirmation_id, req.status, actor,
            legacy_hook=_legacy_machine_status_hook,
            maintenance_type_id=req.maintenance_type_id,
            work_order=req.work_order, opening_notes=req.opening_notes,
            closing_notes=req.closing_notes,
        )
    except MaintenanceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _maintenance_select_base():
    return """
        SELECT c.*, t.name AS type_name, m.nome AS cnc_name
        FROM cnc_maintenance_calls c
        JOIN maintenance_types t ON t.id = c.maintenance_type_id
        JOIN maquinas m ON m.id = c.cnc_id
    """


@app.get("/api/maintenance/types")
def maintenance_types():
    conn = get_conn()
    try:
        ensure_maintenance_schema(conn)
        rows = conn.execute(
            "SELECT id, name, active, display_order FROM maintenance_types WHERE active = 1 ORDER BY display_order, name"
        ).fetchall()
        conn.commit()
        return [{"id": r["id"], "name": r["name"], "active": bool(r["active"]), "displayOrder": r["display_order"]} for r in rows]
    finally:
        conn.close()


@app.get("/api/maintenance/active")
def active_maintenance_calls():
    conn = get_conn()
    try:
        ensure_maintenance_schema(conn)
        close_orphaned_maintenance_calls(conn)
        rows = conn.execute(_maintenance_select_base() + " WHERE c.status = 'OPEN' ORDER BY c.started_at ASC, c.id ASC").fetchall()
        conn.commit()
        return {"serverNow": maintenance_iso_now(), "items": [maintenance_row_to_dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/maintenance/history")
def maintenance_history(
    cnc_id: str | None = None,
    maintenance_type_id: int | None = None,
    work_order: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    opened_by: str | None = None,
    finished_by: str | None = None,
    min_duration_seconds: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    conn = get_conn()
    try:
        ensure_maintenance_schema(conn)
        clauses, params = [], []
        for clause, value in (
            ("c.cnc_id = ?", cnc_id),
            ("c.maintenance_type_id = ?", maintenance_type_id),
            ("c.status = ?", status and status.upper()),
            ("c.started_at >= ?", date_from),
            ("c.started_at <= ?", date_to),
            ("c.opened_by_name = ?", opened_by),
            ("c.finished_by_name = ?", finished_by),
        ):
            if value not in (None, ""):
                clauses.append(clause)
                params.append(value)
        if work_order:
            clauses.append("c.work_order LIKE ?")
            params.append(f"%{work_order.strip()}%")
        if min_duration_seconds is not None:
            clauses.append("c.duration_seconds >= ?")
            params.append(min_duration_seconds)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(_maintenance_select_base() + where + " ORDER BY c.started_at DESC, c.id DESC LIMIT ?", (*params, limit)).fetchall()
        conn.commit()
        return {"serverNow": maintenance_iso_now(), "items": [maintenance_row_to_dict(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/cncs/{cnc_id}/maintenance/active")
def cnc_active_maintenance(cnc_id: str):
    conn = get_conn()
    try:
        ensure_maintenance_schema(conn)
        row = conn.execute(_maintenance_select_base() + " WHERE c.cnc_id = ? AND c.status = 'OPEN'", (cnc_id,)).fetchone()
        conn.commit()
        return {"serverNow": maintenance_iso_now(), "item": maintenance_row_to_dict(row) if row else None}
    finally:
        conn.close()


@app.post("/api/cncs/{cnc_id}/maintenance/start")
def start_maintenance(cnc_id: str, req: MaintenanceStartRequest, actor: dict = Depends(_maintenance_actor)):
    return _run_status_change(
        cnc_id,
        "MANUTENÇÃO",
        actor,
        maintenance_type_id=req.maintenance_type_id,
        work_order=req.work_order,
        opening_notes=req.opening_notes,
        require_new_maintenance_for_start=True,
    )


@app.post("/api/cncs/{cnc_id}/maintenance/finish")
def finish_maintenance(cnc_id: str, req: MaintenanceFinishRequest, actor: dict = Depends(_maintenance_actor)):
    if not req.new_status.strip() or "MANUT" in _normalize_match_text(req.new_status):
        raise HTTPException(status_code=422, detail="O novo status deve encerrar a manutenção.")
    return _run_status_change(
        cnc_id,
        req.new_status,
        actor,
        closing_notes=req.closing_notes,
        require_open_maintenance_for_finish=True,
    )


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


@app.get("/dashboard/manutencao")
def dashboard_manutencao(
    mes: str | None = Query(None, description="Mes no formato YYYY-MM"),
    data: str | None = Query(None, description="Data unica no formato YYYY-MM-DD"),
    data_inicio: str | None = Query(None, description="Data inicial no formato YYYY-MM-DD"),
    data_fim: str | None = Query(None, description="Data final no formato YYYY-MM-DD"),
):
    """
    Retorna a manutencao diaria do mes:
    - series por CNC
    - series por motivo (eletrico, mecanico, lubrificacao)
    """
    now_dt = datetime.now()

    try:
        if data:
            dia = datetime.fromisoformat(data.strip()).date()
            dt_ini = datetime(dia.year, dia.month, dia.day, 0, 0, 0)
            dt_fim_exclusive = dt_ini + timedelta(days=1)
            periodo_ref = dia.isoformat()
        elif data_inicio or data_fim:
            ini_raw = (data_inicio or data_fim or "").strip()
            fim_raw = (data_fim or data_inicio or "").strip()
            dia_ini = datetime.fromisoformat(ini_raw).date()
            dia_fim = datetime.fromisoformat(fim_raw).date()
            if dia_fim < dia_ini:
                dia_ini, dia_fim = dia_fim, dia_ini
            dt_ini = datetime(dia_ini.year, dia_ini.month, dia_ini.day, 0, 0, 0)
            dt_fim_exclusive = datetime(dia_fim.year, dia_fim.month, dia_fim.day, 0, 0, 0) + timedelta(days=1)
            periodo_ref = f"{dia_ini.isoformat()} a {dia_fim.isoformat()}"
        else:
            mes_ref = (mes or now_dt.strftime("%Y-%m")).strip()
            if not re.match(r"^\d{4}-\d{2}$", mes_ref):
                raise ValueError("Mes invalido")
            ano, mes_num = [int(x) for x in mes_ref.split("-")]
            dt_ini = datetime(ano, mes_num, 1, 0, 0, 0)
            if mes_num == 12:
                dt_fim_exclusive = datetime(ano + 1, 1, 1, 0, 0, 0)
            else:
                dt_fim_exclusive = datetime(ano, mes_num + 1, 1, 0, 0, 0)
            periodo_ref = mes_ref
    except Exception:
        raise HTTPException(status_code=400, detail="Periodo invalido. Use YYYY-MM ou YYYY-MM-DD.")

    dt_fim = dt_fim_exclusive - timedelta(seconds=1)
    dias = []
    cur_day = dt_ini.date()
    while cur_day < dt_fim_exclusive.date():
        dias.append(
            {
                "data": cur_day.isoformat(),
                "dia": cur_day.day,
                "label": f"{cur_day.day:02d}",
            }
        )
        cur_day = cur_day + timedelta(days=1)

    day_keys = [d["data"] for d in dias]
    motivo_defs = [
        ("ELETRICO", "Elétrico", "#3b82f6"),
        ("MECANICO", "Mecânico", "#f97316"),
        ("LUBRIFICACAO", "Lubrificação", "#22c55e"),
    ]

    conn = get_conn()
    _ensure_maquina_status_log_table(conn)
    _ensure_maquinas_cols(conn)
    cur = conn.cursor()

    maquinas_rows = cur.execute(
        """
        SELECT id
        FROM maquinas
        WHERE id NOT IN ({})
        ORDER BY id
        """.format(",".join(["?"] * len(TEST_MACHINE_IDS))),
        tuple(TEST_MACHINE_IDS),
    ).fetchall()

    maquinas_ids = [r["id"] for r in maquinas_rows]
    per_machine = {mid: {day: 0 for day in day_keys} for mid in maquinas_ids}
    per_machine_qtd = {mid: {day: 0 for day in day_keys} for mid in maquinas_ids}
    per_machine_motivo = {
        mid: {key: {day: 0 for day in day_keys} for key, _, _ in motivo_defs}
        for mid in maquinas_ids
    }
    per_machine_motivo_qtd = {
        mid: {key: {day: 0 for day in day_keys} for key, _, _ in motivo_defs}
        for mid in maquinas_ids
    }
    per_motivo = {key: {day: 0 for day in day_keys} for key, _, _ in motivo_defs}
    per_motivo_qtd = {key: {day: 0 for day in day_keys} for key, _, _ in motivo_defs}

    logs = cur.execute(
        """
        SELECT maquina_id, status, motivo, inicio_em, fim_em
        FROM maquina_status_log
        WHERE NOT (
            COALESCE(fim_em, ?) <= ?
            OR inicio_em >= ?
        )
          AND COALESCE(invalidado, 0) = 0
        ORDER BY inicio_em
        """,
        (
            now_dt.isoformat(timespec="seconds"),
            dt_ini.isoformat(timespec="seconds"),
            dt_fim_exclusive.isoformat(timespec="seconds"),
        ),
    ).fetchall()
    conn.close()

    total_seg = 0

    for r in logs:
        maquina_id = r["maquina_id"]
        if maquina_id not in per_machine:
            continue
        if _dashboard_bucket_from_status(r["status"], r["motivo"]) != "manutencao":
            continue

        try:
            seg_ini = _local_naive_datetime(r["inicio_em"])
            seg_fim = _local_naive_datetime(r["fim_em"] or now_dt.isoformat(timespec="seconds"))
        except Exception:
            continue

        seg_ini = max(seg_ini, dt_ini)
        seg_fim = min(seg_fim, dt_fim_exclusive)
        if seg_fim <= seg_ini:
            continue

        motivo_key = _normalize_manutencao_motivo(r["motivo"])
        cursor_dt = seg_ini

        while cursor_dt < seg_fim:
            day_start = datetime(cursor_dt.year, cursor_dt.month, cursor_dt.day)
            day_end = min(day_start + timedelta(days=1), seg_fim)
            day_key = cursor_dt.date().isoformat()
            segundos = max(0, int((day_end - cursor_dt).total_seconds()))

            if day_key in per_machine[maquina_id]:
                per_machine[maquina_id][day_key] += segundos
                per_machine_qtd[maquina_id][day_key] += 1
            if motivo_key in per_motivo and day_key in per_motivo[motivo_key]:
                per_motivo[motivo_key][day_key] += segundos
                per_motivo_qtd[motivo_key][day_key] += 1
                per_machine_motivo[maquina_id][motivo_key][day_key] += segundos
                per_machine_motivo_qtd[maquina_id][motivo_key][day_key] += 1

            total_seg += segundos
            cursor_dt = day_end

    maquinas_series = []
    for machine_id in maquinas_ids:
        total_machine = sum(per_machine[machine_id].values())
        total_machine_qtd = sum(per_machine_qtd[machine_id].values())
        motivos_machine_series = []
        for key, label, color in motivo_defs:
            total_machine_motivo = sum(per_machine_motivo[machine_id][key].values())
            total_machine_motivo_qtd = sum(per_machine_motivo_qtd[machine_id][key].values())
            motivos_machine_series.append(
                {
                    "key": key,
                    "label": label,
                    "color": color,
                    "total_qtd": int(total_machine_motivo_qtd),
                    "total_min": round(total_machine_motivo / 60, 2),
                    "total_horas": round(total_machine_motivo / 3600, 2),
                    "pontos": [
                        {
                            "data": day,
                            "dia": int(day[-2:]),
                            "qtd": int(per_machine_motivo_qtd[machine_id][key][day]),
                            "min": round(per_machine_motivo[machine_id][key][day] / 60, 2),
                            "horas": round(per_machine_motivo[machine_id][key][day] / 3600, 2),
                        }
                        for day in day_keys
                    ],
                }
            )
        maquinas_series.append(
            {
                "maquina": machine_id,
                "total_qtd": int(total_machine_qtd),
                "total_min": round(total_machine / 60, 2),
                "total_horas": round(total_machine / 3600, 2),
                "motivos": motivos_machine_series,
                "pontos": [
                    {
                        "data": day,
                        "dia": int(day[-2:]),
                        "qtd": int(per_machine_qtd[machine_id][day]),
                        "min": round(per_machine[machine_id][day] / 60, 2),
                        "horas": round(per_machine[machine_id][day] / 3600, 2),
                    }
                    for day in day_keys
                ],
            }
        )

    motivos_series = []
    for key, label, color in motivo_defs:
        total_motivo = sum(per_motivo[key].values())
        total_motivo_qtd = sum(per_motivo_qtd[key].values())
        motivos_series.append(
            {
                "key": key,
                "label": label,
                "color": color,
                "total_qtd": int(total_motivo_qtd),
                "total_min": round(total_motivo / 60, 2),
                "total_horas": round(total_motivo / 3600, 2),
                "pontos": [
                    {
                        "data": day,
                        "dia": int(day[-2:]),
                        "qtd": int(per_motivo_qtd[key][day]),
                        "min": round(per_motivo[key][day] / 60, 2),
                        "horas": round(per_motivo[key][day] / 3600, 2),
                    }
                    for day in day_keys
                ],
            }
        )

    return {
        "mes": periodo_ref,
        "data_inicio": dt_ini.date().isoformat(),
        "data_fim": dt_fim.date().isoformat(),
        "dias": dias,
        "maquinas": maquinas_series,
        "motivos": motivos_series,
        "totals": {
            "total_min": round(total_seg / 60, 2),
            "total_horas": round(total_seg / 3600, 2),
            "por_maquina": {item["maquina"]: item["total_min"] for item in maquinas_series},
            "qtd_por_maquina": {item["maquina"]: item["total_qtd"] for item in maquinas_series},
            "por_motivo": {item["key"]: item["total_min"] for item in motivos_series},
            "qtd_por_motivo": {item["key"]: item["total_qtd"] for item in motivos_series},
        },
    }


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


@app.post("/arquivos/upload-classified")
async def upload_classified_plans(
    files: List[UploadFile] = File(...),
    classifications: str = Form(...),
):
    try:
        metadata = json.loads(classifications)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Classificação dos planos inválida.") from exc
    if not isinstance(metadata, list) or len(metadata) != len(files):
        raise HTTPException(status_code=400, detail="Informe a classificação de cada plano selecionado.")
    if not files:
        raise HTTPException(status_code=400, detail="Selecione pelo menos um arquivo DXF.")

    prepared = []
    conn = get_conn()
    try:
        _ensure_fila_itens_cols(conn)
        _ensure_arquivos_cols(conn)
        seen_names = set()
        for index, (file, item) in enumerate(zip(files, metadata)):
            safe_name = Path(file.filename or "").name
            if not safe_name.lower().endswith(".dxf"):
                raise HTTPException(status_code=400, detail=f'Arquivo inválido: "{safe_name}". Envie apenas .DXF.')
            name_key = safe_name.strip().lower()
            if name_key in seen_names:
                raise HTTPException(status_code=409, detail=f'O arquivo "{safe_name}" foi selecionado mais de uma vez.')
            seen_names.add(name_key)
            if not isinstance(item, dict) or (item.get("name") and Path(str(item["name"])).name != safe_name):
                raise HTTPException(status_code=400, detail=f'Classificação não corresponde ao arquivo "{safe_name}".')
            try:
                priority = normalize_priority(item.get("priority"))
                cnc_ids = validate_compatible_cnc_ids(conn, item.get("compatible_cnc_ids"))
            except PlanClassificationError as exc:
                raise HTTPException(status_code=422, detail=f'{safe_name}: {exc}') from exc
            if _arquivo_ja_cortado_por_nome(conn, safe_name):
                raise HTTPException(status_code=409, detail=_detalhe_arquivo_ja_cortado(safe_name))
            if _arquivo_ja_em_fila_por_nome(conn, safe_name):
                raise HTTPException(status_code=409, detail=_detalhe_arquivo_ja_em_fila(safe_name))
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail=f'O arquivo "{safe_name}" está vazio.')
            if len(content) > 50 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f'O arquivo "{safe_name}" excede o limite de 50MB.')
            prepared.append((index, safe_name, content, priority, cnc_ids))
    finally:
        conn.close()

    stored_paths: list[Path] = []
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_fila_itens_cols(conn)
        _ensure_arquivos_cols(conn)
        results = []
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for index, safe_name, content, priority, cnc_ids in prepared:
            if _arquivo_ja_cortado_por_nome(conn, safe_name):
                raise HTTPException(status_code=409, detail=_detalhe_arquivo_ja_cortado(safe_name))
            if _arquivo_ja_em_fila_por_nome(conn, safe_name):
                raise HTTPException(status_code=409, detail=_detalhe_arquivo_ja_em_fila(safe_name))
            stored_name = f"{stamp}_{index}__{safe_name}"
            dest = DXF_DIR / stored_name
            dest.write_bytes(content)
            stored_paths.append(dest)
            cursor = conn.execute(
                "INSERT INTO arquivos_dxf (nome, path, criado_em, status, priority) VALUES (?, ?, ?, 'DISPONIVEL', ?)",
                (safe_name, str(dest), datetime.now().isoformat(timespec="seconds"), priority),
            )
            arquivo_id = cursor.lastrowid
            set_plan_classification(conn, arquivo_id, priority, cnc_ids)
            results.append({"id": arquivo_id, "nome": safe_name, "priority": priority, "compatible_cnc_ids": cnc_ids})
        conn.commit()
        return {"ok": True, "items": results}
    except Exception:
        conn.rollback()
        for path in stored_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                logger.exception("Falha ao remover arquivo após rollback de importação: %s", path)
        raise
    finally:
        conn.close()


@app.put("/arquivos/{arquivo_id}/classification")
def update_plan_classification(arquivo_id: int, req: PlanClassificationRequest):
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = set_plan_classification(conn, arquivo_id, req.priority, req.compatible_cnc_ids)
        except PlanClassificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.commit()
        return {"ok": True, **result}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/arquivos")
def listar_arquivos():
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, nome, status, criado_em, deleted_em, priority
        FROM arquivos_dxf
        ORDER BY id DESC
        """
    ).fetchall()
    compatibility = classifications_by_plan(conn, [row["id"] for row in rows])
    result = [{**dict(row), "compatible_cncs": compatibility.get(row["id"], [])} for row in rows]
    conn.close()
    return result


@app.get("/arquivos/disponiveis")
def listar_arquivos_disponiveis():
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    _ensure_chapa_movimentacao_log_table(conn)
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT
            a.id,
            a.nome,
            a.status,
            a.criado_em,
            a.priority,
            (
                SELECT
                    CASE
                        WHEN l.acao = 'CANCELADO_SEM_MATERIAL' THEN 'SEM_MATERIAL'
                        ELSE 'CANCELADO'
                    END
                FROM chapa_movimentacao_log l
                WHERE l.arquivo_id = a.id
                  AND l.acao IN ('CANCELADO', 'CANCELADO_SEM_MATERIAL')
                ORDER BY l.id DESC
                LIMIT 1
            ) AS fila_observacao_tipo,
            (
                SELECT l.detalhe
                FROM chapa_movimentacao_log l
                WHERE l.arquivo_id = a.id
                  AND l.acao IN ('CANCELADO', 'CANCELADO_SEM_MATERIAL')
                ORDER BY l.id DESC
                LIMIT 1
            ) AS fila_observacao,
            (
                SELECT l.maquina_origem
                FROM chapa_movimentacao_log l
                WHERE l.arquivo_id = a.id
                  AND l.acao IN ('CANCELADO', 'CANCELADO_SEM_MATERIAL')
                ORDER BY l.id DESC
                LIMIT 1
            ) AS fila_observacao_maquina,
            (
                SELECT l.operador_nome
                FROM chapa_movimentacao_log l
                WHERE l.arquivo_id = a.id
                  AND l.acao IN ('CANCELADO', 'CANCELADO_SEM_MATERIAL')
                ORDER BY l.id DESC
                LIMIT 1
            ) AS fila_observacao_operador,
            (
                SELECT l.criado_em
                FROM chapa_movimentacao_log l
                WHERE l.arquivo_id = a.id
                  AND l.acao IN ('CANCELADO', 'CANCELADO_SEM_MATERIAL')
                ORDER BY l.id DESC
                LIMIT 1
            ) AS fila_observacao_em
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
        ORDER BY
          CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
          a.criado_em ASC,
          a.id ASC
        """
    ).fetchall()

    compatibility = classifications_by_plan(conn, [row["id"] for row in rows])
    result = []
    for row in rows:
        item = dict(row)
        item["compatible_cncs"] = compatibility.get(row["id"], [])
        item["compatible_cnc_ids"] = [cnc["id"] for cnc in item["compatible_cncs"]]
        result.append(item)
    conn.close()
    return result


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


def _buscar_arquivo_fila_para_vcarve(cur, item_id: int, maquina_id: str | None = None):
    params = [item_id]
    maquina_filter = ""
    if maquina_id:
        maquina_filter = " AND fi.maquina_id = ?"
        params.append(maquina_id)

    return cur.execute(
        f"""
        SELECT a.id, a.nome, a.path, a.status,
               fi.id AS fila_item_id, fi.maquina_id
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.id = ?{maquina_filter}
        """,
        tuple(params),
    ).fetchone()


@app.post("/api/facilitador/abrir-vcarve")
def facilitador_abrir_vcarve(req: AbrirVCarveRequest, request: Request):
    if not req.arquivo_id and not req.item_id:
        raise HTTPException(status_code=400, detail="Informe o item da fila ou o arquivo para abrir no VCarve.")

    conn = get_conn()
    _ensure_arquivos_cols(conn)
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    try:
        if req.item_id:
            row = _buscar_arquivo_fila_para_vcarve(cur, req.item_id, req.maquina_id)
        else:
            row = cur.execute(
                """
                SELECT id, nome, path, status,
                       NULL AS fila_item_id, NULL AS maquina_id
                FROM arquivos_dxf
                WHERE id = ?
                """,
                (req.arquivo_id,),
            ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Arquivo ou item da fila não encontrado.")

        status = (row["status"] or "").upper().strip()
        if status == "EXCLUIDO":
            raise HTTPException(status_code=404, detail="Arquivo excluído.")

        try:
            caminho = _resolve_arquivo_cnc_path(row)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        usuario_header = request.headers.get("x-user-id") or request.headers.get("x-usuario-id")
        try:
            usuario_id = int(usuario_header) if usuario_header else None
        except Exception:
            usuario_id = None

        log_action(
            usuario_id=usuario_id,
            acao="ABRIR_VCARVE",
            maquina_id=row["maquina_id"],
            arquivo_id=row["id"],
            extra=json.dumps(
                {
                    "fila_item_id": row["fila_item_id"],
                    "arquivo_nome": row["nome"],
                    "path": str(caminho),
                },
                ensure_ascii=False,
            ),
        )

        download_url = None
        if row["fila_item_id"] and row["maquina_id"]:
            download_url = str(
                request.url_for(
                    "facilitador_vcarve_download",
                    maquina_id=row["maquina_id"],
                    fila_item_id=row["fila_item_id"],
                )
            )

        return {
            "ok": True,
            "modo": "AGENTE_LOCAL",
            "mensagem": "Arquivo liberado para abertura pelo agente local do VCarve.",
            "agent_url": "http://127.0.0.1:8765/abrir-vcarve",
            "download_url": download_url,
            "arquivo_nome": row["nome"],
            "arquivo_id": row["id"],
            "fila_item_id": row["fila_item_id"],
            "maquina_id": row["maquina_id"],
        }
    finally:
        conn.close()


@app.get("/api/facilitador/vcarve-download/{maquina_id}/{fila_item_id}", name="facilitador_vcarve_download")
def facilitador_vcarve_download(maquina_id: str, fila_item_id: int):
    conn = get_conn()
    _ensure_arquivos_cols(conn)
    _ensure_fila_itens_cols(conn)
    cur = conn.cursor()

    row = _buscar_arquivo_fila_para_vcarve(cur, fila_item_id, maquina_id)
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Arquivo ou item da fila não encontrado.")

    status = (row["status"] or "").upper().strip()
    if status == "EXCLUIDO":
        raise HTTPException(status_code=404, detail="Arquivo excluído.")

    try:
        caminho = _resolve_arquivo_cnc_path(row)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return FileResponse(
        path=str(caminho),
        filename=row["nome"],
        media_type="application/octet-stream",
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
    _ensure_arquivos_cols(conn)
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
               a.nome as arquivo_nome, a.priority
        FROM fila_itens fi
        JOIN arquivos_dxf a ON a.id = fi.arquivo_id
        WHERE fi.maquina_id = ?
          AND fi.status IN ({",".join(["?"] * len(status_list))})
        ORDER BY
          CASE
            WHEN fi.status = 'EM_EXECUCAO' THEN 0
            WHEN fi.status = 'BAIXADO' THEN 1
            ELSE 2
          END,
          fi.posicao ASC,
          fi.id ASC
        """,
        (maquina_id, *status_list),
    ).fetchall()

    compatibility = classifications_by_plan(conn, [row["arquivo_id"] for row in itens])
    result = []
    for row in itens:
        item = dict(row)
        item["compatible_cncs"] = compatibility.get(row["arquivo_id"], [])
        item["compatible_cnc_ids"] = [cnc["id"] for cnc in item["compatible_cncs"]]
        result.append(item)
    conn.close()
    return result


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

    if not plan_is_compatible_with(conn, req.arquivo_id, maquina_id):
        compatible = classifications_by_plan(conn, [req.arquivo_id]).get(req.arquivo_id, [])
        labels = " · ".join(item["id"] for item in compatible)
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"Este plano não é compatível com {maquina_id}. CNCs permitidas: {labels}.",
        )

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
def reorder_fila(maquina_id: str, req: ReorderFilaRequest, request: Request):
    mid = (maquina_id or "").upper().strip()
    ids = req.ids()
    if not ids:
        raise HTTPException(status_code=400, detail="Lista de itens vazia (ordem/ordered_item_ids).")

    ip_origem = obter_ip_cliente(request)
    conn = get_conn()
    _ensure_fila_itens_cols(conn)
    _ensure_cnc_queue_audit_table(conn)
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

    _reindex_fila(conn, mid)

    after_rows = cur.execute(
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
    after_by_id = {int(r["id"]): dict(r) for r in after_rows}

    for item_id, after in after_by_id.items():
        before = before_by_id.get(item_id) or {}
        old_pos = before.get("posicao")
        new_pos = after.get("posicao")
        if old_pos != new_pos:
            _log_chapa_movimentacao(
                conn,
                "REORDENADO_NA_FILA",
                fila_item_id=item_id,
                arquivo_id=after.get("arquivo_id"),
                arquivo_nome=after.get("arquivo_nome"),
                maquina_origem=mid,
                maquina_destino=mid,
                posicao_origem=old_pos,
                posicao_destino=new_pos,
                status_origem=before.get("status"),
                status_destino=after.get("status"),
                detalhe="Ordem da fila alterada.",
            )
            try:
                _log_cnc_queue_audit(
                    conn,
                    cnc_id=mid,
                    arquivo_id=after.get("arquivo_id"),
                    arquivo_nome=after.get("arquivo_nome"),
                    posicao_anterior=old_pos,
                    posicao_nova=new_pos,
                    ip_origem=ip_origem,
                )
            except Exception as exc:
                conn.rollback()
                conn.close()
                raise HTTPException(status_code=500, detail=f"Falha ao registrar auditoria da reordenacao: {exc}")
            logger.info(
                "Fila CNC reorganizada",
                extra={
                    "cnc_id": mid,
                    "arquivo_id": after.get("arquivo_id"),
                    "posicao_anterior": old_pos,
                    "posicao_nova": new_pos,
                    "ip_origem": ip_origem,
                },
            )

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
    if not plan_is_compatible_with(conn, arquivo_id, dest):
        compatible = classifications_by_plan(conn, [arquivo_id]).get(arquivo_id, [])
        labels = " · ".join(entry["id"] for entry in compatible)
        conn.close()
        raise HTTPException(status_code=409, detail=f"Este plano não é compatível com {dest}. CNCs permitidas: {labels}.")

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
    _touch_maquina_comunicacao(conn, maquina_id)

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
        conn.commit()
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
        conn.rollback()
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
        conn.commit()
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
    _touch_maquina_comunicacao(conn, maquina_id)

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
    _touch_maquina_comunicacao(conn, maquina_id)

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

    conn.commit()
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
    _touch_maquina_comunicacao(conn, maquina_id)

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
    _touch_maquina_comunicacao(conn, maquina_id)

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
def _listar_material_solicitacoes_core(
    maquina_id: str | None = None,
    status: str = "pendentes",
    limit: int = 100,
    data_inicial: str | None = None,
    data_final: str | None = None,
    material: str | None = None,
    operador: str | None = None,
    arquivo: str | None = None,
):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    cur = conn.cursor()

    lim = max(1, min(int(limit or 100), 5000))
    st = (status or "pendentes").upper().strip()
    mid = (maquina_id or "").upper().strip()
    where = []
    params: list = []
    date_column = "criado_em"

    if mid:
        where.append("maquina_id = ?")
        params.append(mid)

    if st in ("ABERTA", "PENDENTE", "PENDENTES", "AGUARDANDO", "AGUARDANDO_ALMOXARIFADO"):
        where.append("status IN ('ABERTA', 'AGUARDANDO_ALMOXARIFADO', 'EM_SEPARACAO')")
    elif st in ("ENTREGUE", "ENTREGUES"):
        where.append("status = 'ENTREGUE'")
        date_column = "COALESCE(entregue_em, atendido_em, atualizado_em, criado_em)"
    elif st in ("SEM_MATERIAL", "CANCELADA_SEM_MATERIAL"):
        where.append("status = 'CANCELADA_SEM_MATERIAL'")
        date_column = "COALESCE(cancelado_em, atualizado_em, criado_em)"
    elif st in ("CANCELADA", "CANCELADAS"):
        where.append("status IN ('CANCELADA', 'CANCELADA_SEM_MATERIAL')")
        date_column = "COALESCE(cancelado_em, atualizado_em, criado_em)"
    elif st not in ("TODAS", "TODOS", "ALL", "*"):
        where.append("status = ?")
        params.append(st)

    if data_inicial:
        where.append(f"date({date_column}) >= date(?)")
        params.append(data_inicial)
    if data_final:
        where.append(f"date({date_column}) <= date(?)")
        params.append(data_final)
    if material:
        where.append("LOWER(COALESCE(material, '')) LIKE ?")
        params.append(f"%{material.lower()}%")
    if operador:
        where.append("LOWER(COALESCE(operador_nome, '')) LIKE ?")
        params.append(f"%{operador.lower()}%")
    if arquivo:
        where.append("LOWER(COALESCE(arquivo_nome, '')) LIKE ?")
        params.append(f"%{arquivo.lower()}%")

    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    rows = cur.execute(
        f"""
        SELECT *
        FROM material_solicitacoes
        {sql_where}
        ORDER BY
          CASE WHEN status IN ('ABERTA', 'AGUARDANDO_ALMOXARIFADO', 'EM_SEPARACAO') THEN 0 ELSE 1 END,
          {date_column} DESC,
          id ASC
        LIMIT ?
        """,
        (*params, lim),
    ).fetchall()

    out = []
    for row in rows:
        item = _material_row_to_dict(row)
        unread_alm = cur.execute(
            """
            SELECT COUNT(*)
            FROM material_chat_mensagens
            WHERE solicitacao_id = ? AND lida_almoxarifado = 0
            """,
            (row["id"],),
        ).fetchone()[0]
        unread_op = cur.execute(
            """
            SELECT COUNT(*)
            FROM material_chat_mensagens
            WHERE solicitacao_id = ? AND lida_operador = 0
            """,
            (row["id"],),
        ).fetchone()[0]
        item["nao_lidas_almoxarifado"] = unread_alm
        item["nao_lidas_operador"] = unread_op
        out.append(item)

    conn.close()
    return out


@app.get("/api/material/solicitacoes")
def api_listar_material_solicitacoes(
    maquina_id: str | None = None,
    status: str = "pendentes",
    limit: int = 100,
    data_inicial: str | None = None,
    data_final: str | None = None,
    material: str | None = None,
    operador: str | None = None,
    arquivo: str | None = None,
):
    return _listar_material_solicitacoes_core(
        maquina_id=maquina_id,
        status=status,
        limit=limit,
        data_inicial=data_inicial,
        data_final=data_final,
        material=material,
        operador=operador,
        arquivo=arquivo,
    )


@app.get("/api/material/solicitacoes/pendentes")
def api_listar_material_solicitacoes_pendentes(limit: int = 100):
    return _listar_material_solicitacoes_core(status="pendentes", limit=limit)


@app.get("/api/material/chat-geral")
def api_material_chat_geral(limit: int = 300):
    return _listar_material_solicitacoes_core(status="TODAS", limit=limit)


@app.get("/api/material/solicitacoes/cards")
def api_material_solicitacoes_cards(limit: int = 500):
    return _listar_material_solicitacoes_core(status="TODAS", limit=limit)


@app.get("/api/material/solicitacoes/tv")
def api_material_solicitacoes_tv(limit: int = 500):
    return _listar_material_solicitacoes_core(status="TODAS", limit=limit)


@app.get("/api/material/solicitacoes/minha-cnc")
def api_material_solicitacoes_minha_cnc(maquina_id: str, limit: int = 100):
    return _listar_material_solicitacoes_core(maquina_id=maquina_id, status="TODAS", limit=limit)


@app.get("/almoxarifado/solicitacoes")
def listar_material_solicitacoes(
    maquina_id: str | None = None,
    status: str = "ABERTA",
    limit: int = 100,
):
    return _listar_material_solicitacoes_core(maquina_id=maquina_id, status=status, limit=limit)


@app.post("/api/material/solicitacoes")
def api_criar_material_solicitacao(req: MaterialSolicitacaoIn):
    conn = get_conn()
    item_id = _criar_material_solicitacao_core(conn, req)
    conn.commit()
    conn.close()
    return {"ok": True, "id": item_id}


@app.post("/almoxarifado/solicitacoes")
def criar_material_solicitacao(req: MaterialSolicitacaoIn):
    return api_criar_material_solicitacao(req)


@app.get("/api/material/solicitacoes/{solicitacao_id}")
def api_get_material_solicitacao(solicitacao_id: int):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    row = conn.execute("SELECT * FROM material_solicitacoes WHERE id = ?", (solicitacao_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada.")
    return _material_row_to_dict(row)


@app.get("/api/material/solicitacoes/{solicitacao_id}/mensagens")
def api_listar_material_mensagens(solicitacao_id: int, limit: int = 200):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    lim = max(1, min(int(limit or 200), 500))
    rows = conn.execute(
        """
        SELECT *
        FROM material_chat_mensagens
        WHERE solicitacao_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (solicitacao_id, lim),
    ).fetchall()
    conn.close()
    return [_material_msg_to_dict(r) for r in reversed(rows)]


@app.post("/api/material/solicitacoes/{solicitacao_id}/mensagens")
def api_enviar_material_mensagem(solicitacao_id: int, msg: MaterialChatMensagemIn):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    row = conn.execute("SELECT id, status FROM material_solicitacoes WHERE id = ?", (solicitacao_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada.")
    if _material_status_norm(row["status"]) not in MATERIAL_PENDENTES:
        conn.close()
        raise HTTPException(status_code=409, detail="Solicitacao ja finalizada.")
    msg_id = _material_add_message(
        conn,
        solicitacao_id,
        msg.usuario_id,
        msg.usuario_nome,
        msg.perfil,
        msg.mensagem,
        "USUARIO",
    )
    conn.commit()
    row_msg = conn.execute("SELECT * FROM material_chat_mensagens WHERE id = ?", (msg_id,)).fetchone()
    conn.close()
    return _material_msg_to_dict(row_msg)


@app.patch("/api/material/solicitacoes/{solicitacao_id}/em-separacao")
def api_em_separacao_material_solicitacao(solicitacao_id: int, msg: MaterialChatMensagemIn | None = None):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    row = conn.execute("SELECT id, status FROM material_solicitacoes WHERE id = ?", (solicitacao_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada.")

    status_atual = _material_status_norm(row["status"])
    if status_atual not in MATERIAL_PENDENTES:
        conn.close()
        raise HTTPException(status_code=409, detail="Solicitacao ja finalizada.")

    usuario_id = msg.usuario_id if msg else None
    usuario_nome = (msg.usuario_nome if msg else None) or "Almoxarifado"
    conn.execute(
        """
        UPDATE material_solicitacoes
        SET status = 'EM_SEPARACAO',
            em_separacao_por = ?,
            em_separacao_por_nome = ?,
            em_separacao_em = COALESCE(em_separacao_em, datetime('now','localtime')),
            atualizado_em = datetime('now','localtime'),
            visualizado_operador = 0
        WHERE id = ?
        """,
        (usuario_id, usuario_nome, solicitacao_id),
    )
    _material_add_message(
        conn,
        solicitacao_id,
        usuario_id,
        usuario_nome,
        "ALMOXARIFADO",
        "Almoxarifado iniciou a separacao do material.",
        "STATUS",
    )
    conn.commit()
    conn.close()
    return {"ok": True, "status": "EM_SEPARACAO"}


@app.patch("/api/material/solicitacoes/{solicitacao_id}/entregar")
def api_entregar_material_solicitacao(solicitacao_id: int, msg: MaterialChatMensagemIn | None = None):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    row = conn.execute("SELECT id, status FROM material_solicitacoes WHERE id = ?", (solicitacao_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada.")
    if _material_status_norm(row["status"]) not in MATERIAL_PENDENTES:
        conn.close()
        raise HTTPException(status_code=409, detail="Solicitacao ja finalizada.")

    usuario_id = msg.usuario_id if msg else None
    usuario_nome = (msg.usuario_nome if msg else None) or "Almoxarifado"
    conn.execute(
        """
        UPDATE material_solicitacoes
        SET status = 'ENTREGUE',
            atendido_em = COALESCE(atendido_em, datetime('now','localtime')),
            entregue_por = ?,
            entregue_por_nome = ?,
            entregue_em = datetime('now','localtime'),
            atualizado_em = datetime('now','localtime'),
            visualizado_operador = 0
        WHERE id = ?
        """,
        (usuario_id, usuario_nome, solicitacao_id),
    )
    _material_add_message(conn, solicitacao_id, usuario_id, usuario_nome, "ALMOXARIFADO", "Material entregue pelo Almoxarifado.", "STATUS")
    conn.commit()
    conn.close()
    return {"ok": True, "status": "ENTREGUE"}


@app.patch("/api/material/solicitacoes/{solicitacao_id}/sem-material")
def api_sem_material_solicitacao(solicitacao_id: int, msg: MaterialChatMensagemIn | None = None):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    row = conn.execute("SELECT * FROM material_solicitacoes WHERE id = ?", (solicitacao_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Solicitacao nao encontrada.")

    usuario_id = msg.usuario_id if msg else None
    usuario_nome = (msg.usuario_nome if msg else None) or "Almoxarifado"
    conn.execute(
        """
        UPDATE material_solicitacoes
        SET status = 'CANCELADA_SEM_MATERIAL',
            cancelado_por = ?,
            cancelado_por_nome = ?,
            cancelado_em = datetime('now','localtime'),
            motivo_cancelamento = 'SEM MATERIAL',
            atualizado_em = datetime('now','localtime'),
            visualizado_operador = 0
        WHERE id = ?
        """,
        (usuario_id, usuario_nome, solicitacao_id),
    )

    fila_item_id = row["item_id"]
    if fila_item_id:
        _ensure_fila_itens_cols(conn)
        fila_row = _fila_item_log_snapshot(conn, int(fila_item_id))
        if fila_row and (fila_row["status"] or "").upper() not in _fila_finalizada_status_list():
            conn.execute(
                """
                UPDATE fila_itens
                SET status = 'CANCELADO',
                    finalizado_em = COALESCE(finalizado_em, datetime('now','localtime'))
                WHERE id = ?
                """,
                (int(fila_item_id),),
            )
            _log_chapa_movimentacao(
                conn,
                "CANCELADO_SEM_MATERIAL",
                fila_item_id=int(fila_item_id),
                arquivo_id=fila_row["arquivo_id"],
                arquivo_nome=fila_row["arquivo_nome"],
                maquina_origem=fila_row["maquina_id"],
                maquina_destino=fila_row["maquina_id"],
                posicao_origem=fila_row["posicao"],
                posicao_destino=fila_row["posicao"],
                status_origem=fila_row["status"],
                status_destino="CANCELADO",
                operador_nome=usuario_nome,
                detalhe="Almoxarifado marcou como SEM MATERIAL; arquivo voltou para a fila geral para reordenacao.",
            )
            _reindex_fila(conn, fila_row["maquina_id"])

    _material_add_message(
        conn,
        solicitacao_id,
        usuario_id,
        usuario_nome,
        "ALMOXARIFADO",
        "Almoxarifado marcou esta solicitacao como SEM MATERIAL. Solicitacao cancelada automaticamente.",
        "STATUS",
    )
    conn.commit()
    conn.close()
    return {"ok": True, "status": "CANCELADA_SEM_MATERIAL"}


@app.patch("/api/material/solicitacoes/{solicitacao_id}/visualizar-almoxarifado")
def api_visualizar_material_almoxarifado(solicitacao_id: int):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    conn.execute("UPDATE material_chat_mensagens SET lida_almoxarifado = 1 WHERE solicitacao_id = ?", (solicitacao_id,))
    conn.execute("UPDATE material_solicitacoes SET visualizado_almoxarifado = 1 WHERE id = ?", (solicitacao_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.patch("/api/material/solicitacoes/{solicitacao_id}/visualizar-operador")
def api_visualizar_material_operador(solicitacao_id: int):
    conn = get_conn()
    _ensure_material_solicitacoes_table(conn)
    conn.execute("UPDATE material_chat_mensagens SET lida_operador = 1 WHERE solicitacao_id = ?", (solicitacao_id,))
    conn.execute("UPDATE material_solicitacoes SET visualizado_operador = 1 WHERE id = ?", (solicitacao_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/material/notificacoes/almoxarifado")
def api_notificacoes_almoxarifado():
    rows = _listar_material_solicitacoes_core(status="TODAS", limit=500)
    pendentes = [r for r in rows if r["status"] in MATERIAL_PENDENTES or r["status"] == "AGUARDANDO_ALMOXARIFADO"]
    unread = sum(int(r.get("nao_lidas_almoxarifado") or 0) for r in rows)
    return {"pendentes": len(pendentes), "nao_lidas": unread, "total": len(rows)}


@app.get("/api/material/notificacoes/operador")
def api_notificacoes_operador(maquina_id: str | None = None):
    rows = _listar_material_solicitacoes_core(maquina_id=maquina_id, status="TODAS", limit=100)
    unread = sum(int(r.get("nao_lidas_operador") or 0) for r in rows)
    avisos = [r for r in rows if int(r.get("nao_lidas_operador") or 0) > 0]
    return {"nao_lidas": unread, "avisos": avisos[:20]}


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
        "api",
        "agente",
        "dashboard/indicadores",
        "dashboard/manutencao",
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
