import time
import requests

API = "http://127.0.0.1:18000"
MAQUINA_ID = "CNC01"

print("Agente iniciado para", MAQUINA_ID)

while True:
    try:
        r = requests.get(f"{API}/agente/{MAQUINA_ID}/next")
        data = r.json()

        if not data.get("pendente"):
            print("Sem trabalho...")
            time.sleep(5)
            continue

        fila_id = data["fila_item_id"]
        print("Baixando:", data["arquivo_nome"])

        # Baixa o arquivo
        requests.get(f"{API}/agente/{MAQUINA_ID}/download/fila/{fila_id}")

        print("Simulando corte...")
        time.sleep(5)  # tempo de corte simulado

        # Marca como cortado
        requests.post(
            f"{API}/agente/{MAQUINA_ID}/fila/{fila_id}/cortado",
            json={"ok": True},
        )

        print("Corte finalizado!")

    except Exception as e:
        print("Erro:", e)

    time.sleep(3)
