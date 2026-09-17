import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TERMINAL_STATES = {
    "completed",
    "completed_with_errors",
    "failed",
}


class DemoError(RuntimeError):
    pass


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
) -> tuple[int, object]:
    data = None
    headers: dict[str, str] = {}

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.load(response)


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def missing_real_provider_vars() -> list[str]:
    required = [
        "INFERENCE_API_KEY",
        "INFERENCE_BASE_URL",
        "INFERENCE_MODEL",
    ]

    return [name for name in required if not os.environ.get(name, "").strip()]


def build_server_env(
    provider: str,
    rpm: float,
) -> dict[str, str]:
    env = os.environ.copy()

    if provider == "fake":
        # Offline demos must never accidentally inherit live credentials.
        for name in list(env):
            if name.startswith("INFERENCE_"):
                env.pop(name, None)

        env["INFERENCE_PROVIDER"] = "fake"
        env["REQUESTS_PER_MINUTE"] = "0"
        return env

    env["INFERENCE_PROVIDER"] = "digitalocean"
    env["REQUESTS_PER_MINUTE"] = str(rpm)

    return env


def wait_for_health(
    base_url: str,
    process: subprocess.Popen,
    timeout: float = 15.0,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DemoError("API exited during startup")

        try:
            status, _ = request_json(f"{base_url}/health")
            if status == 200:
                return
        except OSError:
            pass

        time.sleep(0.1)

    raise DemoError("API did not become healthy")


def shutdown(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a complete Batch Inference Engine E2E demo.")

    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="number of prompts to generate",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="temporary API port",
    )

    parser.add_argument(
        "--provider",
        choices=["fake", "digitalocean"],
        default="fake",
    )

    parser.add_argument(
        "--rpm",
        type=float,
        default=200,
        help="request-start pacing for real provider",
    )

    parser.add_argument(
        "--output",
        default="",
        help="optional file path for downloaded result JSON",
    )

    return parser.parse_args()


def validate_status(
    state: dict,
    expected_count: int,
) -> None:
    if state["status"] != "completed":
        raise DemoError(
            state.get("error_message") or f"unexpected terminal state: {state['status']}"
        )

    expected = {
        "items_discovered": expected_count,
        "items_processed": expected_count,
        "items_succeeded": expected_count,
        "items_failed": 0,
    }

    for field, expected_value in expected.items():
        actual = state[field]

        if actual != expected_value:
            raise DemoError(f"{field}: expected {expected_value}, got {actual}")


def validate_results(
    rows: object,
    expected_count: int,
) -> list[dict]:
    if not isinstance(rows, list):
        raise DemoError("download response was not a JSON array")

    if len(rows) != expected_count:
        raise DemoError(f"expected {expected_count} results, got {len(rows)}")

    indexes = [row["item_index"] for row in rows]

    if indexes != list(range(expected_count)):
        raise DemoError("downloaded results are not in input order")

    if not all(row["status"] == "succeeded" for row in rows):
        raise DemoError("download contains one or more failed rows")

    return rows


def run_demo(args: argparse.Namespace) -> int:
    if args.count <= 0:
        raise DemoError("count must be greater than zero")

    if args.rpm < 0:
        raise DemoError("rpm must be zero or greater")

    if not port_available(args.port):
        raise DemoError(f"port {args.port} is already in use; choose another port")

    if args.provider == "digitalocean":
        missing = missing_real_provider_vars()

        if missing:
            raise DemoError(
                "real-provider demo requires "
                + ", ".join(missing)
                + ". No provider requests were made."
            )

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_sample.py",
            "--count",
            str(args.count),
        ],
        check=True,
    )

    env = build_server_env(
        provider=args.provider,
        rpm=args.rpm,
    )

    base_url = f"http://127.0.0.1:{args.port}"

    started = time.monotonic()
    succeeded = False

    with tempfile.NamedTemporaryFile(
        prefix="batch-demo-",
        suffix=".log",
        delete=False,
    ) as log_file:
        log_path = Path(log_file.name)

        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

        try:
            print(f"Batch Inference Engine — E2E demo ({args.provider} provider)")

            if args.provider == "digitalocean":
                print(
                    f"  ! real provider: {args.count} billable "
                    f"request(s), paced at {args.rpm:g} RPM"
                )

            wait_for_health(
                base_url=base_url,
                process=process,
            )

            print(f"  ✓ API healthy on {base_url}")

            post_status, submitted = request_json(
                f"{base_url}/job",
                method="POST",
                body={"input_file": "sample_batch.json"},
            )

            if post_status != 202:
                raise DemoError(f"POST /job returned {post_status}, expected 202")

            if not isinstance(submitted, dict):
                raise DemoError("POST /job returned unexpected JSON")

            job_id = submitted["job_id"]

            print("  ✓ POST /job -> 202")
            print(f"      job_id: {job_id}")

            deadline = time.monotonic() + 600

            while True:
                _, state_object = request_json(f"{base_url}/job/{job_id}/status")

                if not isinstance(state_object, dict):
                    raise DemoError("status endpoint returned unexpected JSON")

                state = state_object

                if state["status"] in TERMINAL_STATES:
                    break

                if time.monotonic() >= deadline:
                    raise DemoError("job timed out")

                time.sleep(0.2)

            print("  ✓ job reached terminal state")
            print(f"      status     {state['status']}")
            print(f"      discovered {state['items_discovered']}")
            print(f"      processed  {state['items_processed']}")
            print(f"      succeeded  {state['items_succeeded']}")
            print(f"      failed     {state['items_failed']}")

            validate_status(
                state=state,
                expected_count=args.count,
            )

            _, downloaded = request_json(f"{base_url}/job/{job_id}/download")

            rows = validate_results(
                rows=downloaded,
                expected_count=args.count,
            )

            if args.output:
                output_path = Path(args.output)

                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                output_path.write_text(
                    json.dumps(rows, indent=2),
                    encoding="utf-8",
                )

                print(f"  ✓ results saved to {output_path}")

            print(f"  ✓ downloaded {len(rows)} ordered results")

            if rows:
                print(f"      item_index: {rows[0]['item_index']}..{rows[-1]['item_index']}")

            elapsed = time.monotonic() - started

            print(f"\nEND-TO-END DEMO: PASS  ({elapsed:.1f}s)")

            succeeded = True
            return 0

        finally:
            shutdown(process)
            log_file.flush()

            if not succeeded:
                try:
                    text = log_path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    if text:
                        print(
                            "\n--- server log tail ---",
                            file=sys.stderr,
                        )
                        print(
                            text[-5000:],
                            file=sys.stderr,
                        )
                except OSError:
                    pass

    if succeeded:
        log_path.unlink(missing_ok=True)

    return 0


def main() -> int:
    args = parse_args()

    try:
        return run_demo(args)
    except (
        DemoError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        print(
            f"\nEND-TO-END DEMO: FAIL — {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
