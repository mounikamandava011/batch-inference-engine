# Batch Inference Engine

Production-oriented asynchronous REST API for processing large prompt batches through an
LLM inference provider.

The service accepts a local JSON batch, returns a job ID immediately, processes prompts
through a bounded asynchronous worker pipeline, persists every result to SQLite, exposes
live job progress, and streams the final ordered result array.

## Quickstart

Requirements:

- Ubuntu/Linux
- Python 3.12

Create the environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Generate the requested 1,000-prompt sample:

```bash
python scripts/generate_sample.py --count 1000
```

Start the API using the default fake inference provider:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Interactive API documentation is available at:

```text
http://localhost:8000/docs
```

## Submit a job

The API accepts a filename relative to `data/input`.

For the generated sample:

```bash
curl -X POST http://localhost:8000/job \
  -H 'Content-Type: application/json' \
  -d '{"input_file":"sample_batch.json"}'
```

Example response:

```json
{
  "job_id": "<uuid>",
  "status": "queued"
}
```

The POST returns HTTP 202 immediately. File parsing and inference happen in the background.

## Check status

```bash
curl http://localhost:8000/job/<job-id>/status
```

Example terminal state:

```json
{
  "job_id": "<uuid>",
  "status": "completed",
  "items_discovered": 1000,
  "items_processed": 1000,
  "items_succeeded": 1000,
  "items_failed": 0,
  "ingestion_complete": true
}
```

## Download final results

```bash
curl http://localhost:8000/job/<job-id>/download \
  -o results.json
```

Results are emitted in original `item_index` order.

Each row contains fields such as:

```json
{
  "item_index": 0,
  "prompt": "Example prompt",
  "status": "succeeded",
  "response": "Example response",
  "error_type": null,
  "error_message": null,
  "attempt_count": 1,
  "latency_ms": 12
}
```

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/job` | Submit a local JSON batch and immediately receive a job ID |
| GET | `/job/{job_id}/status` | Read job state and progress counters |
| GET | `/job/{job_id}/download` | Stream the ordered result array after completion |
| GET | `/health` | Service health check |

## Architecture

Detailed architecture and scaling discussion:

[docs/architecture.md](docs/architecture.md)

Core pipeline:

```text
local JSON
    ↓
streaming ijson producer
    ↓
bounded work queue
    ↓
fixed worker pool
    ↓
global concurrency limit
    ↓
retry / exponential backoff / jitter
    ↓
inference provider
    ↓
bounded result queue
    ↓
batched SQLite writer
    ↓
