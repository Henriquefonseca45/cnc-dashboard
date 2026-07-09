from __future__ import annotations

from dataclasses import dataclass
import os
from datetime import datetime, timezone
import re
import unicodedata


STALE_AFTER_SECONDS = max(1, int(os.getenv("CNC_ASSISTANT_STALE_MINUTES", "5") or "5")) * 60
TEST_MACHINE_IDS = {"CNC_TESTE"}
INDETERMINADO = "indeterminado"


@dataclass(frozen=True)
class NormalizedCnc:
    id: str
    nome: str
    status: str
    status_bruto: str
    status_desde: str | None
    arquivo_atual: str | None
    operador: str | None
    motivo_parada: str | None
    ultima_comunicacao: str | None

    def as_dict(self, now: datetime | None = None) -> dict:
        duration = readable_duration_since(self.status_desde, now)
        stale = stale_status(self.ultima_comunicacao, now)
        return {
            "id": self.id,
            "nome": self.nome,
            "status": self.status,
            "status_label": status_label(self.status, self.status_bruto),
            "status_bruto": self.status_bruto,
            "status_desde": self.status_desde,
            "arquivo_atual": self.arquivo_atual,
            "operador": self.operador,
            "motivo_parada": self.motivo_parada,
            "ultima_comunicacao": self.ultima_comunicacao,
            "ultima_atualizacao": self.ultima_comunicacao,
            "tempo_no_status": duration,
            "dados_desatualizados": stale,
        }


def strip_accents(value: str | None) -> str:
    return (
        unicodedata.normalize("NFD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
        .strip()
    )


def normalize_status(raw_status: str | None) -> str:
    status = strip_accents(raw_status)
    if not status:
        return "nao_informado"
    if "SEM COMUNIC" in status or "OFFLINE" in status or "COMUNICACAO" in status:
        return "sem_comunicacao"
    if "DESLIG" in status:
        return "desligada"
    if "USIN" in status or "CORTE" in status or "EM_EXECUCAO" in status:
        return "usinando"
    if "SETUP" in status:
        return "setup"
    if "MANUT" in status:
        return "manutencao"
    if "PARADA PROGRAM" in status or "PROGRAMADA" in status:
        return "parada_programada"
    if "PAR" in status or "OCIOS" in status or "OPERADOR" in status or "EMPILH" in status:
        return "parada_nao_programada"
    return status.lower().replace(" ", "_")


def infer_stop_reason(raw_status: str | None, normalized_status: str) -> str | None:
    if normalized_status not in {"parada_nao_programada", "parada_programada", "manutencao"}:
        return None
    clean = str(raw_status or "").strip()
    return clean or None


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    return parsed


def readable_duration_since(value: str | None, now: datetime | None = None) -> str:
    start = parse_datetime(value)
    if not start:
        return "nao informado"
    if start.tzinfo is None:
        reference = now or datetime.now()
        if reference.tzinfo is not None:
            reference = reference.astimezone().replace(tzinfo=None)
    else:
        reference = now or datetime.now(start.tzinfo)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=start.tzinfo)
        else:
            reference = reference.astimezone(start.tzinfo)
    seconds = max(0, int((reference - start).total_seconds()))
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}min"
    hours = minutes // 60
    rem_minutes = minutes % 60
    if hours < 24:
        if rem_minutes:
            return f"{hours}h{rem_minutes:02d}min"
        return f"{hours}h"
    days = hours // 24
    rem_hours = hours % 24
    if rem_hours:
        return f"{days} dia" + ("" if days == 1 else "s") + f" e {rem_hours}h"
    return f"{days} dia" + ("" if days == 1 else "s")


def stale_status(value: str | None, now: datetime | None = None) -> bool | None:
    updated = parse_datetime(value)
    if not updated:
        return None
    if updated.tzinfo is None:
        reference = now or datetime.now()
        if reference.tzinfo is not None:
            reference = reference.astimezone().replace(tzinfo=None)
    else:
        reference = now or datetime.now(updated.tzinfo)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=updated.tzinfo)
        else:
            reference = reference.astimezone(updated.tzinfo)
    return (reference - updated).total_seconds() > STALE_AFTER_SECONDS


def normalize_machine(row: dict, arquivo_atual: str | None = None, ultima_comunicacao: str | None = None) -> NormalizedCnc:
    raw_status = row.get("status")
    normalized = normalize_status(raw_status)
    status_desde = row.get("status_desde")
    return NormalizedCnc(
        id=str(row.get("id") or "").upper().strip(),
        nome=str(row.get("nome") or row.get("id") or "").strip(),
        status=normalized,
        status_bruto=str(raw_status or "").strip() or "nao informado",
        status_desde=status_desde,
        arquivo_atual=arquivo_atual,
        operador=(str(row.get("operador_nome") or "").strip() or None),
        motivo_parada=infer_stop_reason(raw_status, normalized),
        ultima_comunicacao=ultima_comunicacao,
    )


