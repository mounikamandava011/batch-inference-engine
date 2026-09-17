PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
READY := $(VENV)/.batch-ready

COUNT ?= 1000
PORT ?= 8000
DEMO_PORT ?= 8001
REAL_PORT ?= 8002
REAL_COUNT ?= 3
RPM ?= 200

.DEFAULT_GOAL := help

.PHONY: help setup test sample run run-real demo demo-real

help:
	@echo "Batch Inference Engine"
	@echo ""
	@echo "  make setup                     create venv and install dependencies"
	@echo "  make test                      lint + format check + tests"
	@echo "  make sample                    generate 1,000 prompts"
	@echo "  make sample COUNT=10           generate custom prompt count"
	@echo "  make run                       offline fake API on port 8000"
	@echo "  make run PORT=9000             fake API on another port"
	@echo "  make demo                      full 1,000-item fake E2E demo"
	@echo "  make demo COUNT=10             smaller fake E2E demo"
	@echo "  make demo-real                 real 3-item DigitalOcean demo"
	@echo "  make demo-real REAL_COUNT=5    real 5-item DigitalOcean demo"
	@echo "  make demo-real RPM=120         override real-provider pacing"
	@echo "  make run-real                  real provider + Swagger (billable)"
	@echo ""
	@echo "Swagger after 'make run':"
	@echo "  http://localhost:$(PORT)/docs"

$(READY): requirements.txt requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt
	@touch $(READY)

setup: $(READY)
	@echo "✓ setup complete"

test: $(READY)
	$(RUFF) check .
	$(RUFF) format --check .
	$(PY) -m pytest -q

sample: $(READY)
	$(PY) scripts/generate_sample.py --count $(COUNT)

run: $(READY)
	@echo "API:     http://localhost:$(PORT)"
	@echo "Swagger: http://localhost:$(PORT)/docs"
	@echo "Health:  http://localhost:$(PORT)/health"
	env -u INFERENCE_API_KEY \
	    -u INFERENCE_BASE_URL \
	    -u INFERENCE_MODEL \
	    INFERENCE_PROVIDER=fake \
	    REQUESTS_PER_MINUTE=0 \
	    $(PY) -m uvicorn app.main:app \
	    --host 0.0.0.0 --port $(PORT)

demo: $(READY)
	env -u INFERENCE_API_KEY \
	    -u INFERENCE_BASE_URL \
	    -u INFERENCE_MODEL \
	    INFERENCE_PROVIDER=fake \
	    REQUESTS_PER_MINUTE=0 \
	    $(PY) scripts/e2e_demo.py \
	    --provider fake \
	    --count $(COUNT) \
	    --port $(DEMO_PORT)

demo-real: $(READY)
	@echo "REAL PROVIDER DEMO — billable"
	$(PY) scripts/e2e_demo.py \
	    --provider digitalocean \
	    --count $(REAL_COUNT) \
	    --port $(REAL_PORT) \
	    --rpm $(RPM)

run-real: $(READY)
	@test -n "$$INFERENCE_API_KEY" || \
	    (echo "ERROR: INFERENCE_API_KEY is required"; exit 1)
	@test -n "$$INFERENCE_BASE_URL" || \
	    (echo "ERROR: INFERENCE_BASE_URL is required"; exit 1)
	@test -n "$$INFERENCE_MODEL" || \
	    (echo "ERROR: INFERENCE_MODEL is required"; exit 1)
	@echo "REAL PROVIDER — billable"
	@echo "Swagger: http://localhost:$(PORT)/docs"
	INFERENCE_PROVIDER=digitalocean \
	REQUESTS_PER_MINUTE=$(RPM) \
	$(PY) -m uvicorn app.main:app \
	    --host 0.0.0.0 --port $(PORT)
