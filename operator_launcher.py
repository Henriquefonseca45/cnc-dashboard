import argparse
import json
import re
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


DEFAULT_BASE_URL = "http://192.168.17.152:18000"
CONFIG_NAME = "operator_config.json"
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_config() -> dict:
    config_path = app_dir() / CONFIG_NAME
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_cnc(value: str | None) -> str | None:
    text = str(value or "").strip().upper()
    match = re.search(r"CNC\s*0?([1-7])\b", text)
    if match:
        return f"CNC{int(match.group(1)):02d}"
    match = re.search(r"\b0?([1-7])\b", text)
    if match:
        return f"CNC{int(match.group(1)):02d}"
    return None


def cnc_from_exe_name() -> str | None:
    stem = Path(sys.executable if getattr(sys, "frozen", False) else __file__).stem
    return normalize_cnc(stem)


def check_server(base_url: str) -> bool:
    try:
        with urlopen(base_url.rstrip("/") + "/", timeout=2):
            return True
    except Exception:
        return False


class ProxyState:
    def __init__(self, base_url: str, idle_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.idle_seconds = idle_seconds
        self.last_request = time.monotonic()


def make_proxy_handler(state: ProxyState):
    class LocalProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args) -> None:
            return

        def do_GET(self) -> None:
            self.forward()

        def do_HEAD(self) -> None:
            self.forward(head_only=True)

        def do_POST(self) -> None:
            self.forward()

        def do_PUT(self) -> None:
            self.forward()

        def do_PATCH(self) -> None:
            self.forward()

        def do_DELETE(self) -> None:
            self.forward()

        def do_OPTIONS(self) -> None:
            self.forward()

        def forward(self, head_only: bool = False) -> None:
            state.last_request = time.monotonic()
            target_url = state.base_url + self.path
            parsed = urlsplit(target_url)
            if parsed.scheme not in {"http", "https"}:
                self.send_error(400, "URL invalida")
                return

            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length) if length else None
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
            }

            req = Request(target_url, data=body, headers=headers, method=self.command)
            try:
                with urlopen(req, timeout=45) as resp:
                    response_body = b"" if head_only else resp.read()
                    self.send_response(resp.status)
                    self.copy_response_headers(resp.headers, len(response_body))
                    self.end_headers()
                    if not head_only and response_body:
                        self.wfile.write(response_body)
            except HTTPError as exc:
                response_body = b"" if head_only else exc.read()
                self.send_response(exc.code)
                self.copy_response_headers(exc.headers, len(response_body))
                self.end_headers()
                if not head_only and response_body:
                    self.wfile.write(response_body)
            except Exception as exc:
                message = f"Erro ao acessar servidor remoto: {exc}".encode("utf-8", errors="replace")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(message)))
                self.end_headers()
                if not head_only:
                    self.wfile.write(message)

        def copy_response_headers(self, headers, body_length: int) -> None:
            sent_length = False
            for key, value in headers.items():
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS:
                    continue
                if lower == "content-length":
                    sent_length = True
                    self.send_header(key, str(body_length))
                    continue
                self.send_header(key, value)
            if not sent_length:
                self.send_header("Content-Length", str(body_length))

    return LocalProxyHandler


def serve_until_idle(server: ThreadingHTTPServer, state: ProxyState, stop_event: Event) -> None:
    while not stop_event.wait(15):
        if state.idle_seconds > 0 and time.monotonic() - state.last_request > state.idle_seconds:
            server.shutdown()
            break


def start_local_proxy(host: str, port: int, base_url: str, idle_seconds: int):
    state = ProxyState(base_url, idle_seconds)
    server = ThreadingHTTPServer((host, port), make_proxy_handler(state))
    stop_event = Event()
    monitor = Thread(target=serve_until_idle, args=(server, state, stop_event), daemon=True)
    monitor.start()
    return server, stop_event


def alert(title: str, message: str) -> None:
    try:
        import tkinter.messagebox as messagebox

        messagebox.showwarning(title, message)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Abre o painel do operador CNC.")
    parser.add_argument("--cnc", help="CNC para abrir, exemplo: CNC01")
    parser.add_argument("--base-url", help="URL base do sistema, exemplo: http://192.168.17.152:18000")
    parser.add_argument("--direct", action="store_true", help="Abre direto no servidor, sem ponte local.")
    args = parser.parse_args()

    config = load_config()
    cnc = normalize_cnc(args.cnc) or cnc_from_exe_name() or normalize_cnc(config.get("cnc")) or "CNC01"
    base_url = str(args.base_url or config.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
    operator_path = str(config.get("operator_path") or "/operador/{cnc}")
    local_host = str(config.get("local_host") or "127.0.0.1").strip()
    local_port = int(config.get("local_port") or 8000)
    idle_seconds = int(config.get("idle_exit_minutes") or 720) * 60
    direct_mode = bool(args.direct or config.get("direct_mode"))

    if not check_server(base_url):
        alert(
            "Painel do Operador",
            f"Nao consegui confirmar o servidor em:\n{base_url}\n\nVou tentar abrir mesmo assim.",
        )

    server = None
    stop_event = None
    if direct_mode:
        url = base_url + operator_path.format(cnc=cnc)
    else:
        url = f"http://{local_host}:{local_port}" + operator_path.format(cnc=cnc)
        try:
            server, stop_event = start_local_proxy(local_host, local_port, base_url, idle_seconds)
        except OSError:
            server = None
            stop_event = None

    opened = webbrowser.open(url, new=2)
    if not opened:
        alert("Painel do Operador", f"Nao foi possivel abrir o navegador automaticamente:\n{url}")
        return 1

    if server:
        try:
            server.serve_forever()
        finally:
            if stop_event:
                stop_event.set()
            server.server_close()
    else:
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
