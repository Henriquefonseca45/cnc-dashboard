from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata


STALE_AFTER_SECONDS = 5 * 60
TEST_MACHINE_IDS = {"CNC_TESTE"}


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
    ultima_atualizacao: str | None

    def as_dict(self, now: datetime | None = None) -> dict:
        duration = readable_duration_since(self.status_desde, now)
        stale = is_stale(self.ultima_atualizacao, now)
        return {
            "id": self.id,
            "nome": self.nome,
            "status": self.status,
            "status_bruto": self.status_bruto,
            "status_desde": self.status_desde,
            "arquivo_atual": self.arquivo_atual,
            "operador": self.operador,
            "motivo_parada": self.motivo_parada,
            "ultima_atualizacao": self.ultima_atualizacao,
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
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def readable_duration_since(value: str | None, now: datetime | None = None) -> str:
    start = parse_datetime(value)
    if not start:
        return "nao informado"
    reference = now or datetime.now(start.tzinfo or timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=start.tzinfo or timezone.utc)
    seconds = max(0, int((reference.astimezone(start.tzinfo) - start).total_seconds()))
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minuto" + ("" if minutes == 1 else "s")
    hours = minutes // 60
    rem_minutes = minutes % 60
    if hours < 24:
        if rem_minutes:
            return f"{hours} hora" + ("" if hours == 1 else "s") + f" e {rem_minutes} minuto" + ("" if rem_minutes == 1 else "s")
        return f"{hours} hora" + ("" if hours == 1 else "s")
    days = hours // 24
    rem_hours = hours % 24
    if rem_hours:
        return f"{days} dia" + ("" if days == 1 else "s") + f" e {rem_hours} hora" + ("" if rem_hours == 1 else "s")
    return f"{days} dia" + ("" if days == 1 else "s")


def is_stale(value: str | None, now: datetime | None = None) -> bool:
    updated = parse_datetime(value)
    if not updated:
        return True
    reference = now or datetime.now(updated.tzinfo or timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=updated.tzinfo or timezone.utc)
    return (reference.astimezone(updated.tzinfo) - updated).total_seconds() > STALE_AFTER_SECONDS


def normalize_machine(row: dict, arquivo_atual: str | None = None, ultima_atualizacao: str | None = None) -> NormalizedCnc:
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
        ultima_atualizacao=ultima_atualizacao or status_desde,
    )


def find_cnc_id(text: str | None) -> str | None:
    match = re.search(r"\bCNC\s*0?(\d{1,2})\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return f"CNC{int(match.group(1)):02d}"


def format_field(value: str | None) -> str:
    return value if value not in (None, "") else "nao informado"


def summarize_machine(machine: dict) -> str:
    stale_alert = " Alerta: dados desatualizados." if machine.get("dados_desatualizados") else ""
    return (
        f"{machine['id']} esta com status {machine['status_bruto']} "
        f"ha {machine['tempo_no_status']}. "
        f"Arquivo atual: {format_field(machine.get('arquivo_atual'))}. "
        f"Operador: {format_field(machine.get('operador'))}. "
        f"Ultima atualizacao: {format_field(machine.get('ultima_atualizacao'))}."
        f"{stale_alert}"
    )


def build_response(intent: str, machines: list[dict], cnc_id: str | None = None) -> str:
    if intent == "cnc":
        machine = next((m for m in machines if m["id"] == cnc_id), None)
        if not machine:
            return f"{cnc_id or 'A maquina informada'} nao foi encontrada."
        return summarize_machine(machine)

    if intent == "arquivo":
        machine = next((m for m in machines if m["id"] == cnc_id), None)
        if not machine:
            return f"{cnc_id or 'A maquina informada'} nao foi encontrada."
        return (
            f"O arquivo atual da {machine['id']} e "
            f"{format_field(machine.get('arquivo_atual'))}. "
            f"Ultima atualizacao: {format_field(machine.get('ultima_atualizacao'))}."
        )

    if intent == "usinando":
        selected = [m for m in machines if m["status"] == "usinando"]
        return _list_response("Maquinas usinando", selected)

    if intent == "paradas":
        selected = [m for m in machines if m["status"] in {"parada_nao_programada", "parada_programada", "desligada", "sem_comunicacao"}]
        return _list_response("Maquinas paradas", selected)

    if intent == "manutencao":
        selected = [m for m in machines if m["status"] == "manutencao"]
        return _list_response("Maquinas em manutencao", selected)

    if intent == "desatualizadas":
        selected = [m for m in machines if m.get("dados_desatualizados")]
        return _list_response("Maquinas com dados desatualizados", selected)

    total = len(machines)
    usinando = len([m for m in machines if m["status"] == "usinando"])
    paradas = len([m for m in machines if m["status"] in {"parada_nao_programada", "parada_programada", "desligada", "sem_comunicacao"}])
    manutencao = len([m for m in machines if m["status"] == "manutencao"])
    ultima = max((m.get("ultima_atualizacao") or "" for m in machines), default="")
    stale_count = len([m for m in machines if m.get("dados_desatualizados")])
    alert = f" Alerta: {stale_count} maquina(s) com dados desatualizados." if stale_count else ""
    return (
        f"Resumo das CNCs: {total} maquina(s), {usinando} usinando, "
        f"{paradas} parada(s), {manutencao} em manutencao. "
        f"Ultima atualizacao: {format_field(ultima)}.{alert}"
    )


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
    if "DESATUAL" in text or "COMUNIC" in text or "ENVIA" in text:
        return "desatualizadas", None
    if "PARAD" in text:
        return "paradas", None
    return "geral", None


def _list_response(title: str, machines: list[dict]) -> str:
    if not machines:
        return f"{title}: nenhuma maquina encontrada nessa condicao."
    parts = [f"{m['id']} ({m['status_bruto']}, ha {m['tempo_no_status']}, ultima atualizacao: {format_field(m.get('ultima_atualizacao'))})" for m in machines]
    return f"{title}: " + "; ".join(parts) + "."
