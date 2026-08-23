"""The single production composition boundary for G0-C.

The runner receives typed use cases and results from this module.  It never
receives a SQLite connection, a configured root, an operator identity, or a
concrete lock/writer.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from xiaoshuo.application.creation.approve_canon_changeset import ApproveCanonChangesetUseCase
from xiaoshuo.application.creation.author_decision import CreateAuthorDecisionUseCase
from xiaoshuo.application.creation.author_decision_transition import ConsumeAuthorDecisionUseCase
from xiaoshuo.application.creation.canon_activation import CanonActivationRequest, CanonActivationUseCase
from xiaoshuo.application.creation.canon_changeset import PrepareCanonChangesetUseCase
from xiaoshuo.application.creation.create_task import CreateChapterTaskUseCase
from xiaoshuo.application.creation.draft_review_submission import (
    SubmitAuthoringArtifactUseCase,
    SubmitDraftForReviewUseCase,
)
from xiaoshuo.application.creation.errors import CreationApplicationError
from xiaoshuo.application.creation.plan_preparation import PreparePlanForApprovalUseCase
from xiaoshuo.application.creation.ports import CanonBundleDescriptor
from xiaoshuo.domain.creation import ArtifactRef
from xiaoshuo.application.creation.transition_task import TransitionChapterTaskUseCase
from xiaoshuo.infrastructure.canon.c4a_apply import C4aApplyService
from xiaoshuo.infrastructure.canon.c4b_activation import C4bActivationService
from xiaoshuo.infrastructure.canon.canonical_bundle import CanonicalBundle
from xiaoshuo.infrastructure.canon.immutable_payload_store import ImmutablePayloadStore
from xiaoshuo.infrastructure.canon.projection_activation import ProjectionActivationReader
from xiaoshuo.infrastructure.canon.c5_g0_runtime import C5G0Runtime, load_c5_g0_runtime
from xiaoshuo.infrastructure.persistence.sqlite.canon_activation_repository import (
    SqliteCanonActivationRepository,
)
from xiaoshuo.infrastructure.persistence.sqlite.connection import get_connection
from xiaoshuo.infrastructure.persistence.sqlite.uow import SqliteCreationUnitOfWork


class C5G0CompositionError(RuntimeError):
    """A composition lifecycle or trusted-boundary construction failure."""


class _CanonicalBundleInspector:
    def inspect(self, data: bytes) -> CanonBundleDescriptor:
        bundle = CanonicalBundle.from_bytes(data)
        return CanonBundleDescriptor(
            content_hash=bundle.content_hash(),
            manifest_hash=bundle.manifest_hash,
            world_hash=bundle.world_hash,
        )


@dataclass(frozen=True, slots=True)
class C5G0BootstrapResult:
    status: str
    attempt_id: str
    project_id: str
    version_id: str
    replay_envelope_json: str


class C5G0Composition:
    """Build only from the validated G0-A runtime."""

    def __init__(self, runtime: C5G0Runtime) -> None:
        if not isinstance(runtime, C5G0Runtime):
            raise C5G0CompositionError("G0-C requires the validated G0-A runtime")
        self._runtime = runtime

    @classmethod
    def load(cls) -> "C5G0Composition":
        return cls(load_c5_g0_runtime())

    @property
    def runtime(self) -> C5G0Runtime:
        return self._runtime

    def bootstrap_c4b(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ) -> C5G0BootstrapResult:
        """Perform one first activation through the existing C4b boundary."""

        conn = get_connection(self._runtime.settings, read_only=False)
        try:
            service = C4bActivationService(
                conn,
                operator_identity=self._runtime.operator_context.author_id,
            )
            result = CanonActivationUseCase(service).activate(
                CanonActivationRequest(project_id, attempt_key, request_digest)
            )
        except Exception as original_exc:
            _close_connection_or_chain(conn, original_exc)
            raise
        try:
            conn.close()
        except Exception as close_exc:
            raise CreationApplicationError("C4b write connection close failed") from close_exc
        return C5G0BootstrapResult(
            status=result.status,
            attempt_id=result.attempt_id,
            project_id=result.project_id,
            version_id=result.version_id,
            replay_envelope_json=result.replay_envelope_json,
        )

    def replay_c4b(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ) -> C5G0BootstrapResult:
        """Replay existing C4b facts through a read-only connection only."""

        conn = get_connection(self._runtime.settings, read_only=True)
        try:
            service = C4bActivationService(
                conn,
                operator_identity=self._runtime.operator_context.author_id,
            )
            result = CanonActivationUseCase(service).activate(
                CanonActivationRequest(project_id, attempt_key, request_digest)
            )
        except Exception as original_exc:
            _close_connection_or_chain(conn, original_exc)
            raise
        try:
            conn.close()
        except Exception as close_exc:
            raise CreationApplicationError("C4b replay connection close failed") from close_exc
        return C5G0BootstrapResult(
            status="REPLAY",
            attempt_id=result.attempt_id,
            project_id=result.project_id,
            version_id=result.version_id,
            replay_envelope_json=result.replay_envelope_json,
        )

    def open_application_scope(self) -> "C5G0ApplicationScope":
        """Open later application connections after the clean verifier gate."""

        return C5G0ApplicationScope(self._runtime)

    def verify_c4b_clean(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ):
        """Return verifier-owned clean evidence for a derived C4b identity."""

        from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
            verify_c4b_activated_clean,
        )

        return verify_c4b_activated_clean(
            self._runtime,
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )

    def verify_fresh_gate(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ):
        """Return the verifier-owned zero-write fresh-gate evidence."""

        from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
            verify_fresh_gate,
        )

        return verify_fresh_gate(
            self._runtime,
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )

    def verify_completed_graph(
        self,
        *,
        project_id: str,
        task_id: str,
        attempt_key: str,
        request_digest: str,
    ):
        """Verify a completed graph through the composition-owned reader."""

        from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
            verify_completed_graph,
        )

        return verify_completed_graph(
            self._runtime,
            project_id=project_id,
            task_id=task_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )

    def classify_runtime(
        self,
        *,
        project_id: str,
        attempt_key: str,
        request_digest: str,
    ):
        """Return the verifier-owned runtime census used for branch selection."""

        from xiaoshuo.infrastructure.persistence.sqlite.c5_g0_activation_state_verifier import (
            C5G0ActivationStateVerifier,
        )

        return C5G0ActivationStateVerifier(self._runtime).classify_runtime(
            project_id=project_id,
            attempt_key=attempt_key,
            request_digest=request_digest,
        )


class C5G0ApplicationScope(AbstractContextManager["C5G0ApplicationScope"]):
    """Typed Phase A/B application services with owned connection lifetime."""

    def __init__(self, runtime: C5G0Runtime) -> None:
        self._runtime = runtime
        self._reader_connection = None
        self._c4a_connection = None
        self._c4a_port = None
        try:
            self._reader_connection = get_connection(runtime.settings, read_only=True)
            self._reader_repository = SqliteCanonActivationRepository(self._reader_connection)
            self.activation_reader = ProjectionActivationReader(
                runtime.projection_dir,
                artifact_ref_resolver=self._reader_repository.resolve_artifact_ref,
            )
            self.payload_store = ImmutablePayloadStore(runtime.payloads_dir)
            self.bundle_inspector = _CanonicalBundleInspector()

            uow_factory: Callable[[], SqliteCreationUnitOfWork] = self._new_uow
            author = runtime.author_context
            self.create_task = CreateChapterTaskUseCase(uow_factory)
            self.transition_task = TransitionChapterTaskUseCase(uow_factory)
            self.create_decision = CreateAuthorDecisionUseCase(
                uow_factory, author, payload_store=self.payload_store
            )
            self.consume_decision = ConsumeAuthorDecisionUseCase(uow_factory, author)
            self.prepare_plan = PreparePlanForApprovalUseCase(
                uow_factory, author, self.payload_store
            )
            self.submit_draft = SubmitAuthoringArtifactUseCase(
                uow_factory, author, self.payload_store
            )
            self.submit_review = SubmitDraftForReviewUseCase(
                uow_factory, author, self.payload_store
            )
            self.prepare_changeset = PrepareCanonChangesetUseCase(
                uow_factory,
                author,
                self.payload_store,
                self.bundle_inspector,
                activation_reader=self.activation_reader,
            )
            self.approve_changeset = ApproveCanonChangesetUseCase(
                uow_factory,
                author,
                self.payload_store,
                self.bundle_inspector,
                activation_reader=self.activation_reader,
            )
        except Exception as original_exc:
            if self._reader_connection is not None:
                try:
                    self._reader_connection.close()
                except Exception as close_exc:
                    raise original_exc from close_exc
            raise

    def persist_creative_intent(self, data: bytes) -> ArtifactRef:
        """Store caller-owned intent bytes and return an app-created ref."""

        if type(data) is not bytes:
            raise C5G0CompositionError("creative intent must be bytes")
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        stored = self.payload_store.put(data)
        if stored != digest or self.payload_store.read(stored) != data:
            raise C5G0CompositionError("creative intent payload readback failed")
        return ArtifactRef(str(uuid4()), 1, digest)

    def _new_uow(self) -> SqliteCreationUnitOfWork:
        return SqliteCreationUnitOfWork(get_connection(self._runtime.settings, read_only=False))

    @property
    def apply_canon(self) -> object:
        if self._c4a_port is None:
            self._c4a_connection = get_connection(self._runtime.settings, read_only=False)
            self._c4a_port = C4aApplyService(
                self._c4a_connection,
                operator_identity=self._runtime.operator_context.author_id,
            )
        return self._c4a_port

    def __enter__(self) -> "C5G0ApplicationScope":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        close_error: Exception | None = None
        # Release the read snapshot before the C4a writer so SQLite can
        # checkpoint the durable facts without a stale reader pinning WAL.
        for connection in (self._reader_connection, self._c4a_connection):
            if connection is None:
                continue
            try:
                connection.close()
            except Exception as error:
                if close_error is None:
                    close_error = error
                else:
                    close_error.__context__ = error
        if close_error is not None:
            raise CreationApplicationError("G0-C application scope close failed") from close_error
        return False


def load_c5_g0_composition() -> C5G0Composition:
    return C5G0Composition.load()


def _close_connection_or_chain(conn: Any, original_exc: Exception) -> None:
    try:
        conn.close()
    except Exception as close_exc:
        raise original_exc from close_exc
