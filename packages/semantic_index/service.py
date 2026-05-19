"""Semantic index service that persists metadata before vector indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Mapping, Protocol

from packages.contracts import SemanticIndexEntry

from .backend import (
    SemanticIndexBackend,
    SemanticIndexDeleteRequest,
    SemanticIndexVector,
    SemanticIndexWriteResult,
)
from .sqlite_vec import SQLITE_VEC_PACKAGE, SQLITE_VEC_VERSION


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SemanticIndexDocument:
    source_id: str
    owner_scope: str
    text: str
    vector: tuple[float, ...]
    provider_id: str
    model_id: str
    dimensions: int
    personal_model_id: str | None = None
    state_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("semantic index source id must not be empty")
        if not self.text.strip():
            raise ValueError("semantic index document text must not be empty")
        if not self.provider_id.strip():
            raise ValueError("semantic index provider id must not be empty")
        if not self.model_id.strip():
            raise ValueError("semantic index model id must not be empty")
        if self.dimensions <= 0:
            raise ValueError("semantic index dimensions must be positive")
        if len(self.vector) != self.dimensions:
            raise ValueError("semantic index vector length must match dimensions")


class SemanticIndexRepository(Protocol):
    def upsert_semantic_index_entry(self, entry: SemanticIndexEntry) -> None:
        """Persist one semantic-index metadata row."""

    def list_semantic_index_entries(
        self,
        *,
        owner_scope: str | None = None,
        state_id: str | None = None,
        personal_model_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> tuple[SemanticIndexEntry, ...]:
        """List semantic-index metadata rows."""

    def delete_semantic_index_entries(
        self,
        *,
        state_id: str | None = None,
        personal_model_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> int:
        """Delete semantic-index metadata rows."""


@dataclass(frozen=True, slots=True)
class SemanticIndexDeleteResult:
    metadata_deleted: int
    vector_deleted: int
    vector_status: str
    semantic_index_entry_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticIndexMetadataRebuildPlan:
    rebuild_entry_ids: tuple[str, ...] = ()
    reuse_entry_ids: tuple[str, ...] = ()
    delete_entry_ids: tuple[str, ...] = ()
    rebuild_documents: tuple[SemanticIndexDocument, ...] = ()


class SemanticIndexService:
    def __init__(self, *, repository: SemanticIndexRepository, backend: SemanticIndexBackend) -> None:
        self.repository = repository
        self.backend = backend

    def index_document(self, document: SemanticIndexDocument) -> SemanticIndexEntry:
        content_hash = semantic_content_hash(document.text)
        entry_id = semantic_index_entry_id(
            source_id=document.source_id,
            provider_id=document.provider_id,
            model_id=document.model_id,
            dimensions=document.dimensions,
            content_hash=content_hash,
        )
        initial_entry = self._entry(
            document,
            entry_id=entry_id,
            content_hash=content_hash,
            status="pending_vector",
            vector_ref="",
            vector_result=None,
        )
        self.repository.upsert_semantic_index_entry(initial_entry)
        result = self.backend.upsert(
            SemanticIndexVector(
                semantic_index_entry_id=entry_id,
                dimensions=document.dimensions,
                values=document.vector,
            )
        )
        indexed_entry = self._entry(
            document,
            entry_id=entry_id,
            content_hash=content_hash,
            status="pending_vector" if result.degraded else "indexed",
            vector_ref="" if result.degraded else _vector_ref(entry_id, document.dimensions),
            vector_result=result,
        )
        self.repository.upsert_semantic_index_entry(indexed_entry)
        return indexed_entry

    def delete_scope(
        self,
        *,
        state_id: str | None = None,
        personal_model_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> SemanticIndexDeleteResult:
        if all(value is None for value in (state_id, personal_model_id, provider_id, model_id)):
            raise ValueError("semantic index delete requires at least one filter")
        entries = self.repository.list_semantic_index_entries(
            state_id=state_id,
            personal_model_id=personal_model_id,
            provider_id=provider_id,
            model_id=model_id,
        )
        entry_ids = tuple(entry.semantic_index_entry_id for entry in entries)
        vector_result = (
            self.backend.delete(SemanticIndexDeleteRequest(entry_ids))
            if entry_ids
            else SemanticIndexWriteResult("deleted", 0, "no semantic vectors matched")
        )
        metadata_deleted = self.repository.delete_semantic_index_entries(
            state_id=state_id,
            personal_model_id=personal_model_id,
            provider_id=provider_id,
            model_id=model_id,
        )
        return SemanticIndexDeleteResult(
            metadata_deleted=metadata_deleted,
            vector_deleted=vector_result.accepted,
            vector_status=vector_result.status,
            semantic_index_entry_ids=entry_ids,
        )

    def rebuild_plan(
        self,
        *,
        desired_documents: tuple[SemanticIndexDocument, ...],
        owner_scope: str | None = None,
        state_id: str | None = None,
        personal_model_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> SemanticIndexMetadataRebuildPlan:
        current = self.repository.list_semantic_index_entries(
            owner_scope=owner_scope,
            state_id=state_id,
            personal_model_id=personal_model_id,
            provider_id=provider_id,
            model_id=model_id,
        )
        desired_by_id = {_entry_id_for_document(document): document for document in desired_documents}
        current_by_id = {entry.semantic_index_entry_id: entry for entry in current}
        desired_source_ids = {document.source_id for document in desired_documents}
        reuse = tuple(sorted(set(current_by_id) & set(desired_by_id)))
        rebuild = tuple(sorted(set(desired_by_id) - set(current_by_id)))
        delete = tuple(
            sorted(
                entry.semantic_index_entry_id
                for entry in current
                if entry.source_id in desired_source_ids and entry.semantic_index_entry_id not in desired_by_id
            )
        )
        return SemanticIndexMetadataRebuildPlan(
            rebuild_entry_ids=rebuild,
            reuse_entry_ids=reuse,
            delete_entry_ids=delete,
            rebuild_documents=tuple(desired_by_id[entry_id] for entry_id in rebuild),
        )

    def _entry(
        self,
        document: SemanticIndexDocument,
        *,
        entry_id: str,
        content_hash: str,
        status: str,
        vector_ref: str,
        vector_result: SemanticIndexWriteResult | None,
    ) -> SemanticIndexEntry:
        now = _utc_now()
        metadata = {
            "backend_package": SQLITE_VEC_PACKAGE,
            "backend_version": SQLITE_VEC_VERSION,
            "content_length": str(len(document.text)),
            "indexed_text": document.text,
            **{str(key): str(value) for key, value in document.metadata.items()},
        }
        if vector_result is not None:
            metadata.update(
                {
                    "vector_status": vector_result.status,
                    "vector_summary": vector_result.summary,
                }
            )
        return SemanticIndexEntry(
            semantic_index_entry_id=entry_id,
            owner_scope=document.owner_scope,
            source_id=document.source_id,
            provider_id=document.provider_id,
            model_id=document.model_id,
            dimensions=document.dimensions,
            content_hash=content_hash,
            personal_model_id=document.personal_model_id,
            state_id=document.state_id,
            vector_ref=vector_ref,
            status=status,
            created_at=now,
            updated_at=now,
            metadata=metadata,
        )


def semantic_content_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def semantic_index_entry_id(
    *,
    source_id: str,
    provider_id: str,
    model_id: str,
    dimensions: int,
    content_hash: str,
) -> str:
    identity = "|".join((source_id, provider_id, model_id, str(dimensions), content_hash))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"semantic-index:{digest}"


def _entry_id_for_document(document: SemanticIndexDocument) -> str:
    return semantic_index_entry_id(
        source_id=document.source_id,
        provider_id=document.provider_id,
        model_id=document.model_id,
        dimensions=document.dimensions,
        content_hash=semantic_content_hash(document.text),
    )


def _vector_ref(entry_id: str, dimensions: int) -> str:
    return f"sqlite-vec:{dimensions}:{entry_id}"
