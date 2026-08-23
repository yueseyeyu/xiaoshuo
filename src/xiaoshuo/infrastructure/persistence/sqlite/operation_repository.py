"""SQLite operation/idempotency ledger adapter."""

from __future__ import annotations

import sqlite3

from xiaoshuo.application.creation.digest import verify_envelope_hash
from xiaoshuo.application.creation.errors import (
    CreationApplicationError,
    OperationIdConflict,
)
from xiaoshuo.application.creation.repository import (
    OperationCreateOutcome,
    OperationLogRecord,
    OperationResult,
)


class SqliteOperationLogRepository:
    """Store immutable completed operation envelopes in the current UoW."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> OperationLogRecord | None:
        try:
            row = self._conn.execute(
                "SELECT operation_id, idempotency_key, request_digest, "
                "result_envelope_json, result_envelope_hash, created_at "
                "FROM creation_operation WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CreationApplicationError("operation ledger read failed") from exc
        if row is None:
            return None
        record = _record_from_row(row)
        if not verify_envelope_hash(
            record.result_envelope_json, record.result_envelope_hash
        ):
            raise CreationApplicationError(
                f"stored result envelope hash mismatch for operation {record.operation_id!r}"
            )
        return record

    def create_or_replay_complete(
        self, record: OperationLogRecord
    ) -> OperationCreateOutcome:
        if not verify_envelope_hash(
            record.result_envelope_json, record.result_envelope_hash
        ):
            raise CreationApplicationError("proposed result envelope hash mismatch")
        existing = self.get_by_idempotency_key(record.idempotency_key)
        if existing is not None:
            return _classify_existing(existing, record)

        try:
            self._conn.execute(
                "INSERT INTO creation_operation ("
                "operation_id, idempotency_key, request_digest, "
                "result_envelope_json, result_envelope_hash, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.operation_id,
                    record.idempotency_key,
                    record.request_digest,
                    record.result_envelope_json,
                    record.result_envelope_hash,
                    record.created_at,
                ),
            )
            return OperationCreateOutcome(OperationResult.NEW)
        except sqlite3.IntegrityError as exc:
            # A concurrent winner may have committed the idempotency key while
            # this INSERT waited. Re-read the database and return its envelope.
            existing = self.get_by_idempotency_key(record.idempotency_key)
            if existing is not None:
                return _classify_existing(existing, record)
            try:
                operation_row = self._conn.execute(
                    "SELECT idempotency_key FROM creation_operation "
                    "WHERE operation_id = ?",
                    (record.operation_id,),
                ).fetchone()
            except sqlite3.Error as read_exc:
                raise CreationApplicationError(
                    "operation ledger conflict diagnosis failed"
                ) from read_exc
            if operation_row is not None:
                raise OperationIdConflict(
                    f"operation_id {record.operation_id!r} already exists"
                ) from exc
            raise CreationApplicationError("operation ledger integrity failure") from exc
        except sqlite3.Error as exc:
            raise CreationApplicationError("operation ledger write failed") from exc


def _record_from_row(row: sqlite3.Row) -> OperationLogRecord:
    return OperationLogRecord(
        operation_id=row["operation_id"],
        idempotency_key=row["idempotency_key"],
        request_digest=row["request_digest"],
        result_envelope_json=row["result_envelope_json"],
        result_envelope_hash=row["result_envelope_hash"],
        created_at=row["created_at"],
    )


def _classify_existing(
    existing: OperationLogRecord,
    proposed: OperationLogRecord,
) -> OperationCreateOutcome:
    if existing.request_digest == proposed.request_digest:
        return OperationCreateOutcome(
            OperationResult.REPLAY,
            replay_envelope_json=existing.result_envelope_json,
        )
    return OperationCreateOutcome(OperationResult.CONFLICT)
