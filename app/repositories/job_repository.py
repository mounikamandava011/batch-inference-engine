from datetime import UTC, datetime

import aiosqlite

from app.domain.models import JobRecord, JobStatus


class JobRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create_job(self, job_id: str, input_file: str) -> JobRecord:
        now = datetime.now(UTC)

        await self._db.execute(
            """
            INSERT INTO jobs (id, status, input_file, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (job_id, JobStatus.QUEUED.value, input_file, now.isoformat()),
        )
        await self._db.commit()

        job = await self.get_job(job_id)
        assert job is not None
        return job

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._db.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            return None

        return JobRecord(
            id=row["id"],
            status=JobStatus(row["status"]),
            input_file=row["input_file"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=(datetime.fromisoformat(row["started_at"]) if row["started_at"] else None),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            items_discovered=row["items_discovered"],
            items_processed=row["items_processed"],
            items_succeeded=row["items_succeeded"],
            items_failed=row["items_failed"],
            ingestion_complete=bool(row["ingestion_complete"]),
            error_message=row["error_message"],
        )
