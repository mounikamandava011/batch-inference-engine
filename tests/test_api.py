from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def settings(tmp_path: Path) -> Settings:
    return Settings(
        input_root=tmp_path / "input",
        database_path=tmp_path / "jobs.sqlite3",
    )


def test_health(tmp_path: Path):
    app = create_app(settings(tmp_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_submit_returns_202_and_status_is_queryable(tmp_path: Path):
    cfg = settings(tmp_path)
    cfg.input_root.mkdir(parents=True)
    (cfg.input_root / "sample_batch.json").write_text(
        '[{"prompt":"hello"}]',
        encoding="utf-8",
    )

    app = create_app(cfg)

    with TestClient(app) as client:
        response = client.post(
            "/job",
            json={"input_file": "sample_batch.json"},
        )

        assert response.status_code == 202
        job_id = response.json()["job_id"]

        status = client.get(f"/job/{job_id}/status")

    assert status.status_code == 200
    assert status.json()["status"] == "queued"


def test_missing_input_rejected(tmp_path: Path):
    app = create_app(settings(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/job",
            json={"input_file": "missing.json"},
        )

    assert response.status_code == 400


def test_path_traversal_rejected(tmp_path: Path):
    cfg = settings(tmp_path)
    cfg.input_root.mkdir(parents=True)
    (tmp_path / "secret.json").write_text("[]", encoding="utf-8")

    app = create_app(cfg)

    with TestClient(app) as client:
        response = client.post(
            "/job",
            json={"input_file": "../secret.json"},
        )

    assert response.status_code == 400


def test_unknown_job_returns_404(tmp_path: Path):
    app = create_app(settings(tmp_path))

    with TestClient(app) as client:
        response = client.get("/job/does-not-exist/status")

    assert response.status_code == 404
