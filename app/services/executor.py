import asyncio
import random
import time

from app.domain.models import ItemResult, ItemStatus, WorkItem
from app.inference.base import InferenceClient, InferenceError
from app.services.rate_limit import RequestPacer


class InferenceExecutor:
    def __init__(
        self,
        client: InferenceClient,
        concurrency: int,
        max_attempts: int,
        requests_per_minute: float = 0,
        base_delay: float = 0.25,
        max_delay: float = 8.0,
    ) -> None:
        self.client = client
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.pacer = RequestPacer(requests_per_minute)
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute(self, item: WorkItem) -> ItemResult:
        started = time.perf_counter()

        for attempt in range(1, self.max_attempts + 1):
            try:
                await self.pacer.wait()

                async with self.semaphore:
                    response = await self.client.complete(item.prompt)

                return ItemResult(
                    item_index=item.item_index,
                    prompt=item.prompt,
                    status=ItemStatus.SUCCEEDED,
                    response=response,
                    error_type=None,
                    error_message=None,
                    attempt_count=attempt,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )

            except InferenceError as exc:
                if exc.job_fatal:
                    raise

                if not exc.retryable or attempt == self.max_attempts:
                    return ItemResult(
                        item_index=item.item_index,
                        prompt=item.prompt,
                        status=ItemStatus.FAILED,
                        response=None,
                        error_type=exc.error_type,
                        error_message=str(exc)[:500],
                        attempt_count=attempt,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )

                if exc.retry_after is not None:
                    delay = min(max(exc.retry_after, 0.0), 60.0)
                else:
                    ceiling = min(
                        self.base_delay * (2 ** (attempt - 1)),
                        self.max_delay,
                    )
                    delay = random.uniform(0.0, ceiling)

                await asyncio.sleep(delay)

            except Exception as exc:  # noqa: BLE001 - isolate unexpected item failure
                return ItemResult(
                    item_index=item.item_index,
                    prompt=item.prompt,
                    status=ItemStatus.FAILED,
                    response=None,
                    error_type="provider_error",
                    error_message=str(exc)[:500],
                    attempt_count=attempt,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )

        raise AssertionError("unreachable")
