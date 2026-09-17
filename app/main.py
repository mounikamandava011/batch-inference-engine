import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_jobs import router as jobs_router
from app.api.routes_ops import router as ops_router
from app.core.config import Settings
from app.inference.fake import FakeInferenceClient
from app.repositories.db import Database
from app.repositories.job_repository import JobRepository
from app.services.coordinator import JobCoordinator


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.input_root.mkdir(parents=True, exist_ok=True)

        database = Database(settings.database_path)
        await database.connect()
        assert database.connection is not None

        repository = JobRepository(database.connection)
        client = FakeInferenceClient()

        app.state.settings = settings
        app.state.database = database
        app.state.repository = repository
        app.state.tasks = set()

        app.state.coordinator = JobCoordinator(
            repository=repository,
            client=client,
            worker_count=settings.worker_count,
            work_queue_size=settings.work_queue_size,
            result_queue_size=settings.result_queue_size,
            writer_batch_size=settings.writer_batch_size,
        )

        try:
            yield
        finally:
            tasks = list(app.state.tasks)

            for task in tasks:
                task.cancel()

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            await database.close()

    app = FastAPI(
        title="Batch Inference Engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(jobs_router)
    app.include_router(ops_router)

    return app


app = create_app()
