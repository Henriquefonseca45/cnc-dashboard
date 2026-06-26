from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import glob
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
}
LAST_RESULT = {
    "ultimo_arquivo": "",
    "ultimo_download_url": "",
    "ultimo_erro": "",
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
    return dest


def open_in_vcarve(path: Path, config: dict) -> None:
    if os.name != "nt":
        raise RuntimeError("Este agente precisa rodar no Windows onde o VCarve esta instalado.")

    launcher = find_vcarve_launcher(config)
    if launcher:
        print(f"[VCARVE] Abrindo com: {launcher}")
        print(f"[VCARVE] Arquivo: {path}")
        if Path(launcher).suffix.lower() == ".lnk":
            subprocess.Popen(["cmd.exe", "/c", "start", "", launcher, str(path)], shell=False)
        else:
            subprocess.Popen([launcher, str(path)], shell=False)
        return

    print("[VCARVE] VCarvePro.exe nao encontrado. Tentando abrir pelo programa padrao do Windows.")
    os.startfile(str(path))


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
