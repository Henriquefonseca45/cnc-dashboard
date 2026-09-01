"""Weekday start-of-shift prompts; responses and automatic transitions are atomic."""
from datetime import datetime, timedelta
import logging

from backend.maintenance import MaintenanceError, change_machine_status
from backend.status_confirmation import _local_now


STATUSES = (
    "DESLIGADA", "USINANDO", "DETALHE CNC", "RNC", "ABERTURA MATERIAL",
    "SETUP", "REFEIÇÃO", "MANUTENÇÃO", "AGUAR.EMPILHADEIRA",
    "FALTA DE OPERADOR", "REUNIÃO", "TROCA CHAPA SACRIFICIO", "OCIOSA",
)
logger = logging.getLogger(__name__)


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS morning_status_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            confirmation_date TEXT NOT NULL,
            cnc_id TEXT NOT NULL,
            status_at_prompt TEXT,
            status_since_at_prompt TEXT,
            prompted_at TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'PENDING',
            resolved_at TEXT,
            resolved_by TEXT,
            selected_status TEXT,
            UNIQUE(confirmation_date, cnc_id)
        )
    """)


def _changed(row, machine):
    return (
        machine is None
        or (row["status_at_prompt"] or "") != (machine["status"] or "")
        or (row["status_since_at_prompt"] or "") != (machine["status_desde"] or "")
    )


def _maintenance_resume_candidate(conn, cnc_id, confirmation_date):
    """Return the call that was open when the previous 23:19 prompt was created."""
    required_tables = {"machine_status_confirmations", "cnc_maintenance_calls", "maintenance_types"}
    tables = {
        row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)", tuple(required_tables)
        )
    }
    if tables != required_tables:
        return None
    previous_date = (datetime.fromisoformat(confirmation_date).date() - timedelta(days=1)).isoformat()
    row = conn.execute("""
        SELECT c.maintenance_type_id, t.name AS type_name, c.work_order
        FROM machine_status_confirmations s
        JOIN cnc_maintenance_calls c
          ON c.cnc_id = s.cnc_id
         AND c.started_at <= s.prompted_at
         AND (c.finished_at IS NULL OR c.finished_at >= s.prompted_at)
        JOIN maintenance_types t ON t.id = c.maintenance_type_id
        WHERE s.confirmation_date = ? AND s.cnc_id = ?
          AND UPPER(s.status_at_prompt) LIKE '%MANUT%'
        ORDER BY c.started_at DESC, c.id DESC
        LIMIT 1
    """, (previous_date, cnc_id)).fetchone()
    if not row:
        return None
    return {
        "maintenanceTypeId": row["maintenance_type_id"],
        "type": row["type_name"],
        "workOrder": row["work_order"] or "",
    }


def _resolve(get_connection, cnc_id, confirmation_id, status, actor, *,
             automatic=False, now=None, legacy_hook=None, **maintenance_data):
    # Read the clock after acquiring the write lock, not when the request arrived.
    resolved_time = []

    def guard(conn, machine):
        current = now or _local_now()
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM morning_status_confirmations WHERE id = ? AND cnc_id = ? AND action = 'PENDING'",
            (confirmation_id, cnc_id),
        ).fetchone()
        if not row or current.weekday() >= 5 or row["confirmation_date"] != current.date().isoformat():
            raise MaintenanceError(409, "Esta confirmação da manhã não está mais pendente.")
        if _changed(row, machine):
            raise MaintenanceError(409, "O status desta CNC já foi alterado. Atualize a tela.")
        due = current >= datetime.fromisoformat(row["deadline_at"])
        if automatic != due:
            raise MaintenanceError(409, "O prazo da confirmação da manhã terminou." if due else "O prazo ainda não terminou.")
        timestamp = current.isoformat(timespec="seconds")
        resolved_time.append(timestamp)
        conn.execute("""
            UPDATE morning_status_confirmations
            SET action = ?, resolved_at = ?, resolved_by = ?, selected_status = ? WHERE id = ?
        """, ("AUTO_ABSENT" if automatic else "CONFIRMED", timestamp, actor["name"], status, row["id"]))
        operator = "" if status in {"DESLIGADA", "FALTA DE OPERADOR"} else actor["name"].strip()
        conn.execute("UPDATE maquinas SET operador_nome = ? WHERE id = ?", (operator, cnc_id))

    return change_machine_status(
        get_connection, cnc_id, status, actor,
        transaction_guard=guard, legacy_hook=legacy_hook,
        now_factory=lambda: resolved_time[0], **maintenance_data,
    )


def confirm_morning_status(get_connection, cnc_id, confirmation_id, status, actor, *,
                           now=None, legacy_hook=None, **maintenance_data):
    if status not in STATUSES:
        raise MaintenanceError(422, "Selecione um status válido para a CNC.")
    if status == "MANUTENÇÃO":
        current = now or _local_now()
        conn = get_connection()
        try:
            candidate = _maintenance_resume_candidate(conn, cnc_id, current.date().isoformat())
        finally:
            conn.close()
        if candidate:
            # A client cannot replace the authorized type/OS with different values.
            maintenance_data.update(
                maintenance_type_id=candidate["maintenanceTypeId"],
                work_order=candidate["workOrder"],
                opening_notes="Retomada da manutenção do turno anterior.",
            )
    return _resolve(get_connection, cnc_id, confirmation_id, status, actor,
                    now=now, legacy_hook=legacy_hook, **maintenance_data)


def process_morning_status_confirmations(get_connection, *, now=None, legacy_hook=None):
    current = now or _local_now()
    today = current.date().isoformat()
    prompt_at = current.replace(hour=5, minute=5, second=0, microsecond=0)
    deadline_at = current.replace(hour=5, minute=15, second=0, microsecond=0)
    due = []
    created = 0
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn)
        # Do not apply a stale Friday prompt to a weekend or a later shift.
        conn.execute("""
            UPDATE morning_status_confirmations SET action = 'EXPIRED', resolved_at = ?
            WHERE action = 'PENDING' AND confirmation_date < ?
        """, (current.isoformat(timespec="seconds"), today))
        # Never invent a missed prompt hours after the morning window has ended.
        if current.weekday() < 5 and prompt_at <= current < deadline_at:
            for machine in conn.execute("SELECT * FROM maquinas WHERE id GLOB 'CNC[0-9]*'").fetchall():
                created += conn.execute("""
                    INSERT OR IGNORE INTO morning_status_confirmations
                    (confirmation_date, cnc_id, status_at_prompt, status_since_at_prompt, prompted_at, deadline_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (today, machine["id"], machine["status"], machine["status_desde"],
                      prompt_at.isoformat(timespec="seconds"), deadline_at.isoformat(timespec="seconds"))).rowcount
        for row in conn.execute(
            "SELECT * FROM morning_status_confirmations WHERE action = 'PENDING' AND confirmation_date = ?", (today,)
        ).fetchall():
            machine = conn.execute("SELECT * FROM maquinas WHERE id = ?", (row["cnc_id"],)).fetchone()
            if _changed(row, machine):
                conn.execute("UPDATE morning_status_confirmations SET action = 'STATUS_CHANGED', resolved_at = ? WHERE id = ?",
                             (current.isoformat(timespec="seconds"), row["id"]))
            elif current.weekday() < 5 and current >= datetime.fromisoformat(row["deadline_at"]):
                due.append((row["id"], row["cnc_id"]))
        conn.commit()
    finally:
        conn.close()

    count = 0
    for confirmation_id, cnc_id in due:
        try:
            _resolve(get_connection, cnc_id, confirmation_id, "FALTA DE OPERADOR",
                     {"id": None, "name": "Sistema", "role": "ADMIN"},
                     automatic=True, now=now, legacy_hook=legacy_hook)
            count += 1
        except MaintenanceError as exc:
            if exc.status_code != 409:
                logger.exception("Falha ao aplicar falta de operador em %s", cnc_id)
        except Exception:
            # The transaction rolls back, leaving the prompt pending for a retry.
            logger.exception("Falha ao aplicar falta de operador em %s", cnc_id)
    return {"created": created, "auto_absent": count}


def get_pending_morning_status(get_connection, cnc_id, *, now=None):
    current = now or _local_now()
    if current.weekday() >= 5:
        return None
    conn = get_connection()
    try:
        ensure_schema(conn)
        row = conn.execute("""
            SELECT * FROM morning_status_confirmations
            WHERE confirmation_date = ? AND cnc_id = ? AND action = 'PENDING'
        """, (current.date().isoformat(), cnc_id)).fetchone()
        if not row:
            return None
        resume = _maintenance_resume_candidate(conn, cnc_id, current.date().isoformat())
        return {
            "id": row["id"], "cncId": cnc_id, "status": row["status_at_prompt"],
            "promptedAt": row["prompted_at"], "deadlineAt": row["deadline_at"],
            "serverNow": current.isoformat(timespec="seconds"), "statuses": STATUSES,
            "maintenanceResume": resume,
        }
    finally:
        conn.close()
