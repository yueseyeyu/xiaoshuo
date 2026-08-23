-- Canon MVP v003: controlled chapter_task rebuild and read-only commit tables.
-- Executed only by MigrationRunner._apply_v003_rebuild.
ALTER TABLE chapter_task RENAME TO chapter_task_v002_legacy;

CREATE TABLE chapter_task (
    task_id TEXT NOT NULL PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    aggregate_revision INTEGER NOT NULL DEFAULT 0,
    project_id TEXT NOT NULL,
    chapter_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    last_stable_status TEXT NOT NULL CHECK (last_stable_status != 'RECOVERY_REQUIRED'),
    creative_intent_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    confirmed_plan_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    current_author_draft_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    review_target_draft_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    adopted_draft_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    latest_review_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    pending_changeset_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    commit_receipt_ref_artifact_id TEXT REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    recovery_failed_operation_id TEXT,
    recovery_error_code TEXT,
    recovery_retry_from_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((status = 'RECOVERY_REQUIRED' AND recovery_failed_operation_id IS NOT NULL AND recovery_error_code IS NOT NULL AND recovery_retry_from_status IS NOT NULL) OR (status != 'RECOVERY_REQUIRED' AND recovery_failed_operation_id IS NULL AND recovery_error_code IS NULL AND recovery_retry_from_status IS NULL)),
    CHECK (recovery_retry_from_status IS NULL OR recovery_retry_from_status NOT IN ('RECOVERY_REQUIRED', 'COMPLETED')),
    CHECK ((status = 'COMPLETED' AND commit_receipt_ref_artifact_id IS NOT NULL) OR (status != 'COMPLETED' AND commit_receipt_ref_artifact_id IS NULL)),
    CHECK (updated_at >= created_at)
) STRICT;

INSERT INTO chapter_task (
    task_id, schema_version, aggregate_revision, project_id, chapter_number, status,
    last_stable_status, creative_intent_ref_artifact_id, confirmed_plan_ref_artifact_id,
    current_author_draft_ref_artifact_id, review_target_draft_ref_artifact_id,
    adopted_draft_ref_artifact_id, latest_review_ref_artifact_id,
    pending_changeset_ref_artifact_id, recovery_failed_operation_id,
    recovery_error_code, recovery_retry_from_status, created_at, updated_at
) SELECT task_id, schema_version, aggregate_revision, project_id, chapter_number, status,
    last_stable_status, creative_intent_ref_artifact_id, confirmed_plan_ref_artifact_id,
    current_author_draft_ref_artifact_id, review_target_draft_ref_artifact_id,
    adopted_draft_ref_artifact_id, latest_review_ref_artifact_id,
    pending_changeset_ref_artifact_id, recovery_failed_operation_id,
    recovery_error_code, recovery_retry_from_status, created_at, updated_at
FROM chapter_task_v002_legacy;
DROP TABLE chapter_task_v002_legacy;
CREATE INDEX idx_chapter_task_project_id ON chapter_task(project_id);

CREATE TABLE canon_commit_journal (
    journal_id TEXT NOT NULL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES chapter_task(task_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL REFERENCES creation_operation(operation_id) ON DELETE RESTRICT,
    decision_id TEXT NOT NULL UNIQUE REFERENCES creation_author_decision(decision_id) ON DELETE RESTRICT,
    changeset_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    target_bundle_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    bundle_hash TEXT NOT NULL,
    base_manifest_hash TEXT NOT NULL,
    target_manifest_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(operation_id)
) STRICT;
CREATE TABLE canon_commit_receipt (
    receipt_id TEXT NOT NULL PRIMARY KEY,
    journal_id TEXT NOT NULL UNIQUE REFERENCES canon_commit_journal(journal_id) ON DELETE RESTRICT,
    receipt_ref_artifact_id TEXT NOT NULL UNIQUE REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
) STRICT;
CREATE INDEX idx_canon_commit_journal_task_id ON canon_commit_journal(task_id);
CREATE TRIGGER trg_canon_commit_journal_no_update BEFORE UPDATE ON canon_commit_journal BEGIN SELECT RAISE(ABORT, 'canon_commit_journal is append-only; UPDATE rejected'); END;
CREATE TRIGGER trg_canon_commit_journal_no_delete BEFORE DELETE ON canon_commit_journal BEGIN SELECT RAISE(ABORT, 'canon_commit_journal is append-only; DELETE rejected'); END;
CREATE TRIGGER trg_canon_commit_receipt_no_update BEFORE UPDATE ON canon_commit_receipt BEGIN SELECT RAISE(ABORT, 'canon_commit_receipt is append-only; UPDATE rejected'); END;
CREATE TRIGGER trg_canon_commit_receipt_no_delete BEFORE DELETE ON canon_commit_receipt BEGIN SELECT RAISE(ABORT, 'canon_commit_receipt is append-only; DELETE rejected'); END;
