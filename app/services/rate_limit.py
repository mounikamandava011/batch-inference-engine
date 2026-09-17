import asyncio
import time


class RequestPacer:
    """Process-wide request-start pacing.

    A rate of 0 disables pacing. Waiting happens before acquiring the
    inference-concurrency semaphore, so pacing never occupies an inference slot.
    """

    def __init__(self, requests_per_minute: float) -> None:
        self.interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_start = 0.0

    async def wait(self) -> None:
        if self.interval == 0:
            return

        async with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_start - now)

            if wait_seconds:
                await asyncio.sleep(wait_seconds)

            now = time.monotonic()
            self._next_start = max(self._next_start, now) + self.interval