def find_cnc_id(text: str | None) -> str | None:
    match = re.search(r"\bCNC\s*0?(\d{1,2})\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return f"CNC{int(match.group(1)):02d}"


def format_field(value: str | None) -> str:
    return value if value not in (None, "") else "nao informado"


def format_datetime_br(value: str | None, *, time_only: bool = False) -> str:
    parsed = parse_datetime(value)
    if not parsed:
        return INDETERMINADO if value in (None, "") else str(value)
    if time_only:
        return parsed.strftime("%H:%M:%S")
    return parsed.strftime("%d/%m/%Y às %H:%M:%S")


def status_label(status: str | None, fallback: str | None = None) -> str:
    labels = {
        "usinando": "Usinando",
        "manutencao": "Em manutenção",
        "setup": "Em setup",
        "parada_nao_programada": "Parada",
        "parada_programada": "Parada programada",
        "desligada": "Desligada",
        "sem_comunicacao": "Sem comunicação",
        "nao_informado": "Não informado",
    }
    return labels.get(str(status or ""), str(fallback or status or "nao informado").replace("_", " ").title())


def summary_label(status: str | None, fallback: str | None = None) -> str:
    labels = {
        "usinando": "usinando",
        "manutencao": "em manutenção",
        "setup": "em setup",
        "parada_nao_programada": "paradas",
        "parada_programada": "paradas programadas",
        "desligada": "desligadas",
        "sem_comunicacao": "sem comunicação",
        "nao_informado": "sem status informado",
    }
    return labels.get(str(status or ""), str(fallback or status or "outros").replace("_", " ").lower())


def is_stale_true(machine: dict) -> bool:
    return machine.get("dados_desatualizados") is True


def summarize_machine(machine: dict) -> str:
    lines = [
        f"{machine['id']} - {status_label(machine.get('status'), machine.get('status_bruto'))} há {machine.get('tempo_no_status') or 'não informado'}",
    ]
    if machine.get("arquivo_atual"):
        lines.append(f"Arquivo atual: {machine['arquivo_atual']}")
    lines.append(f"Última comunicação: {format_datetime_br(machine.get('ultima_comunicacao'))}")
    if machine.get("dados_desatualizados") is True:
        lines.append("Alerta: dados desatualizados.")
    elif machine.get("dados_desatualizados") is None:
        lines.append("Dados desatualizados: indeterminado.")
    return "\n".join(lines)


def _list_response(title: str, machines: list[dict]) -> str:
    if not machines:
        return f"{title}:\nNenhuma máquina encontrada nessa condição."
    return title + ":\n\n" + "\n\n".join(summarize_machine(m) for m in machines)


def build_response(intent: str, machines: list[dict], cnc_id: str | None = None) -> str:
    if intent == "cnc":
        machine = next((m for m in machines if m["id"] == cnc_id), None)
        if not machine:
            return f"{cnc_id or 'A máquina informada'} não foi encontrada."
        return summarize_machine(machine)

    if intent == "arquivo":
        machine = next((m for m in machines if m["id"] == cnc_id), None)
        if not machine:
            return f"{cnc_id or 'A máquina informada'} não foi encontrada."
        return (
            f"O arquivo atual da {machine['id']} é "
            f"{format_field(machine.get('arquivo_atual'))}. "
            f"Última comunicação: {format_datetime_br(machine.get('ultima_comunicacao'))}."
        )

    if intent == "usinando":
        selected = [m for m in machines if m["status"] == "usinando"]
        return _list_response("Máquinas usinando", selected)

    if intent == "paradas":
        selected = [m for m in machines if m["status"] in {"parada_nao_programada", "parada_programada", "desligada", "sem_comunicacao"}]
        return _list_response("Máquinas paradas", selected)

    if intent == "manutencao":
        selected = [m for m in machines if m["status"] == "manutencao"]
        return _list_response("Máquinas em manutenção", selected)

    if intent == "setup":
        selected = [m for m in machines if m["status"] == "setup"]
        return _list_response("Máquinas em setup", selected)

    if intent == "desatualizadas":
        selected = [m for m in machines if is_stale_true(m)]
        unknown = [m for m in machines if m.get("dados_desatualizados") is None]
        response = _list_response("Máquinas com dados desatualizados", selected)
        if unknown:
            response += "\n\nDados indeterminados:\n\n" + "\n\n".join(summarize_machine(m) for m in unknown)
        return response

    counts: dict[str, int] = {}
    label_by_status: dict[str, str] = {}
    for machine in machines:
        key = str(machine.get("status") or "nao_informado")
        counts[key] = counts.get(key, 0) + 1
        label_by_status[key] = summary_label(key, machine.get("status_bruto"))

    lines = ["Resumo das CNCs:"]
    ordered = ["usinando", "manutencao", "setup", "parada_nao_programada"]
    for key in ordered:
        lines.append(f"- {counts.get(key, 0)} {summary_label(key)}")
    extra_keys = [
        key
        for key in sorted(counts, key=lambda item: label_by_status.get(item, item))
        if key not in ordered
    ]
    for key in extra_keys:
        lines.append(f"- {counts[key]} {label_by_status[key]}")
    stale_count = len([m for m in machines if is_stale_true(m)])
    unknown_count = len([m for m in machines if m.get("dados_desatualizados") is None])
    if stale_count:
        lines.append(f"\nAlerta: {stale_count} máquina(s) com dados desatualizados.")
    if unknown_count:
        lines.append(f"\nDados desatualizados indeterminados em {unknown_count} máquina(s).")
    return "\n".join(lines)


def detect_intent(message: str | None) -> tuple[str, str | None]:
    text = strip_accents(message)
    cnc_id = find_cnc_id(message)
    if cnc_id and ("ARQUIVO" in text or "EXECUT" in text):
        return "arquivo", cnc_id
    if cnc_id:
        return "cnc", cnc_id
    if "USIN" in text or "EXECUT" in text:
        return "usinando", None
    if "MANUT" in text:
        return "manutencao", None
    if "SETUP" in text:
        return "setup", None
    if "DESATUAL" in text or "COMUNIC" in text or "ENVIA" in text:
        return "desatualizadas", None
    if "PARAD" in text:
        return "paradas", None
    return "geral", None
