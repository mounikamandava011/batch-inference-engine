import asyncio
from datetime import UTC, datetime

import aiosqlite

from app.domain.models import ItemResult, ItemStatus, JobRecord, JobStatus


class JobRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._write_lock = asyncio.Lock()

    async def create_job(self, job_id: str, input_file: str) -> JobRecord:
        now = datetime.now(UTC)

        async with self._write_lock:
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
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
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

    async def mark_running(self, job_id: str) -> None:
        async with self._write_lock:
            await self._db.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?
                WHERE id = ?
                """,
                (JobStatus.RUNNING.value, datetime.now(UTC).isoformat(), job_id),
            )
            await self._db.commit()

    async def add_discovered(self, job_id: str, count: int) -> None:
        async with self._write_lock:
            await self._db.execute(
                """
                UPDATE jobs
                SET items_discovered = items_discovered + ?
                WHERE id = ?
                """,
                (count, job_id),
            )
            await self._db.commit()

    async def mark_ingestion_complete(self, job_id: str) -> None:
        async with self._write_lock:
            await self._db.execute(
                "UPDATE jobs SET ingestion_complete = 1 WHERE id = ?",
                (job_id,),
            )
            await self._db.commit()

    async def write_results(self, job_id: str, results: list[ItemResult]) -> None:
        if not results:
            return

        succeeded = sum(result.status == ItemStatus.SUCCEEDED for result in results)
        failed = len(results) - succeeded

        async with self._write_lock:
            await self._db.execute("BEGIN")
            try:
                await self._db.executemany(
                    """
                    INSERT INTO results (
                        job_id,
                        item_index,
                        prompt,
                        status,
                        response,
                        error_type,
                        error_message,
                        attempt_count,
                        latency_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            job_id,
                            result.item_index,
                            result.prompt,
                            result.status.value,
                            result.response,
                            result.error_type,
                            result.error_message,
                            result.attempt_count,
                            result.latency_ms,
                        )
                        for result in results
                    ],
                )

                await self._db.execute(
                    """
                    UPDATE jobs
                    SET items_processed = items_processed + ?,
                        items_succeeded = items_succeeded + ?,
                        items_failed = items_failed + ?
                    WHERE id = ?
                    """,
                    (len(results), succeeded, failed, job_id),
                )

                await self._db.commit()
            except BaseException:
                await self._db.rollback()
                raise

    async def finalize(self, job_id: str) -> None:
        job = await self.get_job(job_id)
        assert job is not None

        final_status = JobStatus.COMPLETED_WITH_ERRORS if job.items_failed else JobStatus.COMPLETED

        async with self._write_lock:
            await self._db.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (final_status.value, datetime.now(UTC).isoformat(), job_id),
            )
            await self._db.commit()

    async def mark_failed(self, job_id: str, message: str) -> None:
        async with self._write_lock:
            await self._db.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    JobStatus.FAILED.value,
                    datetime.now(UTC).isoformat(),
                    message[:500],
                    job_id,
                ),
            )
            await self._db.commit()
