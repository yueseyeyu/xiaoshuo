"""Stable application-layer error types for the creation pipeline.

These error types are independent of any SQLite, database, or
infrastructure detail.  Domain errors (CreationDomainError,
InvalidStateTransition, RevisionConflict, etc.) belong to the domain
layer and are not subclassed or replaced here.
"""

from __future__ import annotations


class CreationApplicationError(Exception):
    """Base error for creation application-layer failures."""


class UnsupportedPersistenceBoundary(CreationApplicationError):
    """The requested operation exceeds the current persistence boundary.

    This is a non-retryable error raised for:
    - targeting COMMITTING or COMPLETED as a persistence or migration
      destination through ordinary entry points
    - writing to a task whose commit_receipt_ref is non-null
    - recovering through a retry_from_status that maps to COMMITTING
      or COMPLETED
    - any write that would cross the outermost currently-supported
      persistence state
    """


class RevisionConflict(CreationApplicationError):
    """Optimistic concurrency conflict — the aggregate revision has changed."""


class IdempotencyConflict(CreationApplicationError):
    """An idempotency key was re-used with a different request payload."""


class AdoptedDraftPayloadRejected(CreationApplicationError):
    """The ADOPT_DRAFT payload violates its input contract."""


class AdoptedDraftPayloadPersistenceFailed(CreationApplicationError):
    """The adopted draft payload could not be durably put and read back."""


class AuthoringArtifactInputRejected(CreationApplicationError):
    """An authoring envelope or submission command violates its contract."""


class AuthoringArtifactPayloadPersistenceFailed(CreationApplicationError):
    """Canonical authoring bytes could not be put and read back exactly."""


class AuthoringArtifactBindingRejected(CreationApplicationError):
    """An authoring envelope does not match trusted Task or payload facts."""


class OperationIdConflict(CreationApplicationError):
    """An operation_id was re-used with a different logical operation."""


class NotFound(CreationApplicationError):
    """The requested entity does not exist."""


class ArtifactIdentityConflict(CreationApplicationError):
    """The same artifact_id was declared with differing schema_version or
    content_hash.

    This is a stable application-layer error raised when two or more
    references to the same ``artifact_id`` carry inconsistent identity
    metadata.  It is distinguishable from a domain-level
    ``RevisionConflict`` and does not depend on any infrastructure
    detail (SQLite, WAL, HTTP, config, etc.).
    """


class QueryValidationError(CreationApplicationError):
    """A read-only query input or cursor violates the B3 contract."""


class QueryReadError(CreationApplicationError):
    """A read-only persistence failure without infrastructure detail leakage."""


class CanonResourceBoundaryError(CreationApplicationError):
    """A C2 resource root, payload, bundle, stage, or backup is unsafe.

    This error is a stable application vocabulary only.  C1+C2 does not add
    a Canon commit use case or map infrastructure failures through HTTP.
    """


class LegacyJournalUnbound(CreationApplicationError):
    """A v003 journal cannot be consumed as a v004 active journal."""


class LegacyChangesetUnbound(CreationApplicationError):
    """A v1 ChangeSet lacks a project-bound activation identity."""


class ActivationConflict(CreationApplicationError):
    """An activation key or project already has a different identity."""


class ActivationRecoveryRequired(CreationApplicationError):
    """Activation facts or files require explicit manual recovery."""


class ActivationInputRejected(CreationApplicationError):
    """The maintenance activation request violates its input contract."""


class CanonApplyInputRejected(CreationApplicationError):
    """A C4a Apply command or trusted identity violates its contract."""


class CanonApplyConflict(CreationApplicationError):
    """A C4a Apply conflicts with a durable identity or active lease."""


class CanonApplyRecoveryRequired(CreationApplicationError):
    """C4a durable facts or projection state require manual recovery."""


class CanonCompletionConflict(CreationApplicationError):
    """A C4a completion cannot be committed against the current task facts."""


class CanonApplyCommittedLeaseReleaseUncertain(CreationApplicationError):
    """Tx B committed, but the external lock-release result is uncertain."""

    def __init__(
        self,
        message: str,
        *,
        completed_identity: object | None = None,
        receipt_identity: object | None = None,
        replay_envelope: str | None = None,
    ) -> None:
        super().__init__(message)
        self.completed_identity = completed_identity
        self.receipt_identity = receipt_identity
        self.replay_envelope = replay_envelope
