import email.utils
from datetime import datetime

import httpx

from app.inference.base import InferenceError


class DigitalOceanInferenceClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        if not base_url or not api_key or not model:
            raise ValueError(
                "INFERENCE_BASE_URL, INFERENCE_API_KEY and INFERENCE_MODEL are required"
            )

        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def close(self) -> None:
        await self.client.aclose()

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None

        try:
            return max(float(value), 0.0)
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
                now = datetime.now(parsed.tzinfo)
                return max((parsed - now).total_seconds(), 0.0)
            except (TypeError, ValueError):
                return None

    async def complete(self, prompt: str) -> str:
        try:
            response = await self.client.post(
                "chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_completion_tokens": 64,
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise InferenceError(
                str(exc),
                retryable=True,
                error_type="transport_error",
            ) from exc

        if response.status_code in {401, 403}:
            raise InferenceError(
                "provider authentication failed",
                retryable=False,
                job_fatal=True,
                error_type="authentication_error",
                status_code=response.status_code,
            )

        if response.status_code in {408, 429, 500, 502, 503, 504}:
            raise InferenceError(
                f"provider returned HTTP {response.status_code}",
                retryable=True,
                error_type="rate_limit" if response.status_code == 429 else "provider_error",
                status_code=response.status_code,
                retry_after=self._retry_after(response),
            )

        if response.status_code >= 400:
            raise InferenceError(
                f"provider returned HTTP {response.status_code}",
                retryable=False,
                error_type="provider_error",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise InferenceError(
                "malformed provider response",
                retryable=False,
                error_type="malformed_response",
            ) from exc

        if not isinstance(content, str):
            raise InferenceError(
                "provider response content was not text",
                retryable=False,
                error_type="malformed_response",
            )

        return content
