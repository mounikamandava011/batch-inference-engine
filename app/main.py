from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_jobs import router as jobs_router
from app.api.routes_ops import router as ops_router
from app.core.config import Settings
from app.repositories.db import Database
from app.repositories.job_repository import JobRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.input_root.mkdir(parents=True, exist_ok=True)

        database = Database(settings.database_path)
        await database.connect()

        assert database.connection is not None

        app.state.settings = settings
        app.state.database = database
        app.state.repository = JobRepository(database.connection)

        try:
            yield
        finally:
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
