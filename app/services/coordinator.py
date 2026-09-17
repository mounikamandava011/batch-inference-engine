import asyncio
from pathlib import Path

from app.inference.base import InferenceClient
from app.repositories.job_repository import JobRepository
from app.services.executor import InferenceExecutor
from app.services.pipeline import RESULT_SENTINEL, producer, worker, writer


class JobCoordinator:
    def __init__(
        self,
        repository: JobRepository,
        client: InferenceClient,
        worker_count: int,
        work_queue_size: int,
        result_queue_size: int,
        writer_batch_size: int,
        global_concurrency: int,
        max_attempts: int,
    ) -> None:
        self.repository = repository
        self.worker_count = worker_count
        self.work_queue_size = work_queue_size
        self.result_queue_size = result_queue_size
        self.writer_batch_size = writer_batch_size

        self.executor = InferenceExecutor(
            client=client,
            concurrency=global_concurrency,
            max_attempts=max_attempts,
        )

    async def run(self, job_id: str, input_path: Path) -> None:
        work_queue = asyncio.Queue(maxsize=self.work_queue_size)
        result_queue = asyncio.Queue(maxsize=self.result_queue_size)

        await self.repository.mark_running(job_id)

        producer_task = asyncio.create_task(
            producer(
                job_id,
                input_path,
                self.repository,
                work_queue,
                result_queue,
                self.worker_count,
            )
        )

        worker_tasks = [
            asyncio.create_task(worker(self.executor, work_queue, result_queue))
            for _ in range(self.worker_count)
        ]

        writer_task = asyncio.create_task(
            writer(
                job_id,
                self.repository,
                result_queue,
                self.writer_batch_size,
            )
        )

        all_tasks = [producer_task, *worker_tasks, writer_task]

        try:
            await producer_task
            await asyncio.gather(*worker_tasks)

            await result_queue.put(RESULT_SENTINEL)
            await writer_task

            await self.repository.finalize(job_id)

        except Exception as exc:  # noqa: BLE001 - top-level job failure boundary
            for task in all_tasks:
                if not task.done():
                    task.cancel()

            await asyncio.gather(*all_tasks, return_exceptions=True)
            await self.repository.mark_failed(job_id, str(exc))
