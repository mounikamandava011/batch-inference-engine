from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    input_root: Path = Path("data/input")
    database_path: Path = Path("data/jobs.sqlite3")

    worker_count: int = Field(default=8, gt=0)
    work_queue_size: int = Field(default=32, gt=0)
    result_queue_size: int = Field(default=64, gt=0)
    writer_batch_size: int = Field(default=50, gt=0)
    global_inference_concurrency: int = Field(default=8, gt=0)
    requests_per_minute: float = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, gt=0)

    inference_provider: str = "fake"
    inference_base_url: str = ""
    inference_api_key: str = ""
    inference_model: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )
