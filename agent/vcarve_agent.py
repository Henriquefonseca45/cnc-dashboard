from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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
    "vcarve_exe": r"C:\Program Files\VCarve Pro 12.0\x64\VCarvePro.exe",
    "allowed_download_hosts": ["192.168.17.39", "localhost", "127.0.0.1"],
    "timeout_seconds": 60,
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

    return dest


def open_in_vcarve(path: Path, config: dict) -> None:
    if os.name != "nt":
        raise RuntimeError("Este agente precisa rodar no Windows onde o VCarve esta instalado.")

    vcarve_exe = config.get("vcarve_exe") or os.getenv("VCARVE_EXE", "")
    if vcarve_exe and Path(vcarve_exe).exists():
        subprocess.Popen([vcarve_exe, str(path)], shell=False)
        return

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

            arquivo = download_file(download_url, arquivo_nome, self.config)
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
