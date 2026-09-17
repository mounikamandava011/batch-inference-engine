from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
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
