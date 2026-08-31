from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3
import unicodedata
from typing import Callable


AUTHORIZED_STATUS_ROLES = {"ADMIN", "SUPERVISOR", "OPERADOR", "PROGRAMADOR"}
INITIAL_MAINTENANCE_TYPES = (
    ("Mecânica", 10),
    ("Elétrica", 20),
    ("Software", 30),
    ("Lubrificação", 40),
)


@dataclass
class MaintenanceError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def server_now() -> datetime:
    return datetime.now().astimezone()


def iso_now() -> str:
    return server_now().isoformat(timespec="seconds")


def is_maintenance_status(value: str | None) -> bool:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return "MANUT" in text.upper()


def is_lubrication_type(value: str | None) -> bool:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.upper().startswith("LUBRIFIC")


def ensure_maintenance_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cnc_maintenance_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnc_id TEXT NOT NULL,
            maintenance_type_id INTEGER NOT NULL,
            custom_type TEXT,
            work_order TEXT NOT NULL,
            opening_notes TEXT,
            closing_notes TEXT,
            status TEXT NOT NULL CHECK (status IN ('OPEN', 'CLOSED')),
            started_at TEXT NOT NULL,
            finished_at TEXT,
            duration_seconds INTEGER,
            opened_by_user_id INTEGER,
            opened_by_name TEXT NOT NULL,
            finished_by_user_id INTEGER,
            finished_by_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(cnc_id) REFERENCES maquinas(id),
            FOREIGN KEY(maintenance_type_id) REFERENCES maintenance_types(id),
            FOREIGN KEY(opened_by_user_id) REFERENCES usuarios(id),
            FOREIGN KEY(finished_by_user_id) REFERENCES usuarios(id)
        )
        """
    )
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cnc_one_open_maintenance
        ON cnc_maintenance_calls(cnc_id)
        WHERE status = 'OPEN'
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_maintenance_history_filters
        ON cnc_maintenance_calls(status, cnc_id, maintenance_type_id, started_at, finished_at)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS maintenance_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            maintenance_call_id INTEGER,
            cnc_id TEXT NOT NULL,
            user_id INTEGER,
            user_name TEXT NOT NULL,
            previous_value TEXT,
            new_value TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(maintenance_call_id) REFERENCES cnc_maintenance_calls(id)
        )
        """
    )
    now = iso_now()
    cur.executemany(
        """
        INSERT OR IGNORE INTO maintenance_types
        (name, active, display_order, created_at, updated_at)
        VALUES (?, 1, ?, ?, ?)
        """,
        [(name, order, now, now) for name, order in INITIAL_MAINTENANCE_TYPES],
    )


def _clean_actor(actor: dict | None) -> dict:
    actor = actor or {}
    name = str(actor.get("name") or "").strip()
    role = str(actor.get("role") or "").strip().upper()
    if not name:
        raise MaintenanceError(422, "Usuário responsável é obrigatório.")
    if role not in AUTHORIZED_STATUS_ROLES:
        raise MaintenanceError(403, "Usuário sem permissão para alterar o status da CNC.")
    user_id = actor.get("id")
    try:
        user_id = int(user_id) if user_id not in (None, "") else None
    except (TypeError, ValueError):
        raise MaintenanceError(422, "Identificador do usuário responsável é inválido.")
    return {"id": user_id, "name": name, "role": role}


def _audit(conn, event_type: str, call_id: int | None, cnc_id: str, actor: dict, previous, new, now_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO maintenance_audit_events
        (event_type, maintenance_call_id, cnc_id, user_id, user_name, previous_value, new_value, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            call_id,
            cnc_id,
            actor["id"],
            actor["name"],
            json.dumps(previous, ensure_ascii=False) if previous is not None else None,
            json.dumps(new, ensure_ascii=False) if new is not None else None,
            now_iso,
        ),
    )


def _elapsed_seconds(started_at: str, finished_at: str) -> int:
    try:
        started = datetime.fromisoformat(started_at)
        finished = datetime.fromisoformat(finished_at)
        return max(0, int((finished - started).total_seconds()))
    except (TypeError, ValueError):
        return 0


