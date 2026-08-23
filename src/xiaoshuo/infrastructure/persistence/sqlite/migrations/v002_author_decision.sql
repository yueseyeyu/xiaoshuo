-- B2b v002: AuthorDecision append-only tables
-- 2 new tables, 2 FKs (ON DELETE RESTRICT), 2 UNIQUE constraints, 4 append-only triggers

-- AuthorDecision (append-only, immutable)
CREATE TABLE creation_author_decision (
    decision_id TEXT NOT NULL PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    task_id TEXT NOT NULL REFERENCES chapter_task(task_id) ON DELETE RESTRICT,
    decision_type TEXT NOT NULL CHECK (decision_type IN (
        'CONFIRM_PLAN', 'REJECT_PLAN', 'ADOPT_DRAFT', 'REJECT_DRAFT',
        'APPROVE_CHANGESET', 'REJECT_CHANGESET',
        'CONFIRM_NO_CANON_CHANGE', 'CANCEL_TASK'
    )),
    target_ref_artifact_id TEXT NOT NULL REFERENCES creation_artifact_ref(artifact_id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN ('APPROVE', 'REJECT')),
    based_on_task_revision INTEGER NOT NULL CHECK (based_on_task_revision >= 0),
    author_id TEXT NOT NULL,
    reason TEXT,
    actor_kind TEXT NOT NULL CHECK (actor_kind = 'AUTHOR'),
    actor_id TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash GLOB 'sha256:[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'),
    created_at TEXT NOT NULL
) STRICT;

-- Decision consumption (append-only; one decision consumed at most once)
CREATE TABLE creation_decision_consumption (
    consumption_id TEXT NOT NULL PRIMARY KEY,
    decision_id TEXT NOT NULL REFERENCES creation_author_decision(decision_id) ON DELETE RESTRICT,
    operation_id TEXT NOT NULL REFERENCES creation_operation(operation_id) ON DELETE RESTRICT,
    task_id TEXT NOT NULL REFERENCES chapter_task(task_id) ON DELETE RESTRICT,
    consumed_at_task_revision INTEGER NOT NULL CHECK (consumed_at_task_revision >= 0),
    consumed_at TEXT NOT NULL,
    UNIQUE (decision_id),
    UNIQUE (operation_id)
) STRICT;

-- Append-only triggers for creation_author_decision
CREATE TRIGGER trg_author_decision_no_update
BEFORE UPDATE ON creation_author_decision
BEGIN
    SELECT RAISE(ABORT, 'creation_author_decision is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_author_decision_no_delete
BEFORE DELETE ON creation_author_decision
BEGIN
    SELECT RAISE(ABORT, 'creation_author_decision is append-only; DELETE rejected');
END;

-- Append-only triggers for creation_decision_consumption
CREATE TRIGGER trg_decision_consumption_no_update
BEFORE UPDATE ON creation_decision_consumption
BEGIN
    SELECT RAISE(ABORT, 'creation_decision_consumption is append-only; UPDATE rejected');
END;

CREATE TRIGGER trg_decision_consumption_no_delete
BEFORE DELETE ON creation_decision_consumption
BEGIN
    SELECT RAISE(ABORT, 'creation_decision_consumption is append-only; DELETE rejected');
END;

-- Indexes for common query patterns
CREATE INDEX idx_author_decision_task_id ON creation_author_decision(task_id);
CREATE INDEX idx_decision_consumption_task_id ON creation_decision_consumption(task_id);
