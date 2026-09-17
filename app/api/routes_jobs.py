import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.schemas import CreateJobRequest, CreateJobResponse, JobStatusResponse
from app.core.paths import UnsafeInputPath, resolve_input_file
from app.domain.models import JobStatus

router = APIRouter(tags=["jobs"])


def repository(request: Request):
    return request.app.state.repository


@router.post(
    "/job",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(payload: CreateJobRequest, request: Request) -> CreateJobResponse:
    settings = request.app.state.settings

    try:
        input_path = resolve_input_file(settings.input_root, payload.input_file)
    except (UnsafeInputPath, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = str(uuid.uuid4())
    job = await repository(request).create_job(job_id, payload.input_file)

    task = asyncio.create_task(request.app.state.coordinator.run(job_id, input_path))

    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)

    return CreateJobResponse(job_id=job.id, status=job.status)


@router.get(
    "/job/{job_id}/status",
    response_model=JobStatusResponse,
)
async def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    job = await repository(request).get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        items_discovered=job.items_discovered,
        items_processed=job.items_processed,
        items_succeeded=job.items_succeeded,
        items_failed=job.items_failed,
        ingestion_complete=job.ingestion_complete,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
    )


@router.get("/job/{job_id}/download")
async def download_results(job_id: str, request: Request):
    repo = repository(request)
    job = await repo.get_job(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    if job.status not in {
        JobStatus.COMPLETED,
        JobStatus.COMPLETED_WITH_ERRORS,
    }:
        raise HTTPException(
            status_code=409,
            detail="results are available only after job completion",
        )

    async def stream():
        first = True
        after_index = -1

        yield "["

        while True:
            rows = await repo.get_result_page(
                job_id,
                after_index,
                limit=500,
            )

            if not rows:
                break

            for row in rows:
                if not first:
                    yield ","

                yield json.dumps(row, separators=(",", ":"))
                first = False
                after_index = row["item_index"]

        yield "]"

    return StreamingResponse(
        stream(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}.json"',
        },
    )