def change_machine_status(
    get_connection: Callable[[], sqlite3.Connection],
    cnc_id: str,
    new_status: str,
    actor: dict | None,
    *,
    maintenance_type_id: int | None = None,
    work_order: str | None = None,
    opening_notes: str | None = None,
    closing_notes: str | None = None,
    require_new_maintenance_for_start: bool = False,
    require_open_maintenance_for_finish: bool = False,
    now_factory: Callable[[], str] = iso_now,
    legacy_hook: Callable[[sqlite3.Connection, dict, str, str], None] | None = None,
    transaction_guard: Callable[[sqlite3.Connection, dict], None] | None = None,
) -> dict:
    """Single transactional use case for every CNC status transition."""
    actor_clean = _clean_actor(actor)
    status_clean = str(new_status or "").strip()
    if not status_clean:
        raise MaintenanceError(400, "Status inválido.")

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_maintenance_schema(conn)
        machine_row = conn.execute(
            "SELECT id, nome, status, status_desde FROM maquinas WHERE id = ?",
            (cnc_id,),
        ).fetchone()
        if not machine_row:
            raise MaintenanceError(404, "Máquina não encontrada.")
        machine = dict(machine_row)
        if transaction_guard:
            transaction_guard(conn, machine)
        old_status = str(machine.get("status") or "")
        repair_missing_maintenance = False
        if old_status.strip().upper() == status_clean.upper():
            if require_new_maintenance_for_start:
                if conn.execute(
                    "SELECT id FROM cnc_maintenance_calls WHERE cnc_id = ? AND status = 'OPEN'",
                    (cnc_id,),
                ).fetchone():
                    raise MaintenanceError(409, "Já existe uma manutenção aberta para esta CNC.")
                if is_maintenance_status(status_clean):
                    repair_missing_maintenance = True
                else:
                    raise MaintenanceError(409, "O status informado já está ativo nesta CNC.")
            if require_open_maintenance_for_finish:
                raise MaintenanceError(409, "Esta manutenção já foi encerrada.")
            if not repair_missing_maintenance:
                conn.commit()
                return {"ok": True, "machine": machine, "status_unchanged": True, "maintenance": None}

        now_iso = now_factory()
        was_maintenance = is_maintenance_status(old_status)
        will_maintenance = is_maintenance_status(status_clean)
        call = None

        if will_maintenance and (not was_maintenance or repair_missing_maintenance):
            work_order_clean = str(work_order or "").strip()
            if maintenance_type_id is None:
                raise MaintenanceError(422, "Tipo da manutenção é obrigatório.")
            type_row = conn.execute(
                "SELECT id, name FROM maintenance_types WHERE id = ? AND active = 1",
                (maintenance_type_id,),
            ).fetchone()
            if not type_row:
                raise MaintenanceError(422, "Tipo de manutenção inválido ou inativo.")
            if not work_order_clean and not is_lubrication_type(type_row["name"]):
                raise MaintenanceError(422, "Ordem de Serviço é obrigatória.")
            if conn.execute(
                "SELECT id FROM cnc_maintenance_calls WHERE cnc_id = ? AND status = 'OPEN'",
                (cnc_id,),
            ).fetchone():
                raise MaintenanceError(409, "Já existe uma manutenção aberta para esta CNC.")
            cur = conn.execute(
                """
                INSERT INTO cnc_maintenance_calls
                (cnc_id, maintenance_type_id, work_order, opening_notes, status, started_at,
                 opened_by_user_id, opened_by_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, ?)
                """,
                (
                    cnc_id,
                    int(maintenance_type_id),
                    work_order_clean,
                    str(opening_notes or "").strip() or None,
                    now_iso,
                    actor_clean["id"],
                    actor_clean["name"],
                    now_iso,
                    now_iso,
                ),
            )
            call = {"id": cur.lastrowid, "type": type_row["name"], "workOrder": work_order_clean, "startedAt": now_iso}
            _audit(conn, "MAINTENANCE_OPENED", cur.lastrowid, cnc_id, actor_clean, None, call, now_iso)

        elif was_maintenance and not will_maintenance:
            open_row = conn.execute(
                """
                SELECT c.*, t.name AS type_name
                FROM cnc_maintenance_calls c
                JOIN maintenance_types t ON t.id = c.maintenance_type_id
                WHERE c.cnc_id = ? AND c.status = 'OPEN'
                """,
                (cnc_id,),
            ).fetchone()
            if not open_row:
                if require_open_maintenance_for_finish:
                    raise MaintenanceError(409, "Não existe manutenção aberta para encerrar nesta CNC.")
            else:
                open_call = dict(open_row)
                duration = _elapsed_seconds(open_call["started_at"], now_iso)
                updated = conn.execute(
                    """
                    UPDATE cnc_maintenance_calls
                    SET status = 'CLOSED', finished_at = ?, duration_seconds = ?, closing_notes = ?,
                        finished_by_user_id = ?, finished_by_name = ?, updated_at = ?
                    WHERE id = ? AND status = 'OPEN'
                    """,
                    (
                        now_iso,
                        duration,
                        str(closing_notes or "").strip() or None,
                        actor_clean["id"],
                        actor_clean["name"],
                        now_iso,
                        open_call["id"],
                    ),
                )
                if updated.rowcount != 1:
                    raise MaintenanceError(409, "Esta manutenção já foi encerrada.")
                call = {
                    "id": open_call["id"],
                    "type": open_call["type_name"],
                    "workOrder": open_call["work_order"],
                    "startedAt": open_call["started_at"],
                    "finishedAt": now_iso,
                    "durationSeconds": duration,
                }
                _audit(conn, "MAINTENANCE_CLOSED", open_call["id"], cnc_id, actor_clean, open_call, call, now_iso)

        if not repair_missing_maintenance:
            conn.execute(
                "UPDATE maquinas SET status = ?, status_desde = ? WHERE id = ?",
                (status_clean, now_iso, cnc_id),
            )
            if legacy_hook:
                legacy_hook(conn, machine, status_clean, now_iso)
            _audit(conn, "MACHINE_STATUS_CHANGED", call and call.get("id"), cnc_id, actor_clean, old_status, status_clean, now_iso)
        conn.commit()
        return {
            "ok": True,
            "machine": {
                **machine,
                "status": status_clean,
                "status_desde": machine.get("status_desde") if repair_missing_maintenance else now_iso,
            },
            "status_unchanged": repair_missing_maintenance,
            "maintenance": call,
            "serverNow": now_iso,
        }
    except MaintenanceError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "idx_cnc_one_open_maintenance" in str(exc) or "cnc_maintenance_calls.cnc_id" in str(exc):
            raise MaintenanceError(409, "Já existe uma manutenção aberta para esta CNC.") from exc
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def maintenance_row_to_dict(row) -> dict:
    data = dict(row)
    return {
        "id": data["id"],
        "cncId": data["cnc_id"],
        "cncName": data.get("cnc_name") or data["cnc_id"],
        "maintenanceTypeId": data["maintenance_type_id"],
        "type": data.get("type_name") or data.get("custom_type"),
        "customType": data.get("custom_type"),
        "workOrder": data["work_order"],
        "openingNotes": data.get("opening_notes"),
        "closingNotes": data.get("closing_notes"),
        "status": data["status"],
        "startedAt": data["started_at"],
        "finishedAt": data.get("finished_at"),
        "durationSeconds": data.get("duration_seconds"),
        "openedByUserId": data.get("opened_by_user_id"),
        "openedByName": data.get("opened_by_name"),
        "finishedByUserId": data.get("finished_by_user_id"),
        "finishedByName": data.get("finished_by_name"),
    }


