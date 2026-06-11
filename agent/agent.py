import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests


def load_config() -> dict:
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent

    cfg_path = base_dir / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json não encontrado em: {cfg_path}")

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    for k in ["api_base", "maquina_id", "download_dir"]:
        if k not in cfg or not str(cfg[k]).strip():
            raise ValueError(f"config.json inválido: faltando '{k}'")

    cfg["api_base"] = str(cfg["api_base"]).rstrip("/")
    cfg["maquina_id"] = str(cfg["maquina_id"]).strip()
    cfg["download_dir"] = str(cfg["download_dir"]).strip()

    cfg.setdefault("poll_seconds", 3)
    cfg.setdefault("timeout_seconds", 20)
    cfg.setdefault("simulate_run_seconds", 5)
    return cfg


def ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def http_get_json(url: str, timeout: int) -> dict:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def http_post_json(url: str, payload: dict, timeout: int) -> dict:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def download_file(url: str, dest_path: Path, timeout: int) -> None:
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with dest_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def safe_filename(name: str) -> str:
    name = name.strip()
    name = "".join(c if c.isalnum() or c in " ._-()[]" else "_" for c in name)
    name = name.strip().strip(".")
    if not name.lower().endswith(".dxf"):
        name += ".dxf"
    return name


def interpret_next_payload(data: dict):
    """
    Suporta 2 formatos:
    A) Seu formato atual: pendente, fila_item_id, arquivo_nome, download_url
    B) Formato alternativo: tem_proximo, arquivo_id, nome, download_url
    """
    # Formato A (atual)
    if "pendente" in data:
        tem = bool(data.get("pendente"))
        fila_item_id = data.get("fila_item_id")
        arquivo_id = data.get("arquivo_id")
        nome = data.get("arquivo_nome") or data.get("nome") or f"arquivo_{arquivo_id}.dxf"
        download_url = data.get("download_url")
        return tem, fila_item_id, arquivo_id, nome, download_url

    # Formato B (fallback)
    tem = bool(data.get("tem_proximo"))
    fila_item_id = data.get("fila_item_id")
    arquivo_id = data.get("arquivo_id")
    nome = data.get("nome") or f"arquivo_{arquivo_id}.dxf"
    download_url = data.get("download_url")
    return tem, fila_item_id, arquivo_id, nome, download_url


def main():
    cfg = load_config()
    api = cfg["api_base"]
    maquina_id = cfg["maquina_id"]
    download_dir = cfg["download_dir"]
    poll_s = int(cfg["poll_seconds"])
    timeout = int(cfg["timeout_seconds"])
    simulate_s = int(cfg["simulate_run_seconds"])

    ensure_dir(download_dir)

    print(f"[AGENTE] Iniciando")
    print(f"[AGENTE] API: {api}")
    print(f"[AGENTE] Máquina: {maquina_id}")
    print(f"[AGENTE] Pasta download: {download_dir}\n")

    next_url = f"{api}/agente/{maquina_id}/next"

    while True:
        try:
            data = http_get_json(next_url, timeout=timeout)
            tem, fila_item_id, arquivo_id, nome, download_url = interpret_next_payload(data)

            if not tem:
                time.sleep(poll_s)
                continue

            if not download_url:
                # fallback: se não vier URL, tenta padrão por arquivo_id
                download_url = f"/agente/{maquina_id}/download/{arquivo_id}"

            full_download_url = urljoin(api + "/", download_url.lstrip("/"))

            fname = safe_filename(nome)
            dest = Path(download_dir) / fname

            print(f"[AGENTE] Próximo: fila_item_id={fila_item_id} arquivo_id={arquivo_id}")
            print(f"[AGENTE] Baixando: {full_download_url}")
            download_file(full_download_url, dest, timeout=timeout)
            print(f"[AGENTE] Salvo em: {dest}")

            # Confirma baixado (se existir no seu backend)
            # Pelo seu swagger antigo, existe: POST /agente/{maquina_id}/baixado
            baixado_url = f"{api}/agente/{maquina_id}/baixado"
            payload = {"arquivo_id": arquivo_id}
            if fila_item_id is not None:
                payload["fila_item_id"] = fila_item_id

            try:
                http_post_json(baixado_url, payload, timeout=timeout)
                print("[AGENTE] Confirmado: BAIXADO")
            except Exception as e:
                print(f"[AGENTE] Aviso: não consegui confirmar BAIXADO ({e})")

            # Simula execução (troca depois pela integração real com a CNC)
            print(f"[AGENTE] Simulando execução por {simulate_s}s...")
            time.sleep(simulate_s)

            # Confirma concluído (se existir)
            concluido_url = f"{api}/agente/{maquina_id}/concluido"
            payload2 = {"arquivo_id": arquivo_id, "ok": True, "tempo_seg": simulate_s}
            if fila_item_id is not None:
                payload2["fila_item_id"] = fila_item_id

            try:
                http_post_json(concluido_url, payload2, timeout=timeout)
                print("[AGENTE] Confirmado: CONCLUÍDO\n")
            except Exception as e:
                print(f"[AGENTE] Aviso: não consegui confirmar CONCLUÍDO ({e})\n")

        except Exception as e:
            print(f"[AGENTE] ERRO: {e}")
            time.sleep(max(2, poll_s))


if __name__ == "__main__":
    main()