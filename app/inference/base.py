from typing import Protocol


class InferenceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        error_type: str = "provider_error",
        status_code: int | None = None,
        retry_after: float | None = None,
        job_fatal: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_type = error_type
        self.status_code = status_code
        self.retry_after = retry_after
        self.job_fatal = job_fatal


class InferenceClient(Protocol):
    async def complete(self, prompt: str) -> str: ...
