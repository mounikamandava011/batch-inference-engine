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

TERMINAL_STATES = {"completed", "completed_with_errors", "failed"}


class DemoError(RuntimeError):
    pass


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
):
    data = None
    headers = {}

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


def missing_real_vars() -> list[str]:
    required = [
        "INFERENCE_API_KEY",
        "INFERENCE_BASE_URL",
        "INFERENCE_MODEL",
    ]

    return [name for name in required if not os.environ.get(name, "").strip()]


def build_server_env(provider: str, rpm: float) -> dict[str, str]:
    env = os.environ.copy()

    if provider == "fake":
        # A fake demo must stay offline even if the caller's shell
        # happens to contain real provider credentials.
        for name in list(env):
            if name.startswith("INFERENCE_"):
                env.pop(name, None)

        env["INFERENCE_PROVIDER"] = "fake"
        env["REQUESTS_PER_MINUTE"] = "0"

    else:
        env["INFERENCE_PROVIDER"] = "digitalocean"
        env["REQUESTS_PER_MINUTE"] = str(rpm)

    return env


def wait_for_health(
    base_url: str,
    process: subprocess.Popen,
    timeout: float = 15,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DemoError("API exited during startup")

        try:
            status, _ = request_json(f"{base_url}/health")
            if status == 200:
                return
        except (OSError, urllib.error.URLError):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--provider",
        choices=["fake", "digitalocean"],
        default="fake",
    )
    parser.add_argument(
        "--rpm",
        type=float,
        default=200,
        help="request-start rate for real provider only",
    )

    args = parser.parse_args()

    if args.count <= 0:
        print("ERROR: count must be positive", file=sys.stderr)
        return 1

    if not port_available(args.port):
        print(
            f"ERROR: port {args.port} is already in use.\nChoose another port.",
            file=sys.stderr,
        )
        return 1

    if args.provider == "digitalocean":
        missing = missing_real_vars()

        if missing:
            print(
                "ERROR: real-provider demo requires " + ", ".join(missing),
                file=sys.stderr,
            )
            print("No provider requests were made.", file=sys.stderr)
            return 1

    subprocess.run(
        [
            sys.executable,
            "scripts/generate_sample.py",
            "--count",
            str(args.count),
        ],
        check=True,
    )

    env = build_server_env(args.provider, args.rpm)
    base_url = f"http://127.0.0.1:{args.port}"

    log = tempfile.NamedTemporaryFile(  # noqa: SIM115 - kept open for server lifetime
        prefix="batch-demo-",
        suffix=".log",
        delete=False,
    )
    log_path = Path(log.name)

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
        stdout=log,
        stderr=subprocess.STDOUT,
    )

    started = time.monotonic()
    succeeded = False

    try:
        print(f"Batch Inference Engine — E2E demo ({args.provider} provider)")

        if args.provider == "digitalocean":
            print(f"  ! real provider: {args.count} billable request(s), paced at {args.rpm:g} RPM")

        wait_for_health(base_url, process)
        print(f"  ✓ API healthy on {base_url}")

        http_status, submitted = request_json(
            f"{base_url}/job",
            method="POST",
            body={"input_file": "sample_batch.json"},
        )

        if http_status != 202:
            raise DemoError(f"POST /job returned {http_status}, expected 202")

        job_id = submitted["job_id"]

        print("  ✓ POST /job -> 202")
        print(f"      job_id: {job_id}")

        deadline = time.monotonic() + 600

        while True:
            _, state = request_json(f"{base_url}/job/{job_id}/status")

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

        if state["status"] != "completed":
            raise DemoError(state.get("error_message") or f"unexpected status {state['status']}")

        if state["items_discovered"] != args.count:
            raise DemoError("wrong discovered count")

        if state["items_processed"] != args.count:
            raise DemoError("wrong processed count")

        if state["items_succeeded"] != args.count:
            raise DemoError("not every item succeeded")

        if state["items_failed"] != 0:
            raise DemoError("one or more items failed")

        _, rows = request_json(f"{base_url}/job/{job_id}/download")

        if not isinstance(rows, list):
            raise DemoError("download response was not an array")

        if len(rows) != args.count:
            raise DemoError(f"expected {args.count} rows, got {len(rows)}")

        indexes = [row["item_index"] for row in rows]

        if indexes != list(range(args.count)):
            raise DemoError("download ordering is incorrect")

        if not all(row["status"] == "succeeded" for row in rows):
            raise DemoError("download contains failed rows")

        print(f"  ✓ downloaded {len(rows)} ordered results")

        if rows:
            print(f"      item_index: {rows[0]['item_index']}..{rows[-1]['item_index']}")

        print(f"\nEND-TO-END DEMO: PASS  ({time.monotonic() - started:.1f}s)")

        succeeded = True
        return 0

    except Exception as exc:  # noqa: BLE001 - top-level demo failure boundary
        print(
            f"\nEND-TO-END DEMO: FAIL — {exc}",
            file=sys.stderr,
        )
        return 1

    finally:
        shutdown(process)
        log.close()

        if succeeded:
            log_path.unlink(missing_ok=True)
        else:
            try:
                text = log_path.read_text(errors="replace")
                if text:
                    print(
                        "\n--- server log tail ---",
                        file=sys.stderr,
                    )
                    print(text[-5000:], file=sys.stderr)
            except OSError:
                pass

            print(
                f"server log retained at {log_path}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