ordered keyset-paginated download
```

### Why fixed workers instead of one task per prompt?

Creating one asyncio task per input item still consumes memory even if a semaphore limits
the number of simultaneous network calls.

At 500,000 prompts that approach can create hundreds of thousands of coroutine/task objects.

This implementation creates a fixed worker pool once. Workers repeatedly pull work from a
bounded queue, so task count remains bounded regardless of batch size.

### Backpressure

The work queue has a maximum size. When workers cannot keep up, the producer blocks on
`await queue.put(...)`.

This propagates pressure back toward ingestion instead of continuously accumulating items
in memory.

The result queue provides the same protection between inference workers and persistence.

## Retry and failure behavior

Retryable failures include provider transport failures and HTTP:

- 408
- 429
- 500
- 502
- 503
- 504

Retries use bounded exponential backoff with jitter.

When a `Retry-After` header is supplied, the retry layer honors it subject to a safety cap.

HTTP 401 and 403 are considered job-fatal authentication errors.

Persistent per-item failures are recorded as failed result rows after the configured retry
budget is exhausted. Processing of unrelated items continues.

The design therefore preserves the important invariant:

```text
items_processed = items_succeeded + items_failed
```

No discovered item is silently dropped.

## Persistence

SQLite is used as the durable local store.

Job metadata and individual inference results are persisted incrementally rather than
waiting for the entire batch to complete.

SQLite runs in WAL mode.

Result batches and counter updates are committed transactionally so the status endpoint
reflects durable processing progress.

For a single-node take-home service, SQLite provides a simple and reliable persistence
boundary without adding external infrastructure.

## Scaling to 500,000 items

The important property is that resident memory is bounded by configuration rather than N.

### Input

`ijson` incrementally parses the input array.

The complete 500,000-item JSON document is never loaded through `json.load()`.

### Task creation

The service uses a fixed worker pool.

It does not create 500,000 asyncio tasks.

### Pending work

The bounded work queue places a hard limit on the amount of queued input resident in memory.

### Provider requests

A shared semaphore bounds simultaneous inference requests.

### Results

Workers place results into a bounded result queue.

A single batched writer persists them to SQLite and releases the in-memory objects.

### Download

The download endpoint uses ordered keyset pagination:

```sql
WHERE item_index > ?
ORDER BY item_index
LIMIT ?
```

Only one result page is resident at a time.

The HTTP response itself is streamed.

Therefore the only O(N) structure is the SQLite table on disk, which is intentional.

## Scale ceilings

Effective throughput is approximately:

```text
min(
  worker processing capacity,
  global concurrency / average provider latency,
  provider request quota
)
```

For example, if the provider allows only a fixed number of requests per minute, adding
hundreds of workers cannot increase useful throughput.

Worker count, queue sizes, concurrency and retry attempts are configuration values rather
than constants embedded into the processing algorithm.

### Multi-process limitation

The current provider concurrency control is process-local.

Running multiple Uvicorn worker processes would multiply those limits.

A horizontally scaled production version should use:

- a shared durable work queue
- shared/distributed provider rate limiting
- shared result storage
- job ownership or leasing
- crash recovery checkpoints

## DigitalOcean serverless inference

The default provider is:

```text
INFERENCE_PROVIDER=fake
```

This allows deterministic local execution and CI without API credentials, network
dependency or inference cost.

For DigitalOcean inference:

```bash
export INFERENCE_PROVIDER=digitalocean
export INFERENCE_BASE_URL='https://inference.do-ai.run/v1'
export INFERENCE_MODEL='<model-id>'
export INFERENCE_API_KEY='<model-access-key>'

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The real adapter uses the OpenAI-compatible `/chat/completions` API.

Credentials are supplied only through environment variables and are excluded from Git.

CI never requires a real provider key.

## Testing

Run:

```bash
ruff check .
ruff format --check .
python -m pytest -q
```

The current test suite covers important behaviors including:

- health endpoint
- asynchronous job submission
- status lookup
- unknown jobs
- local input validation
- path traversal rejection
- background batch execution
- malformed-item isolation
- retryable HTTP 429 behavior
- retry exhaustion / persistent provider failure
- ordered result download

In addition to the automated suite, the complete fake-provider pipeline has been manually
validated with a generated 1,000-prompt input:

```text
items_discovered = 1000
items_processed  = 1000
items_succeeded  = 1000
items_failed     = 0
```

## CI/CD

`.github/workflows/ci.yml` runs on every push and pull request.

CI performs:

```text
ruff check .
ruff format --check .
python -m pytest -q
```

The CI path uses no inference credentials.

## Security

Input paths are resolved relative to the configured input directory.

Absolute paths and paths that escape the input root through `..` or symlinks are rejected.

Inference credentials are provided only through environment variables and are excluded by
`.gitignore`.

## Extensions

### Progressive DigitalOcean Spaces persistence

A future storage backend could upload completed result chunks progressively to DigitalOcean
Spaces. This would preserve progress if the local machine is lost during a long-running
batch and could support resumable recovery.

### Completion webhook

A future job request could accept a callback URL and invoke it when the job reaches a
terminal state.

Production webhook support should include:

- destination validation
- SSRF protection
- bounded retries
- idempotency
- signed callback payloads

## Known limitations

This implementation intentionally targets a single application process.

A hard process crash can leave a previously running job requiring recovery logic on restart.
A production deployment would add stale-job reconciliation and resumable checkpoints.

Provider rate limiting is currently enforced primarily by concurrency and retry behavior.
A distributed or high-volume production deployment should add shared request-rate admission
based on the provider's actual account quota.