def close_orphaned_maintenance_calls(
    conn: sqlite3.Connection,
    *,
    now_factory: Callable[[], str] = iso_now,
) -> int:
    """Fecha chamados abertos cuja CNC já saiu do status de manutenção."""
    ensure_maintenance_schema(conn)
    rows = conn.execute(
        """
        SELECT c.*, m.status AS machine_status
        FROM cnc_maintenance_calls c
        JOIN maquinas m ON m.id = c.cnc_id
        WHERE c.status = 'OPEN'
        ORDER BY c.id
        """
    ).fetchall()
    now_iso = now_factory()
    system_actor = {"id": None, "name": "Sistema"}
    closed_count = 0

    for row in rows:
        previous = dict(row)
        if is_maintenance_status(previous.get("machine_status")):
            continue

        duration = _elapsed_seconds(previous["started_at"], now_iso)
        updated = conn.execute(
            """
            UPDATE cnc_maintenance_calls
            SET status = 'CLOSED', finished_at = ?, duration_seconds = ?,
                closing_notes = COALESCE(closing_notes, ?),
                finished_by_user_id = NULL, finished_by_name = ?, updated_at = ?
            WHERE id = ? AND status = 'OPEN'
            """,
            (
                now_iso,
                duration,
                "Encerrado automaticamente: a CNC já estava em outro status.",
                system_actor["name"],
                now_iso,
                previous["id"],
            ),
        )
        if updated.rowcount != 1:
            continue

        closed = {
            "id": previous["id"],
            "finishedAt": now_iso,
            "durationSeconds": duration,
            "reason": "ORPHANED_ACTIVE_CALL",
        }
        _audit(
            conn,
            "MAINTENANCE_CLOSED_AUTOMATICALLY",
            previous["id"],
            previous["cnc_id"],
            system_actor,
            previous,
            closed,
            now_iso,
        )
        closed_count += 1

    return closed_count
