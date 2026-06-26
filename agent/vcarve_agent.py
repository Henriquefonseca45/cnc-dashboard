from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import glob
import ctypes
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ALLOWED_EXTENSIONS = {".dxf", ".dwg", ".crv", ".crv3d"}
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "download_dir": str(Path(tempfile.gettempdir()) / "cnc_vcarve_agent"),
    "vcarve_exe": r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\VCarve Pro 7.5",
    "allowed_download_hosts": ["192.168.17.39", "localhost", "127.0.0.1"],
    "timeout_seconds": 60,
    "open_method": "dialog",
    "vcarve_start_wait_seconds": 6,
    "dialog_wait_seconds": 1,
}
LAST_RESULT = {
    "ultimo_arquivo": "",
    "ultimo_download_url": "",
    "ultimo_erro": "",
    "ultimo_dxf": {},
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_config() -> dict:
    config_path = app_dir() / "vcarve_agent_config.json"
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        try:
            config.update(json.loads(config_path.read_text(encoding="utf-8")))
        except Exception as exc:
            print(f"[VCARVE] Aviso: nao consegui ler {config_path}: {exc}")

    config["host"] = str(config.get("host") or DEFAULT_CONFIG["host"]).strip()
    config["port"] = int(config.get("port") or DEFAULT_CONFIG["port"])
    config["download_dir"] = str(config.get("download_dir") or DEFAULT_CONFIG["download_dir"]).strip()
    config["vcarve_exe"] = str(config.get("vcarve_exe") or "").strip()
    config["timeout_seconds"] = int(config.get("timeout_seconds") or DEFAULT_CONFIG["timeout_seconds"])
    config["open_method"] = str(config.get("open_method") or DEFAULT_CONFIG["open_method"]).strip().lower()
    config["vcarve_start_wait_seconds"] = float(
        config.get("vcarve_start_wait_seconds") or DEFAULT_CONFIG["vcarve_start_wait_seconds"]
    )
    config["dialog_wait_seconds"] = float(config.get("dialog_wait_seconds") or DEFAULT_CONFIG["dialog_wait_seconds"])
    config["allowed_download_hosts"] = [
        str(host).lower().strip()
        for host in (config.get("allowed_download_hosts") or [])
        if str(host).strip()
    ]
    return config


def _expand_launcher_candidate(candidate: str) -> list[str]:
    try:
        path = Path(candidate)
        if path.is_dir():
            found = []
            found.extend(str(p) for p in path.glob("*.lnk"))
            found.extend(str(p) for p in path.rglob("VCarvePro.exe"))
            found.extend(str(p) for p in path.rglob("VCarve.exe"))
            return found
    except Exception:
        pass
    return [candidate]


def find_vcarve_launcher(config: dict) -> str:
    candidates = []
    configured = str(config.get("vcarve_exe") or "").strip()
    env_path = os.getenv("VCARVE_EXE", "").strip()
    if configured:
        candidates.append(configured)
    if env_path:
        candidates.append(env_path)

    program_roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    patterns = []
    for root in program_roots:
        if not root:
            continue
        patterns.extend(
            [
                str(Path(root) / "VCarve*" / "**" / "VCarvePro.exe"),
                str(Path(root) / "VCarve*" / "**" / "VCarve.exe"),
                str(Path(root) / "Vectric" / "**" / "VCarvePro.exe"),
                str(Path(root) / "Vectric" / "**" / "VCarve.exe"),
            ]
        )

    for pattern in patterns:
        candidates.extend(glob.glob(pattern, recursive=True))

    expanded_candidates = []
    for candidate in candidates:
        expanded_candidates.extend(_expand_launcher_candidate(candidate))

    for candidate in expanded_candidates:
        try:
            path = Path(candidate)
            if path.exists() and path.is_file() and path.suffix.lower() in {".exe", ".lnk"}:
                return str(path)
        except Exception:
            continue
    return ""


def set_clipboard_text(text: str) -> None:
    if os.name != "nt":
        raise RuntimeError("Clipboard automatico disponivel somente no Windows.")

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    cf_unicode_text = 13
    gmem_moveable = 0x0002

    data = text.encode("utf-16le") + b"\x00\x00"
    handle = kernel32.GlobalAlloc(gmem_moveable, len(data))
    if not handle:
        raise RuntimeError("Nao consegui alocar memoria para o clipboard.")

    locked = kernel32.GlobalLock(handle)
    ctypes.memmove(locked, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        raise RuntimeError("Nao consegui abrir o clipboard do Windows.")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(cf_unicode_text, handle):
            raise RuntimeError("Nao consegui gravar o caminho no clipboard.")
        handle = None
    finally:
        user32.CloseClipboard()


def send_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    keyeventf_keyup = 0x0002
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, 0, keyeventf_keyup, 0)


def send_ctrl_key(vk: int) -> None:
    user32 = ctypes.windll.user32
    keyeventf_keyup = 0x0002
    vk_control = 0x11
    user32.keybd_event(vk_control, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, 0, keyeventf_keyup, 0)
    user32.keybd_event(vk_control, 0, keyeventf_keyup, 0)


def focus_vcarve_window() -> bool:
    if os.name != "nt":
        return False

    user32 = ctypes.windll.user32
    matches = []

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value or ""
        if "vcarve" in title.lower():
            matches.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    if not matches:
        return False

    hwnd = matches[0]
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return True


def safe_filename(name: str) -> str:
    name = Path(str(name or "")).name.strip()
    name = "".join(c if c.isalnum() or c in " ._-()[]" else "_" for c in name)
    name = name.strip().strip(".")
    return name or f"arquivo_vcarve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"


def validate_download_url(url: str, allowed_hosts: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL de download invalida.")

    hostname = (parsed.hostname or "").lower()
    if allowed_hosts and hostname not in allowed_hosts:
        raise ValueError(f"Host de download nao permitido: {hostname}")


def validate_downloaded_file(path: Path) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        raise ValueError("Arquivo baixado vazio.")

    head = path.read_bytes()[:4096].lstrip()
    lower_head = head[:512].lower()
    if lower_head.startswith(b"<!doctype") or lower_head.startswith(b"<html") or lower_head.startswith(b"{"):
        raise ValueError(
            "O servidor retornou uma pagina/JSON em vez do arquivo DXF. "
            f"Arquivo salvo para conferencia: {path}"
        )

    suffix = path.suffix.lower()
    if suffix == ".dxf":
        text_head = head.decode("latin-1", errors="ignore").upper()
        looks_like_dxf = "SECTION" in text_head or "HEADER" in text_head or "ENTITIES" in text_head
        if not looks_like_dxf:
            raise ValueError(
                "O arquivo baixado nao parece um DXF valido. "
                f"Arquivo salvo para conferencia: {path}"
            )


def inspect_dxf(path: Path) -> dict:
    info = {
        "arquivo": str(path),
        "tamanho_bytes": 0,
        "linhas": 0,
        "acadver": "",
        "aviso": "",
    }
    try:
        info["tamanho_bytes"] = path.stat().st_size
        acadver_next = False
        with path.open("r", encoding="latin-1", errors="ignore") as fh:
            for idx, line in enumerate(fh, start=1):
                text = line.strip()
                if acadver_next and text:
                    info["acadver"] = text
                    acadver_next = False
                elif text.upper() == "$ACADVER":
                    acadver_next = True
            info["linhas"] = idx if "idx" in locals() else 0

        newer_versions = {"AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}
        if info["acadver"] in newer_versions:
            info["aviso"] = (
                "DXF em versao nova. O VCarve Pro 7.5 pode travar. "
                "Salve/exporte o DXF como AutoCAD R12, R14 ou 2000 antes de abrir."
            )
    except Exception as exc:
        info["aviso"] = f"Nao consegui inspecionar o DXF: {exc}"
    return info


def download_file(url: str, filename: str, config: dict) -> Path:
    validate_download_url(url, config["allowed_download_hosts"])

    safe_name = safe_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("Tipo de arquivo nao permitido para abrir no VCarve.")

    download_dir = Path(config["download_dir"])
    download_dir.mkdir(parents=True, exist_ok=True)

    dest = download_dir / safe_name
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = download_dir / f"{dest.stem}_{stamp}{dest.suffix}"

    req = Request(url, headers={"User-Agent": "CNC-VCarve-Agent/1.0"})
    with urlopen(req, timeout=config["timeout_seconds"]) as response:
        with dest.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)

    validate_downloaded_file(dest)
    LAST_RESULT["ultimo_dxf"] = inspect_dxf(dest)
    return dest


def open_in_vcarve(path: Path, config: dict) -> None:
    if os.name != "nt":
        raise RuntimeError("Este agente precisa rodar no Windows onde o VCarve esta instalado.")

    launcher = find_vcarve_launcher(config)
    open_method = str(config.get("open_method") or "dialog").lower()

    if open_method == "direct":
        if launcher:
            print(f"[VCARVE] Abrindo direto com: {launcher}")
            print(f"[VCARVE] Arquivo: {path}")
            if Path(launcher).suffix.lower() == ".lnk":
                subprocess.Popen(["cmd.exe", "/c", "start", "", launcher, str(path)], shell=False)
            else:
                subprocess.Popen([launcher, str(path)], shell=False)
            return

        print("[VCARVE] VCarvePro.exe nao encontrado. Tentando abrir pelo programa padrao do Windows.")
        os.startfile(str(path))
        return

    if not launcher:
        raise RuntimeError("Nao encontrei o atalho ou executavel do VCarve para abrir a janela.")

    print(f"[VCARVE] Abrindo VCarve para usar dialogo: {launcher}")
    if Path(launcher).suffix.lower() == ".lnk":
        subprocess.Popen(["cmd.exe", "/c", "start", "", launcher], shell=False)
    else:
        subprocess.Popen([launcher], shell=False)

    time.sleep(float(config.get("vcarve_start_wait_seconds") or 6))
    if not focus_vcarve_window():
        raise RuntimeError("VCarve aberto, mas nao consegui localizar/focar a janela para enviar Ctrl+O.")

    print(f"[VCARVE] Enviando Ctrl+O e caminho do arquivo: {path}")
    set_clipboard_text(str(path))
    send_ctrl_key(0x4F)  # O
    time.sleep(float(config.get("dialog_wait_seconds") or 1))
    set_clipboard_text(str(path))
    send_ctrl_key(0x56)  # V
    time.sleep(0.2)
    send_key(0x0D)  # Enter
    return



class VCarveHandler(BaseHTTPRequestHandler):
    config: dict = {}

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send_json(200, {"ok": True})

    def do_GET(self):
        if self.path.rstrip("/") in {"", "/"}:
            self._send_json(200, {"ok": True, "mensagem": "Agente VCarve ativo."})
            return
        if self.path.rstrip("/") == "/status":
            vcarve_launcher = find_vcarve_launcher(self.config)
            download_dir = Path(self.config["download_dir"])
            self._send_json(
                200,
                {
                    "ok": True,
                    "mensagem": "Agente VCarve ativo.",
                    "vcarve_encontrado": bool(vcarve_launcher),
                    "vcarve_exe": vcarve_launcher,
                    "download_dir": str(download_dir),
                    "download_dir_existe": download_dir.exists(),
                    "allowed_download_hosts": self.config["allowed_download_hosts"],
                    "ultimo_arquivo": LAST_RESULT["ultimo_arquivo"],
                    "ultimo_download_url": LAST_RESULT["ultimo_download_url"],
                    "ultimo_erro": LAST_RESULT["ultimo_erro"],
                    "ultimo_dxf": LAST_RESULT["ultimo_dxf"],
                },
            )
            return
        self._send_json(404, {"ok": False, "detail": "Rota nao encontrada."})

    def do_POST(self):
        if self.path.rstrip("/") != "/abrir-vcarve":
            self._send_json(404, {"ok": False, "detail": "Rota nao encontrada."})
            return

        try:
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            download_url = str(payload.get("download_url") or "").strip()
            arquivo_nome = str(payload.get("arquivo_nome") or "").strip()

            if not download_url:
                raise ValueError("download_url nao informado.")
            if not arquivo_nome:
                arquivo_nome = "arquivo_vcarve.dxf"

            LAST_RESULT["ultimo_download_url"] = download_url
            LAST_RESULT["ultimo_erro"] = ""
            arquivo = download_file(download_url, arquivo_nome, self.config)
            LAST_RESULT["ultimo_arquivo"] = str(arquivo)
            print(f"[VCARVE] Arquivo baixado: {arquivo}")
            print(f"[VCARVE] Diagnostico DXF: {LAST_RESULT['ultimo_dxf']}")
            open_in_vcarve(arquivo, self.config)

            self._send_json(
                200,
                {
                    "ok": True,
                    "mensagem": "Arquivo enviado para abertura no VCarve.",
                    "arquivo": str(arquivo),
                },
            )
        except Exception as exc:
            LAST_RESULT["ultimo_erro"] = str(exc)
            self._send_json(400, {"ok": False, "detail": str(exc)})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[VCARVE] {self.address_string()} - {fmt % args}")


def main() -> None:
    config = load_config()
    VCarveHandler.config = config
    server = ThreadingHTTPServer((config["host"], config["port"]), VCarveHandler)
    print(f"[VCARVE] Agente local ativo em http://{config['host']}:{config['port']}")
    print(f"[VCARVE] Pasta de download: {config['download_dir']}")
    print("[VCARVE] Deixe esta janela aberta para usar o botao Visualizar no VCarve.")
    server.serve_forever()


if __name__ == "__main__":
    main()
