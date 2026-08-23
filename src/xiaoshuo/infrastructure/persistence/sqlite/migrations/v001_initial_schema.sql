-- B0b v001: Initial creation schema
-- 7 tables, 13 FKs (all ON DELETE RESTRICT), 3-table 6-trigger append-only, CHECK constraints

-- Schema migration ledger
CREATE TABLE creation_schema_migration (
    version INTEGER NOT NULL PRIMARY KEY,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL
) STRICT;

-- Artifact identity registry (no role column)
CREATE TABLE creation_artifact_ref (
    artifact_id TEXT NOT NULL PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash GLOB 'sha256:[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]')
) STRICT;

-- ChapterTask aggregate (19 columns, no commit_receipt_ref)
CREATE TABLE chapter_task (
    task_id TEXT NOT NULL PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    aggregate_revision INTEGER NOT NULL DEFAULT 0,
    project_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status NOT IN ('COMMITTING', 'COMPLETED')),
    last_stable_status TEXT NOT NULL CHECK (last_stable_status != 'RECOVERY_REQUIRED'),
    creative_intent_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    confirmed_plan_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    current_author_draft_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    review_target_draft_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    adopted_draft_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    latest_review_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    pending_changeset_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    recovery_failed_operation_id TEXT,
    recovery_error_code TEXT,
    recovery_retry_from_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (status = 'RECOVERY_REQUIRED' AND recovery_failed_operation_id IS NOT NULL
         AND recovery_error_code IS NOT NULL AND recovery_retry_from_status IS NOT NULL)
        OR
        (status != 'RECOVERY_REQUIRED' AND recovery_failed_operation_id IS NULL
         AND recovery_error_code IS NULL AND recovery_retry_from_status IS NULL)
    ),
    CHECK (
        recovery_retry_from_status IS NULL
        OR recovery_retry_from_status NOT IN ('RECOVERY_REQUIRED', 'COMMITTING', 'COMPLETED')
    ),
    CHECK (updated_at >= created_at)
) STRICT;

-- Operation/idempotency ledger
CREATE TABLE creation_operation (
    operation_id TEXT NOT NULL PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL,
    result_envelope_json TEXT NOT NULL,
    result_envelope_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

-- AuditEvent (12 domain-field scalar columns + CHECK)
CREATE TABLE creation_audit_event (
    event_id TEXT NOT NULL PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    task_id TEXT NOT NULL REFERENCES chapter_task(task_id) ON DELETE RESTRICT,
    project_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK (actor_kind IN ('AUTHOR', 'MODEL', 'SYSTEM', 'ANALYSIS_IMPORT')),
    actor_id TEXT,
    model_run_id TEXT,
    before_task_revision INTEGER NOT NULL CHECK (before_task_revision >= 0),
    after_task_revision INTEGER NOT NULL CHECK (after_task_revision >= 0),
    operation_id TEXT NOT NULL REFERENCES creation_operation(operation_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    CHECK (after_task_revision >= before_task_revision),
    CHECK (
        (actor_kind = 'AUTHOR' AND actor_id IS NOT NULL)
        OR
        (actor_kind = 'MODEL' AND model_run_id IS NOT NULL)
        OR
        actor_kind IN ('SYSTEM', 'ANALYSIS_IMPORT')
    )
) STRICT;

-- AuditEvent source artifact refs (ordinal association)
CREATE TABLE creation_audit_event_source_artifact_ref (
    event_id TEXT NOT NULL REFERENCES creation_audit_event(event_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    PRIMARY KEY (event_id, ordinal)
) STRICT;

-- AuditEvent object refs (ordinal association)
CREATE TABLE creation_audit_event_object_ref (
    event_id TEXT NOT NULL REFERENCES creation_audit_event(event_id) ON DELETE RESTRICT,
    ordinal INTEGER NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    PRIMARY KEY (event_id, ordinal)
) STRICT;

-- Append-only triggers (6 total)
CREATE TRIGGER trg_creation_audit_event_no_update
BEFORE UPDATE ON creation_audit_event
BEGIN
    SELECT RAISE(ABORT, 'creation_audit_event is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_creation_audit_event_no_delete
BEFORE DELETE ON creation_audit_event
BEGIN
    SELECT RAISE(ABORT, 'creation_audit_event is append-only; DELETE rejected');
END;

CREATE TRIGGER trg_cae_source_artifact_ref_no_update
BEFORE UPDATE ON creation_audit_event_source_artifact_ref
BEGIN
    SELECT RAISE(ABORT, 'append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_cae_source_artifact_ref_no_delete
BEFORE DELETE ON creation_audit_event_source_artifact_ref
BEGIN
    SELECT RAISE(ABORT, 'append-only; DELETE rejected');
END;

CREATE TRIGGER trg_cae_object_ref_no_update
BEFORE UPDATE ON creation_audit_event_object_ref
BEGIN
    SELECT RAISE(ABORT, 'append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_cae_object_ref_no_delete
BEFORE DELETE ON creation_audit_event_object_ref
BEGIN
    SELECT RAISE(ABORT, 'append-only; DELETE rejected');
END;

-- Indexes for common query patterns
CREATE INDEX idx_chapter_task_project_id ON chapter_task(project_id);
CREATE INDEX idx_creation_audit_event_task_id ON creation_audit_event(task_id);
CREATE INDEX idx_creation_audit_event_operation_id ON creation_audit_event(operation_id);
