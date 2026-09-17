import asyncio


class FakeInferenceClient:
    def __init__(self, latency_seconds: float = 0.0) -> None:
        self.latency_seconds = latency_seconds

    async def complete(self, prompt: str) -> str:
        if self.latency_seconds:
            await asyncio.sleep(self.latency_seconds)
        return f"fake:{prompt}"
