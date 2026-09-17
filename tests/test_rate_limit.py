import asyncio
import time

import pytest

from app.services.rate_limit import RequestPacer


@pytest.mark.asyncio
async def test_zero_rate_disables_pacing():
    pacer = RequestPacer(0)

    started = time.monotonic()
    await pacer.wait()
    await pacer.wait()

    assert time.monotonic() - started < 0.1


@pytest.mark.asyncio
async def test_request_starts_are_paced():
    pacer = RequestPacer(6000)  # 0.01 seconds between starts

    starts = []

    async def acquire():
        await pacer.wait()
        starts.append(time.monotonic())

    await asyncio.gather(acquire(), acquire(), acquire())

    assert len(starts) == 3
    assert starts[1] - starts[0] >= 0.008
    assert starts[2] - starts[1] >= 0.008
