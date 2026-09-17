from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.models import JobStatus


class CreateJobRequest(BaseModel):
    input_file: str = Field(min_length=1)


class CreateJobResponse(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    items_discovered: int
    items_processed: int
    items_succeeded: int
    items_failed: int
    ingestion_complete: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
