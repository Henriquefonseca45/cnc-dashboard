from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import sqlite3
from typing import Callable


PROMPT_HOUR = 23
PROMPT_MINUTE = 19
DEADLINE_HOUR = 23
DEADLINE_MINUTE = 24


@dataclass
class StatusConfirmationError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _scheduled_time(now: datetime, hour: int, minute: int) -> datetime:
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def ensure_status_confirmation_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS machine_status_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            confirmation_date TEXT NOT NULL,
            cnc_id TEXT NOT NULL,
            status_at_prompt TEXT NOT NULL,
            status_since_at_prompt TEXT,
            prompted_at TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            action TEXT NOT NULL DEFAULT 'PENDING',
            confirmed_at TEXT,
            confirmed_by TEXT,
            auto_shutdown_at TEXT,
            updated_at TEXT NOT NULL,
            error_message TEXT,
            UNIQUE(confirmation_date, cnc_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_machine_status_confirmations_pending "
        "ON machine_status_confirmations(action, deadline_at)"
    )


def process_status_confirmations(
    get_connection: Callable[[], sqlite3.Connection],
    shutdown_machine: Callable[[str], None],
    *,
    now: datetime | None = None,
) -> dict:
    current = now or _local_now()
    prompt_at = _scheduled_time(current, PROMPT_HOUR, PROMPT_MINUTE)
    deadline_at = _scheduled_time(current, DEADLINE_HOUR, DEADLINE_MINUTE)
    now_iso = current.isoformat(timespec="seconds")
    confirmation_date = current.date().isoformat()
    created = 0
    cancelled = 0
    shutdown_ids: list[tuple[int, str]] = []

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_status_confirmation_schema(conn)

        retry_before = (current - timedelta(minutes=2)).isoformat(timespec="seconds")
        conn.execute(
            """
            UPDATE machine_status_confirmations
            SET action = 'PENDING', updated_at = ?, error_message = 'Nova tentativa após interrupção.'
            WHERE action = 'PROCESSING' AND updated_at <= ?
            """,
            (now_iso, retry_before),
        )

        if current >= prompt_at:
            machines = conn.execute(
                """
                SELECT id, status, status_desde
                FROM maquinas
                WHERE id GLOB 'CNC[0-9]*'
                  AND UPPER(TRIM(COALESCE(status, ''))) <> 'DESLIGADA'
                ORDER BY id
                """
            ).fetchall()
            for machine in machines:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO machine_status_confirmations
                    (confirmation_date, cnc_id, status_at_prompt, status_since_at_prompt,
                     prompted_at, deadline_at, action, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)
                    """,
                    (
                        confirmation_date,
                        machine["id"],
                        machine["status"] or "",
                        machine["status_desde"],
                        prompt_at.isoformat(timespec="seconds"),
                        deadline_at.isoformat(timespec="seconds"),
                        now_iso,
                    ),
                )
                created += max(0, cursor.rowcount)

        pending_rows = conn.execute(
            """
            SELECT c.id, c.cnc_id, c.status_at_prompt, c.status_since_at_prompt,
                   c.deadline_at, m.status AS current_status, m.status_desde AS current_status_since
            FROM machine_status_confirmations c
            LEFT JOIN maquinas m ON m.id = c.cnc_id
            WHERE c.action = 'PENDING'
            """,
        ).fetchall()

        for row in pending_rows:
            status_changed = (
                row["current_status"] is None
                or str(row["current_status"] or "").strip().upper() == "DESLIGADA"
                or str(row["current_status"] or "") != str(row["status_at_prompt"] or "")
                or str(row["current_status_since"] or "") != str(row["status_since_at_prompt"] or "")
            )
            if status_changed:
                conn.execute(
                    "UPDATE machine_status_confirmations SET action = 'STATUS_CHANGED', updated_at = ? WHERE id = ?",
                    (now_iso, row["id"]),
                )
                cancelled += 1
                continue
            if current >= datetime.fromisoformat(row["deadline_at"]):
                shutdown_ids.append((row["id"], row["cnc_id"]))

        conn.commit()
    finally:
        conn.close()

    shutdown_count = 0
    for confirmation_id, cnc_id in shutdown_ids:
        claim_conn = get_connection()
        try:
            claim_conn.execute("BEGIN IMMEDIATE")
            claimed = claim_conn.execute(
                """
                UPDATE machine_status_confirmations
                SET action = 'PROCESSING', updated_at = ?, error_message = NULL
                WHERE id = ? AND action = 'PENDING'
                """,
                (now_iso, confirmation_id),
            ).rowcount
            claim_conn.commit()
        finally:
            claim_conn.close()
        if not claimed:
            continue

        try:
            shutdown_machine(cnc_id)
        except Exception as exc:
            failure_conn = get_connection()
            try:
                failure_conn.execute(
                    """
                    UPDATE machine_status_confirmations
                    SET action = 'PENDING', updated_at = ?, error_message = ?
                    WHERE id = ? AND action = 'PROCESSING'
                    """,
                    (now_iso, str(exc)[:500], confirmation_id),
                )
                failure_conn.commit()
            finally:
                failure_conn.close()
            continue

        done_conn = get_connection()
        try:
            done_conn.execute(
                """
                UPDATE machine_status_confirmations
                SET action = 'AUTO_SHUTDOWN', auto_shutdown_at = ?, updated_at = ?, error_message = NULL
                WHERE id = ? AND action = 'PROCESSING'
                """,
                (now_iso, now_iso, confirmation_id),
            )
            done_conn.commit()
            shutdown_count += 1
        finally:
            done_conn.close()

    return {"created": created, "cancelled": cancelled, "auto_shutdown": shutdown_count}


def get_pending_status_confirmation(
    get_connection: Callable[[], sqlite3.Connection],
    cnc_id: str,
    *,
    now: datetime | None = None,
) -> dict | None:
    current = now or _local_now()
    conn = get_connection()
    try:
        ensure_status_confirmation_schema(conn)
        row = conn.execute(
            """
            SELECT id, cnc_id, status_at_prompt, status_since_at_prompt, prompted_at, deadline_at
            FROM machine_status_confirmations
            WHERE confirmation_date = ? AND cnc_id = ? AND action = 'PENDING'
            LIMIT 1
            """,
            (current.date().isoformat(), cnc_id),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "cncId": row["cnc_id"],
            "status": row["status_at_prompt"],
            "statusSince": row["status_since_at_prompt"],
            "promptedAt": row["prompted_at"],
            "deadlineAt": row["deadline_at"],
            "serverNow": current.isoformat(timespec="seconds"),
        }
    finally:
        conn.close()


def confirm_current_status(
    get_connection: Callable[[], sqlite3.Connection],
    cnc_id: str,
    confirmed_by: str,
    *,
    now: datetime | None = None,
) -> dict:
    current = now or _local_now()
    now_iso = current.isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_status_confirmation_schema(conn)
        row = conn.execute(
            """
            SELECT c.*, m.status AS current_status, m.status_desde AS current_status_since
            FROM machine_status_confirmations c
            LEFT JOIN maquinas m ON m.id = c.cnc_id
            WHERE c.confirmation_date = ? AND c.cnc_id = ? AND c.action = 'PENDING'
            LIMIT 1
            """,
            (current.date().isoformat(), cnc_id),
        ).fetchone()
        if not row:
            raise StatusConfirmationError(404, "Não existe confirmação de status pendente para esta CNC.")
        if current >= datetime.fromisoformat(row["deadline_at"]):
            raise StatusConfirmationError(409, "O prazo de confirmação terminou e a CNC será desligada.")
        if (
            row["current_status"] is None
            or str(row["current_status"] or "") != str(row["status_at_prompt"] or "")
            or str(row["current_status_since"] or "") != str(row["status_since_at_prompt"] or "")
        ):
            conn.execute(
                "UPDATE machine_status_confirmations SET action = 'STATUS_CHANGED', updated_at = ? WHERE id = ?",
                (now_iso, row["id"]),
            )
            conn.commit()
            raise StatusConfirmationError(409, "O status da CNC já foi alterado.")
        conn.execute(
            """
            UPDATE machine_status_confirmations
            SET action = 'CONFIRMED', confirmed_at = ?, confirmed_by = ?, updated_at = ?
            WHERE id = ? AND action = 'PENDING'
            """,
            (now_iso, str(confirmed_by or "Operador").strip() or "Operador", now_iso, row["id"]),
        )
        conn.commit()
        return {"ok": True, "cncId": cnc_id, "status": row["status_at_prompt"], "confirmedAt": now_iso}
    except StatusConfirmationError:
        conn.rollback()
        raise
    finally:
        conn.close()
