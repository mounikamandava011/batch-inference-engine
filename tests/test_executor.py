import pytest

from app.domain.models import WorkItem
from app.inference.base import InferenceError
from app.services.executor import InferenceExecutor


class RetryThenSuccess:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt: str) -> str:
        self.calls += 1

        if self.calls < 3:
            raise InferenceError(
                "rate limited",
                retryable=True,
                error_type="rate_limit",
                status_code=429,
            )

        return f"ok:{prompt}"


class AlwaysFails:
    async def complete(self, prompt: str) -> str:
        raise InferenceError(
            "upstream 500",
            retryable=True,
            error_type="provider_error",
            status_code=500,
        )


@pytest.mark.asyncio
async def test_429_retries_then_succeeds():
    client = RetryThenSuccess()

    executor = InferenceExecutor(
        client=client,
        concurrency=2,
        max_attempts=5,
        base_delay=0,
    )

    result = await executor.execute(WorkItem(item_index=0, prompt="hello"))

    assert result.status == "succeeded"
    assert result.attempt_count == 3
    assert client.calls == 3


@pytest.mark.asyncio
async def test_persistent_500_becomes_item_failure():
    executor = InferenceExecutor(
        client=AlwaysFails(),
        concurrency=2,
        max_attempts=3,
        base_delay=0,
    )

    result = await executor.execute(WorkItem(item_index=0, prompt="hello"))

    assert result.status == "failed"
    assert result.attempt_count == 3
    assert result.error_type == "provider_error"
