from typing import Protocol


class InferenceClient(Protocol):
    async def complete(self, prompt: str) -> str: ...
