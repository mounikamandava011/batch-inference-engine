from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ItemStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class JobRecord:
    id: str
    status: JobStatus
    input_file: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    items_discovered: int
    items_processed: int
    items_succeeded: int
    items_failed: int
    ingestion_complete: bool
    error_message: str | None


@dataclass(slots=True)
class WorkItem:
    item_index: int
    prompt: str


@dataclass(slots=True)
class ItemResult:
    item_index: int
    prompt: str
    status: ItemStatus
    response: str | None
    error_type: str | None
    error_message: str | None
    attempt_count: int
    latency_ms: int
