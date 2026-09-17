import asyncio
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any

import ijson

from app.domain.models import ItemResult, ItemStatus, WorkItem
from app.repositories.job_repository import JobRepository

WORK_SENTINEL = object()
RESULT_SENTINEL = object()


def _next_batch(iterator: Iterator[Any], size: int = 64) -> list[Any]:
    return list(islice(iterator, size))


def _to_work_item(raw: Any, item_index: int) -> WorkItem | ItemResult:
    if isinstance(raw, str) and raw.strip():
        return WorkItem(item_index=item_index, prompt=raw)

    if isinstance(raw, dict):
        prompt = raw.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            return WorkItem(item_index=item_index, prompt=prompt)

    return ItemResult(
        item_index=item_index,
        prompt="" if raw is None else str(raw),
        status=ItemStatus.FAILED,
        response=None,
        error_type="invalid_input",
        error_message="item must be a prompt string or object containing a non-empty prompt",
        attempt_count=0,
        latency_ms=0,
    )


async def producer(
    job_id: str,
    input_path: Path,
    repository: JobRepository,
    work_queue: asyncio.Queue,
    result_queue: asyncio.Queue,
    worker_count: int,
) -> None:
    index = 0

    try:
        with input_path.open("rb") as file:
            iterator = ijson.items(file, "item")

            while True:
                batch = await asyncio.to_thread(_next_batch, iterator, 64)

                if not batch:
                    break

                await repository.add_discovered(job_id, len(batch))

                for raw in batch:
                    item = _to_work_item(raw, index)
                    index += 1

                    if isinstance(item, WorkItem):
                        await work_queue.put(item)
                    else:
                        await result_queue.put(item)

        await repository.mark_ingestion_complete(job_id)

    finally:
        for _ in range(worker_count):
            await work_queue.put(WORK_SENTINEL)


async def worker(
    executor,
    work_queue: asyncio.Queue,
    result_queue: asyncio.Queue,
) -> None:
    while True:
        item = await work_queue.get()

        try:
            if item is WORK_SENTINEL:
                return

            assert isinstance(item, WorkItem)

            result = await executor.execute(item)
            await result_queue.put(result)

        finally:
            work_queue.task_done()


async def writer(
    job_id: str,
    repository: JobRepository,
    result_queue: asyncio.Queue,
    batch_size: int,
    flush_seconds: float = 0.25,
) -> None:
    pending: list[ItemResult] = []

    async def flush() -> None:
        if pending:
            await repository.write_results(job_id, pending.copy())
            pending.clear()

    while True:
        try:
            item = await asyncio.wait_for(
                result_queue.get(),
                timeout=flush_seconds,
            )
        except TimeoutError:
            await flush()
            continue

        try:
            if item is RESULT_SENTINEL:
                await flush()
                return

            assert isinstance(item, ItemResult)
            pending.append(item)

            if len(pending) >= batch_size:
                await flush()

        finally:
            result_queue.task_done()
