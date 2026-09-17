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
        assert response.json()["status"] == "queued"
        job_id = response.json()["job_id"]

        status = client.get(f"/job/{job_id}/status")

    assert status.status_code == 200
    assert status.json()["status"] in {
        "queued",
        "running",
        "completed",
    }


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


def wait_for_terminal(client: TestClient, job_id: str) -> dict:
    import time

    deadline = time.time() + 3

    while time.time() < deadline:
        body = client.get(f"/job/{job_id}/status").json()

        if body["status"] in {
            "completed",
            "completed_with_errors",
            "failed",
        }:
            return body

        time.sleep(0.01)

    raise AssertionError("job did not complete")


def test_batch_is_processed_in_background(tmp_path: Path):
    cfg = settings(tmp_path)
    cfg.input_root.mkdir(parents=True)

    (cfg.input_root / "batch.json").write_text(
        """
        [
          {"prompt": "one"},
          {"prompt": "two"},
          {"prompt": "three"}
        ]
        """,
        encoding="utf-8",
    )

    app = create_app(cfg)

    with TestClient(app) as client:
        submitted = client.post(
            "/job",
            json={"input_file": "batch.json"},
        )

        assert submitted.status_code == 202

        job_id = submitted.json()["job_id"]
        final = wait_for_terminal(client, job_id)

    assert final["status"] == "completed"
    assert final["items_discovered"] == 3
    assert final["items_processed"] == 3
    assert final["items_succeeded"] == 3
    assert final["items_failed"] == 0
    assert final["ingestion_complete"] is True


def test_bad_item_does_not_fail_other_items(tmp_path: Path):
    cfg = settings(tmp_path)
    cfg.input_root.mkdir(parents=True)

    (cfg.input_root / "batch.json").write_text(
        """
        [
          {"prompt": "good"},
          {"wrong": "shape"},
          {"prompt": "also good"}
        ]
        """,
        encoding="utf-8",
    )

    app = create_app(cfg)

    with TestClient(app) as client:
        submitted = client.post(
            "/job",
            json={"input_file": "batch.json"},
        )

        job_id = submitted.json()["job_id"]
        final = wait_for_terminal(client, job_id)

    assert final["status"] == "completed_with_errors"
    assert final["items_discovered"] == 3
    assert final["items_processed"] == 3
    assert final["items_succeeded"] == 2
    assert final["items_failed"] == 1
