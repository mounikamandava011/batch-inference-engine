# Live Provider Validation

The DigitalOcean inference adapter was validated end to end against the live
DigitalOcean Serverless Inference API on September 17, 2026.

## Validation path

The live run exercised the normal application path:

- local JSON input
- streaming ingestion
- bounded work queue
- fixed asynchronous worker pool
- request pacing and global concurrency control
- DigitalOcean inference API
- retry / exponential backoff / jitter
- persistent SQLite result storage
- job status polling
- ordered streaming result download

## Result

The smoke test used three prompts.

- Final status: completed
- Items discovered: 3
- Items processed: 3
- Items succeeded: 3
- Items failed: 0
- Download order: item_index 0 through 2

All three live provider calls returned successful inference responses.

The sanitized downloaded result array is stored in:

`docs/real-provider-smoke.json`

No API credential is stored in this repository.

## Reproducing the live test

Enter a DigitalOcean model-access key without displaying it:

    read -s -p "DigitalOcean model access key: " INFERENCE_API_KEY
    echo
    export INFERENCE_API_KEY

Then run:

    make demo-real

The default live-provider configuration is:

- Base URL: https://inference.do-ai.run/v1
- Model: deepseek-4-flash
- Prompt count: 3
- Request pacing: 200 RPM

The downloaded result is written to:

`data/output/real-demo-latest.json`

The `data/` directory is ignored by Git.

When finished:

    unset INFERENCE_API_KEY
